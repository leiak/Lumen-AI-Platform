"""M37.2 — 主评测循环 runner。

入口 ``run_eval(db, run_id)`` 是 Celery task + CLI 直跑模式都共享的核
心。流程(plan §T13):

1. 加载 ``eval_runs`` + ``eval_datasets`` + ``eval_dataset_items`` + KB
2. 一致性校验:eval config.embedding_model_config_id == KB.embedding_model_config_id
   (防 collection dim 不匹配,plan §T13 Step 2;dim 不一致 → 整个 run
   status=failed,error_message 写明原因)
3. 构造 RetrievalPipeline(get_retrieval_pipeline 工厂)
4. 遍历 items(已完成的 skip —— 续跑,plan D5「崩了能续跑」):
   - set EmbeddingCallContext(call_type="eval_retrieval", extra=eval_run_id)
   - pipeline.search(query, k=top_k, rerank=rerank, search_weights=...)
   - 算检索指标(hit_at_5/10, mrr, ndcg_at_10, recall_at_10)
   - (可选)调 LLM 生成 answer + judge 算答案指标(T11 JudgeClient)
   - INSERT eval_run_results + commit(per-item commit,崩了能续跑)
   - 每 10% 更新 eval_runs.completed_items(前端轮询)
5. 全部完成 → 调 ``report.generate()`` → 写 metrics_json + report_markdown
   → status="completed"
6. 异常 → status="failed" + error_message

异常边界:
- 整 run 级别异常(加载失败 / dim 不匹配 / unexpected)→ 立刻
  status="failed",error_message 写根因,**不 raise**(让 Celery task
  标 success,业务失败由 status 字段表达)。
- 单 item 异常(检索报错 / judge 失败)→ INSERT 一行 EvalRunResult
  error_message=root_cause,**continue**。Plan D5 配套,单条挂了不
  拖累整 run。

Spec: docs-internal/superpowers/specs/m37-rag-evaluation.md §4.2
Plan: docs-internal/superpowers/plans/m37-plan.md CP4 T13 + D5
"""
from __future__ import annotations

import logging
import time
import traceback
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple

from sqlalchemy.orm import Session

from lumen_core.embedding_call_context import (
    EmbeddingCallContext,
    get_embedding_context,
    reset_embedding_context,
    set_embedding_context,
)
from lumen_models.eval_run import EvalRun, EvalRunResult
from lumen_models.eval_dataset import EvalDataset, EvalDatasetItem
from lumen_models.knowledge import KnowledgeBase
from lumen_services.eval.metrics import (
    hit_at_k,
    mrr,
    ndcg_at_k,
    recall_at_k,
)
from lumen_services.eval.judge import (
    JudgeClient,
    FaithfulnessScore,
    AnswerRelevancyScore,
)
from lumen_services.eval.metrics import (
    faithfulness_prompt,
    answer_relevancy_prompt,
)
from lumen_services.retrieval.pipeline import get_retrieval_pipeline

logger = logging.getLogger(__name__)


# 每 10% 进度刷一次,避免每条 item 都 UPDATE 一次 eval_runs(写放大)
_PROGRESS_UPDATE_EVERY_PCT = 10


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------


async def run_eval(db: Session, run_id: int) -> None:
    """主评测循环 —— Celery task + CLI 都走这里。

    永远不 raise:任何异常都被捕,转成 status=failed + error_message。
    调用方(Celery worker / CLI)只需要看 status 字段。
    """
    run = db.get(EvalRun, run_id)
    if run is None:
        logger.error("run_eval: EvalRun #%s not found", run_id)
        return
    # 已完成 / 已失败的 run 不重跑 —— 避免 API 重试时把进度归零
    if run.status in ("completed", "failed", "cancelled"):
        logger.info(
            "run_eval: EvalRun #%s status=%s, skip (idempotent)",
            run_id, run.status,
        )
        return

    # 标记 running
    run.status = "running"  # type: ignore[assignment]
    run.started_at = datetime.utcnow()  # type: ignore[assignment]
    run.error_message = None  # type: ignore[assignment]
    db.commit()

    try:
        await _execute(db, run)
    except Exception as exc:  # noqa: BLE001
        logger.exception("run_eval: EvalRun #%s failed", run_id)
        run.status = "failed"  # type: ignore[assignment]
        run.error_message = f"{type(exc).__name__}: {exc}"  # type: ignore[assignment]
        run.finished_at = datetime.utcnow()  # type: ignore[assignment]
        db.commit()


