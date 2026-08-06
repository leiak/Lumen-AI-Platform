"""M37.1 T3: Tests for EvalDatasetService business logic.

Spec: docs-internal/superpowers/specs/m37-rag-evaluation.md §4.1
Plan: docs-internal/superpowers/plans/m37-plan.md CP1 T3 (10 tests)
"""
import uuid

import pytest

# Pre-load every ORM module that Base.metadata needs for FK resolution
# (KnowledgeBase.embedding_model_config_id → model_configs.id). If any of
# these are missing the SQLAlchemy mapper raises NoReferencedTableError
# when the flush step walks the sorted-table list.
from lumen_core.database import SessionLocal, ensure_eval_datasets_table
from lumen_core.security import get_password_hash
from lumen_models import model_config  # noqa: F401  — registers model_configs table
from lumen_models.eval_dataset import EvalDataset, EvalDatasetItem
from lumen_models.knowledge import KnowledgeBase
from lumen_models.tenant import Tenant
from lumen_models.user import User
from lumen_schemas.eval_dataset import (
    EvalDatasetCreate,
    EvalDatasetItemCreate,
    EvalDatasetUpdate,
)
from lumen_services.eval_dataset_service import EvalDatasetService


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db_session():
    ensure_eval_datasets_table()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _make_tenant(db, suffix: str) -> Tenant:
    t = Tenant(name=f"eval_ds_t_{suffix}", code=f"eval_ds_t_{suffix}")
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


