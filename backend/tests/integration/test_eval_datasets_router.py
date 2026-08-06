"""M37.1: integration tests for /api/v1/eval/datasets/* endpoints.

Covers 8 endpoints:

  GET    /                              list datasets (tenant-scoped)
  POST   /                              create dataset (tenant auto-derived)
  GET    /{dataset_id}                  detail
  PUT    /{dataset_id}                  partial update
  DELETE /{dataset_id}                  cascade delete items
  POST   /{dataset_id}/items            add single item
  POST   /{dataset_id}/items/bulk-import  bulk import with partial_errors
  DELETE /{dataset_id}/items/{item_id}  delete single item

Spec: docs-internal/superpowers/specs/m37-rag-evaluation.md §4.1
Plan: docs-internal/superpowers/plans/m37-plan.md CP1 T3 (8 integration tests)
"""
import uuid

import pytest
from fastapi.testclient import TestClient

from lumen_core.database import SessionLocal, ensure_eval_datasets_table
from lumen_core.security import create_access_token
from lumen_main import app
from lumen_models.eval_dataset import EvalDataset, EvalDatasetItem
from lumen_models.knowledge import KnowledgeBase
from lumen_models.model_config import ModelConfig
from lumen_models.user import User


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def db_session():
    ensure_eval_datasets_table()
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
def tenant_user_2(db_session):
    """Pick a second user in a different tenant for cross-tenant tests."""
    user = db_session.query(User).filter(User.tenant_id != 1).first()
    if user is None:
        pytest.skip("No user in a non-default tenant; cross-tenant test skipped")
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
    kb = KnowledgeBase(
        name=f"m37-eval-api-kb-{uuid.uuid4().hex[:8]}",
        tenant_id=1,
        embedding_model_config_id=cfg.id,
        status="active",
    )
    db_session.add(kb)
    db_session.commit()
    db_session.refresh(kb)
    yield kb
    # Cascade order: items → datasets → kb
    db_session.query(EvalDatasetItem).filter(
        EvalDatasetItem.dataset_id.in_(
            db_session.query(EvalDataset.id).filter(EvalDataset.kb_id == kb.id)
        )
    ).delete(synchronize_session=False)
    db_session.query(EvalDataset).filter(EvalDataset.kb_id == kb.id).delete(
        synchronize_session=False
    )
    db_session.query(KnowledgeBase).filter(KnowledgeBase.id == kb.id).delete(
        synchronize_session=False
    )
    db_session.commit()


# ---------------------------------------------------------------------------
# dataset endpoint tests
# ---------------------------------------------------------------------------