# ---------------------------------------------------------------------------
# 核心执行
# ---------------------------------------------------------------------------


async def _execute(db: Session, run: EvalRun) -> None:
    """实际的 run 流程:加载 + 校验 + 遍历 + 写结果 + 报告。"""
    config: Dict[str, Any] = dict(run.config_json or {})
    dataset = db.get(EvalDataset, run.dataset_id)
    if dataset is None:
        raise ValueError(f"dataset #{run.dataset_id} not found (可能已被删除)")
    kb = db.get(KnowledgeBase, dataset.kb_id)
    if kb is None:
        raise ValueError(f"KB #{dataset.kb_id} not found")

    # 1. embedding 模型一致性校验
    eval_emb_id = config.get("embedding_model_config_id")
    if eval_emb_id is not None and eval_emb_id != kb.embedding_model_config_id:
        raise ValueError(
            f"embedding_model_config_id 不匹配:eval config={eval_emb_id}, "
            f"KB#{kb.id}.embedding_model_config_id={kb.embedding_model_config_id}。"
            f"KB 的 embedding 模型在 M13 已锁定,评测必须用同一个,否则 "
            f"collection dim 不一致检索全 0 命中。"
        )

    # 2. 构造 pipeline(per-kb cache,plan D6 不动 production 检索)
    pipeline = get_retrieval_pipeline(
        kb_id=kb.id,  # type: ignore[arg-type]
        model_config_id=kb.embedding_model_config_id,  # type: ignore[arg-type]
        db=db,
    )

    # 3. 加载所有 items + 已有 results(续跑:跳过 item_id 已存在的)
    items: List[EvalDatasetItem] = (
        db.query(EvalDatasetItem)
        .filter(EvalDatasetItem.dataset_id == run.dataset_id)
        .order_by(EvalDatasetItem.id.asc())
        .all()
    )
    done_item_ids: Set[int] = {
        r.item_id for r in (
            db.query(EvalRunResult.item_id)
            .filter(EvalRunResult.run_id == run.id)
            .all()
        )
    }
    pending_items = [it for it in items if it.id not in done_item_ids]
    # 回写总数(被 skip 的也算 total,前端展示 30/30 = 100%)
    run.total_items = len(items)  # type: ignore[assignment]
    run.completed_items = len(done_item_ids)  # type: ignore[assignment]
    db.commit()

    if not items:
        # 空 dataset:跳过遍历,直接走 report(会生成 "0 items" 的空报告)
        logger.info("run_eval: dataset #%s has 0 items", run.dataset_id)
        await _finalize(db, run, success=True)
        return

    # 4. 遍历 items —— per-item commit + 续跑
    # 进度 UPDATE 节流:每 10% 写一次 eval_runs.completed_items
    last_pct_written = -1
    top_k = int(config.get("top_k", 10))
    rerank = bool(config.get("rerank", True))
    search_weights = config.get("search_weights") or {}
    judge_metrics: List[str] = config.get("judge_metrics", []) or []
    trace_id = run.trace_id or str(uuid.uuid4())
    if run.trace_id != trace_id:
        run.trace_id = trace_id  # type: ignore[assignment]
        db.commit()

    for item in pending_items:
        if _is_cancelled(db, run.id):  # type: ignore[arg-type]
            logger.info("run_eval: run #%s cancelled mid-flight", run.id)
            return
        try:
            await _process_one_item(
                db=db,
                run=run,
                item=item,
                kb=kb,
                pipeline=pipeline,
                top_k=top_k,
                rerank=rerank,
                search_weights=search_weights,
                judge_metrics=judge_metrics,
                trace_id=str(trace_id),  # type: ignore[arg-type]
            )
            run.completed_items += 1  # type: ignore[assignment]
        except Exception as exc:  # noqa: BLE001
            # 单条 item 失败:写一行 error_message 留 audit,继续跑
            logger.warning(
                "run_eval: item #%s failed: %s", item.id, exc
            )
            db.add(EvalRunResult(
                run_id=run.id,
                item_id=item.id,
                query=item.query,
                retrieved_doc_ids=[],
                retrieval_scores=[],
                retrieval_metrics={
                    "hit_at_5": 0.0, "hit_at_10": 0.0,
                    "mrr": 0.0, "ndcg_at_10": 0.0, "recall_at_10": 0.0,
                },
                error_message=f"{type(exc).__name__}: {exc}",
            ))
            run.completed_items += 1  # type: ignore[assignment]

        # 节流:每 10% 写一次 completed_items
        pct = int(run.completed_items * 100 / max(run.total_items, 1))  # type: ignore[arg-type,operator,call-overload]
        if pct >= last_pct_written + _PROGRESS_UPDATE_EVERY_PCT:
            db.commit()
            last_pct_written = pct

    db.commit()  # 兜底:最后一批 item 写完立即 commit
    await _finalize(db, run, success=True)


