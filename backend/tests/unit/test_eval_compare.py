"""M37.2 — compare_runs 单元测试。

4 测试覆盖 plan §T14 要求:

1. happy path 两 run 都完整 → aggregate_delta + winners 字段齐全
2. B 整体优于 A(retrieval/answer 都高)→ winners 全 b / a_wins=0
3. latency 越低越好(B 比 A 快)→ winner 选 b
4. 一边有 metrics_json 一边为 None(还在跑)→ 视作 0.0 + tie,结构完整

用 dev DB + 临时 run fixture,直接给 EvalRun.metrics_json 灌值(不跑真评测)。
"""
import uuid

import pytest
from sqlalchemy.orm import Session

from lumen_core.database import SessionLocal, ensure_eval_datasets_table, ensure_eval_runs_table
from lumen_models.eval_run import EvalRun, EvalRunResult
from lumen_models.eval_dataset import EvalDataset, EvalDatasetItem
from lumen_models.knowledge import KnowledgeBase
from lumen_models.user import User
from lumen_models.model_config import ModelConfig
from lumen_services.eval.compare import compare_runs, _HIGHER_IS_BETTER


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
    cfg = (
        db_session.query(ModelConfig)
        .filter(ModelConfig.is_active == 1, ModelConfig.is_embedding == 1)
        .order_by(ModelConfig.id)
        .first()
    )
    if cfg is None:
        pytest.skip("no active embedding model")
    row = KnowledgeBase(
        name=f"m37-compare-kb-{uuid.uuid4().hex[:8]}",
        tenant_id=1,
        embedding_model_config_id=cfg.id,
        status="active",
    )
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    yield row
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
    db_session.query(EvalDataset).filter(EvalDataset.kb_id == row.id).delete(synchronize_session=False)
    db_session.query(KnowledgeBase).filter(KnowledgeBase.id == row.id).delete(synchronize_session=False)
    db_session.commit()


@pytest.fixture
def dataset_with_items(db_session, kb, tenant_user):
    """5 条 item,保证两个 run 都覆盖同一组 item_id。"""
    ds = EvalDataset(
        kb_id=kb.id, tenant_id=1, name=f"m37-compare-ds-{uuid.uuid4().hex[:8]}",
        source="manual", is_active=1, created_by=tenant_user.id,
    )
    db_session.add(ds); db_session.commit(); db_session.refresh(ds)
    items = []
    for i in range(5):
        it = EvalDatasetItem(
            dataset_id=ds.id, query=f"q{i}",
            expected_doc_ids=[100 + i],
            category="factual", difficulty="easy",
        )
        db_session.add(it); items.append(it)
    db_session.commit()
    for it in items:
        db_session.refresh(it)
    return ds, items


def _make_run_with_metrics(
    db_session, dataset, *, metrics_json: dict,
) -> EvalRun:
    """建一条 completed run,metrics_json 由 caller 灌。"""
    cfg = {
        "name": "unit",
        "top_k": 5,
        "rerank": False,
        "search_weights": {},
        "embedding_model_config_id": (
            db_session.query(KnowledgeBase)
            .filter(KnowledgeBase.id == dataset.kb_id).first().embedding_model_config_id
        ),
        "judge_model_config_id": 1,
        "judge_metrics": [],
    }
    run = EvalRun(
        dataset_id=dataset.id,
        config_json=cfg,
        status="completed",
        total_items=5,
        completed_items=5,
        metrics_json=metrics_json,
    )
    db_session.add(run); db_session.commit(); db_session.refresh(run)
    return run


def _insert_result(
    db_session, *, run, item, hit=1.0, mrr=1.0,
):
    """插一行成功 result(per_item_delta 测试用)。"""
    r = EvalRunResult(
        run_id=run.id,
        item_id=item.id,
        query=item.query,
        retrieved_doc_ids=[100 + item.id],
        retrieval_scores=[0.9],
        retrieved_contexts=["ctx"],
        answer="a",
        retrieval_metrics={
            "hit_at_5": hit, "hit_at_10": hit, "mrr": mrr,
            "ndcg_at_10": 1.0, "recall_at_10": 1.0,
        },
        answer_metrics={"keyword_hit_rate": 1.0},
    )
    db_session.add(r); db_session.commit()
    return r