def test_list_datasets_returns_envelope(client, tenant_user, kb):
    _, headers = tenant_user
    resp = client.get("/api/v1/eval/datasets/", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["code"] == 200
    assert isinstance(body["data"], list)
    assert body["total"] >= 0


def test_create_then_get_dataset_round_trip(client, tenant_user, kb):
    _, headers = tenant_user
    suffix = uuid.uuid4().hex[:8]
    create_resp = client.post(
        "/api/v1/eval/datasets/",
        headers=headers,
        json={"kb_id": kb.id, "name": f"create_{suffix}", "source": "manual"},
    )
    assert create_resp.status_code == 201, create_resp.text
    body = create_resp.json()
    assert body["code"] == 200
    assert body["data"]["name"] == f"create_{suffix}"
    assert body["data"]["kb_id"] == kb.id
    assert body["data"]["tenant_id"] == 1  # derived from current_user
    dataset_id = body["data"]["id"]

    # GET it back
    get_resp = client.get(
        f"/api/v1/eval/datasets/{dataset_id}", headers=headers
    )
    assert get_resp.status_code == 200
    assert get_resp.json()["data"]["name"] == f"create_{suffix}"

    # Cleanup
    client.delete(
        f"/api/v1/eval/datasets/{dataset_id}", headers=headers
    )


def test_create_dataset_invisible_kb_returns_404(client, tenant_user_2):
    """Tenant 2 trying to bind a KB belonging to another tenant → 404."""
    user, headers = tenant_user_2
    # Find an existing KB in a different tenant than this user
    db = SessionLocal()
    try:
        other_kb = (
            db.query(KnowledgeBase)
            .filter(KnowledgeBase.tenant_id != user.tenant_id)
            .first()
        )
    finally:
        db.close()
    if other_kb is None:
        pytest.skip("No KB in a different tenant; cross-tenant 404 skipped")

    resp = client.post(
        "/api/v1/eval/datasets/",
        headers=headers,
        json={"kb_id": other_kb.id, "name": "should_not_create"},
    )
    assert resp.status_code == 404, resp.text


def test_get_dataset_other_tenant_returns_404(client, tenant_user, tenant_user_2, kb):
    """Tenant A creates a dataset; tenant B's GET → 404 (visibility filter)."""
    _, headers_a = tenant_user
    user_b, headers_b = tenant_user_2
    # Sanity: A is tenant 1; B is in a different tenant. KB is on tenant 1.
    suffix = uuid.uuid4().hex[:8]
    create_resp = client.post(
        "/api/v1/eval/datasets/",
        headers=headers_a,
        json={"kb_id": kb.id, "name": f"hidden_{suffix}"},
    )
    assert create_resp.status_code == 201
    dataset_id = create_resp.json()["data"]["id"]

    # Tenant B tries to read — but if user_b's tenant == 1, they can see it,
    # in which case this test is meaningless. Skip instead of asserting wrong.
    if user_b.tenant_id == 1:
        client.delete(
            f"/api/v1/eval/datasets/{dataset_id}", headers=headers_a
        )
        pytest.skip("tenant_user_2 ended up in tenant 1; can't test isolation")

    resp = client.get(
        f"/api/v1/eval/datasets/{dataset_id}", headers=headers_b
    )
    assert resp.status_code == 404

    # Cleanup (A still owns it)
    client.delete(
        f"/api/v1/eval/datasets/{dataset_id}", headers=headers_a
    )


def test_update_dataset_partial_fields(client, tenant_user, kb):
    _, headers = tenant_user
    suffix = uuid.uuid4().hex[:8]
    create_resp = client.post(
        "/api/v1/eval/datasets/",
        headers=headers,
        json={"kb_id": kb.id, "name": f"u_{suffix}"},
    )
    assert create_resp.status_code == 201
    dataset_id = create_resp.json()["data"]["id"]

    update_resp = client.put(
        f"/api/v1/eval/datasets/{dataset_id}",
        headers=headers,
        json={"name": f"renamed_{suffix}", "is_active": 0},
    )
    assert update_resp.status_code == 200, update_resp.text
    body = update_resp.json()["data"]
    assert body["name"] == f"renamed_{suffix}"
    assert body["is_active"] == 0
    # kb_id 不可变(Pydantic schema 也不接受)
    assert body["kb_id"] == kb.id

    # Cleanup
    client.delete(
        f"/api/v1/eval/datasets/{dataset_id}", headers=headers
    )


def test_delete_dataset_cascades_items(client, tenant_user, kb):
    _, headers = tenant_user
    suffix = uuid.uuid4().hex[:8]
    create_resp = client.post(
        "/api/v1/eval/datasets/",
        headers=headers,
        json={"kb_id": kb.id, "name": f"d_{suffix}"},
    )
    assert create_resp.status_code == 201
    dataset_id = create_resp.json()["data"]["id"]

    # Add 2 items
    for i in range(2):
        item_resp = client.post(
            f"/api/v1/eval/datasets/{dataset_id}/items",
            headers=headers,
            json={"query": f"q{i}_{suffix}"},
        )
        assert item_resp.status_code == 201

    # Delete dataset
    del_resp = client.delete(
        f"/api/v1/eval/datasets/{dataset_id}", headers=headers
    )
    assert del_resp.status_code == 200

    # Verify items are gone via DB
    db = SessionLocal()
    try:
        remaining = (
            db.query(EvalDatasetItem)
            .filter(EvalDatasetItem.dataset_id == dataset_id)
            .count()
        )
        assert remaining == 0
    finally:
        db.close()


# ---------------------------------------------------------------------------
# item endpoint tests
# ---------------------------------------------------------------------------

def test_add_and_bulk_import_items_partial_errors(client, tenant_user, kb):
    _, headers = tenant_user
    suffix = uuid.uuid4().hex[:8]
    create_resp = client.post(
        "/api/v1/eval/datasets/",
        headers=headers,
        json={"kb_id": kb.id, "name": f"items_{suffix}"},
    )
    assert create_resp.status_code == 201
    dataset_id = create_resp.json()["data"]["id"]

    # Single add
    add_resp = client.post(
        f"/api/v1/eval/datasets/{dataset_id}/items",
        headers=headers,
        json={
            "query": f"single_{suffix}",
            "expected_doc_ids": [1, 2],
            "category": "factual",
            "difficulty": "easy",
        },
    )
    assert add_resp.status_code == 201, add_resp.text
    assert add_resp.json()["data"]["query"] == f"single_{suffix}"

    # Bulk import with 2 bad rows → 200 OK with partial_errors
    bulk_resp = client.post(
        f"/api/v1/eval/datasets/{dataset_id}/items/bulk-import",
        headers=headers,
        json={
            "rows": [
                {"query": f"good_a_{suffix}", "category": "reasoning"},
                {"query": f"bad_cat_{suffix}", "category": "bogus"},  # Pydantic fail
                {"query": f"good_b_{suffix}", "difficulty": "hard"},
                {"query": f"bad_diff_{suffix}", "difficulty": "super_hard"},  # Pydantic fail
            ]
        },
    )
    assert bulk_resp.status_code == 200, bulk_resp.text
    body = bulk_resp.json()["data"]
    assert body["imported_count"] == 2
    assert body["failed_count"] == 2
    assert {e["row_index"] for e in body["partial_errors"]} == {1, 3}

    # Verify items via DB (no GET /items endpoint yet — counted via DB)
    db = SessionLocal()
    try:
        item_count = (
            db.query(EvalDatasetItem)
            .filter(EvalDatasetItem.dataset_id == dataset_id)
            .count()
        )
        assert item_count == 3  # 1 single + 2 imported
        # Pick one for delete
        sample_item = (
            db.query(EvalDatasetItem)
            .filter(EvalDatasetItem.dataset_id == dataset_id)
            .first()
        )
        sample_id = sample_item.id
    finally:
        db.close()

    del_item_resp = client.delete(
        f"/api/v1/eval/datasets/{dataset_id}/items/{sample_id}",
        headers=headers,
    )
    assert del_item_resp.status_code == 200

    # Cleanup
    client.delete(
        f"/api/v1/eval/datasets/{dataset_id}", headers=headers
    )


def test_dataset_not_found_returns_404(client, tenant_user):
    _, headers = tenant_user
    resp = client.get("/api/v1/eval/datasets/999999", headers=headers)
    assert resp.status_code == 404


def test_list_items_endpoint_round_trip(client, tenant_user, kb):
    """GET /api/v1/eval/datasets/{id}/items —— T6 详情页表格用。

    新加的 endpoint,plan §CP2 T6 强依赖。覆盖:
      - 200 OK + PaginatedResponse 信封
      - 加 2 条 item 后 list 能看到
      - dataset 不可见 → 404
    """
    _, headers = tenant_user
    suffix = uuid.uuid4().hex[:8]
    create_resp = client.post(
        "/api/v1/eval/datasets/",
        headers=headers,
        json={"kb_id": kb.id, "name": f"list_items_{suffix}"},
    )
    assert create_resp.status_code == 201
    dataset_id = create_resp.json()["data"]["id"]

    # Empty list initially
    empty_resp = client.get(
        f"/api/v1/eval/datasets/{dataset_id}/items",
        headers=headers,
    )
    assert empty_resp.status_code == 200
    assert empty_resp.json()["total"] == 0
    assert empty_resp.json()["data"] == []

    # Add 2 items
    for i in range(2):
        r = client.post(
            f"/api/v1/eval/datasets/{dataset_id}/items",
            headers=headers,
            json={
                "query": f"q{i}_{suffix}",
                "category": "factual",
                "difficulty": "easy",
            },
        )
        assert r.status_code == 201

    # Now list should return both
    list_resp = client.get(
        f"/api/v1/eval/datasets/{dataset_id}/items",
        headers=headers,
    )
    assert list_resp.status_code == 200
    body = list_resp.json()
    assert body["total"] == 2
    assert len(body["data"]) == 2
    queries = {it["query"] for it in body["data"]}
    assert queries == {f"q0_{suffix}", f"q1_{suffix}"}

    # Cleanup
    client.delete(
        f"/api/v1/eval/datasets/{dataset_id}", headers=headers
    )


def test_list_items_other_tenant_returns_404(client, tenant_user, tenant_user_2):
    """跨租户 list_items → 404(visibility filter 一致)。"""
    _, headers_a = tenant_user
    user_b, headers_b = tenant_user_2
    # A 建 1 个 dataset(需 KB,先在 A 自己的 KB 上)
    # 用现成 builtin dataset(如果有),或跳过
    db = SessionLocal()
    try:
        # 找一个 tenant 1 的 KB
        from lumen_models.knowledge import KnowledgeBase

        kb_a = (
            db.query(KnowledgeBase).filter(KnowledgeBase.tenant_id == 1).first()
        )
    finally:
        db.close()
    if kb_a is None or user_b.tenant_id == 1:
        pytest.skip("no cross-tenant test environment")

    suffix = uuid.uuid4().hex[:8]
    create_resp = client.post(
        "/api/v1/eval/datasets/",
        headers=headers_a,
        json={"kb_id": kb_a.id, "name": f"hidden_items_{suffix}"},
    )
    assert create_resp.status_code == 201
    dataset_id = create_resp.json()["data"]["id"]

    resp = client.get(
        f"/api/v1/eval/datasets/{dataset_id}/items", headers=headers_b
    )
    assert resp.status_code == 404

    # Cleanup
    client.delete(
        f"/api/v1/eval/datasets/{dataset_id}", headers=headers_a
    )