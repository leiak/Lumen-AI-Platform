"""Tests for TTSService business logic.

Spec: docs-internal/superpowers/specs/M35-overview.md §4

Mirrors test_image_generation_service.py: fresh `db_session` fixture +
fixture-based `clean_rows` for teardown (M29 lesson — InnoDB
REPEATABLE READ isolation, must open NEW SessionLocal in teardown).
"""
import uuid

import pytest
from fastapi import BackgroundTasks

from lumen_core.database import (
    SessionLocal,
    ensure_generated_audios_table,
    ensure_playbooks_table,
)
from lumen_core.security import get_password_hash
from lumen_models.tts import GeneratedAudio
from lumen_models.playbook import Playbook
from lumen_models.model_config import ModelConfig
from lumen_models.tenant import Tenant
from lumen_models.user import User
from lumen_services.tts_service import TTSService


# ---- fixtures -------------------------------------------------------------

@pytest.fixture
def db_session():
    """Bootstrap all M35 tables; ``Base.metadata.create_all`` resolves
    the full FK graph. Also runs the column migrations so
    ``is_tts`` / ``is_subtitle_generation`` exist on ``model_configs``
    (lumen_main runs these on startup).
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
    t = Tenant(name=f"tts_svc_t_{suffix}", code=f"tts_svc_t_{suffix}")
    db.add(t); db.commit(); db.refresh(t)
    return t


def _make_user(db, *, tenant_id: int, suffix: str) -> User:
    u = User(
        username=f"tts_svc_u_{suffix}",
        email=f"tts_svc_{suffix}@test.local",
        hashed_password=get_password_hash("x"),
        tenant_id=tenant_id, is_active=True,
    )
    db.add(u); db.commit(); db.refresh(u)
    return u


def _make_tts_model_config(db, *, tenant_id: int, is_tts: bool = True) -> ModelConfig:
    mc = ModelConfig(
        name=f"tts_svc_mc_{uuid.uuid4().hex[:6]}",
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


def _make_playbook(db, *, tenant_id: int = 1, name: str, yaml_content: str) -> Playbook:
    pb = Playbook(
        tenant_id=tenant_id, name=name, yaml_content=yaml_content,
        style_tokens={"keywords": ["cinematic"], "voice_tone": "warm"},
        scope=["image", "tts"], is_builtin=False,
    )
    db.add(pb); db.commit(); db.refresh(pb)
    return pb


@pytest.fixture
def clean_rows():
    """M29-pattern cleanup: open NEW SessionLocal in teardown so the
    committed rows from the test session are visible."""
    tenant_ids: list = []
    mc_ids: list = []
    user_ids: list = []
    pb_ids: list = []
    audio_ids: list = []
    yield tenant_ids, mc_ids, user_ids, pb_ids, audio_ids

    db = SessionLocal()
    try:
        if audio_ids:
            db.query(GeneratedAudio).filter(
                GeneratedAudio.id.in_(audio_ids)
            ).delete(synchronize_session=False)
            db.commit()
        if pb_ids:
            db.query(Playbook).filter(Playbook.id.in_(pb_ids)).delete(
                synchronize_session=False
            )
            db.commit()
        if mc_ids:
            db.query(ModelConfig).filter(ModelConfig.id.in_(mc_ids)).delete(
                synchronize_session=False
            )
            db.commit()
        if user_ids:
            db.query(User).filter(User.id.in_(user_ids)).delete(
                synchronize_session=False
            )
            db.commit()
        if tenant_ids:
            db.query(Tenant).filter(Tenant.id.in_(tenant_ids)).delete(
                synchronize_session=False
            )
            db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()


# ---- tests ----------------------------------------------------------------

def test_create_empty_text_rejected(db_session):
    svc = TTSService()
    row, err = svc.create(
        db_session, tenant_id=1, user_id=1, model_config_id=1,
        text="   ", background_tasks=BackgroundTasks(),
    )
    assert row is None
    assert err == "empty_text"


def test_create_too_long_text_rejected(db_session):
    svc = TTSService()
    row, err = svc.create(
        db_session, tenant_id=1, user_id=1, model_config_id=1,
        text="x" * 10001, background_tasks=BackgroundTasks(),
    )
    assert row is None
    assert err == "text_too_long"


def test_create_model_not_found(db_session):
    svc = TTSService()
    row, err = svc.create(
        db_session, tenant_id=1, user_id=1,
        model_config_id=99999, text="hello",
        background_tasks=BackgroundTasks(),
    )
    assert row is None
    assert err == "not_found"


def test_create_model_not_tts_capable(db_session, clean_rows):
    tenant_ids, mc_ids, user_ids, pb_ids, audio_ids = clean_rows
    suffix = uuid.uuid4().hex[:8]
    tenant = _make_tenant(db_session, suffix); tenant_ids.append(tenant.id)
    user = _make_user(db_session, tenant_id=tenant.id, suffix=suffix)
    user_ids.append(user.id)
    mc = _make_tts_model_config(db_session, tenant_id=tenant.id, is_tts=False)
    mc_ids.append(mc.id)

    svc = TTSService()
    row, err = svc.create(
        db_session, tenant_id=tenant.id, user_id=user.id,
        model_config_id=mc.id, text="hello",
        background_tasks=BackgroundTasks(),
    )
    assert row is None
    assert err == "not_tts_capable"


def test_create_pending_row_scheduled(db_session, clean_rows):
    tenant_ids, mc_ids, user_ids, pb_ids, audio_ids = clean_rows
    suffix = uuid.uuid4().hex[:8]
    tenant = _make_tenant(db_session, suffix); tenant_ids.append(tenant.id)
    user = _make_user(db_session, tenant_id=tenant.id, suffix=suffix)
    user_ids.append(user.id)
    mc = _make_tts_model_config(db_session, tenant_id=tenant.id)
    mc_ids.append(mc.id)

    svc = TTSService()
    bt = BackgroundTasks()
    row, err = svc.create(
        db_session, tenant_id=tenant.id, user_id=user.id,
        model_config_id=mc.id, text="hello world", voice="zh-CN-XiaoxiaoNeural",
        speed=1.0, format="mp3", background_tasks=bt,
    )
    assert err is None
    assert row is not None
    assert row.status == "pending"
    assert row.text == "hello world"
    assert row.voice == "zh-CN-XiaoxiaoNeural"
    assert row.char_count == 11
    assert row.mime_type == "audio/mpeg"
    audio_ids.append(row.id)
    assert len(bt.tasks) == 1


def test_create_with_valid_playbook(db_session, clean_rows):
    """Valid playbook_id enriches log but does not reject."""
    tenant_ids, mc_ids, user_ids, pb_ids, audio_ids = clean_rows
    suffix = uuid.uuid4().hex[:8]
    tenant = _make_tenant(db_session, suffix); tenant_ids.append(tenant.id)
    user = _make_user(db_session, tenant_id=tenant.id, suffix=suffix)
    user_ids.append(user.id)
    mc = _make_tts_model_config(db_session, tenant_id=tenant.id)
    mc_ids.append(mc.id)
    pb = _make_playbook(
        db_session, tenant_id=tenant.id, name=f"pb_{suffix}",
        yaml_content="keywords:\n  - warm\n",
    )
    pb_ids.append(pb.id)

    svc = TTSService()
    row, err = svc.create(
        db_session, tenant_id=tenant.id, user_id=user.id,
        model_config_id=mc.id, text="x",
        playbook_id=pb.id, background_tasks=BackgroundTasks(),
    )
    assert err is None
    assert row is not None
    assert row.playbook_id == pb.id
    audio_ids.append(row.id)


def test_create_playbook_not_found_rejected(db_session, clean_rows):
    tenant_ids, mc_ids, user_ids, pb_ids, audio_ids = clean_rows
    suffix = uuid.uuid4().hex[:8]
    tenant = _make_tenant(db_session, suffix); tenant_ids.append(tenant.id)
    user = _make_user(db_session, tenant_id=tenant.id, suffix=suffix)
    user_ids.append(user.id)
    mc = _make_tts_model_config(db_session, tenant_id=tenant.id)
    mc_ids.append(mc.id)

    svc = TTSService()
    row, err = svc.create(
        db_session, tenant_id=tenant.id, user_id=user.id,
        model_config_id=mc.id, text="x",
        playbook_id=99999, background_tasks=BackgroundTasks(),
    )
    assert row is None
    assert err == "playbook_not_found"


def test_list_tenant_isolation(db_session, clean_rows):
    tenant_ids, mc_ids, user_ids, pb_ids, audio_ids = clean_rows
    suffix = uuid.uuid4().hex[:8]
    t1 = _make_tenant(db_session, f"iso1_{suffix}"); tenant_ids.append(t1.id)
    t2 = _make_tenant(db_session, f"iso2_{suffix}"); tenant_ids.append(t2.id)
    u1 = _make_user(db_session, tenant_id=t1.id, suffix=f"u1_{suffix}")
    user_ids.append(u1.id)
    u2 = _make_user(db_session, tenant_id=t2.id, suffix=f"u2_{suffix}")
    user_ids.append(u2.id)
    mc1 = _make_tts_model_config(db_session, tenant_id=t1.id); mc_ids.append(mc1.id)
    mc2 = _make_tts_model_config(db_session, tenant_id=t2.id); mc_ids.append(mc2.id)

    svc = TTSService()
    r1, _ = svc.create(
        db_session, tenant_id=t1.id, user_id=u1.id,
        model_config_id=mc1.id, text="t1 a",
        background_tasks=BackgroundTasks(),
    )
    r2, _ = svc.create(
        db_session, tenant_id=t1.id, user_id=u1.id,
        model_config_id=mc1.id, text="t1 b",
        background_tasks=BackgroundTasks(),
    )
    audio_ids.extend([r1.id, r2.id])

    rows_t1, total_t1 = svc.list_for_tenant(db_session, tenant_id=t1.id, page=1, page_size=10)
    rows_t2, total_t2 = svc.list_for_tenant(db_session, tenant_id=t2.id, page=1, page_size=10)
    assert total_t1 == 2
    assert all(r.tenant_id == t1.id for r in rows_t1)
    assert total_t2 == 0
    assert rows_t2 == []


def test_get_cross_tenant_returns_none(db_session, clean_rows):
    """get() enforces tenant_id in WHERE clause."""
    tenant_ids, mc_ids, user_ids, pb_ids, audio_ids = clean_rows
    suffix = uuid.uuid4().hex[:8]
    t1 = _make_tenant(db_session, f"x1_{suffix}"); tenant_ids.append(t1.id)
    t2 = _make_tenant(db_session, f"x2_{suffix}"); tenant_ids.append(t2.id)
    u1 = _make_user(db_session, tenant_id=t1.id, suffix=f"u1_{suffix}")
    user_ids.append(u1.id)
    mc1 = _make_tts_model_config(db_session, tenant_id=t1.id); mc_ids.append(mc1.id)

    svc = TTSService()
    row, _ = svc.create(
        db_session, tenant_id=t1.id, user_id=u1.id,
        model_config_id=mc1.id, text="x",
        background_tasks=BackgroundTasks(),
    )
    audio_ids.append(row.id)
    assert svc.get(db_session, tenant_id=t1.id, audio_id=row.id) is not None
    # Same id, different tenant → not found
    assert svc.get(db_session, tenant_id=t2.id, audio_id=row.id) is None


def test_cancel_pending_row(db_session, clean_rows):
    """Cancel marks a pending row as cancelled."""
    tenant_ids, mc_ids, user_ids, pb_ids, audio_ids = clean_rows
    suffix = uuid.uuid4().hex[:8]
    tenant = _make_tenant(db_session, suffix); tenant_ids.append(tenant.id)
    user = _make_user(db_session, tenant_id=tenant.id, suffix=suffix)
    user_ids.append(user.id)
    mc = _make_tts_model_config(db_session, tenant_id=tenant.id)
    mc_ids.append(mc.id)

    svc = TTSService()
    row, _ = svc.create(
        db_session, tenant_id=tenant.id, user_id=user.id,
        model_config_id=mc.id, text="x",
        background_tasks=BackgroundTasks(),
    )
    audio_ids.append(row.id)
    cancelled = svc.cancel(db_session, tenant_id=tenant.id, audio_id=row.id)
    assert cancelled is not None
    assert cancelled.status == "cancelled"
    assert cancelled.finished_at is not None