def _make_user(db, *, tenant_id: int, suffix: str) -> User:
    u = User(
        username=f"eval_ds_u_{suffix}",
        email=f"eval_ds_{suffix}@test.local",
        hashed_password=get_password_hash("x"),
        tenant_id=tenant_id,
        is_active=True,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _make_kb(db, *, tenant_id: int, suffix: str) -> KnowledgeBase:
    kb = KnowledgeBase(
        name=f"eval_kb_{suffix}",
        tenant_id=tenant_id,
        embedding_model="nomic-embed-text",
        status="active",
    )
    db.add(kb)
    db.commit()
    db.refresh(kb)
    return kb


def _cleanup(db, *, dataset_ids, item_ids, kb_id, user_id, tenant_id):
    """Teardown — deletes items first, then dataset, then kb/user/tenant."""
    if item_ids:
        db.query(EvalDatasetItem).filter(EvalDatasetItem.id.in_(item_ids)).delete(
            synchronize_session=False,
        )
    if dataset_ids:
        db.query(EvalDataset).filter(EvalDataset.id.in_(dataset_ids)).delete(
            synchronize_session=False,
        )
    if kb_id:
        db.query(KnowledgeBase).filter(KnowledgeBase.id == kb_id).delete(
            synchronize_session=False,
        )
    if user_id:
        db.query(User).filter(User.id == user_id).delete(
            synchronize_session=False,
        )
    if tenant_id:
        db.query(Tenant).filter(Tenant.id == tenant_id).delete(
            synchronize_session=False,
        )
    db.commit()


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------

def test_create_and_get_dataset(db_session):
    """Create a tenant-scoped dataset, then fetch it back."""
    svc = EvalDatasetService()
    suffix = uuid.uuid4().hex[:8]
    tenant = _make_tenant(db_session, suffix)
    user = _make_user(db_session, tenant_id=tenant.id, suffix=suffix)
    kb = _make_kb(db_session, tenant_id=tenant.id, suffix=suffix)
    dataset_ids, item_ids = [], []
    try:
        row = svc.create_dataset(
            db_session,
            payload=EvalDatasetCreate(kb_id=kb.id, name=f"baseline_{suffix}", source="manual"),
            tenant_id=tenant.id,
            created_by=user.id,
        )
        dataset_ids.append(row.id)
        assert row.tenant_id == tenant.id
        assert row.kb_id == kb.id
        assert row.source == "manual"
        assert row.is_active == 1
        assert row.created_by == user.id

        # get_dataset should find it
        got = svc.get_dataset(
            db_session, dataset_id=row.id, tenant_id=tenant.id
        )
        assert got is not None
        assert got.name == f"baseline_{suffix}"
    finally:
        _cleanup(db_session, dataset_ids=dataset_ids, item_ids=item_ids,
                 kb_id=kb.id, user_id=user.id, tenant_id=tenant.id)


def test_create_dataset_rejects_invisible_kb(db_session):
    """Tenant A's KB is not visible to tenant B → create should raise ValueError."""
    svc = EvalDatasetService()
    suffix = uuid.uuid4().hex[:8]
    tenant_a = _make_tenant(db_session, f"a_{suffix}")
    tenant_b = _make_tenant(db_session, f"b_{suffix}")
    user_b = _make_user(db_session, tenant_id=tenant_b.id, suffix=f"b_{suffix}")
    kb_a = _make_kb(db_session, tenant_id=tenant_a.id, suffix=f"a_{suffix}")
    dataset_ids, item_ids = [], []
    try:
        with pytest.raises(ValueError, match="not visible"):
            svc.create_dataset(
                db_session,
                payload=EvalDatasetCreate(kb_id=kb_a.id, name="x"),
                tenant_id=tenant_b.id,
                created_by=user_b.id,
            )
    finally:
        # 每个 tenant 独立走一次 _cleanup:删 kb 后删 user,最后 tenant
        # tenant_a 只有 kb_a,没有 user;tenant_b 有 user_b
        _cleanup(db_session, dataset_ids=dataset_ids, item_ids=item_ids,
                 kb_id=kb_a.id, user_id=None, tenant_id=tenant_a.id)
        _cleanup(db_session, dataset_ids=dataset_ids, item_ids=item_ids,
                 kb_id=None, user_id=user_b.id, tenant_id=tenant_b.id)


def test_list_datasets_filters_by_tenant(db_session):
    """Tenant A only sees own + builtin; never sees tenant B's datasets."""
    svc = EvalDatasetService()
    suffix = uuid.uuid4().hex[:8]
    tenant_a = _make_tenant(db_session, f"a_{suffix}")
    tenant_b = _make_tenant(db_session, f"b_{suffix}")
    user_a = _make_user(db_session, tenant_id=tenant_a.id, suffix=f"a_{suffix}")
    user_b = _make_user(db_session, tenant_id=tenant_b.id, suffix=f"b_{suffix}")
    kb_a = _make_kb(db_session, tenant_id=tenant_a.id, suffix=f"a_{suffix}")
    kb_b = _make_kb(db_session, tenant_id=tenant_b.id, suffix=f"b_{suffix}")
    a_ids, b_ids = [], []
    item_ids = []
    try:
        a_row = svc.create_dataset(
            db_session, payload=EvalDatasetCreate(kb_id=kb_a.id, name=f"a_{suffix}"),
            tenant_id=tenant_a.id, created_by=user_a.id,
        )
        a_ids.append(a_row.id)
        b_row = svc.create_dataset(
            db_session, payload=EvalDatasetCreate(kb_id=kb_b.id, name=f"b_{suffix}"),
            tenant_id=tenant_b.id, created_by=user_b.id,
        )
        b_ids.append(b_row.id)

        rows, total = svc.list_datasets(
            db_session, tenant_id=tenant_a.id, page=1, page_size=50,
        )
        ids = {r[0].id for r in rows}
        assert a_row.id in ids
        assert b_row.id not in ids
        assert total >= 1
    finally:
        # tenant_a: dataset → kb → user → tenant
        _cleanup(db_session, dataset_ids=a_ids + b_ids, item_ids=item_ids,
                 kb_id=kb_a.id, user_id=user_a.id, tenant_id=tenant_a.id)
        # tenant_b: dataset(b_id)已删 → kb → user → tenant
        _cleanup(db_session, dataset_ids=[], item_ids=[],
                 kb_id=kb_b.id, user_id=user_b.id, tenant_id=tenant_b.id)


def test_list_datasets_item_count_subquery(db_session):
    """``item_count`` should reflect EvalDatasetItem rows accurately."""
    svc = EvalDatasetService()
    suffix = uuid.uuid4().hex[:8]
    tenant = _make_tenant(db_session, suffix)
    user = _make_user(db_session, tenant_id=tenant.id, suffix=suffix)
    kb = _make_kb(db_session, tenant_id=tenant.id, suffix=suffix)
    dataset_ids, item_ids = [], []
    try:
        row = svc.create_dataset(
            db_session, payload=EvalDatasetCreate(kb_id=kb.id, name=f"count_{suffix}"),
            tenant_id=tenant.id, created_by=user.id,
        )
        dataset_ids.append(row.id)
        for i in range(3):
            item = svc.add_item(
                db_session, dataset_id=row.id, tenant_id=tenant.id,
                payload=EvalDatasetItemCreate(query=f"q{i}_{suffix}"),
            )
            item_ids.append(item.id)

        rows, _ = svc.list_datasets(
            db_session, tenant_id=tenant.id, page=1, page_size=50,
        )
        match = [r for r in rows if r[0].id == row.id]
        assert len(match) == 1
        assert match[0][1] == 3  # item_count
    finally:
        _cleanup(db_session, dataset_ids=dataset_ids, item_ids=item_ids,
                 kb_id=kb.id, user_id=user.id, tenant_id=tenant.id)


def test_update_dataset_partial_fields(db_session):
    """Only non-None fields are written; kb_id is never touched."""
    svc = EvalDatasetService()
    suffix = uuid.uuid4().hex[:8]
    tenant = _make_tenant(db_session, suffix)
    user = _make_user(db_session, tenant_id=tenant.id, suffix=suffix)
    kb = _make_kb(db_session, tenant_id=tenant.id, suffix=suffix)
    dataset_ids, item_ids = [], []
    try:
        row = svc.create_dataset(
            db_session, payload=EvalDatasetCreate(kb_id=kb.id, name=f"u_{suffix}"),
            tenant_id=tenant.id, created_by=user.id,
        )
        dataset_ids.append(row.id)

        updated = svc.update_dataset(
            db_session, dataset_id=row.id, tenant_id=tenant.id,
            payload=EvalDatasetUpdate(name=f"renamed_{suffix}", is_active=0),
        )
        assert updated is not None
        assert updated.name == f"renamed_{suffix}"
        assert updated.is_active == 0
        # kb_id should be untouched
        assert updated.kb_id == kb.id
    finally:
        _cleanup(db_session, dataset_ids=dataset_ids, item_ids=item_ids,
                 kb_id=kb.id, user_id=user.id, tenant_id=tenant.id)


def test_delete_dataset_cascades_items(db_session):
    """Deleting a dataset should CASCADE delete its items."""
    svc = EvalDatasetService()
    suffix = uuid.uuid4().hex[:8]
    tenant = _make_tenant(db_session, suffix)
    user = _make_user(db_session, tenant_id=tenant.id, suffix=suffix)
    kb = _make_kb(db_session, tenant_id=tenant.id, suffix=suffix)
    dataset_ids, item_ids = [], []
    try:
        row = svc.create_dataset(
            db_session, payload=EvalDatasetCreate(kb_id=kb.id, name=f"d_{suffix}"),
            tenant_id=tenant.id, created_by=user.id,
        )
        dataset_ids.append(row.id)
        for i in range(2):
            item = svc.add_item(
                db_session, dataset_id=row.id, tenant_id=tenant.id,
                payload=EvalDatasetItemCreate(query=f"q{i}"),
            )
            item_ids.append(item.id)

        # items exist before delete
        assert db_session.query(EvalDatasetItem).filter(
            EvalDatasetItem.id.in_(item_ids)
        ).count() == 2

        ok = svc.delete_dataset(
            db_session, dataset_id=row.id, tenant_id=tenant.id
        )
        assert ok is True
        # dataset_ids is local var; let teardown skip it now that it's gone
        dataset_ids.remove(row.id)

        # items CASCADE
        assert db_session.query(EvalDatasetItem).filter(
            EvalDatasetItem.id.in_(item_ids)
        ).count() == 0
    finally:
        _cleanup(db_session, dataset_ids=dataset_ids, item_ids=item_ids,
                 kb_id=kb.id, user_id=user.id, tenant_id=tenant.id)


def test_add_and_list_items(db_session):
    svc = EvalDatasetService()
    suffix = uuid.uuid4().hex[:8]
    tenant = _make_tenant(db_session, suffix)
    user = _make_user(db_session, tenant_id=tenant.id, suffix=suffix)
    kb = _make_kb(db_session, tenant_id=tenant.id, suffix=suffix)
    dataset_ids, item_ids = [], []
    try:
        row = svc.create_dataset(
            db_session, payload=EvalDatasetCreate(kb_id=kb.id, name=f"items_{suffix}"),
            tenant_id=tenant.id, created_by=user.id,
        )
        dataset_ids.append(row.id)
        for i in range(3):
            item = svc.add_item(
                db_session, dataset_id=row.id, tenant_id=tenant.id,
                payload=EvalDatasetItemCreate(
                    query=f"q{i}", expected_doc_ids=[i * 10, i * 10 + 1],
                    category="factual", difficulty="easy",
                ),
            )
            item_ids.append(item.id)

        items, total = svc.list_items(
            db_session, dataset_id=row.id, tenant_id=tenant.id,
            page=1, page_size=10,
        )
        assert total == 3
        assert len(items) == 3
        assert all(it.query.startswith("q") for it in items)
    finally:
        _cleanup(db_session, dataset_ids=dataset_ids, item_ids=item_ids,
                 kb_id=kb.id, user_id=user.id, tenant_id=tenant.id)


def test_bulk_import_items_partial_errors(db_session):
    """Bad row → partial_errors; good rows still import."""
    svc = EvalDatasetService()
    suffix = uuid.uuid4().hex[:8]
    tenant = _make_tenant(db_session, suffix)
    user = _make_user(db_session, tenant_id=tenant.id, suffix=suffix)
    kb = _make_kb(db_session, tenant_id=tenant.id, suffix=suffix)
    dataset_ids, item_ids = [], []
    try:
        row = svc.create_dataset(
            db_session, payload=EvalDatasetCreate(kb_id=kb.id, name=f"bulk_{suffix}"),
            tenant_id=tenant.id, created_by=user.id,
        )
        dataset_ids.append(row.id)

        rows = [
            {"query": "good1", "category": "factual"},
            {"query": "good2", "category": "reasoning", "difficulty": "hard"},
            {"query": "bad_category", "category": "bogus"},   # Pydantic Literal fail
            {"query": "good3"},
            {"query": "bad_difficulty", "difficulty": "super_hard"},  # Pydantic Literal fail
        ]
        resp = svc.bulk_import_items(
            db_session, dataset_id=row.id, tenant_id=tenant.id, rows=rows,
        )
        assert resp.imported_count == 3
        assert resp.failed_count == 2
        assert {e.row_index for e in resp.partial_errors} == {2, 4}

        # collect actual item ids for teardown
        items, _ = svc.list_items(
            db_session, dataset_id=row.id, tenant_id=tenant.id,
            page=1, page_size=100,
        )
        item_ids.extend(it.id for it in items)
    finally:
        _cleanup(db_session, dataset_ids=dataset_ids, item_ids=item_ids,
                 kb_id=kb.id, user_id=user.id, tenant_id=tenant.id)


def test_get_dataset_returns_none_for_other_tenant(db_session):
    """Tenant A cannot read tenant B's dataset (visibility filter)."""
    svc = EvalDatasetService()
    suffix = uuid.uuid4().hex[:8]
    tenant_a = _make_tenant(db_session, f"a_{suffix}")
    tenant_b = _make_tenant(db_session, f"b_{suffix}")
    user_a = _make_user(db_session, tenant_id=tenant_a.id, suffix=f"a_{suffix}")
    kb_a = _make_kb(db_session, tenant_id=tenant_a.id, suffix=f"a_{suffix}")
    dataset_ids, item_ids = [], []
    try:
        row = svc.create_dataset(
            db_session, payload=EvalDatasetCreate(kb_id=kb_a.id, name=f"hidden_{suffix}"),
            tenant_id=tenant_a.id, created_by=user_a.id,
        )
        dataset_ids.append(row.id)

        got = svc.get_dataset(
            db_session, dataset_id=row.id, tenant_id=tenant_b.id,
        )
        assert got is None

        delete_blocked = svc.delete_dataset(
            db_session, dataset_id=row.id, tenant_id=tenant_b.id,
        )
        assert delete_blocked is False
    finally:
        # tenant_a 自己清(包含 user_a + kb_a + dataset)
        _cleanup(db_session, dataset_ids=dataset_ids, item_ids=item_ids,
                 kb_id=kb_a.id, user_id=user_a.id, tenant_id=tenant_a.id)
        # tenant_b 没人/kb,只清 tenant
        _cleanup(db_session, dataset_ids=[], item_ids=[],
                 kb_id=None, user_id=None, tenant_id=tenant_b.id)


def test_builtin_dataset_visible_to_all_tenants(db_session):
    """tenant_id=NULL means builtin — visible to every tenant."""
    svc = EvalDatasetService()
    suffix = uuid.uuid4().hex[:8]
    tenant = _make_tenant(db_session, suffix)
    user = _make_user(db_session, tenant_id=tenant.id, suffix=suffix)
    kb = _make_kb(db_session, tenant_id=tenant.id, suffix=suffix)
    dataset_ids, item_ids = [], []
    try:
        # Seed a builtin dataset directly via ORM (bypasses Create schema's
        # auto-derived tenant_id — see create_dataset docstring).
        builtin = EvalDataset(
            kb_id=kb.id, tenant_id=None, name=f"builtin_{suffix}",
            source="manual", is_active=1, created_by=None,
        )
        db_session.add(builtin)
        db_session.commit()
        db_session.refresh(builtin)
        dataset_ids.append(builtin.id)

        # tenant should see it via list
        rows, total = svc.list_datasets(
            db_session, tenant_id=tenant.id, page=1, page_size=50,
        )
        assert any(r[0].id == builtin.id for r in rows)

        # tenant should be able to get it
        got = svc.get_dataset(
            db_session, dataset_id=builtin.id, tenant_id=tenant.id,
        )
        assert got is not None
        assert got.tenant_id is None
    finally:
        _cleanup(db_session, dataset_ids=dataset_ids, item_ids=item_ids,
                 kb_id=kb.id, user_id=user.id, tenant_id=tenant.id)