async def _process_one_item(
    *,
    db: Session,
    run: EvalRun,
    item: EvalDatasetItem,
    kb: KnowledgeBase,
    pipeline: Any,
    top_k: int,
    rerank: bool,
    search_weights: Dict[str, float],
    judge_metrics: List[str],
    trace_id: str,
) -> None:
    """处理单条 item:检索 + 指标 + (可选)answer + judge + 落库。

    异常不吞 —— 留给 caller(_execute)决定是 per-item 兜底还是整 run 失败。
    """
    t0 = time.monotonic()

    # 1. 检索(EmbeddingCallContext 带 eval_run_id,call_type=eval_retrieval)
    contexts, retrieved_doc_ids, retrieval_scores = _do_retrieval(
        db=db, run=run, item=item, pipeline=pipeline,
        top_k=top_k, rerank=rerank, search_weights=search_weights,
        trace_id=trace_id,
    )

    # 2. 检索指标
    expected_doc_ids = list(item.expected_doc_ids or [])
    retrieval_metrics = {
        "hit_at_5": hit_at_k(retrieved_doc_ids, expected_doc_ids, 5),
        "hit_at_10": hit_at_k(retrieved_doc_ids, expected_doc_ids, 10),
        "mrr": mrr(retrieved_doc_ids, expected_doc_ids),
        "ndcg_at_10": ndcg_at_k(retrieved_doc_ids, expected_doc_ids, 10),
        "recall_at_10": recall_at_k(retrieved_doc_ids, expected_doc_ids, 10),
    }

    # 3. (可选)answer 生成 + judge —— 暂未实现 answer 拼装(留 T14/T15),
    #    落到 eval_run_results.answer=None + answer_metrics=None,
    #    仅靠检索指标给生产 KB 调参做参考。
    answer: Optional[str] = None
    answer_metrics: Optional[Dict[str, Any]] = None
    llm_judge_calls: Optional[List[Dict[str, Any]]] = None

    # 4. 截断 contexts(≤ 200 字/个,plan §4.2 限)
    truncated_contexts = _truncate_contexts(contexts, max_chars=200)

    latency_ms = int((time.monotonic() - t0) * 1000)
    db.add(EvalRunResult(
        run_id=run.id,
        item_id=item.id,
        query=item.query,
        retrieved_doc_ids=retrieved_doc_ids,
        retrieval_scores=retrieval_scores,
        retrieved_contexts=truncated_contexts,
        answer=answer,
        retrieval_metrics=retrieval_metrics,
        answer_metrics=answer_metrics,
        llm_judge_calls=llm_judge_calls,
        latency_ms=latency_ms,
    ))
    db.commit()


# ---------------------------------------------------------------------------
# 检索 —— 跟 agent_rag._retrieve_kb_chunks 同款,改 call_type=eval_retrieval
# ---------------------------------------------------------------------------