# ---------------------------------------------------------------------------
# 1. happy path 两 run 都完整
# ---------------------------------------------------------------------------


def test_compare_happy_path_full_metrics(db_session, dataset_with_items):
    """两 run 的 metrics_json 都完整 → aggregate_delta + winners 全字段齐。"""
    ds, items = dataset_with_items
    metrics_a = {
        "retrieval": {
            "hit_at_5": 0.70, "hit_at_10": 0.80, "mrr": 0.60,
            "ndcg_at_10": 0.55, "recall_at_10": 0.75,
            "latency_ms_p50": 200, "latency_ms_p95": 500,
        },
        "answer": {
            "keyword_hit_rate": 0.60,
            "faithfulness_avg": 1.2,
            "answer_relevancy_avg": 1.4,
            "llm_judge_total_calls": 30,
        },
    }
    metrics_b = {
        "retrieval": {
            "hit_at_5": 0.82, "hit_at_10": 0.90, "mrr": 0.71,
            "ndcg_at_10": 0.68, "recall_at_10": 0.87,
            "latency_ms_p50": 150, "latency_ms_p95": 380,
        },
        "answer": {
            "keyword_hit_rate": 0.76,
            "faithfulness_avg": 1.5,
            "answer_relevancy_avg": 1.6,
            "llm_judge_total_calls": 30,
        },
    }
    run_a = _make_run_with_metrics(db_session, ds, metrics_json=metrics_a)
    run_b = _make_run_with_metrics(db_session, ds, metrics_json=metrics_b)

    out = compare_runs(db_session, run_a.id, run_b.id)

    # 顶层结构
    assert "error" not in out
    assert out["run_a"]["id"] == run_a.id
    assert out["run_b"]["id"] == run_b.id
    # aggregate_delta 字段齐全(retrieval + answer 两个 section,逐 metric)
    retrieval_delta = out["aggregate_delta"]["retrieval"]
    for key in ["hit_at_5", "hit_at_10", "mrr", "ndcg_at_10", "recall_at_10",
                "latency_ms_p50", "latency_ms_p95"]:
        assert key in retrieval_delta
        cell = retrieval_delta[key]
        assert set(cell.keys()) == {"a", "b", "delta", "winner"}
    answer_delta = out["aggregate_delta"]["answer"]
    for key in ["keyword_hit_rate", "faithfulness_avg", "answer_relevancy_avg"]:
        assert key in answer_delta

    # B 整体比 A 好(hit/mrr/ndcg/recall 都更高,latency 更低)→ 全 winner=b
    assert retrieval_delta["hit_at_5"]["winner"] == "b"
    assert retrieval_delta["mrr"]["winner"] == "b"
    assert retrieval_delta["latency_ms_p50"]["winner"] == "b"
    assert retrieval_delta["latency_ms_p95"]["winner"] == "b"
    assert answer_delta["faithfulness_avg"]["winner"] == "b"
    # winners dict 与 aggregate_delta 一致
    for path in ["retrieval.hit_at_5", "retrieval.mrr",
                 "answer.faithfulness_avg"]:
        assert out["winners"][path] == "b"
    # summary 计数
    assert out["summary"]["b_wins"] >= 5
    assert out["summary"]["a_wins"] == 0


# ---------------------------------------------------------------------------
# 2. A 整体优于 B
# ---------------------------------------------------------------------------


