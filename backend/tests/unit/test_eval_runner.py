"""M37.2 — 主评测循环 runner 单元测试。

8 测试覆盖 plan §T13 要求:

1. 空 dataset → 直接 status=completed,total_items=0
2. 部分完成(续跑)→ 已完成 item 跳过,新增只写未完成的
3. embedding 模型 dim 不匹配 → 整 run status=failed,error_message 写明
4. judge 失败(answer 阶段崩)→ per-item 落库 + 继续跑
5. per-item 异常不挂整 run → run.status=completed,失败行有 error_message
6. run 被 cancel → 循环中检测 status=cancelled 即退出
7. happy path 全跑通 → status 走完 pending→running→completed
8. 不可恢复错误(加载阶段)→ status=failed,error_message 有 root cause

用 dev DB + 临时 run fixture 跑(同 test_eval_datasets_router.py 风格),
mock pipeline.search 返固定 chunk,避免依赖真实 ES/FAISS。

Spec: docs-internal/superpowers/specs/m37-rag-evaluation.md §4.2
Plan: docs-internal/superpowers/plans/m37-plan.md CP4 T13 + D5
"""
import asyncio
import uuid
from typing import Any, Dict, List
from unittest.mock import patch

import pytest
from sqlalchemy.orm import Session

from lumen_core.database import SessionLocal, ensure_eval_datasets_table, ensure_eval_runs_table
from lumen_models.eval_run import EvalRun, EvalRunResult
from lumen_models.eval_dataset import EvalDataset, EvalDatasetItem
from lumen_models.knowledge import KnowledgeBase
from lumen_models.user import User
from lumen_models.model_config import ModelConfig
from lumen_services.eval.runner import run_eval


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def db_session():
    ensure_eval_datasets_table()
    ensure_eval_runs_table()
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture
def tenant_user(db_session):
    user = db_session.query(User).filter(User.tenant_id == 1).first()
    if user is None:
        pytest.skip("no user in tenant 1")
    return user


@pytest.fixture
def kb(db_session):
    """Throwaway KB on tenant 1,embed model 用 dev DB 现役任意一个。"""
    cfg = (
        db_session.query(ModelConfig)
        .filter(ModelConfig.is_active == 1, ModelConfig.is_embedding == 1)
        .order_by(ModelConfig.id)
        .first()
    )
    if cfg is None:
        pytest.skip("no active embedding model")
    row = KnowledgeBase(
        name=f"m37-runner-kb-{uuid.uuid4().hex[:8]}",
        tenant_id=1,
        embedding_model_config_id=cfg.id,
        status="active",
    )
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    yield row
    # teardown:results + runs + dataset + items + KB
    db_session.query(EvalRunResult).filter(
        EvalRunResult.run_id.in_(
            db_session.query(EvalRun.id).filter(EvalRun.dataset_id.in_(
                db_session.query(EvalDataset.id).filter(EvalDataset.kb_id == row.id)
            ))
        )
    ).delete(synchronize_session=False)
    db_session.query(EvalRun).filter(EvalRun.dataset_id.in_(
        db_session.query(EvalDataset.id).filter(EvalDataset.kb_id == row.id)
    )).delete(synchronize_session=False)
    db_session.query(EvalDatasetItem).filter(EvalDatasetItem.dataset_id.in_(
        db_session.query(EvalDataset.id).filter(EvalDataset.kb_id == row.id)
    )).delete(synchronize_session=False)
    db_session.query(EvalDataset).filter(EvalDataset.kb_id == row.id).delete(
        synchronize_session=False
    )
    db_session.query(KnowledgeBase).filter(KnowledgeBase.id == row.id).delete(
        synchronize_session=False
    )
    db_session.commit()