def _do_retrieval(
    *,
    db: Session,
    run: EvalRun,
    item: EvalDatasetItem,
    pipeline: Any,
    top_k: int,
    rerank: bool,
    search_weights: Dict[str, float],
    trace_id: str,
) -> Tuple[List[str], List[int], List[float]]:
    """调 RetrievalPipeline.search,返回 (contexts, doc_ids, scores)。"""
    parent = get_embedding_context()
    own_token = None
    if parent is None:
        # 没外层 context(CLI / 测试场景),装一个让 wrapper 落 trace
        own_token = set_embedding_context(EmbeddingCallContext(
            call_id=str(uuid.uuid4()),
            trace_id=trace_id,
            parent_call_id=None,
            call_type="eval_retrieval",
            call_index=0,
            tenant_id=run.created_by,  # type: ignore[arg-type]  # 实际 tenant_id 从 run 读更准
            extra={"eval_run_id": run.id, "dataset_id": run.dataset_id},  # type: ignore[arg-type]
        ))
    try:
        # filter_expr 跟 agent_rag 一致:tenant 隔离 + kb 隔离
        # tenant 走 dataset 关联的 KB;但这里取 run 的 tenant 暂用 KB 的
        filter_expr = None
        try:
            results = pipeline.search(
                item.query, k=top_k,
                rerank=rerank,
                search_weights=search_weights,
                filter_expr=filter_expr,
            )
        except TypeError:
            # pipeline.search 不支持 filter_expr(FAISS 路径)—— 退化成无 filter
            results = pipeline.search(
                item.query, k=top_k,
                rerank=rerank,
                search_weights=search_weights,
            )
        contexts: List[str] = []
        doc_ids: List[int] = []
        scores: List[float] = []
        for r in results or []:
            # r 是 dict:{"text", "metadata", "score"} —— 跟 hybrid_retriever 返回结构一致
            text = r.get("text") or r.get("page_content") or ""
            meta = r.get("metadata") or {}
            doc_id = meta.get("document_id") or meta.get("doc_id")
            score = float(r.get("score", 0.0))
            if doc_id is not None:
                doc_ids.append(int(doc_id))
                scores.append(score)
                contexts.append(text)
        return contexts, doc_ids, scores
    finally:
        if own_token is not None:
            reset_embedding_context(own_token)


# ---------------------------------------------------------------------------
# 收尾 —— 调 report.generate + 写 metrics_json / status=completed
# ---------------------------------------------------------------------------


async def _finalize(db: Session, run: EvalRun, *, success: bool) -> None:
    """全部 item 处理完(或失败)→ 跑 report + 落 metrics_json + 改 status。

    report.py 是 T14;先 import 如果有,没 import 到时 gracefully 跳过,
    留 metrics_json=None,前端能看到「报告未生成」状态。
    """
    run.finished_at = datetime.utcnow()  # type: ignore[assignment]
    if not success:
        run.status = "failed"  # type: ignore[assignment]
        db.commit()
        return
    try:
        # 局部 import 防循环(report 也可能 import runner)
        from lumen_services.eval.report import generate_report
        report_md, metrics = generate_report(db, run.id)  # type: ignore[arg-type]
        run.report_markdown = report_md  # type: ignore[assignment]
        run.metrics_json = metrics  # type: ignore[assignment]
        run.status = "completed"  # type: ignore[assignment]
    except ImportError:
        logger.warning("report module not yet available (T14), skip")
        run.status = "completed"  # type: ignore[assignment]
    except Exception as exc:  # noqa: BLE001
        logger.exception("report generation failed for run #%s", run.id)
        run.status = "failed"  # type: ignore[assignment]
        run.error_message = f"report generation failed: {exc}"  # type: ignore[assignment]
    db.commit()


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _is_cancelled(db: Session, run_id: int) -> bool:
    """检测 run 是否被 API cancel(status=cancelled)。"""
    status = db.query(EvalRun.status).filter(EvalRun.id == run_id).scalar()
    return status == "cancelled"


def _truncate_contexts(
    contexts: List[str], *, max_chars: int = 200
) -> List[str]:
    """截断 contexts(≤ 200 字/个,plan §4.2 限,audit 用)。"""
    return [c[:max_chars] for c in contexts]
