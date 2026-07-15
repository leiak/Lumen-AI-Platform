"""Tests for Playbook ORM model + ensure_playbooks_table.

Spec: docs-internal/superpowers/specs/M35-playbook-schema.md
"""
import uuid
import pytest
from sqlalchemy import inspect

from lumen_core.database import SessionLocal, ensure_playbooks_table
from lumen_models.playbook import Playbook
from lumen_models.tenant import Tenant


@pytest.fixture
def db_session():
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


def test_playbooks_table_exists():
    ensure_playbooks_table()
    insp = inspect(SessionLocal().bind)
    assert "playbooks" in insp.get_table_names()


def test_create_playbook_minimal(db_session):
    suffix = uuid.uuid4().hex[:8]
    pb = Playbook(
        tenant_id=1,
        name=f"pb_test_{suffix}",
        yaml_content="keywords:\n  - cinematic\n",
        style_tokens={"keywords": ["cinematic"]},
        scope=["image", "tts"],
        is_builtin=False,
    )
    db_session.add(pb); db_session.commit(); db_session.refresh(pb)
    assert pb.id is not None
    assert pb.is_builtin is False
    assert "cinematic" in (pb.style_tokens or {}).get("keywords", [])

    # Cleanup
    db_session.query(Playbook).filter(Playbook.id == pb.id).delete(synchronize_session=False)
    db_session.commit()


def test_unique_tenant_name(db_session):
    """(tenant_id, name) is unique — second insert with same name fails."""
    from sqlalchemy.exc import IntegrityError
    suffix = uuid.uuid4().hex[:8]
    name = f"pb_dup_{suffix}"
    pb1 = Playbook(
        tenant_id=1, name=name, yaml_content="keywords:\n  - x\n",
        is_builtin=False,
    )
    db_session.add(pb1); db_session.commit()

    pb2 = Playbook(
        tenant_id=1, name=name, yaml_content="keywords:\n  - y\n",
        is_builtin=False,
    )
    db_session.add(pb2)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()

    # Cleanup
    db_session.query(Playbook).filter(Playbook.name == name).delete(synchronize_session=False)
    db_session.commit()