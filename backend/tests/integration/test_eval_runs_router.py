"""M37.2: integration tests for /api/v1/eval/runs/* endpoints.

5 endpoints covered:

  GET    /                          list runs (tenant-scoped, with completed_count)
  POST   /                          start a new run (Celery eager dispatch)
  GET    /{run_id}                  detail (含 metrics_json + report_markdown)
  POST   /{run_id}/cancel           mark run as cancelled
  POST   /compare                   compare two runs (同 dataset)

测试策略(参考 test_eval_datasets_router.py):
- 用 dev DB 上的真实 KB / ModelConfig 跑 happy path
- 用 Celery eager mode 直接同步跑 task,避免启 worker
- 不调真实 LLM —— runner 已被 patch 成 mock 跳过 retrieval/judge
- 跨租户 / 非法 dataset → 404 / 422

Plan: docs-internal/superpowers/plans/m37-plan.md CP5 T16 (3 integration tests)
"""
from __future__ import annotations

import uuid
from typing import Any, Dict, List
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from lumen_core.database import (
    SessionLocal,
    ensure_eval_datasets_table,
    ensure_eval_runs_table,
)
from lumen_core.security import create_access_token
from lumen_main import app
from lumen_models.eval_dataset import EvalDataset, EvalDatasetItem
from lumen_models.eval_run import EvalRun, EvalRunResult
from lumen_models.knowledge import KnowledgeBase
from lumen_models.model_config import ModelConfig
from lumen_models.user import User
from lumen_tasks.celery_app import celery_app


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def client():
    return TestClient(app)


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
    """Pick the first user in tenant 1; mint a JWT for API auth."""
    user = db_session.query(User).filter(User.tenant_id == 1).first()
    if user is None:
        pytest.skip("No user in tenant 1; cannot auth")
    token = create_access_token(data={"sub": user.username})
    return user, {"Authorization": f"Bearer {token}"}


@pytest.fixture
def kb(db_session):
    """Create a throwaway KB on tenant 1 with a real embedding model."""
    cfg = (
        db_session.query(ModelConfig)
        .filter(ModelConfig.is_active == 1, ModelConfig.is_embedding == 1)
        .order_by(ModelConfig.id)
        .first()
    )
    if cfg is None:
        pytest.skip("dev DB has no active embedding ModelConfig")
    row = KnowledgeBase(
        name=f"m37-runs-api-kb-{uuid.uuid4().hex[:8]}",
        tenant_id=1,
        embedding_model_config_id=cfg.id,
        status="active",
    )
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    yield row
    # teardown:results → runs → items → dataset → kb(FK CASCADE 处理前 3 个)
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
def eager_celery():
    """Celery eager mode:同步跑 task,跳过真 worker。"""
    celery_app.conf.task_always_eager = True
    yield celery_app
    celery_app.conf.task_always_eager = False


@pytest.fixture
def dataset_with_empty_items(db_session, kb, tenant_user):
    """建一个 dataset + 0 items —— 跑出来 status=completed,0 items,避开真实检索。

    spec §4.2 评测集至少 1 条 item 起评,本 fixture 故意空,让 runner 走
    ``empty dataset 直接 completed`` 路径,免去 mock retrieval pipeline。
    """
    user, _ = tenant_user
    ds = EvalDataset(
        kb_id=kb.id,
        tenant_id=1,
        name=f"m37-runs-api-ds-{uuid.uuid4().hex[:8]}",
        source="manual",
        is_active=1,
        created_by=user.id,
    )
    db_session.add(ds)
    db_session.commit()
    db_session.refresh(ds)
    return ds