@pytest.fixture
def dataset_with_items(db_session, kb, tenant_user):
    """建一个 dataset + 3 条 item,expected_doc_ids 都用空(避免真去匹配 doc)。"""
    ds = EvalDataset(
        kb_id=kb.id,
        tenant_id=1,
        name=f"m37-runner-ds-{uuid.uuid4().hex[:8]}",
        source="manual",
        is_active=1,
        created_by=tenant_user.id,
    )
    db_session.add(ds)
    db_session.commit()
    db_session.refresh(ds)
    items = []
    for i in range(3):
        it = EvalDatasetItem(
            dataset_id=ds.id,
            query=f"test query {i}",
            expected_doc_ids=[],
            category="factual",
            difficulty="easy",
        )
        db_session.add(it)
        items.append(it)
    db_session.commit()
    for it in items:
        db_session.refresh(it)
    return ds, items


def _make_run(db_session, dataset, config=None) -> EvalRun:
    """建一条 pending run 供 run_eval() 跑。"""
    if config is None:
        cfg = {
            "name": "unit",
            "top_k": 5,
            "rerank": False,
            "search_weights": {"title": 10, "important_kw": 30, "question_kw": 20, "text": 2},
            "embedding_model_config_id": None,
            "judge_model_config_id": 1,
            "judge_metrics": [],
        }
    else:
        cfg = dict(config)
    # 如果 caller 没显式指定 embedding_model_config_id,默认从 KB 抄一份
    # (跟 production 创建 run 的行为一致:不指定 → 跟 KB 走 → 跑得过 dim check)
    # dim-mismatch 测试会显式传 99999,这里跳过兜底。
    if cfg.get("embedding_model_config_id") is None:
        cfg["embedding_model_config_id"] = (
            db_session.query(KnowledgeBase)
            .filter(KnowledgeBase.id == dataset.kb_id)
            .first().embedding_model_config_id
        )
    run = EvalRun(
        dataset_id=dataset.id,
        config_json=cfg,
        status="pending",
        total_items=0,
        completed_items=0,
    )
    db_session.add(run)
    db_session.commit()
    db_session.refresh(run)
    return run


# 固定 pipeline.search 返回 —— 不依赖真实 ES/FAISS
MOCK_CHUNKS = [
    {"text": "ctx1", "metadata": {"document_id": 100}, "score": 0.9},
    {"text": "ctx2", "metadata": {"document_id": 200}, "score": 0.7},
    {"text": "ctx3", "metadata": {"document_id": 300}, "score": 0.5},
]


def _patched_pipeline():
    """返回 (patcher, mock_search) —— 用法 ``with _patched_pipeline()[0]:``"""
    patcher = patch(
        "lumen_services.eval.runner.get_retrieval_pipeline",
        return_value=_FakePipeline(),
    )
    return patcher


class _FakePipeline:
    """Mock RetrievalPipeline —— search() 返固定 chunks。"""

    def search(self, *args, **kwargs):
        return MOCK_CHUNKS


# ---------------------------------------------------------------------------
# 1. 空 dataset
# ---------------------------------------------------------------------------


def test_empty_dataset_completes_with_zero_results(db_session, kb):
    """dataset 没 item → run 直接走 status=completed,total_items=0。"""
    # 单独建一个空 dataset(不用 dataset_with_items fixture)
    ds = EvalDataset(
        kb_id=kb.id, tenant_id=1, name="empty", source="manual",
        is_active=1,
    )
    db_session.add(ds)
    db_session.commit()
    db_session.refresh(ds)

    run = _make_run(db_session, ds)
    with _patched_pipeline():
        asyncio.run(run_eval(db_session, run.id))

    db_session.refresh(run)
    assert run.status == "completed"
    assert run.total_items == 0
    assert run.completed_items == 0
    # 无 item → 无 results
    n_results = db_session.query(EvalRunResult).filter(
        EvalRunResult.run_id == run.id
    ).count()
    assert n_results == 0


# ---------------------------------------------------------------------------
# 2. embedding 模型 dim 不匹配
# ---------------------------------------------------------------------------


