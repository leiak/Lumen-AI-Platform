"""M37.2 — Report 聚合单元测试。

3 测试覆盖 plan §T14 要求:

1. 聚合 happy path → metrics_json 结构跟 spec §4.2 示例一致
2. by_category / by_difficulty 分组正确,空组不出 key
3. error_message 非空行跳过聚合,失败列表单独展示

用 dev DB + 临时 dataset/run fixture,跑完生成 report 验 dict 结构 + Markdown 长度。
"""
import json
import uuid

import pytest
from sqlalchemy.orm import Session

from lumen_core.database import SessionLocal, ensure_eval_datasets_table, ensure_eval_runs_table
from lumen_models.eval_run import EvalRun, EvalRunResult
from lumen_models.eval_dataset import EvalDataset, EvalDatasetItem
from lumen_models.knowledge import KnowledgeBase
from lumen_models.user import User
from lumen_models.model_config import ModelConfig
from lumen_services.eval.report import generate_report, _REPORT_MAX_BYTES


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
        name=f"m37-report-kb-{uuid.uuid4().hex[:8]}",
        tenant_id=1,
        embedding_model_config_id=cfg.id,
        status="active",
    )
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    yield row
    # teardown
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
    """建一个 dataset + 6 条 item,3 个 category + 2 个 difficulty。"""
    ds = EvalDataset(
        kb_id=kb.id, tenant_id=1, name=f"m37-report-ds-{uuid.uuid4().hex[:8]}",
        source="manual", is_active=1, created_by=tenant_user.id,
    )
    db_session.add(ds)
    db_session.commit()
    db_session.refresh(ds)
    specs = [
        ("factual", "easy"),
        ("factual", "medium"),
        ("reasoning", "medium"),
        ("reasoning", "hard"),
        ("multi_hop", "hard"),
        ("multi_hop", "hard"),
    ]
    items = []
    for i, (cat, diff) in enumerate(specs):
        it = EvalDatasetItem(
            dataset_id=ds.id, query=f"q{i}",
            expected_doc_ids=[100 + i],
            category=cat, difficulty=diff,
        )
        db_session.add(it)
        items.append(it)
    db_session.commit()
    for it in items:
        db_session.refresh(it)
    return ds, items


def _make_run(db_session, dataset, config=None) -> EvalRun:
    cfg = config or {
        "name": "unit",
        "top_k": 5,
        "rerank": False,
        "search_weights": {"title": 10, "important_kw": 30, "question_kw": 20, "text": 2},
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
        total_items=0,
        completed_items=0,
        finished_at=None,
    )
    db_session.add(run)
    db_session.commit()
    db_session.refresh(run)
    return run


def _insert_result(
    db_session, *, run, item, hit=1.0, mrr=1.0, ndcg=1.0, recall=1.0,
    kw=1.0, faith=None, relevancy=None, latency=200, error=None,
):
    """插一行 EvalRunResult + commit;error 非 None 表示失败行。

    为什么必须 commit:SessionLocal 是 ``autoflush=False``,光 add 不 flush
    也不写库,后续 query 看不到。runner.py 是 commit-per-item,这里对齐。
    """
    r = EvalRunResult(
        run_id=run.id,
        item_id=item.id,
        query=item.query,
        retrieved_doc_ids=[100 + item.id],
        retrieval_scores=[0.9],
        retrieved_contexts=["ctx"],
        answer="answer",
        retrieval_metrics={
            "hit_at_5": hit, "hit_at_10": hit, "mrr": mrr,
            "ndcg_at_10": ndcg, "recall_at_10": recall,
        },
        answer_metrics={
            "keyword_hit_rate": kw,
            "faithfulness": faith,
            "answer_relevancy": relevancy,
        },
        llm_judge_calls=None,
        latency_ms=latency,
        error_message=error,
    )
    db_session.add(r)
    db_session.commit()
    return r


# ---------------------------------------------------------------------------
# 1. 聚合 happy path
# ---------------------------------------------------------------------------