@pytest.fixture
def dataset_with_two_items(db_session, kb, tenant_user):
    """2 items(最小有效评测集),跑出来 completed + 2 个 result 行。

    item 的 expected_doc_ids 故意指向真实存在的 doc_id(本 fixture 不导入,
    让 retrieval_metrics 全 0.0 / 报错走 error_message 分支也都行——测试
    主要看 lifecycle 流转,不看 metric 数值)。
    """
    user, _ = tenant_user
    ds = EvalDataset(
        kb_id=kb.id,
        tenant_id=1,
        name=f"m37-runs-api-ds-{uuid.uuid4().hex[:8]}",
        source="manual",
        is_active=1,
        created_by=user.id,
    )
    db_session.add(ds)
    db_session.commit()
    db_session.refresh(ds)
    for i in range(2):
        db_session.add(EvalDatasetItem(
            dataset_id=ds.id,
            query=f"pick_{i}_{uuid.uuid4().hex[:6]}",
            expected_doc_ids=[1000 + i],
            category="factual",
            difficulty="easy",
        ))
    db_session.commit()
    return ds


# 真实 EmbeddingCallLog / LLMCallLog mock 数据(空 pipeline)
MOCK_CHUNK = {
    "text": "ctx",
    "metadata": {"document_id": 1001},
    "score": 0.9,
}


class _FakePipeline:
    def search(self, *args, **kwargs):
        return [MOCK_CHUNK]


def _patch_pipeline():
    return patch(
        "lumen_services.eval.runner.get_retrieval_pipeline",
        return_value=_FakePipeline(),
    )


def _reload_run(db_session, run_id: int) -> EvalRun:
    """fresh read —— 跨 session commit 后 InnoDB REPEATABLE READ 需 commit 释放。"""
    db_session.commit()
    db_session.expire_all()
    return db_session.get(EvalRun, run_id)


# ---------------------------------------------------------------------------
# 1. list / detail / cancel — full lifecycle
# ---------------------------------------------------------------------------


def test_run_lifecycle_list_detail_cancel(
    client, db_session, eager_celery, dataset_with_empty_items, tenant_user, kb
):
    """POST → 启动 run → list 看到 → GET 详情 → cancel(已 completed 状态不重写)。"""
    _, headers = tenant_user
    ds = dataset_with_empty_items

    # 1. POST /runs → 创建 pending + 派 Celery(eager 同步跑)
    payload = {
        "dataset_id": ds.id,
        "config": {
            "name": "lifecycle-test",
            "search_weights": {"title": 10, "important_kw": 30, "question_kw": 20, "text": 2},
            "top_k": 5,
            "rerank": False,
            "embedding_model_config_id": kb.embedding_model_config_id,
            "judge_model_config_id": 1,
            "judge_metrics": [],
        },
    }
    with _patch_pipeline():
        create_resp = client.post("/api/v1/eval/runs/", headers=headers, json=payload)
    assert create_resp.status_code == 201, create_resp.text
    body = create_resp.json()
    run_id = body["data"]["id"]
    assert body["data"]["status"] == "completed"  # empty dataset → 直接 completed
    assert body["data"]["dataset_id"] == ds.id
    assert body["data"]["config"]["embedding_model_config_id"] == kb.embedding_model_config_id

    # 2. GET /runs → list 看到
    list_resp = client.get("/api/v1/eval/runs/", headers=headers)
    assert list_resp.status_code == 200
    list_body = list_resp.json()
    ids = [r["id"] for r in list_body["data"]]
    assert run_id in ids
    # 找到自己那条行
    row = next(r for r in list_body["data"] if r["id"] == run_id)
    assert row["status"] == "completed"
    assert row["total_items"] == 0
    assert row["completed_count"] == 0  # 0 items → 0 成功

    # 3. GET /runs/{id} → 详情能拿回
    detail_resp = client.get(f"/api/v1/eval/runs/{run_id}", headers=headers)
    assert detail_resp.status_code == 200
    detail_body = detail_resp.json()
    assert detail_body["data"]["id"] == run_id
    assert detail_body["data"]["status"] == "completed"
    # metrics_json 是 {} 或 None 都行(empty dataset)
    assert detail_body["data"]["metrics_json"] is None or isinstance(
        detail_body["data"]["metrics_json"], dict
    )

    # 4. cancel 已 completed run → 200 + 状态不重写
    cancel_resp = client.post(
        f"/api/v1/eval/runs/{run_id}/cancel",
        headers=headers,
        json={"reason": "lifecycle test"},
    )
    assert cancel_resp.status_code == 200
    assert cancel_resp.json()["data"]["status"] == "completed"  # no-op


