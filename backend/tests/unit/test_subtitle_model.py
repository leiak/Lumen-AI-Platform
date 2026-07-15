"""Tests for Subtitle ORM model + ensure_subtitles_table.

Spec: docs-internal/superpowers/specs/M35-overview.md §5
"""
import uuid
import pytest
from sqlalchemy import inspect

from lumen_core.database import SessionLocal, ensure_subtitles_table
from lumen_core.security import get_password_hash
from lumen_models.subtitle import Subtitle
from lumen_models.tenant import Tenant
from lumen_models.user import User


@pytest.fixture
def db_session():
    """Bootstrap the M35 FK chain in Base.metadata."""
    from lumen_core.database import Base, engine
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


def test_subtitles_table_exists():
    ensure_subtitles_table()
    insp = inspect(SessionLocal().bind)
    assert "subtitles" in insp.get_table_names()


def test_create_subtitle_minimal(db_session):
    suffix = uuid.uuid4().hex[:8]
    tenant = Tenant(name=f"sub_mdl_t_{suffix}", code=f"sub_mdl_t_{suffix}")
    db_session.add(tenant); db_session.commit(); db_session.refresh(tenant)
    user = User(
        username=f"sub_mdl_u_{suffix}",
        email=f"sub_mdl_{suffix}@test.local",
        hashed_password=get_password_hash("x"),
        tenant_id=tenant.id, is_active=True,
    )
    db_session.add(user); db_session.commit(); db_session.refresh(user)

    sub = Subtitle(
        tenant_id=tenant.id, user_id=user.id,
        source_type="script", language="zh-CN", format="srt",
        content="1\r\n00:00:00,000 --> 00:00:01,000\r\nhi\r\n",
        cue_count=1, duration_ms=1000, char_count=2,
    )
    db_session.add(sub); db_session.commit(); db_session.refresh(sub)
    assert sub.id is not None
    assert sub.cue_count == 1
    assert sub.language == "zh-CN"

    # Cleanup
    db_session.query(Subtitle).filter(Subtitle.id == sub.id).delete(synchronize_session=False)
    db_session.query(User).filter(User.id == user.id).delete(synchronize_session=False)
    db_session.query(Tenant).filter(Tenant.id == tenant.id).delete(synchronize_session=False)
    db_session.commit()