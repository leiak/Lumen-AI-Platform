"""M36 T3: Tests for VideoComposeService business logic.

Spec: docs-internal/superpowers/specs/m36-multimodal-foundation.md §4
"""
import uuid
from pathlib import Path
from unittest.mock import MagicMock

# M36 video FK resolution: pre-import every model that GeneratedVideo
# FKs into. Without this, Base.metadata is missing the target tables
# when create_all() runs (NoReferencedTableError, see MEMORY 2026-06-26).
import lumen_models.chat  # noqa: F401  (generated_videos.conversation_id)
import lumen_models.model_config  # noqa: F401
import lumen_models.playbook  # noqa: F401
import lumen_models.tts  # noqa: F401  (generated_videos.source_audio_id)
import lumen_models.subtitle  # noqa: F401  (generated_videos.source_subtitle_id)
import lumen_models.video  # noqa: F401  (this module)

import pytest
from fastapi import BackgroundTasks

from lumen_core.database import SessionLocal, ensure_generated_videos_table
from lumen_core.security import get_password_hash
from lumen_core.config import settings
from lumen_schemas.video import VideoComposeCreate
from lumen_services.video_compose_service import (
    AssetNotFound,
    VideoComposeService,
    _resolve_asset_to_path,
)
from lumen_models.video import GeneratedVideo
from lumen_models.tenant import Tenant
from lumen_models.user import User


@pytest.fixture
def db_session():
    ensure_generated_videos_table()
    db = SessionLocal()
    try:
        if not db.query(Tenant).filter(Tenant.id == 1).first():
            t = Tenant(id=1, name="Default Tenant", code="default")
            db.add(t); db.commit(); db.refresh(t)
        yield db
    finally:
        db.close()


def _make_tenant_user(db, suffix):
    t = Tenant(name=f"vcs_t_{suffix}", code=f"vcs_{suffix}")
    db.add(t); db.commit(); db.refresh(t)
    u = User(
        username=f"vcs_u_{suffix}",
        email=f"vcs_{suffix}@test.local",
        hashed_password=get_password_hash("x"),
        tenant_id=t.id, is_active=True,
    )
    db.add(u); db.commit(); db.refresh(u)
    return t, u


@pytest.fixture
def clean_rows():
    rows = []
    yield rows
    if not rows:
        return
    db = SessionLocal()
    try:
        db.query(GeneratedVideo).filter(GeneratedVideo.id.in_(rows)).delete(
            synchronize_session=False,
        )
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()


def test_create_empty_sources_returns_empty_sources_err(db_session):
    svc = VideoComposeService()
    payload = VideoComposeCreate(source_images=[])
    bg = BackgroundTasks()
    row, err = svc.create(
        db_session, tenant_id=1, user_id=1, payload=payload, background_tasks=bg,
    )
    assert row is None
    assert err == "empty_sources"


def test_create_writes_pending_row_and_schedules_bg_task(db_session, clean_rows):
    """create() persists the row in pending and adds a _run_composition task."""
    suffix = uuid.uuid4().hex[:8]
    tenant, user = _make_tenant_user(db_session, suffix)
    try:
        svc = VideoComposeService()
        payload = VideoComposeCreate(source_images=["/tmp/a.png"])
        bg = BackgroundTasks()
        row, err = svc.create(
            db_session,
            tenant_id=tenant.id, user_id=user.id,
            payload=payload, background_tasks=bg,
        )
        assert err is None
        assert row is not None
        assert row.status == "pending"
        assert row.source_images == ["/tmp/a.png"]
        # Background task is queued.
        assert len(bg.tasks) == 1
        clean_rows.append(row.id)
    finally:
        try:
            db_session.delete(user); db_session.commit()
        except Exception:
            db_session.rollback()
        try:
            db_session.delete(tenant); db_session.commit()
        except Exception:
            db_session.rollback()


def test_create_sync_for_workflow_returns_compose_inline_error_on_empty(db_session):
    """sync variant mirrors the empty_sources error tag."""
    svc = VideoComposeService()
    payload = VideoComposeCreate(source_images=[])
    row, err = svc.create_sync_for_workflow(
        db_session, tenant_id=1, user_id=1, payload=payload,
    )
    assert row is None
    assert err == "empty_sources"


def test_resolve_asset_to_path_returns_none_for_blank_string(db_session):
    """None / "" / "  " → returns None (caller treats as no asset)."""
    assert _resolve_asset_to_path(db_session, tenant_id=1, kind="audio", value=None) is None
    assert _resolve_asset_to_path(db_session, tenant_id=1, kind="audio", value="") is None
    assert _resolve_asset_to_path(db_session, tenant_id=1, kind="audio", value="  ") is None


