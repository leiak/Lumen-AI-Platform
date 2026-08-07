"""Tests for StockMusic ORM model + ensure_stock_musics_table.

M36.2.2 background-music library — mirrors the M36.2.1
``test_stock_asset_model`` shape.
"""
import uuid

import pytest
from sqlalchemy import inspect

from lumen_core.database import SessionLocal, engine, ensure_stock_musics_table
from lumen_core.security import get_password_hash
from lumen_models.stock_music import StockMusic
from lumen_models.tenant import Tenant
from lumen_models.user import User


@pytest.fixture
def db_session():
    ensure_stock_musics_table()
    db = SessionLocal()
    try:
        if not db.query(Tenant).filter(Tenant.id == 1).first():
            t = Tenant(id=1, name="Default Tenant", code="default")
            db.add(t)
            db.commit()
            db.refresh(t)
        yield db
    finally:
        db.close()


def _make_tenant(db, suffix: str) -> Tenant:
    t = Tenant(name=f"sm_mdl_t_{suffix}", code=f"sm_mdl_t_{suffix}")
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


def _make_user(db, *, tenant_id: int, suffix: str) -> User:
    u = User(
        username=f"sm_mdl_u_{suffix}",
        email=f"sm_mdl_{suffix}@test.local",
        hashed_password=get_password_hash("x"),
        tenant_id=tenant_id,
        is_active=True,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def test_stock_musics_table_exists():
    """ensure_stock_musics_table creates the stock_musics table."""
    ensure_stock_musics_table()
    insp = inspect(engine)
    assert insp.has_table("stock_musics")


def test_ensure_is_idempotent():
    """Calling ensure_stock_musics_table twice is a no-op."""
    ensure_stock_musics_table()
    ensure_stock_musics_table()


def test_create_global_stock_music(db_session):
    """Built-in BGM rows have tenant_id NULL (visible to every tenant)."""
    suffix = uuid.uuid4().hex[:8]
    row = StockMusic(
        name=f"global_{suffix}",
        category="舒缓",
        description="Test global BGM",
        file_path=f"stock/music/{suffix}.mp3",
        mime_type="audio/mpeg",
        file_size=235000,
        duration_seconds=30.0,
        source="builtin",
        tenant_id=None,
    )
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    assert row.id is not None
    assert row.tenant_id is None
    assert row.source == "builtin"
    assert row.duration_seconds == 30.0

    db_session.query(StockMusic).filter(StockMusic.id == row.id).delete(
        synchronize_session=False,
    )
    db_session.commit()


def test_create_tenant_scoped_stock_music(db_session):
    """Per-tenant BGM rows keep tenant_id set to the owning tenant."""
    suffix = uuid.uuid4().hex[:8]
    tenant = _make_tenant(db_session, suffix)
    user = _make_user(db_session, tenant_id=tenant.id, suffix=suffix)
    row = StockMusic(
        name=f"tenant_{suffix}",
        category="振奋",
        description="Test tenant BGM",
        file_path=f"stock/music/{tenant.id}/{suffix}.mp3",
        mime_type="audio/mpeg",
        file_size=128000,
        duration_seconds=45.0,
        source="uploaded",
        tenant_id=tenant.id,
    )
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    assert row.tenant_id == tenant.id
    assert row.source == "uploaded"

    db_session.query(StockMusic).filter(StockMusic.id == row.id).delete(
        synchronize_session=False,
    )
    db_session.query(User).filter(User.id == user.id).delete(
        synchronize_session=False,
    )
    db_session.query(Tenant).filter(Tenant.id == tenant.id).delete(
        synchronize_session=False,
    )
    db_session.commit()
