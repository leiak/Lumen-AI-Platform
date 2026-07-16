"""Tests for StockAsset ORM model + ensure_stock_assets_table.

M36.2.1 stock footage library.
"""
import uuid
from pathlib import Path

import pytest
from sqlalchemy import inspect

from lumen_core.database import (
    SessionLocal,
    engine,
    ensure_stock_assets_table,
)
from lumen_core.security import get_password_hash
from lumen_models.stock_asset import StockAsset
from lumen_models.tenant import Tenant
from lumen_models.user import User


@pytest.fixture
def db_session():
    ensure_stock_assets_table()
    db = SessionLocal()
    try:
        tenant = db.query(Tenant).filter(Tenant.id == 1).first()
        if not tenant:
            tenant = Tenant(id=1, name="Default Tenant", code="default")
            db.add(tenant)
            db.commit()
            db.refresh(tenant)
        yield db
    finally:
        db.close()


def _make_tenant(db, suffix: str) -> Tenant:
    t = Tenant(name=f"stock_mdl_t_{suffix}", code=f"stock_mdl_t_{suffix}")
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


def _make_user(db, *, tenant_id: int, suffix: str) -> User:
    u = User(
        username=f"stock_mdl_u_{suffix}",
        email=f"stock_mdl_{suffix}@test.local",
        hashed_password=get_password_hash("x"),
        tenant_id=tenant_id,
        is_active=True,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def test_stock_assets_table_exists():
    """ensure_stock_assets_table creates the stock_assets table."""
    ensure_stock_assets_table()
    insp = inspect(engine)
    assert insp.has_table("stock_assets")


def test_ensure_is_idempotent():
    """Calling ensure_stock_assets_table twice is a no-op."""
    ensure_stock_assets_table()
    ensure_stock_assets_table()


def test_create_global_stock_asset(db_session):
    """Built-in stock rows have tenant_id NULL (visible to every tenant)."""
    suffix = uuid.uuid4().hex[:8]
    row = StockAsset(
        name=f"global_{suffix}",
        category="风景",
        tags=["builtin", "test"],
        file_path=f"stock/test_{suffix}.png",
        mime_type="image/png",
        file_size=1024,
        source="builtin",
        tenant_id=None,
        description="Test global stock",
    )
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    assert row.id is not None
    assert row.tenant_id is None
    assert row.source == "builtin"

    db_session.query(StockAsset).filter(StockAsset.id == row.id).delete(
        synchronize_session=False,
    )
    db_session.commit()


def test_create_tenant_scoped_stock_asset(db_session):
    """Per-tenant stock rows keep tenant_id set to the owning tenant."""
    suffix = uuid.uuid4().hex[:8]
    tenant = _make_tenant(db_session, suffix)
    user = _make_user(db_session, tenant_id=tenant.id, suffix=suffix)
    row = StockAsset(
        name=f"tenant_{suffix}",
        category="产品",
        tags=["uploaded"],
        file_path=f"stock/{tenant.id}/tenant_{suffix}.png",
        mime_type="image/png",
        file_size=2048,
        source="uploaded",
        tenant_id=tenant.id,
        description="Test tenant stock",
    )
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    assert row.tenant_id == tenant.id
    assert row.source == "uploaded"

    db_session.query(StockAsset).filter(StockAsset.id == row.id).delete(
        synchronize_session=False,
    )
    db_session.query(User).filter(User.id == user.id).delete(
        synchronize_session=False,
    )
    db_session.query(Tenant).filter(Tenant.id == tenant.id).delete(
        synchronize_session=False,
    )
    db_session.commit()
