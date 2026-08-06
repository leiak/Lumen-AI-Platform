"""M37.2 — 评测报告生成:聚合 metrics_json + Markdown 报告。

入口 ``generate_report(db, run_id)`` 返回 ``(markdown, metrics_dict)``,
由 ``runner._finalize()`` 在所有 item 跑完后调用一次。

设计要点:

- **空 dataset / 全失败**:不 raise,返回空 markdown + 全 0 metrics。
  spec §4.2 示例格式保持不变 —— 前端看到 hit_at_5 = 0 直接展示,不会崩。
- **error_message 非空的结果行**:跳过参与聚合(不污染 hit_at_5 等)。
  error 行单算「failure 列表」,在 report 的「Failures」段展示。
- **by_category / by_difficulty 分组聚合**:用 ``EvalDatasetItem.category
  / .difficulty`` 作为分组键;某分组无结果时该 key 缺失(不要返 0.0 干扰雷达图)。
- **Markdown 上限 50KB**(spec §4.2 限),超长截断并加「...truncated」
  标记;failure 段最多 20 条(item 多时不全列)。
- **不做 baseline 对比**:spec 示例里 `Δ vs baseline #38` 是相对另一个 run
  的对比,由 ``compare.py`` 单独出;report.py 只生成单 run 视图。

Spec: docs-internal/superpowers/specs/m37-rag-evaluation.md §4.2
Plan: docs-internal/superpowers/plans/m37-plan.md CP4 T14
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from lumen_models.eval_run import EvalRun, EvalRunResult
from lumen_models.eval_dataset import EvalDatasetItem
from lumen_models.knowledge import KnowledgeBase
from lumen_models.model_config import ModelConfig
from lumen_services.eval.metrics import aggregate

logger = logging.getLogger(__name__)


# Markdown 报告的硬限(spec §4.2)—— 超长截断防止 DB TEXT 撑爆
_REPORT_MAX_BYTES = 50 * 1024  # 50KB

# 失败列表最多展示数(超出按 mrr 升序取前 N 条)
_FAILURE_TOP_N = 20


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------


def generate_report(db: Session, run_id: int) -> Tuple[Optional[str], Dict[str, Any]]:
    """聚合 ``eval_run_results`` → ``(report_markdown, metrics_json)``。

    Args:
        db: SQLAlchemy session。
        run_id: EvalRun.id。

    Returns:
        ``(markdown, metrics)`` 元组:
        - markdown: 字符串;run 不存在 / 状态不是 completed 且没有 results
          时返 ``None``(让 runner 跳过 report,留 metrics_json 字段给前端
          区分「报告未生成」 vs 「报告生成失败」)。
        - metrics: 整体聚合 dict,跟 spec §4.2 示例一致;空 dataset 时
          字段齐全、值全 0.0。

    异常策略:
    - DB IO / Pydantic 校验失败 → logger.exception + 返回 ``(None, {})``
      —— 跟 runner 一样不 raise,让外层跑完 status=completed 把 metrics
      写空也行,不阻断 dashboard 看板(只是少了雷达图)。
    """
    run = db.get(EvalRun, run_id)
    if run is None:
        logger.error("generate_report: EvalRun #%s not found", run_id)
        return None, {}

    # 加载所有 results + 对应 items(JOIN 一次性拿 category / difficulty)
    #   error_message 非空 → 仍 SELECT 出来,但下面聚合时跳过
    rows: List[Tuple[EvalRunResult, Optional[EvalDatasetItem]]] = []
    raw_results = (
        db.query(EvalRunResult)
        .filter(EvalRunResult.run_id == run_id)
        .all()
    )
    item_ids = {int(r.item_id) for r in raw_results}
    items_by_id: Dict[int, EvalDatasetItem] = {}
    if item_ids:
        items_by_id = {
            int(it.id): it for it in (  # type: ignore[misc]
                db.query(EvalDatasetItem)
                .filter(EvalDatasetItem.id.in_(item_ids))
                .all()
            )
        }
    for r in raw_results:
        rows.append((r, items_by_id.get(int(r.item_id))))  # type: ignore[call-overload]

    metrics = _build_metrics(rows)
    markdown = _build_markdown(db, run, rows, metrics)
    return markdown, metrics


# ---------------------------------------------------------------------------
# metrics_json 聚合
# ---------------------------------------------------------------------------


def _build_metrics(
    rows: List[Tuple[EvalRunResult, Optional[EvalDatasetItem]]],
) -> Dict[str, Any]:
    """聚合检索 / 答案 / 分组指标。

    Args:
        rows: (result, item) 元组列表。item 可能 None(result 写入时 item
            已 CASCADE 删除,留给 audit 看到「dangling result」)。

    Returns:
        跟 spec §4.2 示例完全对齐的 dict。空 rows → 全 0.0 + 空分组。
    """
    # 1. 拆分 success / failed
    success_results = [r for r, _ in rows if r.error_message is None]
    failed_results = [r for r, _ in rows if r.error_message is not None]

    # 2. retrieval 段 —— 整体聚合(hit/mrr/ndcg/recall + latency)
    retrieval_metrics_values: Dict[str, List[float]] = {
        "hit_at_5": [],
        "hit_at_10": [],
        "mrr": [],
        "ndcg_at_10": [],
        "recall_at_10": [],
    }
    latencies: List[float] = []
    for r in success_results:
        rm: Dict[str, Any] = dict(r.retrieval_metrics or {})
        for k in retrieval_metrics_values:
            v = rm.get(k)
            if v is not None:
                retrieval_metrics_values[k].append(float(v))
        if r.latency_ms is not None:
            latencies.append(float(r.latency_ms))  # type: ignore[arg-type]

    retrieval_agg: Dict[str, float] = {}
    for k, vals in retrieval_metrics_values.items():
        a = aggregate(vals)
        retrieval_agg[k] = round(a["mean"], 4)
    # latency 用 p50/p95(延迟天然长尾,mean 会被 1 个长尾污染)
    if latencies:
        lat_a = aggregate(latencies)
        retrieval_agg["latency_ms_p50"] = int(lat_a["p50"])
        retrieval_agg["latency_ms_p95"] = int(lat_a["p95"])
    else:
        retrieval_agg["latency_ms_p50"] = 0
        retrieval_agg["latency_ms_p95"] = 0

    # 3. answer 段 —— keyword_hit_rate / faithfulness / answer_relevancy
    keyword_hits: List[float] = []
    faithfulness_vals: List[float] = []
    relevancy_vals: List[float] = []
    llm_judge_calls = 0
    for r in success_results:
        am: Dict[str, Any] = dict(r.answer_metrics or {})
        # keyword_hit_rate 即使 judge 跳过也会算(规则指标)
        if am.get("keyword_hit_rate") is not None:
            keyword_hits.append(float(am["keyword_hit_rate"]))
        if am.get("faithfulness") is not None:
            faithfulness_vals.append(float(am["faithfulness"]))
        if am.get("answer_relevancy") is not None:
            relevancy_vals.append(float(am["answer_relevancy"]))
        # llm_judge_calls 是 list,数 length = 真实 judge 调用次数
        if r.llm_judge_calls:
            llm_judge_calls += len(r.llm_judge_calls)

    answer_agg: Dict[str, Any] = {
        "keyword_hit_rate": round(aggregate(keyword_hits)["mean"], 4),
        "faithfulness_avg": round(aggregate(faithfulness_vals)["mean"], 4),
        "answer_relevancy_avg": round(aggregate(relevancy_vals)["mean"], 4),
        "llm_judge_total_calls": llm_judge_calls,
    }

    # 4. by_category / by_difficulty 分组
    by_category = _aggregate_by_group(
        success_results, rows, group_key="category"
    )
    by_difficulty = _aggregate_by_group(
        success_results, rows, group_key="difficulty"
    )

    return {
        "retrieval": retrieval_agg,
        "answer": answer_agg,
        "by_category": by_category,
        "by_difficulty": by_difficulty,
        "totals": {
            "items_total": len(rows),
            "items_success": len(success_results),
            "items_failed": len(failed_results),
        },
    }


def _aggregate_by_group(
    success_results: List[EvalRunResult],
    rows: List[Tuple[EvalRunResult, Optional[EvalDatasetItem]]],
    *,
    group_key: str,
) -> Dict[str, Dict[str, float]]:
    """按 EvalDatasetItem.{group_key} 分组聚合 hit_at_5 + mrr。

    Args:
        success_results: 跑成功的 result 行(不参与失败的 item)。
        rows: 完整 rows(用来建 result_id → item 反查表)。
        group_key: ``"category"`` 或 ``"difficulty"``。

    Returns:
        ``{group_value: {"hit_at_5": x, "mrr": y, "count": n}}``。
        group_value 为 None 的归入 ``"(unset)"``;空分组时该 key 不出现。
    """
    item_by_result_id: Dict[int, Optional[EvalDatasetItem]] = {
        id(r): item for r, item in rows
    }
    buckets: Dict[str, Dict[str, List[float]]] = defaultdict(
        lambda: {"hit_at_5": [], "mrr": []}
    )
    for r in success_results:
        item = item_by_result_id.get(id(r))
        group_val = getattr(item, group_key, None) if item else None
        # None / 空串 → 归入 "(unset)" 防止字典 key 缺失
        group_key_str = group_val if group_val else "(unset)"
        rm: Dict[str, Any] = dict(r.retrieval_metrics or {})
        if rm.get("hit_at_5") is not None:
            buckets[group_key_str]["hit_at_5"].append(float(rm["hit_at_5"]))
        if rm.get("mrr") is not None:
            buckets[group_key_str]["mrr"].append(float(rm["mrr"]))

    out: Dict[str, Dict[str, float]] = {}
    for group_val, metrics in buckets.items():
        if not metrics["hit_at_5"] and not metrics["mrr"]:
            continue  # 空 bucket 不出 key,前端按需 fallback
        out[group_val] = {
            "hit_at_5": round(aggregate(metrics["hit_at_5"])["mean"], 4),
            "mrr": round(aggregate(metrics["mrr"])["mean"], 4),
            "count": len(metrics["hit_at_5"]),
        }
    return out


# ---------------------------------------------------------------------------
# Markdown 报告
# ---------------------------------------------------------------------------


def _build_markdown(
    db: Session,
    run: EvalRun,
    rows: List[Tuple[EvalRunResult, Optional[EvalDatasetItem]]],
    metrics: Dict[str, Any],
) -> Optional[str]:
    """渲染 Markdown 报告(≤ 50KB,超长截断)。

    Args:
        db: 用于查 KB / ModelConfig 名字(报告里要展示「embedding: bge-m3」)。
        run: 当前 EvalRun ORM。
        rows: 完整 rows(失败列表用)。
        metrics: 已经聚合好的 metrics dict(复用检索指标)。

    Returns:
        Markdown 字符串;rows 为空 → 返一个 minimal 报告(说明「无 item」),
        让 dashboard 不会显示「未生成」歧义。
    """
    kb_name = _resolve_kb_name(db, run)
    emb_name = _resolve_model_name(db, run, "embedding_model_config_id")
    judge_name = _resolve_model_name(db, run, "judge_model_config_id")
    finished_at_str = (
        run.finished_at.strftime("%Y-%m-%d %H:%M") if run.finished_at else "N/A"
    )

    lines: List[str] = []
    lines.append(
        f"# Eval Run #{run.id} — KB \"{kb_name}\" ({finished_at_str})"
    )
    lines.append("")

    # Config
    lines.append("## Config")
    cfg: Dict[str, Any] = dict(run.config_json or {})
    sw = cfg.get("search_weights") or {}
    lines.append(
        f"- search_weights: {sw if sw else '{}'}"
    )
    lines.append(
        f"- top_k: {cfg.get('top_k', 'N/A')}, "
        f"rerank: {cfg.get('rerank', 'N/A')}"
    )
    lines.append(f"- embedding: {emb_name}")
    lines.append(f"- judge: {judge_name}")
    if cfg.get("judge_metrics"):
        lines.append(f"- judge_metrics: {cfg['judge_metrics']}")
    lines.append("")

    # Retrieval metrics
    totals = metrics.get("totals", {})
    total_items = totals.get("items_total", 0)
    retrieval = metrics.get("retrieval", {})
    answer = metrics.get("answer", {})
    lines.append(f"## Retrieval Metrics ({total_items} items)")
    lines.append("| Metric       | Value |")
    lines.append("|--------------|-------|")
    for k, label in [
        ("hit_at_5", "Hit@5"),
        ("hit_at_10", "Hit@10"),
        ("mrr", "MRR"),
        ("ndcg_at_10", "NDCG@10"),
        ("recall_at_10", "Recall@10"),
    ]:
        v = retrieval.get(k, 0.0)
        lines.append(f"| {label:<12} | {v:.4f} |")
    lines.append(
        f"| latency p50  | {retrieval.get('latency_ms_p50', 0)} ms |"
    )
    lines.append(
        f"| latency p95  | {retrieval.get('latency_ms_p95', 0)} ms |"
    )
    lines.append("")

    # Answer metrics
    lines.append("## Answer Metrics")
    lines.append("| Metric            | Value |")
    lines.append("|-------------------|-------|")
    lines.append(
        f"| keyword_hit_rate  | {answer.get('keyword_hit_rate', 0.0):.4f} |"
    )
    lines.append(
        f"| faithfulness_avg  | {answer.get('faithfulness_avg', 0.0):.2f} |"
    )
    lines.append(
        f"| answer_relevancy_avg | {answer.get('answer_relevancy_avg', 0.0):.2f} |"
    )
    lines.append(
        f"| llm_judge_calls   | {answer.get('llm_judge_total_calls', 0)} |"
    )
    lines.append("")

    # By Category
    by_cat = metrics.get("by_category", {})
    if by_cat:
        lines.append("## By Category")
        for cat, m in sorted(by_cat.items()):
            lines.append(
                f"- {cat}: hit@5 = {m['hit_at_5']:.4f}, "
                f"mrr = {m['mrr']:.4f} (n={m['count']})"
            )
        lines.append("")

    # By Difficulty
    by_diff = metrics.get("by_difficulty", {})
    if by_diff:
        lines.append("## By Difficulty")
        for diff, m in sorted(by_diff.items()):
            lines.append(
                f"- {diff}: hit@5 = {m['hit_at_5']:.4f}, "
                f"mrr = {m['mrr']:.4f} (n={m['count']})"
            )
        lines.append("")

    # Failures(top N by worst mrr)
    failed_rows = [(r, it) for r, it in rows if r.error_message]
    if failed_rows:
        lines.append(
            f"## Failures ({len(failed_rows)} of {total_items})"
        )
        for r, _it in failed_rows[:_FAILURE_TOP_N]:
            lines.append(
                f"- result #{r.id}: query=\"{_truncate(str(r.query), 80)}\", "  # type: ignore[arg-type]
                f"error=\"{_truncate(str(r.error_message or ''), 120)}\""  # type: ignore[arg-type]
            )
        if len(failed_rows) > _FAILURE_TOP_N:
            lines.append(
                f"- ... {len(failed_rows) - _FAILURE_TOP_N} more failures"
            )
        lines.append("")

    # Worst retrieval(非 error 但 mrr 最低)
    worst = _worst_retrieval_rows(rows, top_n=5)
    if worst:
        lines.append("## Worst Retrieval (top 5 by MRR)")
        for r in worst:
            got: List[Any] = list(r.retrieved_doc_ids or [])
            rm: Dict[str, Any] = dict(r.retrieval_metrics or {})
            mrr_v = rm.get("mrr", 0.0)
            lines.append(
                f"- result #{r.id}: query=\"{_truncate(str(r.query), 60)}\", "  # type: ignore[arg-type]
                f"got=[{', '.join(str(x) for x in got[:5])}], "
                f"mrr={float(mrr_v):.3f}"  # type: ignore[arg-type]
            )
        lines.append("")

    md = "\n".join(lines).rstrip() + "\n"
    if len(md.encode("utf-8")) > _REPORT_MAX_BYTES:
        logger.warning(
            "report for run #%s exceeds %s bytes, truncating",
            run.id, _REPORT_MAX_BYTES,
        )
        # 保留 Config + Retrieval + Answer 三个核心段,后段裁掉
        md = _truncate_markdown(md, _REPORT_MAX_BYTES)
    return md


def _worst_retrieval_rows(
    rows: List[Tuple[EvalRunResult, Optional[EvalDatasetItem]]],
    *,
    top_n: int = 5,
) -> List[EvalRunResult]:
    """返回 mrr 最低的 top N 条 success result。

    Args:
        rows: 完整 rows。
        top_n: 最多返回 N 条。

    Returns:
        排好序的 result 列表(mrr 升序,失败行已被过滤)。
    """
    success = [
        r for r, _ in rows
        if r.error_message is None and (dict(r.retrieval_metrics or {})).get("mrr") is not None
    ]
    success.sort(key=lambda r: float(dict(r.retrieval_metrics or {}).get("mrr", 0.0)))  # type: ignore[call-overload,arg-type]
    return success[:top_n]


def _resolve_kb_name(db: Session, run: EvalRun) -> str:
    dataset = run.dataset
    if dataset is None:
        return "(deleted)"
    kb = dataset.kb
    return kb.name if kb else "(deleted)"


def _resolve_model_name(
    db: Session, run: EvalRun, config_key: str
) -> str:
    """按 config_key 从 run.config_json 取 model_config_id → 查 ModelConfig.name。

    失败(配置没填 / model 被删)→ 返 ``"(unset)"`` 或 ``"(deleted)"``,
    让 dashboard 明确知道是配置问题,而不是显示莫名空白。
    """
    cfg: Dict[str, Any] = dict(run.config_json or {})
    mc_id = cfg.get(config_key)
    if mc_id is None:
        return "(unset)"
    mc = db.get(ModelConfig, int(mc_id))
    if mc is None:
        return f"(id={mc_id}, deleted)"
    return f"{mc.name} (id={mc.id})"


def _truncate(s: str, max_chars: int) -> str:
    if len(s) <= max_chars:
        return s
    return s[: max_chars - 1] + "…"


def _truncate_markdown(md: str, max_bytes: int) -> str:
    """超长时按字节截断 + 加 truncation 标记。"""
    encoded = md.encode("utf-8")
    if len(encoded) <= max_bytes:
        return md
    # 留 100 字节放 truncation 标记
    truncated = encoded[: max_bytes - 100].decode("utf-8", errors="ignore")
    return truncated + "\n\n...*(报告超 50KB,后续内容已截断)*\n"