def test_resolve_asset_to_path_passes_through_literal_path(db_session):
    """Non-numeric strings are returned as-is (treated as local paths)."""
    p = "/tmp/audio_that_does_not_exist.mp3"
    out = _resolve_asset_to_path(db_session, tenant_id=1, kind="audio", value=p)
    assert out == p


def test_resolve_asset_to_path_audio_id_not_found_raises(db_session):
    """Numeric audio id with no row → AssetNotFound('audio_not_found')."""
    with pytest.raises(AssetNotFound) as info:
        _resolve_asset_to_path(
            db_session, tenant_id=1, kind="audio", value="999999",
        )
    assert info.value.tag == "audio_not_found"


def test_resolve_asset_to_path_subtitle_id_writes_tmp_srt(db_session, clean_rows):
    """Numeric subtitle id → writes SRT body to storage/_tmp/subtitles/ and returns path."""
    from lumen_models.subtitle import Subtitle
    suffix = uuid.uuid4().hex[:8]
    tenant, user = _make_tenant_user(db_session, suffix)
    sub = Subtitle(
        tenant_id=tenant.id, user_id=user.id,
        source_type="script", language="zh-CN", format="srt",
        content="1\n00:00:00,000 --> 00:00:01,000\nhello\n\n",
        cue_count=1, duration_ms=1000,
    )
    db_session.add(sub); db_session.commit(); db_session.refresh(sub)
    try:
        out_path = _resolve_asset_to_path(
            db_session, tenant_id=tenant.id, kind="subtitle", value=str(sub.id),
        )
        assert out_path is not None
        p = Path(out_path)
        assert p.exists()
        # File body matches the row's content.
        assert p.read_text(encoding="utf-8") == sub.content
        assert p.suffix == ".srt"
    finally:
        try:
            db_session.delete(sub); db_session.commit()
        except Exception:
            db_session.rollback()
        try:
            db_session.delete(user); db_session.commit()
        except Exception:
            db_session.rollback()
        try:
            db_session.delete(tenant); db_session.commit()
        except Exception:
            db_session.rollback()


def test_cancel_returns_false_for_completed_row(db_session, clean_rows):
    """cancel() refuses to flip rows in terminal status."""
    suffix = uuid.uuid4().hex[:8]
    tenant, user = _make_tenant_user(db_session, suffix)
    row = GeneratedVideo(
        tenant_id=tenant.id, user_id=user.id,
        source_images=["/tmp/a.png"], resolution="1280x720", fps=24,
        file_path="x.mp4", file_size=1, mime_type="video/mp4",
        status="completed",
    )
    db_session.add(row); db_session.commit(); db_session.refresh(row)
    clean_rows.append(row.id)
    try:
        svc = VideoComposeService()
        ok = svc.cancel(
            db_session, tenant_id=tenant.id, user_id=user.id, video_id=row.id,
        )
        assert ok is False
        # Row status did not change.
        db_session.refresh(row)
        assert row.status == "completed"
    finally:
        try:
            db_session.delete(row); db_session.commit()
        except Exception:
            db_session.rollback()
        try:
            db_session.delete(user); db_session.commit()
        except Exception:
            db_session.rollback()
        try:
            db_session.delete(tenant); db_session.commit()
        except Exception:
            db_session.rollback()


def test_cancel_flips_pending_row_to_cancelled(db_session, clean_rows):
    suffix = uuid.uuid4().hex[:8]
    tenant, user = _make_tenant_user(db_session, suffix)
    row = GeneratedVideo(
        tenant_id=tenant.id, user_id=user.id,
        source_images=["/tmp/a.png"], resolution="1280x720", fps=24,
        file_path="x.mp4", file_size=1, mime_type="video/mp4",
        status="pending",
    )
    db_session.add(row); db_session.commit(); db_session.refresh(row)
    clean_rows.append(row.id)
    try:
        svc = VideoComposeService()
        ok = svc.cancel(
            db_session, tenant_id=tenant.id, user_id=user.id, video_id=row.id,
        )
        assert ok is True
        db_session.refresh(row)
        assert row.status == "cancelled"
        assert row.finished_at is not None
    finally:
        try:
            db_session.delete(row); db_session.commit()
        except Exception:
            db_session.rollback()
        try:
            db_session.delete(user); db_session.commit()
        except Exception:
            db_session.rollback()
        try:
            db_session.delete(tenant); db_session.commit()
        except Exception:
            db_session.rollback()
