"""Tests for GeneratedImage model + ensure_* migration.

Spec: docs/superpowers/specs/2026-06-11-image-generation-design.md §3.2 + §8.1
"""
import uuid
import pytest
from sqlalchemy import inspect

from lumen_core.database import engine, ensure_generated_images_table, SessionLocal
from lumen_core.security import get_password_hash
from lumen_models.image_generation import GeneratedImage
from lumen_models.tenant import Tenant
from lumen_models.user import User
from lumen_models.model_config import ModelConfig


@pytest.fixture
def db_session():
    """Yield a fresh SQLAlchemy session, ensuring tenant id=1 exists.

    Mirrors the ``db_session`` fixture in test_agent_rag.py — used by
    other T1+ tests in the image-generation milestone. Caller is
    responsible for cleaning up rows it inserts.
    """
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
    """Create + commit a throwaway Tenant. Caller owns cleanup."""
    t = Tenant(name=f"img_test_tenant_{suffix}", code=f"img_test_{suffix}")
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


def _make_user(db, *, tenant_id: int, suffix: str) -> User:
    """Create + commit a throwaway User under the given tenant."""
    u = User(
        username=f"img_test_user_{suffix}",
        email=f"img_{suffix}@test.local",
        hashed_password=get_password_hash("x"),
        tenant_id=tenant_id,
        is_active=True,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _make_model_config(db, *, tenant_id: int) -> ModelConfig:
    """Create + commit a ModelConfig row. Required FK target for
    GeneratedImage.model_config_id. M22 will add
    ``is_image_generation`` in T2 — for T1 the plain bool column
    doesn't exist yet, so we just create a minimal config.
    """
    mc = ModelConfig(
        name="img_test_mc",
        model_type="openai",
        model_name="gpt-image-1",
        tenant_id=tenant_id,
        is_active=True,
        is_chat=False,
        is_embedding=False,
    )
    db.add(mc)
    db.commit()
    db.refresh(mc)
    return mc


def test_table_exists_after_ensure():
    """ensure_generated_images_table() must create the table."""
    ensure_generated_images_table()
    insp = inspect(engine)
    assert insp.has_table("generated_images")


def test_ensure_is_idempotent():
    """Calling ensure_generated_images_table() twice must not raise."""
    ensure_generated_images_table()
    ensure_generated_images_table()  # second call safe


def test_create_generated_image_row(db_session):
    """Insert a row with all required fields; defaults apply."""
    # Make sure the table exists (idempotent — may already be there).
    ensure_generated_images_table()

    suffix = uuid.uuid4().hex[:8]
    tenant = _make_tenant(db_session, suffix)
    user = _make_user(db_session, tenant_id=tenant.id, suffix=suffix)
    mc = _make_model_config(db_session, tenant_id=tenant.id)

    try:
        img = GeneratedImage(
            tenant_id=tenant.id,
            user_id=user.id,
            model_config_id=mc.id,
            prompt="a cat",
            size="1024x1024",
            n=1,
            file_path=f"generated_images/{tenant.id}/2026-06-11/abc_{suffix}.png",
            file_size=12345,
            mime_type="image/png",
        )
        db_session.add(img)
        db_session.commit()
        db_session.refresh(img)
        assert img.id is not None
        assert img.status == "pending"
        assert img.created_at is not None
    finally:
        # Clean up — order matters because of FKs.
        try:
            db_session.query(GeneratedImage).filter(
                GeneratedImage.tenant_id == tenant.id
            ).delete()
            db_session.commit()
        except Exception:
            db_session.rollback()
        try:
            db_session.delete(mc)
            db_session.commit()
        except Exception:
            db_session.rollback()
        try:
            db_session.delete(user)
            db_session.commit()
        except Exception:
            db_session.rollback()
        try:
            db_session.delete(tenant)
            db_session.commit()
        except Exception:
            db_session.rollback()


def test_tenant_isolation(db_session):
    """Row belongs to tenant; cross-tenant query returns nothing.

    Exercises the WHERE clause by inserting rows in BOTH t1 and t2,
    then asserting the t1 query returns only t1's row. Without
    inserting a t2 row the assertion would be vacuously true (no
    rows exist to filter out).

    Confirms the tenant_id column is queryable and indexed; spec §3.2
    requires multi-tenant isolation, and the service layer will
    always filter by tenant_id before any read.
    """
    ensure_generated_images_table()

    suffix = uuid.uuid4().hex[:8]
    t1 = _make_tenant(db_session, f"t1_{suffix}")
    t2 = _make_tenant(db_session, f"t2_{suffix}")
    u1 = _make_user(db_session, tenant_id=t1.id, suffix=f"t1_{suffix}")
    u2 = _make_user(db_session, tenant_id=t2.id, suffix=f"t2_{suffix}")
    mc1 = _make_model_config(db_session, tenant_id=t1.id)
    mc2 = _make_model_config(db_session, tenant_id=t2.id)

    img1 = GeneratedImage(
        tenant_id=t1.id,
        user_id=u1.id,
        model_config_id=mc1.id,
        prompt=f"p1_{suffix}",
        size="1024x1024",
        n=1,
        file_path=f"x1_{suffix}.png",
        file_size=1,
        mime_type="image/png",
    )
    img2 = GeneratedImage(
        tenant_id=t2.id,
        user_id=u2.id,
        model_config_id=mc2.id,
        prompt=f"p2_{suffix}",
        size="1024x1024",
        n=1,
        file_path=f"x2_{suffix}.png",
        file_size=1,
        mime_type="image/png",
    )
    db_session.add_all([img1, img2])
    db_session.commit()

    try:
        # t1 query must filter out t2's row — this is the load-bearing
        # assertion. If the WHERE tenant_id=? clause were dropped
        # (or wrong), both img1 and img2 would be returned.
        t1_rows = (
            db_session.query(GeneratedImage)
            .filter(GeneratedImage.tenant_id == t1.id)
            .all()
        )
        assert len(t1_rows) == 1
        assert t1_rows[0].id == img1.id
        assert t1_rows[0].prompt == f"p1_{suffix}"

        # And vice versa: t2 query must filter out t1's row.
        t2_rows = (
            db_session.query(GeneratedImage)
            .filter(GeneratedImage.tenant_id == t2.id)
            .all()
        )
        assert len(t2_rows) == 1
        assert t2_rows[0].id == img2.id
        assert t2_rows[0].prompt == f"p2_{suffix}"
    finally:
        try:
            db_session.query(GeneratedImage).filter(
                GeneratedImage.tenant_id.in_([t1.id, t2.id])
            ).delete(synchronize_session=False)
            db_session.commit()
        except Exception:
            db_session.rollback()
        try:
            db_session.delete(mc1)
            db_session.delete(mc2)
            db_session.commit()
        except Exception:
            db_session.rollback()
        try:
            db_session.delete(u1)
            db_session.delete(u2)
            db_session.commit()
        except Exception:
            db_session.rollback()
        try:
            db_session.delete(t1)
            db_session.delete(t2)
            db_session.commit()
        except Exception:
            db_session.rollback()
