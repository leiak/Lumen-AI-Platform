"""M36: Tests for GeneratedVideo ORM model + ensure_* migration."""
import uuid
from sqlalchemy import inspect

# M36 video FK resolution: pre-import every model that GeneratedVideo
# FKs into. Without this, Base.metadata is missing the target tables
# (NoReferencedTableError — MEMORY 2026-06-26).
import lumen_models.chat  # noqa: F401  (generated_videos.conversation_id)
import lumen_models.model_config  # noqa: F401
import lumen_models.playbook  # noqa: F401
import lumen_models.tts  # noqa: F401
import lumen_models.subtitle  # noqa: F401
import lumen_models.video  # noqa: F401

import pytest

from lumen_core.database import (
    engine, ensure_generated_videos_table, SessionLocal,
)
from lumen_core.security import get_password_hash
from lumen_models.video import GeneratedVideo
from lumen_models.tenant import Tenant
from lumen_models.user import User


@pytest.fixture
def db_session():
    ensure_generated_videos_table()
    db = SessionLocal()
    try:
        tenant = db.query(Tenant).filter(Tenant.id == 1).first()
        if not tenant:
            tenant = Tenant(id=1, name="Default Tenant", code="default")
            db.add(tenant); db.commit(); db.refresh(tenant)
        yield db
    finally:
        db.close()


def _make_tenant_user(db, suffix):
    t = Tenant(name=f"vid_test_t_{suffix}", code=f"vid_test_{suffix}")
    db.add(t); db.commit(); db.refresh(t)
    u = User(
        username=f"vid_test_u_{suffix}",
        email=f"vid_{suffix}@test.local",
        hashed_password=get_password_hash("x"),
        tenant_id=t.id, is_active=True,
    )
    db.add(u); db.commit(); db.refresh(u)
    return t, u


def test_table_exists_after_ensure():
    ensure_generated_videos_table()
    insp = inspect(engine)
    assert insp.has_table("generated_videos")


def test_ensure_is_idempotent():
    """Calling ensure_generated_videos_table() twice must not raise."""
    ensure_generated_videos_table()
    ensure_generated_videos_table()


def test_create_generated_video_row_persists_core_fields(db_session):
    ensure_generated_videos_table()
    suffix = uuid.uuid4().hex[:8]
    tenant, user = _make_tenant_user(db_session, suffix)
    row = GeneratedVideo(
        tenant_id=tenant.id,
        user_id=user.id,
        source_images=["/tmp/a.png", "/tmp/b.png"],
        resolution="1280x720",
        fps=24,
        params={"audio_fade_in": 0.5},
        file_path=f"generated_videos/{tenant.id}/2026-07-15/{suffix}.mp4",
        file_size=12345,
        mime_type="video/mp4",
    )
    db_session.add(row); db_session.commit(); db_session.refresh(row)
    try:
        assert row.id is not None
        assert row.status == "pending"
        assert row.created_at is not None
        assert row.source_images == ["/tmp/a.png", "/tmp/b.png"]
        assert row.params == {"audio_fade_in": 0.5}
        assert row.fps == 24
        assert row.resolution == "1280x720"
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


def test_composite_index_present(db_session):
    """Spec §3: composite index ix_gen_videos_tenant_status_created exists.

    The composite index is what powers the GET /videos/?status=... pagination
    query — if it's missing, the executor does a full scan per tenant.
    """
    ensure_generated_videos_table()
    insp = inspect(engine)
    idx = insp.get_indexes("generated_videos")
    names = {i["name"] for i in idx}
    assert "ix_gen_videos_tenant_status_created" in names
    target = next(i for i in idx if i["name"] == "ix_gen_videos_tenant_status_created")
    assert target["column_names"] == ["tenant_id", "status", "created_at"]
