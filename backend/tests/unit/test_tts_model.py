"""Tests for GeneratedAudio ORM model + ensure_generated_audios_table.

Spec: docs-internal/superpowers/specs/M35-overview.md §4
"""
import uuid
import pytest
from sqlalchemy import inspect

from lumen_core.database import SessionLocal, ensure_generated_audios_table
from lumen_core.security import get_password_hash
from lumen_models.tts import GeneratedAudio
from lumen_models.tenant import Tenant
from lumen_models.user import User
from lumen_models.model_config import ModelConfig


@pytest.fixture
def db_session():
    """Yield a fresh SessionLocal, ensuring tables exist.

    Loads the full M35 model chain into ``Base.metadata`` so FK
    validation passes; ``create_all`` is idempotent in MySQL. Also
    runs the column migrations so ``is_tts`` / ``is_subtitle_generation``
    exist on ``model_configs`` (lumen_main runs these on startup).
    """
    from lumen_core.database import (
        Base, engine,
        ensure_model_configs_tts_subtitle_flags,
    )
    ensure_model_configs_tts_subtitle_flags()
    from lumen_models.chat import Conversation
    from lumen_models.model_config import ModelConfig
    from lumen_models.tts import GeneratedAudio
    from lumen_models.subtitle import Subtitle
    from lumen_models.playbook import Playbook
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        tenant = db.query(Tenant).filter(Tenant.id == 1).first()
        if not tenant:
            tenant = Tenant(id=1, name="Default Tenant", code="default")
            db.add(tenant); db.commit(); db.refresh(tenant)
        yield db
    finally:
        db.close()


def _make_tenant(db, suffix: str) -> Tenant:
    t = Tenant(name=f"tts_model_t_{suffix}", code=f"tts_model_t_{suffix}")
    db.add(t); db.commit(); db.refresh(t)
    return t


def _make_user(db, *, tenant_id: int, suffix: str) -> User:
    u = User(
        username=f"tts_model_u_{suffix}",
        email=f"tts_model_{suffix}@test.local",
        hashed_password=get_password_hash("x"),
        tenant_id=tenant_id, is_active=True,
    )
    db.add(u); db.commit(); db.refresh(u)
    return u


def _make_model_config(db, *, tenant_id: int, is_tts: bool = True) -> ModelConfig:
    mc = ModelConfig(
        name=f"tts_model_mc_{uuid.uuid4().hex[:6]}",
        model_type="edge",
        model_name="edge-tts",
        tenant_id=tenant_id,
        is_active=True,
        is_chat=False,
        is_embedding=False,
        is_image_generation=False,
        is_tts=is_tts,
    )
    db.add(mc); db.commit(); db.refresh(mc)
    return mc


def test_tts_table_exists():
    """ensure_generated_audios_table() creates the table."""
    ensure_generated_audios_table()
    insp = inspect(SessionLocal().bind)
    assert "generated_audios" in insp.get_table_names()


def test_create_audio_row_minimal(db_session):
    """Insert a minimal GeneratedAudio row."""
    suffix = uuid.uuid4().hex[:8]
    tenant = _make_tenant(db_session, suffix)
    user = _make_user(db_session, tenant_id=tenant.id, suffix=suffix)
    mc = _make_model_config(db_session, tenant_id=tenant.id)

    audio = GeneratedAudio(
        tenant_id=tenant.id,
        user_id=user.id,
        model_config_id=mc.id,
        text="hello",
        voice="default",
        speed="1.0",
        format="mp3",
        char_count=5,
        status="pending",
        mime_type="audio/mpeg",
    )
    db_session.add(audio)
    db_session.commit()
    db_session.refresh(audio)

    assert audio.id is not None
    assert audio.status == "pending"
    assert audio.text == "hello"
    assert audio.mime_type == "audio/mpeg"

    # Cleanup
    db_session.query(GeneratedAudio).filter(GeneratedAudio.id == audio.id).delete(synchronize_session=False)
    db_session.query(ModelConfig).filter(ModelConfig.id == mc.id).delete(synchronize_session=False)
    db_session.query(User).filter(User.id == user.id).delete(synchronize_session=False)
    db_session.query(Tenant).filter(Tenant.id == tenant.id).delete(synchronize_session=False)
    db_session.commit()


def test_audio_status_default_pending(db_session):
    """Status defaults to pending on insert."""
    suffix = uuid.uuid4().hex[:8]
    tenant = _make_tenant(db_session, suffix)
    user = _make_user(db_session, tenant_id=tenant.id, suffix=suffix)
    mc = _make_model_config(db_session, tenant_id=tenant.id)

    audio = GeneratedAudio(
        tenant_id=tenant.id, user_id=user.id, model_config_id=mc.id,
        text="x", char_count=1, mime_type="audio/mpeg",
    )
    db_session.add(audio); db_session.commit(); db_session.refresh(audio)
    assert audio.status == "pending"

    # Cleanup
    db_session.query(GeneratedAudio).filter(GeneratedAudio.id == audio.id).delete(synchronize_session=False)
    db_session.query(ModelConfig).filter(ModelConfig.id == mc.id).delete(synchronize_session=False)
    db_session.query(User).filter(User.id == user.id).delete(synchronize_session=False)
    db_session.query(Tenant).filter(Tenant.id == tenant.id).delete(synchronize_session=False)
    db_session.commit()