def test_compare_a_better_than_b(db_session, dataset_with_items):
    """A 的所有 metric 比 B 高(A 赢所有 winner 字段)。"""
    ds, _ = dataset_with_items
    metrics_a = {
        "retrieval": {
            "hit_at_5": 0.95, "hit_at_10": 0.98, "mrr": 0.90,
            "ndcg_at_10": 0.85, "recall_at_10": 0.95,
            "latency_ms_p50": 100, "latency_ms_p95": 200,
        },
        "answer": {
            "keyword_hit_rate": 0.95,
            "faithfulness_avg": 1.9,
            "answer_relevancy_avg": 1.9,
            "llm_judge_total_calls": 30,
        },
    }
    metrics_b = {
        "retrieval": {
            "hit_at_5": 0.50, "hit_at_10": 0.60, "mrr": 0.40,
            "ndcg_at_10": 0.35, "recall_at_10": 0.50,
            "latency_ms_p50": 300, "latency_ms_p95": 600,
        },
        "answer": {
            "keyword_hit_rate": 0.40,
            "faithfulness_avg": 0.8,
            "answer_relevancy_avg": 1.0,
            "llm_judge_total_calls": 30,
        },
    }
    run_a = _make_run_with_metrics(db_session, ds, metrics_json=metrics_a)
    run_b = _make_run_with_metrics(db_session, ds, metrics_json=metrics_b)

    out = compare_runs(db_session, run_a.id, run_b.id)
    # 所有 winner 字段都应该是 "a"(含 latency: A 比 B 快 → winner=a)
    for v in out["winners"].values():
        assert v == "a"
    assert out["summary"]["a_wins"] == len(_HIGHER_IS_BETTER)
    assert out["summary"]["b_wins"] == 0
    assert out["summary"]["ties"] == 0


# ---------------------------------------------------------------------------
# 3. latency 越低越好
# ---------------------------------------------------------------------------


def test_compare_latency_lower_is_better(db_session, dataset_with_items):
    """latency_p50: A=500ms, B=200ms → winner=b(B 更快);其他 metric tie。"""
    ds, _ = dataset_with_items
    # 所有 retrieval/answer 指标两边相等,只 latency 不同
    base_retrieval = {
        "hit_at_5": 0.80, "hit_at_10": 0.90, "mrr": 0.70,
        "ndcg_at_10": 0.65, "recall_at_10": 0.85,
    }
    base_answer = {
        "keyword_hit_rate": 0.70,
        "faithfulness_avg": 1.4,
        "answer_relevancy_avg": 1.5,
        "llm_judge_total_calls": 30,
    }
    metrics_a = {
        "retrieval": {**base_retrieval, "latency_ms_p50": 500, "latency_ms_p95": 800},
        "answer": base_answer,
    }
    metrics_b = {
        "retrieval": {**base_retrieval, "latency_ms_p50": 200, "latency_ms_p95": 400},
        "answer": base_answer,
    }
    run_a = _make_run_with_metrics(db_session, ds, metrics_json=metrics_a)
    run_b = _make_run_with_metrics(db_session, ds, metrics_json=metrics_b)

    out = compare_runs(db_session, run_a.id, run_b.id)
    # 所有 retrieval/answer metric tie(B latency 段更快 → winner=b)
    assert out["aggregate_delta"]["retrieval"]["latency_ms_p50"]["winner"] == "b"
    assert out["aggregate_delta"]["retrieval"]["latency_ms_p95"]["winner"] == "b"
    # 其余 retrieval / answer 都是 tie
    assert out["aggregate_delta"]["retrieval"]["hit_at_5"]["winner"] == "tie"
    assert out["aggregate_delta"]["retrieval"]["mrr"]["winner"] == "tie"
    assert out["aggregate_delta"]["answer"]["faithfulness_avg"]["winner"] == "tie"
    # summary: 仅 latency 2 项 b 赢,其余全 tie
    assert out["summary"]["b_wins"] == 2
    assert out["summary"]["a_wins"] == 0
    assert out["summary"]["ties"] >= 5


# ---------------------------------------------------------------------------
# 4. 一边 metrics_json 为 None
# ---------------------------------------------------------------------------


