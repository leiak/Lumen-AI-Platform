"""M36.2.2 tests: BGM asset resolution in VideoComposeService.

Covers ``kind='music'`` resolution in ``_resolve_asset_to_path`` plus
the ``music_not_found`` error tag flowing back through the create
path. Regression: when BGM is not specified, behavior is unchanged.
"""
import uuid
from pathlib import Path

import pytest
from fastapi import BackgroundTasks

from lumen_core.config import settings
from lumen_core.database import SessionLocal, ensure_stock_musics_table
from lumen_core.security import get_password_hash
from lumen_models.stock_music import StockMusic
from lumen_models.tenant import Tenant
from lumen_models.user import User
from lumen_models.video import GeneratedVideo
from lumen_schemas.video import VideoComposeCreate
from lumen_services.video_compose_service import (
    VideoComposeService,
    _resolve_asset_to_path,
)

import lumen_models.chat  # noqa: F401  (FK: conversations)
import lumen_models.model_config  # noqa: F401
import lumen_models.playbook  # noqa: F401
import lumen_models.tts  # noqa: F401
import lumen_models.subtitle  # noqa: F401
import lumen_models.video  # noqa: F401


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


def _make_tenant_user(db, suffix):
    t = Tenant(name=f"bgm_t_{suffix}", code=f"bgm_{suffix}")
    db.add(t); db.commit(); db.refresh(t)
    u = User(
        username=f"bgm_u_{suffix}",
        email=f"bgm_{suffix}@test.local",
        hashed_password=get_password_hash("x"),
        tenant_id=t.id, is_active=True,
    )
    db.add(u); db.commit(); db.refresh(u)
    return t, u


def _make_music(db, *, name: str, rel_path: str) -> StockMusic:
    row = StockMusic(
        name=name, category="舒缓", description="",
        file_path=rel_path, mime_type="audio/mpeg",
        file_size=235000, duration_seconds=30.0,
        source="builtin", tenant_id=None,
    )
    db.add(row); db.commit(); db.refresh(row)
    return row


@pytest.fixture
def music_row(db_session):
    """Insert one global builtin BGM row backed by a real on-disk stub."""
    suffix = uuid.uuid4().hex[:8]
    rel_path = f"stock/music/bgm_{suffix}.mp3"
    abs_path = settings.STORAGE_DIR / rel_path
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    abs_path.write_bytes(b"ID3\x03\x00\x00\x00\x00\x00\x00stub")
    row = _make_music(db_session, name=f"bgm_{suffix}", rel_path=rel_path)
    yield row
    db_session.query(StockMusic).filter(StockMusic.id == row.id).delete(
        synchronize_session=False,
    )
    db_session.commit()
    abs_path.unlink(missing_ok=True)


def test_resolve_music_id_to_disk_path(db_session, music_row):
    """_resolve_asset_to_path with kind='music' resolves a builtin BGM id
    to its on-disk absolute path (same pattern as 'audio' / 'subtitle')."""
    resolved = _resolve_asset_to_path(
        db_session, tenant_id=1, kind="music", value=str(music_row.id),
    )
    assert resolved is not None
    assert Path(resolved).is_file()
    assert resolved.endswith(f"bgm_{music_row.name.removeprefix('bgm_')}.mp3")


def test_resolve_music_invalid_id_raises_music_not_found(db_session):
    """Unknown BGM id → AssetNotFound('music_not_found') (NOT a generic ValueError)."""
    from lumen_services.video_compose_service import AssetNotFound
    with pytest.raises(AssetNotFound) as excinfo:
        _resolve_asset_to_path(
            db_session, tenant_id=1, kind="music", value="9999999",
        )
    assert excinfo.value.tag == "music_not_found"


def _cleanup(tenant_id: int, user_id: int, video_id: int | None = None) -> None:
    """Delete generated_videos → users → tenants in FK-safe order using
    a fresh session. Mirrors the M36 / M22 cleanup pattern (separate
    SessionLocal so the test's main session isn't tied to cleanup)."""
    db = SessionLocal()
    try:
        if video_id is not None:
            db.query(GeneratedVideo).filter(GeneratedVideo.id == video_id).delete(
                synchronize_session=False,
            )
            db.commit()
        # Even when no row was created (err-tag path), defensively delete
        # any stray generated_videos referencing this user_id.
        db.query(GeneratedVideo).filter(GeneratedVideo.user_id == user_id).delete(
            synchronize_session=False,
        )
        db.commit()
        db.query(User).filter(User.id == user_id).delete(synchronize_session=False)
        db.commit()
        db.query(Tenant).filter(Tenant.id == tenant_id).delete(synchronize_session=False)
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()


def test_create_with_bgm_resolves_stock_music_id(db_session, music_row, tmp_path):
    """``create`` accepts ``background_music_path='1'`` (built-in id),
    persists the resolved local path in ``params.background_music_path``,
    and writes the row in ``status=pending``. The BGM file is resolved
    even though no audio / subtitle is provided."""
    suffix = uuid.uuid4().hex[:8]
    tenant, user = _make_tenant_user(db_session, suffix)
    img = tmp_path / "img.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\nstub")

    svc = VideoComposeService()
    payload = VideoComposeCreate(
        source_images=[str(img)],
        audio_path=None,  # no narration
        background_music_path=str(music_row.id),
        background_music_volume=0.25,
    )
    bg = BackgroundTasks()
    row = None
    try:
        row, err = svc.create(
            db_session,
            tenant_id=tenant.id, user_id=user.id,
            payload=payload, background_tasks=bg,
        )
        assert err is None
        assert row is not None
        assert row.status == "pending"
        assert row.params is not None
        assert row.params["background_music_path"] is not None
        assert row.params["background_music_path"].endswith(".mp3")
        assert row.params["background_music_volume"] == 0.25
    finally:
        _cleanup(tenant.id, user.id, video_id=(row.id if row else None))


def test_create_with_invalid_bgm_id_returns_music_not_found(db_session):
    """``create`` with ``background_music_path='999'`` → ``('music_not_found')``
    error tag, no row written."""
    suffix = uuid.uuid4().hex[:8]
    tenant, user = _make_tenant_user(db_session, suffix)

    svc = VideoComposeService()
    payload = VideoComposeCreate(
        source_images=["/tmp/anything.png"],
        background_music_path="999",
    )
    bg = BackgroundTasks()
    try:
        row, err = svc.create(
            db_session,
            tenant_id=tenant.id, user_id=user.id,
            payload=payload, background_tasks=bg,
        )
        assert row is None
        assert err == "music_not_found"
    finally:
        _cleanup(tenant.id, user.id)


def test_create_without_bgm_still_works(db_session, tmp_path):
    """Regression: omitting BGM must keep the legacy 0-BGM code path."""
    suffix = uuid.uuid4().hex[:8]
    tenant, user = _make_tenant_user(db_session, suffix)
    img = tmp_path / "img.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\nstub")

    svc = VideoComposeService()
    payload = VideoComposeCreate(source_images=[str(img)])  # no BGM
    bg = BackgroundTasks()
    row = None
    try:
        row, err = svc.create(
            db_session,
            tenant_id=tenant.id, user_id=user.id,
            payload=payload, background_tasks=bg,
        )
        assert err is None
        assert row is not None
        assert row.status == "pending"
        assert row.params["background_music_path"] is None
        assert row.params["background_music_volume"] == 0.3
    finally:
        _cleanup(tenant.id, user.id, video_id=(row.id if row else None))