# ---------------------------------------------------------------------------
# 2. start_run with missing dataset → 404
# ---------------------------------------------------------------------------


def test_start_run_missing_dataset_returns_404(client, tenant_user):
    """dataset_id 不存在 / 不可见 → 404(不暴露存在/不存在的区别)。"""
    _, headers = tenant_user
    payload = {
        "dataset_id": 99999999,
        "config": {
            "search_weights": {"title": 10, "important_kw": 30, "question_kw": 20, "text": 2},
            "embedding_model_config_id": 1,
            "judge_model_config_id": 1,
        },
    }
    resp = client.post("/api/v1/eval/runs/", headers=headers, json=payload)
    assert resp.status_code == 404, resp.text


# ---------------------------------------------------------------------------
# 3. start_run with embedding mismatch → 422
# ---------------------------------------------------------------------------


def test_start_run_embedding_mismatch_returns_422(
    client, eager_celery, dataset_with_empty_items, tenant_user, kb
):
    """config.embedding_model_config_id != kb.embedding_model_config_id → 422。"""
    _, headers = tenant_user
    ds = dataset_with_empty_items

    # 故意用错的 embedding_model_config_id
    wrong_emb_id = 99999
    payload = {
        "dataset_id": ds.id,
        "config": {
            "search_weights": {"title": 10, "important_kw": 30, "question_kw": 20, "text": 2},
            "embedding_model_config_id": wrong_emb_id,
            "judge_model_config_id": 1,
        },
    }
    resp = client.post("/api/v1/eval/runs/", headers=headers, json=payload)
    assert resp.status_code == 422, resp.text
    assert "embedding_model_config_id" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# 4. compare two runs on same dataset → 200 + winners list
# ---------------------------------------------------------------------------


def test_compare_two_runs_on_same_dataset(
    client, eager_celery, db_session, dataset_with_empty_items, tenant_user, kb
):
    """两条 run(都 empty dataset)compare → 200,winners 列表非空,aggregate_delta 含 hit_at_5。"""
    _, headers = tenant_user
    ds = dataset_with_empty_items
    cfg_payload = {
        "search_weights": {"title": 10, "important_kw": 30, "question_kw": 20, "text": 2},
        "embedding_model_config_id": kb.embedding_model_config_id,
        "judge_model_config_id": 1,
    }

    # 跑 2 次同 dataset
    run_ids: List[int] = []
    with _patch_pipeline():
        for _ in range(2):
            r = client.post(
                "/api/v1/eval/runs/",
                headers=headers,
                json={"dataset_id": ds.id, "config": cfg_payload},
            )
            assert r.status_code == 201
            run_ids.append(r.json()["data"]["id"])
    a_id, b_id = run_ids

    # 拿任意 judge model_config_id(给 report 占位)
    judge_id = cfg_payload["judge_model_config_id"]

    # 直接 fake metrics_json 让我们拿到的 aggregate_delta 有数据(2 个 empty run 都全 0.0 winner=tie)
    db_session.commit()
    db_session.expire_all()
    for r in (db_session.get(EvalRun, a_id), db_session.get(EvalRun, b_id)):
        # 不同 search_weights → 让 a/b 数值不同,winner 才有 b
        r.metrics_json = {
            "retrieval": {
                "hit_at_5": 0.5 if r.id == a_id else 0.8,
                "mrr": 0.4 if r.id == a_id else 0.7,
            },
            "answer": {"keyword_hit_rate": 0.6},
        }
    db_session.commit()

    compare_resp = client.post(
        "/api/v1/eval/runs/compare",
        headers=headers,
        json={"run_id_a": a_id, "run_id_b": b_id},
    )
    assert compare_resp.status_code == 200, compare_resp.text
    body = compare_resp.json()["data"]
    assert body["run_id_a"] == a_id
    assert body["run_id_b"] == b_id
    assert "retrieval.hit_at_5" in body["aggregate_delta"]
    assert body["aggregate_delta"]["retrieval.hit_at_5"] == pytest.approx(0.3, abs=1e-3)
    # winners 是 list[{metric, winner, delta}]
    assert isinstance(body["winners"], list)
    hit_winner = next(w for w in body["winners"] if w["metric"] == "retrieval.hit_at_5")
    assert hit_winner["winner"] == "b"


