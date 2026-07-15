"""Tests for MemoryService global-memory conversation_id tracking.

Added in M15: GlobalMemory rows now record which conversation they came
from, so the /dashboard/memory page can distinguish "this entry is
from the currently selected conversation" from "it came from some
other conversation". Legacy rows (pre-M15) have NULL and are treated
as "unknown source" → UI does not dim them.
"""
import pytest
import uuid

from lumen_core.database import SessionLocal
from lumen_models.tenant import Tenant
from lumen_services.memory_service import MemoryService


@pytest.fixture
def db():
    """Per-test SQLAlchemy session, closed in teardown."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def tenant(db):
    """Create a per-test Tenant row, delete it in teardown.

    Each test gets its own tenant so the global-memory rows it
    creates don't leak between tests (global_memory has a tenant_id
    FK and rows survive across tests in the dev DB).
    """
    suffix = uuid.uuid4().hex[:8]
    t = Tenant(name=f"mem_test_{suffix}", code=f"mem_test_{suffix}")
    db.add(t)
    db.commit()
    db.refresh(t)
    yield t
    try:
        # Clean up the global_memories rows first (no FK CASCADE).
        from lumen_models.memory import GlobalMemory
        db.query(GlobalMemory).filter(GlobalMemory.tenant_id == t.id).delete()
        db.delete(t)
        db.commit()
    except Exception:
        db.rollback()
        # Re-raise so pytest reports teardown failures instead of
        # silently leaking rows in the dev DB.
        raise
    # session close handled by the `db` fixture


def test_add_global_memory_persists_conversation_id(db, tenant):
    """add_global_memory stores the conv id; get_global_memory surfaces it."""
    svc = MemoryService()
    svc.add_global_memory(
        db, tenant_id=tenant.id, role="user", content="hi from conv 42",
        conversation_id=42,
    )
    rows = svc.get_global_memory(db, tenant_id=tenant.id)
    assert len(rows) == 1
    assert rows[0]["conversation_id"] == 42
    assert rows[0]["content"] == "hi from conv 42"


def test_add_global_memory_without_conversation_id_keeps_legacy_semantics(db, tenant):
    """Omitting conversation_id (legacy callers / pre-M15 paths) → NULL."""
    svc = MemoryService()
    svc.add_global_memory(db, tenant_id=tenant.id, role="user", content="legacy")
    rows = svc.get_global_memory(db, tenant_id=tenant.id)
    assert rows[0]["conversation_id"] is None


def test_search_global_memory_returns_conversation_id(db, tenant):
    """search_global_memory must include conversation_id so the UI can
    apply the same dim/filter logic to search results."""
    svc = MemoryService()
    svc.add_global_memory(
        db, tenant_id=tenant.id, role="user", content="alpha",
        conversation_id=7,
    )
    svc.add_global_memory(
        db, tenant_id=tenant.id, role="user", content="beta",
        conversation_id=8,
    )
    rows = svc.search_global_memory(db, tenant_id=tenant.id, query_text="alpha")
    assert len(rows) == 1
    assert rows[0]["conversation_id"] == 7


def test_get_global_memory_orders_chronologically(db, tenant):
    """Sanity: get_global_memory returns oldest→newest; both rows carry conv_id."""
    svc = MemoryService()
    svc.add_global_memory(db, tenant_id=tenant.id, role="user", content="first", conversation_id=1)
    svc.add_global_memory(db, tenant_id=tenant.id, role="user", content="second", conversation_id=2)
    rows = svc.get_global_memory(db, tenant_id=tenant.id)
    assert [r["content"] for r in rows] == ["first", "second"]
    assert [r["conversation_id"] for r in rows] == [1, 2]