def test_generate_report_happy_path(db_session, dataset_with_items):
    """6 条全 success,每条不同 hit_at_5 / mrr → 聚合正确 + Markdown 含 4 段。"""
    ds, items = dataset_with_items
    run = _make_run(db_session, ds)
    # 6 条:hit_at_5 全部 1.0;mrr 0.5, 0.5, 1.0, 1.0, 0.5, 0.5 → mean = 0.667
    mrr_vals = [0.5, 0.5, 1.0, 1.0, 0.5, 0.5]
    for item, mrr_v in zip(items, mrr_vals):
        _insert_result(db_session, run=run, item=item, mrr=mrr_v)

    markdown, metrics = generate_report(db_session, run.id)

    # metrics_json 关键字段
    assert "retrieval" in metrics
    assert "answer" in metrics
    assert "by_category" in metrics
    assert "by_difficulty" in metrics
    assert "totals" in metrics
    assert metrics["totals"]["items_success"] == 6
    assert metrics["totals"]["items_failed"] == 0
    # hit_at_5 mean = 1.0(全命中)
    assert metrics["retrieval"]["hit_at_5"] == 1.0
    # mrr mean = 3/6 = 0.5(0.5+0.5+1+1+0.5+0.5)/6
    assert abs(metrics["retrieval"]["mrr"] - 0.6667) < 0.01
    # latency p50 / p95(全部 200 → 都 200)
    assert metrics["retrieval"]["latency_ms_p50"] == 200
    assert metrics["retrieval"]["latency_ms_p95"] == 200
    # answer.keyword_hit_rate mean = 1.0
    assert metrics["answer"]["keyword_hit_rate"] == 1.0

    # Markdown 结构
    assert markdown is not None
    assert f"# Eval Run #{run.id}" in markdown
    assert "## Config" in markdown
    assert "## Retrieval Metrics" in markdown
    assert "## Answer Metrics" in markdown
    assert "## By Category" in markdown
    assert "## By Difficulty" in markdown
    assert len(markdown.encode("utf-8")) <= _REPORT_MAX_BYTES


# ---------------------------------------------------------------------------
# 2. by_category / by_difficulty 分组
# ---------------------------------------------------------------------------


def test_by_category_and_difficulty_grouping(db_session, dataset_with_items):
    """6 条 item 跨 3 category / 3 difficulty → 分组 hit_at_5 / mrr 正确,
    空组不出 key。
    """
    ds, items = dataset_with_items
    run = _make_run(db_session, ds)
    # factual: items[0],items[1] → hit=1.0,mrr=1.0 → 平均 (1.0, 1.0)
    _insert_result(db_session, run=run, item=items[0], mrr=1.0)
    _insert_result(db_session, run=run, item=items[1], mrr=1.0)
    # reasoning: items[2],items[3] → hit=0.5,mrr=0.33
    _insert_result(db_session, run=run, item=items[2], hit=0.5, mrr=0.33)
    _insert_result(db_session, run=run, item=items[3], hit=0.5, mrr=0.33)
    # multi_hop: items[4],items[5] → 全 0
    _insert_result(db_session, run=run, item=items[4], hit=0.0, mrr=0.0)
    _insert_result(db_session, run=run, item=items[5], hit=0.0, mrr=0.0)

    _, metrics = generate_report(db_session, run.id)

    by_cat = metrics["by_category"]
    assert "factual" in by_cat
    assert "reasoning" in by_cat
    assert "multi_hop" in by_cat
    # factual n=2, hit=1.0,mrr=1.0
    assert by_cat["factual"]["count"] == 2
    assert by_cat["factual"]["hit_at_5"] == 1.0
    assert by_cat["factual"]["mrr"] == 1.0
    # reasoning n=2, hit=0.5,mrr=0.33
    assert by_cat["reasoning"]["hit_at_5"] == 0.5
    assert abs(by_cat["reasoning"]["mrr"] - 0.33) < 0.01
    # multi_hop n=2, hit=0.0,mrr=0.0
    assert by_cat["multi_hop"]["hit_at_5"] == 0.0

    by_diff = metrics["by_difficulty"]
    assert "easy" in by_diff
    assert "medium" in by_diff
    assert "hard" in by_diff
    # easy: items[0] → 1.0
    assert by_diff["easy"]["count"] == 1
    assert by_diff["easy"]["hit_at_5"] == 1.0


# ---------------------------------------------------------------------------
# 3. error_message 失败行跳过聚合
# ---------------------------------------------------------------------------


def test_failed_items_excluded_from_aggregates(db_session, dataset_with_items):
    """3 条 success + 3 条 failed → retrieval / answer / by_category 都只算
    success 那 3 条,failed 进 failures 列表。
    """
    ds, items = dataset_with_items
    run = _make_run(db_session, ds)
    # items[0..2] success,hits 全 1.0
    for item in items[:3]:
        _insert_result(db_session, run=run, item=item, hit=1.0, mrr=1.0)
    # items[3..5] failed
    for item in items[3:]:
        _insert_result(
            db_session, run=run, item=item,
            hit=0.0, mrr=0.0, error="simulated failure",
        )

    markdown, metrics = generate_report(db_session, run.id)

    # success / failed 计数
    assert metrics["totals"]["items_success"] == 3
    assert metrics["totals"]["items_failed"] == 3
    assert metrics["totals"]["items_total"] == 6
    # 聚合只看 success 3 条 → hit=1.0,mrr=1.0
    assert metrics["retrieval"]["hit_at_5"] == 1.0
    assert metrics["retrieval"]["mrr"] == 1.0
    # by_category 也只算 success(成功覆盖 factual + reasoning,multi_hop 全失败
    # → 不出 key)
    by_cat = metrics["by_category"]
    assert "factual" in by_cat
    assert "reasoning" in by_cat
    assert "multi_hop" not in by_cat  # 全失败 → 空 bucket

    # Markdown 含 Failures 段 + 列出 3 条
    assert "## Failures" in markdown
    assert "simulated failure" in markdown