# ---------------------------------------------------------------------------
# 5. compare across different datasets → 422
# ---------------------------------------------------------------------------


def test_compare_across_datasets_returns_422(
    client, eager_celery, db_session, kb, tenant_user
):
    """两个 run 跨 dataset(虽然 1 dataset 也能起)→ 422 拒绝。"""
    _, headers = tenant_user
    user, _ = tenant_user

    # 建 2 个 dataset(绑同一个 KB,但本身不同)
    ds_a = EvalDataset(
        kb_id=kb.id, tenant_id=1,
        name=f"a_{uuid.uuid4().hex[:6]}",
        source="manual", is_active=1, created_by=user.id,
    )
    ds_b = EvalDataset(
        kb_id=kb.id, tenant_id=1,
        name=f"b_{uuid.uuid4().hex[:6]}",
        source="manual", is_active=1, created_by=user.id,
    )
    db_session.add_all([ds_a, ds_b])
    db_session.commit()
    db_session.refresh(ds_a)
    db_session.refresh(ds_b)

    # 直接手工 INSERT EvalRun(避免真跑,免 Celery 副作用)
    cfg = {
        "search_weights": {"title": 10, "important_kw": 30, "question_kw": 20, "text": 2},
        "embedding_model_config_id": kb.embedding_model_config_id,
        "judge_model_config_id": 1,
    }
    run_a = EvalRun(dataset_id=ds_a.id, config_json=cfg, status="completed",
                    total_items=0, completed_items=0)
    run_b = EvalRun(dataset_id=ds_b.id, config_json=cfg, status="completed",
                    total_items=0, completed_items=0)
    db_session.add_all([run_a, run_b])
    db_session.commit()
    db_session.refresh(run_a)
    db_session.refresh(run_b)

    resp = client.post(
        "/api/v1/eval/runs/compare",
        headers=headers,
        json={"run_id_a": run_a.id, "run_id_b": run_b.id},
    )
    assert resp.status_code == 422, resp.text
    assert "dataset" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# 6. run happy path with 2 items produces 2 result rows
# ---------------------------------------------------------------------------


def test_run_with_two_items_writes_two_results(
    client, eager_celery, db_session, dataset_with_two_items, tenant_user, kb
):
    """dataset 有 2 items,跑完应见 2 个 EvalRunResult 行。"""
    _, headers = tenant_user
    ds = dataset_with_two_items

    payload = {
        "dataset_id": ds.id,
        "config": {
            "search_weights": {"title": 10, "important_kw": 30, "question_kw": 20, "text": 2},
            "top_k": 5,
            "rerank": False,
            "embedding_model_config_id": kb.embedding_model_config_id,
            "judge_model_config_id": 1,
            "judge_metrics": [],
        },
    }
    with _patch_pipeline():
        create_resp = client.post("/api/v1/eval/runs/", headers=headers, json=payload)
    assert create_resp.status_code == 201
    run_id = create_resp.json()["data"]["id"]

    # 跨 session commit 释放 REPEATABLE READ
    fresh = _reload_run(db_session, run_id)
    assert fresh.status == "completed"
    assert fresh.total_items == 2
    assert fresh.completed_items == 2

    # 详情接口 include_results=true 看 result 行
    detail_resp = client.get(
        f"/api/v1/eval/runs/{run_id}?include_results=true",
        headers=headers,
    )
    assert detail_resp.status_code == 200
    body = detail_resp.json()["data"]
    assert body["results_total"] == 2
    assert len(body["results"]) == 2
    # metrics_json 至少含 retrieval.0 字段(empty category 除外)
    m = body["metrics_json"] or {}
    assert "retrieval" in m or "by_category" in m
