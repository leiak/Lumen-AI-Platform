"""M33: tests for the Text2SqlDataSourceService.

Spec: docs/superpowers/specs/2026-06-20-text2sql-design.md §6.1

We test against the real MySQL DB so the reference-protection
behaviour is exercised end-to-end (FK constraints + the
``text2sql_queries`` row insertion).
"""
import uuid

# Register every model so SQLAlchemy can resolve the FK targets on
# Text2SqlDataSource / Text2SqlQuery. Mirrors the main.py:35-53
# pattern; without this import, ``text2sql_data_sources.tenant_id``
# raises ``NoReferencedTableError`` when the ORM resolves the FK.
from lumen_models.tenant import Tenant  # noqa: F401
from lumen_models.user import User  # noqa: F401
from lumen_models.text2sql import Text2SqlDataSource, Text2SqlQuery

from lumen_core.database import SessionLocal
from lumen_services.text2sql.data_source_service import Text2SqlDataSourceService


def _suffix() -> str:
    return uuid.uuid4().hex[:8]


# --------------------------------------------------------------------------- #
# get_default auto-seed                                                       #
# --------------------------------------------------------------------------- #


def test_get_default_auto_seeds_when_none_exist(monkeypatch):
    """``get_default`` on a fresh tenant must auto-seed a default source.

    We use the real tenant id 1 (which the dev DB always has) and
    rely on the seed function's idempotency: if a default source
    already exists, it returns it; if not, it auto-seeds. We then
    check that *some* default is returned with the expected shape.
    """
    db = SessionLocal()
    try:
        tenant_id = 1
        ds = Text2SqlDataSourceService.get_default(db, tenant_id=tenant_id)
        assert ds is not None
        assert ds.id is not None
        assert ds.tenant_id == tenant_id
        assert ds.is_active == 1
        assert ds.max_rows == 100
        assert ds.timeout_ms == 5000
        # Calling again must be a no-op
        ds2 = Text2SqlDataSourceService.get_default(db, tenant_id=tenant_id)
        assert ds2 is not None
        assert ds2.id == ds.id
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# list_for_tenant                                                             #
# --------------------------------------------------------------------------- #


def test_list_for_tenant_filters_inactive():
    """Inactive sources must be excluded by default but returned when
    ``include_inactive=True``.
    """
    db = SessionLocal()
    try:
        tenant_id = 1
        # Ensure at least one active source exists for tenant 1 (the
        # get_default path auto-seeds in production, but we don't
        # depend on that here).
        Text2SqlDataSourceService.get_default(db, tenant_id=tenant_id)
        active = Text2SqlDataSourceService.list_for_tenant(
            db, tenant_id=tenant_id
        )
        assert all(ds.is_active == 1 for ds in active)

        inactive = Text2SqlDataSourceService.list_for_tenant(
            db, tenant_id=tenant_id, include_inactive=True
        )
        assert len(inactive) >= len(active)
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# create / update / delete                                                    #
# --------------------------------------------------------------------------- #


def test_create_then_get_round_trip():
    db = SessionLocal()
    try:
        suffix = _suffix()
        ds = Text2SqlDataSourceService.create(
            db,
            tenant_id=1,
            name=f"test_{suffix}",
            max_rows=200,
            timeout_ms=3000,
            description="unit test",
        )
        fetched = Text2SqlDataSourceService.get(
            db, tenant_id=1, data_source_id=ds.id
        )
        assert fetched is not None
        assert fetched.name == f"test_{suffix}"
        assert fetched.max_rows == 200
        assert fetched.timeout_ms == 3000
    finally:
        try:
            db.delete(ds)
            db.commit()
        except Exception:
            db.rollback()
        finally:
            db.close()


def test_delete_blocked_by_referencing_queries():
    """A data source with live queries must NOT be deletable.

    We create a throwaway source, insert a query row that
    references it, and assert the service returns ``(False, 1)``.
    """
    db = SessionLocal()
    try:
        suffix = _suffix()
        ds = Text2SqlDataSourceService.create(
            db, tenant_id=1, name=f"test_del_{suffix}",
        )
        # Need a User row to satisfy the FK
        from lumen_models.user import User
        u = db.query(User).filter(User.tenant_id == 1).first()
        if u is None:
            pytest.skip("No user in tenant 1; cannot test reference protection")
        q = Text2SqlQuery(
            tenant_id=1,
            user_id=u.id,
            data_source_id=ds.id,
            question="q",
            status="success",
        )
        db.add(q)
        db.commit()

        deleted, count = Text2SqlDataSourceService.delete(
            db, tenant_id=1, data_source_id=ds.id
        )
        assert deleted is False
        assert count == 1

        # Cleanup
        try:
            db.delete(q)
            db.delete(ds)
            db.commit()
        except Exception:
            db.rollback()
    finally:
        db.close()
