"""Tests for ImageGenerationService business logic.

Spec: docs/superpowers/specs/2026-06-11-image-generation-design.md §7
"""
import uuid
from pathlib import Path

import pytest
from fastapi import BackgroundTasks
from sqlalchemy import inspect

from lumen_core.database import (
    SessionLocal,
    ensure_generated_images_table,
)
from lumen_core.security import get_password_hash
from lumen_core import storage
from lumen_models.image_generation import GeneratedImage
from lumen_models.model_config import ModelConfig
from lumen_models.tenant import Tenant
from lumen_models.user import User
from lumen_services.image_generation_service import ImageGenerationService


# ---- fixtures & helpers ---------------------------------------------------

@pytest.fixture
def db_session():
    """Yield a fresh SQLAlchemy session, ensuring tenant id=1 exists.

    Mirrors the pattern from test_image_generation_model.py. Caller is
    responsible for cleaning up rows it inserts.
    """
    ensure_generated_images_table()
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
    t = Tenant(name=f"svc_test_tenant_{suffix}", code=f"svc_test_{suffix}")
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


def _make_user(db, *, tenant_id: int, suffix: str) -> User:
    u = User(
        username=f"svc_test_user_{suffix}",
        email=f"svc_{suffix}@test.local",
        hashed_password=get_password_hash("x"),
        tenant_id=tenant_id,
        is_active=True,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _make_model_config(db, *, tenant_id: int, is_image_generation: bool = True) -> ModelConfig:
    mc = ModelConfig(
        name=f"svc_test_mc_{uuid.uuid4().hex[:6]}",
        model_type="openai",
        model_name="gpt-image-1",
        tenant_id=tenant_id,
        is_active=True,
        is_chat=False,
        is_embedding=False,
        is_image_generation=is_image_generation,
    )
    db.add(mc)
    db.commit()
    db.refresh(mc)
    return mc


@pytest.fixture
def clean_rows():
    """Track (db, tenant_ids) for cleanup after test."""
    tenant_ids: list = []
    mc_ids: list = []
    user_ids: list = []
    yield tenant_ids, mc_ids, user_ids

    db = SessionLocal()
    try:
        if tenant_ids:
            db.query(GeneratedImage).filter(
                GeneratedImage.tenant_id.in_(tenant_ids)
            ).delete(synchronize_session=False)
            db.commit()
        if user_ids:
            db.query(User).filter(User.id.in_(user_ids)).delete(
                synchronize_session=False
            )
            db.commit()
        if mc_ids:
            db.query(ModelConfig).filter(ModelConfig.id.in_(mc_ids)).delete(
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

def test_create_model_not_found(db_session):
    svc = ImageGenerationService()
    bt = BackgroundTasks()
    rows, batch = svc.create(
        db_session,
        tenant_id=1,
        user_id=1,
        model_config_id=99999,
        prompt="x",
        background_tasks=bt,
    )
    assert rows == []
    assert batch is None


def test_create_model_not_image_capable(db_session, clean_rows):
    tenant_ids, mc_ids, user_ids = clean_rows
    suffix = uuid.uuid4().hex[:8]
    tenant = _make_tenant(db_session, suffix)
    tenant_ids.append(tenant.id)
    mc = _make_model_config(db_session, tenant_id=tenant.id, is_image_generation=False)
    mc_ids.append(mc.id)

    svc = ImageGenerationService()
    rows, err = svc.create(
        db_session,
        tenant_id=tenant.id,
        user_id=1,
        model_config_id=mc.id,
        prompt="x",
        background_tasks=BackgroundTasks(),
    )
    assert rows == []
    assert err == "not_image_capable"


def test_create_pending_row_scheduled(db_session, clean_rows):
    tenant_ids, mc_ids, user_ids = clean_rows
    suffix = uuid.uuid4().hex[:8]
    tenant = _make_tenant(db_session, suffix)
    tenant_ids.append(tenant.id)
    user = _make_user(db_session, tenant_id=tenant.id, suffix=suffix)
    user_ids.append(user.id)
    mc = _make_model_config(db_session, tenant_id=tenant.id, is_image_generation=True)
    mc_ids.append(mc.id)

    svc = ImageGenerationService()
    bt = BackgroundTasks()
    rows, batch = svc.create(
        db_session,
        tenant_id=tenant.id,
        user_id=user.id,
        model_config_id=mc.id,
        prompt="hello",
        size="512x512",
        n=1,
        background_tasks=bt,
    )
    assert len(rows) == 1
    assert rows[0].status == "pending"
    assert rows[0].prompt == "hello"
    assert rows[0].size == "512x512"
    assert batch is None  # n=1 → no batch_id
    # background task scheduled
    assert len(bt.tasks) == 1


def test_create_n3_uses_batch_id(db_session, clean_rows):
    tenant_ids, mc_ids, user_ids = clean_rows
    suffix = uuid.uuid4().hex[:8]
    tenant = _make_tenant(db_session, suffix)
    tenant_ids.append(tenant.id)
    user = _make_user(db_session, tenant_id=tenant.id, suffix=suffix)
    user_ids.append(user.id)
    mc = _make_model_config(db_session, tenant_id=tenant.id, is_image_generation=True)
    mc_ids.append(mc.id)

    svc = ImageGenerationService()
    rows, batch = svc.create(
        db_session,
        tenant_id=tenant.id,
        user_id=user.id,
        model_config_id=mc.id,
        prompt="x",
        n=3,
        background_tasks=BackgroundTasks(),
    )
    assert len(rows) == 3
    assert batch is not None
    for r in rows:
        assert r.batch_id == batch


def test_list_tenant_isolation(db_session, clean_rows):
    tenant_ids, mc_ids, user_ids = clean_rows
    suffix = uuid.uuid4().hex[:8]
    t1 = _make_tenant(db_session, f"t1_{suffix}")
    t2 = _make_tenant(db_session, f"t2_{suffix}")
    tenant_ids.extend([t1.id, t2.id])
    u1 = _make_user(db_session, tenant_id=t1.id, suffix=f"u1_{suffix}")
    u2 = _make_user(db_session, tenant_id=t2.id, suffix=f"u2_{suffix}")
    user_ids.extend([u1.id, u2.id])
    mc1 = _make_model_config(db_session, tenant_id=t1.id, is_image_generation=True)
    mc2 = _make_model_config(db_session, tenant_id=t2.id, is_image_generation=True)
    mc_ids.extend([mc1.id, mc2.id])

    svc = ImageGenerationService()
    for _ in range(2):
        svc.create(
            db_session,
            tenant_id=t1.id,
            user_id=u1.id,
            model_config_id=mc1.id,
            prompt="x",
            background_tasks=BackgroundTasks(),
        )
    rows, total = svc.list_for_tenant(db_session, tenant_id=t1.id, page=1, page_size=10)
    assert total == 2
    assert all(r.tenant_id == t1.id for r in rows)

    rows_t2, total_t2 = svc.list_for_tenant(db_session, tenant_id=t2.id, page=1, page_size=10)
    assert total_t2 == 0
    assert rows_t2 == []


def test_delete_removes_file_and_row(db_session, clean_rows, tmp_path, monkeypatch):
    """Create a real file on disk via save_bytes, then delete the row and
    confirm the file is also gone."""
    # Redirect STORAGE_DIR — storage.save_bytes / delete_relative use
    # settings.STORAGE_DIR (a property pointing at DEFAULT_STORAGE_DIR).
    monkeypatch.setattr(storage, "settings", type("S", (), {"STORAGE_DIR": tmp_path})())

    tenant_ids, mc_ids, user_ids = clean_rows
    suffix = uuid.uuid4().hex[:8]
    tenant = _make_tenant(db_session, suffix)
    tenant_ids.append(tenant.id)
    user = _make_user(db_session, tenant_id=tenant.id, suffix=suffix)
    user_ids.append(user.id)
    mc = _make_model_config(db_session, tenant_id=tenant.id, is_image_generation=True)
    mc_ids.append(mc.id)

    svc = ImageGenerationService()
    rows, _ = svc.create(
        db_session,
        tenant_id=tenant.id,
        user_id=user.id,
        model_config_id=mc.id,
        prompt="x",
        background_tasks=BackgroundTasks(),
    )
    img_id = rows[0].id

    # Now save a real file on disk and patch the row's file_path to it.
    abs_p, sz, rel = storage.save_bytes(tenant.id, b"x" * 10, "image/png")
    rows[0].file_path = rel
    db_session.commit()
    assert Path(abs_p).exists()
    assert rel in str(abs_p) or Path(abs_p).as_posix().endswith(rel)

    ok = svc.delete(db_session, tenant_id=tenant.id, image_id=img_id)
    assert ok is True
    assert not Path(abs_p).exists()
    assert svc.get(db_session, tenant_id=tenant.id, image_id=img_id) is None


def test_regenerate_creates_new_row(db_session, clean_rows):
    tenant_ids, mc_ids, user_ids = clean_rows
    suffix = uuid.uuid4().hex[:8]
    tenant = _make_tenant(db_session, suffix)
    tenant_ids.append(tenant.id)
    user = _make_user(db_session, tenant_id=tenant.id, suffix=suffix)
    user_ids.append(user.id)
    mc = _make_model_config(db_session, tenant_id=tenant.id, is_image_generation=True)
    mc_ids.append(mc.id)

    svc = ImageGenerationService()
    rows, _ = svc.create(
        db_session,
        tenant_id=tenant.id,
        user_id=user.id,
        model_config_id=mc.id,
        prompt="orig",
        background_tasks=BackgroundTasks(),
    )
    new_rows = svc.regenerate(
        db_session,
        tenant_id=tenant.id,
        user_id=user.id,
        image_id=rows[0].id,
        background_tasks=BackgroundTasks(),
    )
    assert new_rows is not None
    assert len(new_rows) == 1
    assert new_rows[0].id != rows[0].id
    assert new_rows[0].prompt == "orig"
    # old row unchanged
    assert svc.get(db_session, tenant_id=tenant.id, image_id=rows[0].id) is not None
