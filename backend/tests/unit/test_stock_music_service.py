"""Tests for StockMusicService query layer.

Covers tenant-scoped list/get and the safe file-path resolver that
blocks ``..`` escapes — mirrors ``test_stock_asset_service``.
"""
import uuid
from pathlib import Path

import pytest

from lumen_core.config import settings
from lumen_core.database import SessionLocal, ensure_stock_musics_table
from lumen_core.security import get_password_hash
from lumen_models.stock_music import StockMusic
from lumen_models.tenant import Tenant
from lumen_models.user import User
from lumen_services.stock_music_service import StockMusicService


@pytest.fixture
def db_session():
    ensure_stock_musics_table()
    db = SessionLocal()
    try:
        if not db.query(Tenant).filter(Tenant.id == 1).first():
            t = Tenant(id=1, name="Default Tenant", code="default")
            db.add(t); db.commit(); db.refresh(t)
        yield db
    finally:
        db.close()


def _make_tenant(db, suffix: str) -> Tenant:
    t = Tenant(name=f"sm_svc_t_{suffix}", code=f"sm_svc_t_{suffix}")
    db.add(t); db.commit(); db.refresh(t)
    return t


def _make_user(db, *, tenant_id: int, suffix: str) -> User:
    u = User(
        username=f"sm_svc_u_{suffix}",
        email=f"sm_svc_{suffix}@test.local",
        hashed_password=get_password_hash("x"),
        tenant_id=tenant_id,
        is_active=True,
    )
    db.add(u); db.commit(); db.refresh(u)
    return u


def _make_music(db, *, name: str, category: str, tenant_id, rel_path: str) -> StockMusic:
    row = StockMusic(
        name=name, category=category, description="test",
        file_path=rel_path, mime_type="audio/mpeg",
        file_size=235000, duration_seconds=30.0,
        source="builtin", tenant_id=tenant_id,
    )
    db.add(row); db.commit(); db.refresh(row)
    return row


def test_list_returns_global_and_own_tenant_only(db_session):
    """Service list exposes global rows + current tenant rows, never other tenants."""
    svc = StockMusicService()
    suffix = uuid.uuid4().hex[:8]
    t1 = _make_tenant(db_session, f"t1_{suffix}")
    t2 = _make_tenant(db_session, f"t2_{suffix}")
    user1 = _make_user(db_session, tenant_id=t1.id, suffix=f"t1_{suffix}")

    global_row = _make_music(
        db_session, name=f"g_{suffix}", category="舒缓",
        tenant_id=None, rel_path=f"stock/music/g_{suffix}.mp3",
    )
    own_row = _make_music(
        db_session, name=f"o_{suffix}", category="振奋",
        tenant_id=t1.id, rel_path=f"stock/music/{t1.id}/o_{suffix}.mp3",
    )
    other_row = _make_music(
        db_session, name=f"x_{suffix}", category="商务",
        tenant_id=t2.id, rel_path=f"stock/music/{t2.id}/x_{suffix}.mp3",
    )
    g_id, o_id, x_id = global_row.id, own_row.id, other_row.id

    try:
        # search by suffix filters down to the three rows we just made.
        rows, total = svc.list_musics(
            db_session, tenant_id=t1.id, search=suffix,
            page=1, page_size=50,
        )
        ids = {r.id for r in rows}
        assert g_id in ids
        assert o_id in ids
        assert x_id not in ids
        assert total == 2
    finally:
        for row_id in (g_id, o_id, x_id):
            db_session.query(StockMusic).filter(StockMusic.id == row_id).delete(
                synchronize_session=False,
            )
        db_session.query(User).filter(User.id == user1.id).delete(
            synchronize_session=False,
        )
        for tid in (t1.id, t2.id):
            db_session.query(Tenant).filter(Tenant.id == tid).delete(
                synchronize_session=False,
            )
        db_session.commit()


def test_get_returns_global_or_own_tenant_row(db_session):
    """``get`` returns a global row from any tenant, but only the tenant's own rows."""
    svc = StockMusicService()
    suffix = uuid.uuid4().hex[:8]
    t1 = _make_tenant(db_session, f"t1_{suffix}")
    t2 = _make_tenant(db_session, f"t2_{suffix}")
    g = _make_music(
        db_session, name=f"g_{suffix}", category="舒缓",
        tenant_id=None, rel_path=f"stock/music/g_{suffix}.mp3",
    )
    o = _make_music(
        db_session, name=f"o_{suffix}", category="舒缓",
        tenant_id=t1.id, rel_path=f"stock/music/{t1.id}/o_{suffix}.mp3",
    )
    other = _make_music(
        db_session, name=f"x_{suffix}", category="舒缓",
        tenant_id=t2.id, rel_path=f"stock/music/{t2.id}/x_{suffix}.mp3",
    )

    try:
        # Global row visible to any tenant
        assert svc.get(db_session, music_id=g.id, tenant_id=t1.id) is not None
        # Own tenant row visible
        assert svc.get(db_session, music_id=o.id, tenant_id=t1.id) is not None
        # Other tenant's row hidden
        assert svc.get(db_session, music_id=other.id, tenant_id=t1.id) is None
    finally:
        for row_id in (g.id, o.id, other.id):
            db_session.query(StockMusic).filter(StockMusic.id == row_id).delete(
                synchronize_session=False,
            )
        for tid in (t1.id, t2.id):
            db_session.query(Tenant).filter(Tenant.id == tid).delete(
                synchronize_session=False,
            )
        db_session.commit()


def test_get_file_abs_path_returns_existing_file(db_session):
    """``get_file_abs_path`` resolves a real on-disk file under STORAGE_DIR."""
    svc = StockMusicService()
    suffix = uuid.uuid4().hex[:8]
    rel_path = f"stock/music/abs_{suffix}.mp3"
    abs_path = settings.STORAGE_DIR / rel_path
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    abs_path.write_bytes(b"ID3\x03\x00\x00\x00\x00\x00\x00stub")
    row = StockMusic(
        name=f"abs_{suffix}", category="舒缓", description="",
        file_path=rel_path, mime_type="audio/mpeg",
        file_size=12, duration_seconds=0.1,
        source="builtin", tenant_id=None,
    )
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)

    try:
        resolved = svc.get_file_abs_path(row)
        assert resolved is not None
        assert Path(resolved).is_file()
    finally:
        db_session.query(StockMusic).filter(StockMusic.id == row.id).delete(
            synchronize_session=False,
        )
        db_session.commit()
        abs_path.unlink(missing_ok=True)


def test_get_file_abs_path_rejects_path_escape(db_session):
    """``file_path = '../evil.mp3'`` must NOT escape STORAGE_DIR."""
    svc = StockMusicService()
    suffix = uuid.uuid4().hex[:8]
    row = StockMusic(
        name=f"evil_{suffix}", category="戏剧", description="",
        file_path=f"../evil_{suffix}.mp3", mime_type="audio/mpeg",
        file_size=0, duration_seconds=1.0,
        source="builtin", tenant_id=None,
    )
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    try:
        assert svc.get_file_abs_path(row) is None
    finally:
        db_session.query(StockMusic).filter(StockMusic.id == row.id).delete(
            synchronize_session=False,
        )
        db_session.commit()