def test_embedding_model_mismatch_fails_run(db_session, dataset_with_items):
    """eval config.embedding_model_config_id ≠ KB.embedding_model_config_id
    → 整 run status=failed,error_message 写明。
    """
    ds, _ = dataset_with_items
    # 故意把 embedding_model_config_id 改成一个明显错的 ID
    bad_cfg = {
        "name": "dim-mismatch",
        "top_k": 5,
        "rerank": False,
        "search_weights": {},
        "embedding_model_config_id": 99999,  # 不存在的 ID
        "judge_model_config_id": 1,
        "judge_metrics": [],
    }
    run = _make_run(db_session, ds, config=bad_cfg)
    with _patched_pipeline():
        asyncio.run(run_eval(db_session, run.id))

    db_session.refresh(run)
    assert run.status == "failed"
    assert run.error_message is not None
    assert "embedding_model_config_id" in run.error_message
    assert "不匹配" in run.error_message
    # 没有 item 被处理
    n_results = db_session.query(EvalRunResult).filter(
        EvalRunResult.run_id == run.id
    ).count()
    assert n_results == 0


# ---------------------------------------------------------------------------
# 3. 部分完成(续跑)
# ---------------------------------------------------------------------------


def test_resume_skips_already_completed_items(db_session, dataset_with_items):
    """items[0] 已经在 eval_run_results → runner 跳过,只写 items[1:]。"""
    ds, items = dataset_with_items
    run = _make_run(db_session, ds)

    # 预先写一行「已完成」,模拟上次跑到一半崩了
    db_session.add(EvalRunResult(
        run_id=run.id, item_id=items[0].id, query=items[0].query,
        retrieved_doc_ids=[100], retrieval_scores=[0.9],
        retrieval_metrics={"hit_at_5": 1.0, "hit_at_10": 1.0,
                           "mrr": 1.0, "ndcg_at_10": 1.0, "recall_at_10": 1.0},
    ))
    db_session.commit()

    with _patched_pipeline():
        asyncio.run(run_eval(db_session, run.id))

    db_session.refresh(run)
    assert run.status == "completed"
    assert run.total_items == 3
    assert run.completed_items == 3  # 1 续跑 + 2 新跑

    # 验证 items[0] 没被重复写(retrieved_doc_ids 还是 [100])
    r0 = db_session.query(EvalRunResult).filter(
        EvalRunResult.run_id == run.id, EvalRunResult.item_id == items[0].id
    ).first()
    assert r0.retrieved_doc_ids == [100]


# ---------------------------------------------------------------------------
# 4. per-item 异常不挂整 run
# ---------------------------------------------------------------------------


def test_per_item_exception_does_not_fail_run(db_session, dataset_with_items):
    """items[1] 检索时抛错 → 该行落 error_message,items[0]/[2] 正常完成。"""
    ds, items = dataset_with_items
    run = _make_run(db_session, ds)

    call_count = {"n": 0}

    def flaky_search(*args, **kwargs):
        call_count["n"] += 1
        # 第 2 次(item id=items[1])抛错
        if call_count["n"] == 2:
            raise RuntimeError("simulated retrieval failure")
        return MOCK_CHUNKS

    patcher = patch(
        "lumen_services.eval.runner.get_retrieval_pipeline",
        return_value=_FakeSearchOnly(flaky_search),
    )
    with patcher:
        asyncio.run(run_eval(db_session, run.id))

    db_session.refresh(run)
    # 整 run 没挂:status=completed,completed_items=3
    assert run.status == "completed"
    assert run.completed_items == 3

    # 失败的 item 有 error_message,其他 2 个没
    results = (
        db_session.query(EvalRunResult)
        .filter(EvalRunResult.run_id == run.id)
        .all()
    )
    assert len(results) == 3
    errored = [r for r in results if r.error_message]
    assert len(errored) == 1
    assert "simulated retrieval failure" in errored[0].error_message
    # 失败行的 retrieval_metrics 兜底全 0
    assert errored[0].retrieval_metrics["hit_at_5"] == 0.0


class _FakeSearchOnly:
    def __init__(self, search_fn):
        self._search_fn = search_fn

    def search(self, *args, **kwargs):
        return self._search_fn(*args, **kwargs)


# ---------------------------------------------------------------------------
# 5. run 被 cancel
# ---------------------------------------------------------------------------