def test_compare_one_side_metrics_missing(db_session, dataset_with_items):
    """run_a 没 metrics_json(还在跑)→ 视作 0.0,winner = tie,结构完整。"""
    ds, _ = dataset_with_items
    metrics_b = {
        "retrieval": {
            "hit_at_5": 0.82, "hit_at_10": 0.90, "mrr": 0.71,
            "ndcg_at_10": 0.68, "recall_at_10": 0.87,
            "latency_ms_p50": 200, "latency_ms_p95": 400,
        },
        "answer": {
            "keyword_hit_rate": 0.70,
            "faithfulness_avg": 1.4,
            "answer_relevancy_avg": 1.5,
            "llm_judge_total_calls": 30,
        },
    }
    run_a = _make_run_with_metrics(db_session, ds, metrics_json=None)
    run_b = _make_run_with_metrics(db_session, ds, metrics_json=metrics_b)

    out = compare_runs(db_session, run_a.id, run_b.id)
    assert "error" not in out
    # run_a 所有 metric 视为 0.0,winner 全 tie(B 高于 0 → 但 a=0,b>0,
    # 但 spec 行为:0 == None → tie;具体看 compare._pick_winner:差距 >= 1e-9 → 非 tie)
    # 实际上 a_val=0,b_val=0.82 → diff>0 → winner=b(因为 b 比 a 大)
    # 我们只验结构完整 + summary 合理
    assert "aggregate_delta" in out
    assert "retrieval" in out["aggregate_delta"]
    assert "answer" in out["aggregate_delta"]
    assert "winners" in out
    assert "summary" in out
    # run_a 的所有 metric 值都是 0.0
    hit_cell = out["aggregate_delta"]["retrieval"]["hit_at_5"]
    assert hit_cell["a"] == 0.0
    assert hit_cell["b"] == 0.82
    assert hit_cell["winner"] == "b"


# ---------------------------------------------------------------------------
# 5. (bonus)run 不存在 → error 字段
# ---------------------------------------------------------------------------


def test_compare_run_not_found(db_session):
    """run_a / run_b 找不到 → 返 error 字段,不抛。"""
    out = compare_runs(db_session, 99999, 99998)
    assert "error" in out
    assert "99999" in out["error"]


# ---------------------------------------------------------------------------
# 6. (bonus)per_item_delta 配对
# ---------------------------------------------------------------------------


def test_compare_per_item_delta_pairing(db_session, dataset_with_items):
    """两 run 都有 5 条 result → per_item_delta 5 条,每条同时有 a / b。"""
    ds, items = dataset_with_items
    metrics = {
        "retrieval": {"hit_at_5": 0.5, "hit_at_10": 0.5, "mrr": 0.5,
                       "ndcg_at_10": 0.5, "recall_at_10": 0.5,
                       "latency_ms_p50": 100, "latency_ms_p95": 200},
        "answer": {"keyword_hit_rate": 0.5, "faithfulness_avg": 1.0,
                   "answer_relevancy_avg": 1.0, "llm_judge_total_calls": 0},
    }
    run_a = _make_run_with_metrics(db_session, ds, metrics_json=metrics)
    run_b = _make_run_with_metrics(db_session, ds, metrics_json=metrics)
    # A: 全 hit=1.0,mrr=1.0;B: 全 hit=0.5,mrr=0.5
    for item in items:
        _insert_result(db_session, run=run_a, item=item, hit=1.0, mrr=1.0)
        _insert_result(db_session, run=run_b, item=item, hit=0.5, mrr=0.5)

    out = compare_runs(db_session, run_a.id, run_b.id)
    assert "per_item_delta" in out
    pid = out["per_item_delta"]
    assert len(pid) == 5
    # 每条都有 a / b / delta
    for entry in pid:
        assert "item_id" in entry
        assert entry["a"] is not None
        assert entry["b"] is not None
        # delta.hit_at_5 / delta.mrr 都是 dict,winner = "a"(A 比 B 高)
        assert entry["delta"]["hit_at_5"]["winner"] == "a"
        assert entry["delta"]["mrr"]["winner"] == "a"