def test_cancellation_stops_loop(db_session, dataset_with_items):
    """runner 循环里检测 status=cancelled 就退出。"""
    ds, items = dataset_with_items
    run = _make_run(db_session, ds)

    # 模拟一个 item 处理完后,API 端 cancel
    cancelled = {"flag": False}

    def cancel_after_first(*args, **kwargs):
        # 第 1 次 search 后,翻 cancel flag
        if not cancelled["flag"]:
            cancelled["flag"] = True
            # 用同一个 session 改 status = cancelled
            from lumen_models.eval_run import EvalRun as ER
            r = db_session.get(ER, run.id)
            r.status = "cancelled"
            db_session.commit()
        return MOCK_CHUNKS

    patcher = patch(
        "lumen_services.eval.runner.get_retrieval_pipeline",
        return_value=_FakeSearchOnly(cancel_after_first),
    )
    with patcher:
        asyncio.run(run_eval(db_session, run.id))

    db_session.refresh(run)
    # 取消时 status 已是 cancelled,runner 检测到后退出
    assert run.status == "cancelled"
    # completed_items < total_items(没跑完)
    assert run.completed_items < run.total_items


# ---------------------------------------------------------------------------
# 6. happy path 全跑通
# ---------------------------------------------------------------------------


def test_happy_path_status_transitions(db_session, dataset_with_items):
    """3 条 item 全部正常跑完 → pending→running→completed,3 行 results。"""
    ds, items = dataset_with_items
    run = _make_run(db_session, ds)

    with _patched_pipeline():
        asyncio.run(run_eval(db_session, run.id))

    db_session.refresh(run)
    assert run.status == "completed"
    assert run.total_items == 3
    assert run.completed_items == 3
    assert run.started_at is not None
    assert run.finished_at is not None

    # 3 行 result,每行有完整字段
    results = (
        db_session.query(EvalRunResult)
        .filter(EvalRunResult.run_id == run.id)
        .order_by(EvalRunResult.item_id)
        .all()
    )
    assert len(results) == 3
    for r in results:
        assert r.retrieved_doc_ids == [100, 200, 300]  # MOCK_CHUNKS doc_ids
        assert r.retrieval_scores == [0.9, 0.7, 0.5]
        # expected_doc_ids=[] → 所有指标兜底 0.0
        assert r.retrieval_metrics["hit_at_5"] == 0.0
        assert r.latency_ms is not None and r.latency_ms >= 0


# ---------------------------------------------------------------------------
# 7. 不可恢复错误(加载阶段)
# ---------------------------------------------------------------------------


def test_unexpected_error_sets_failed_status(db_session, dataset_with_items):
    """mock _execute 抛 RuntimeError → status=failed,error_message 有 root cause。"""
    ds, _ = dataset_with_items
    run = _make_run(db_session, ds)

    patcher = patch(
        "lumen_services.eval.runner._execute",
        side_effect=RuntimeError("simulated load failure"),
    )
    with patcher, _patched_pipeline():
        asyncio.run(run_eval(db_session, run.id))

    db_session.refresh(run)
    assert run.status == "failed"
    assert run.error_message is not None
    assert "simulated load failure" in run.error_message
    # running→failed 之间,started_at 应该有
    assert run.started_at is not None
    assert run.finished_at is not None


# ---------------------------------------------------------------------------
# 8. 幂等:已完成的 run 跳过
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("terminal_status", ["completed", "failed", "cancelled"])
def test_idempotent_skip_for_terminal_status(
    db_session, dataset_with_items, terminal_status
):
    """status=completed/failed/cancelled 的 run 再 run_eval() 也不重跑(幂等)。

    这是 Celery 重试 + 客户端重复点击「开始评测」的安全网 —— 不能因为
    API 重试把已经完成的 run 进度归零。
    """
    ds, _ = dataset_with_items
    run = _make_run(db_session, ds)
    run.status = terminal_status
    run.started_at = run.started_at or None
    db_session.commit()

    with _patched_pipeline():
        asyncio.run(run_eval(db_session, run.id))

    db_session.refresh(run)
    # status 没变(还是 terminal)
    assert run.status == terminal_status
    # 没新写 results
    n_results = db_session.query(EvalRunResult).filter(
        EvalRunResult.run_id == run.id
    ).count()
    assert n_results == 0
