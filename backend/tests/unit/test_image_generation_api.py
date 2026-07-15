"""Integration tests for /api/v1/image-generation endpoints.

Spec: docs/superpowers/specs/2026-06-11-image-generation-design.md §4 + §8.1
"""
import uuid

import pytest
from fastapi.testclient import TestClient

from lumen_core import storage


# ---- module-level helpers (mirrors T9 / T11 plan convention) ---------

def _make_client():
    from lumen_main import app
    return TestClient(app)


def _make_auth_header(user):
    from lumen_services.auth_service import create_access_token
    token = create_access_token(
        data={"sub": user.username, "user_id": user.id}
    )
    return {"Authorization": f"Bearer {token}"}


def _make_tenant(db, suffix: str):
    from lumen_models.tenant import Tenant
    t = Tenant(name=f"img_api_t_{suffix}", code=f"img_api_{suffix}")
    db.add(t); db.commit(); db.refresh(t)
    return t


def _make_user(db, *, tenant_id: int, suffix: str):
    from lumen_core.security import get_password_hash
    from lumen_models.user import User
    u = User(
        username=f"img_api_u_{suffix}",
        email=f"img_api_{suffix}@test.local",
        hashed_password=get_password_hash("x"),
        tenant_id=tenant_id,
        is_active=True,
    )
    db.add(u); db.commit(); db.refresh(u)
    return u


def _make_model_config(
    db, *, tenant_id: int, is_image_generation: bool = True,
    model_type: str = "stub",
):
    from lumen_models.model_config import ModelConfig
    mc = ModelConfig(
        name=f"img_api_mc_{uuid.uuid4().hex[:6]}",
        # 2026-06-17 收口-FA: model_type now routes via factory
        # (services/image_providers/factory.py). Anything that maps to
        # a real provider (openai / stability / ollama / minimax)
        # requires a non-empty api_key and network access — the dev
        # DB has neither, so the background task flips status to
        # "failed" and test_get_detail fails. Default to "stub" which
        # routes to StubImageProvider (synchronous Pillow PNG, no
        # external deps). Tests that explicitly want a specific
        # provider can pass model_type=... to override.
        model_type=model_type,
        model_name="stub-image-1",
        tenant_id=tenant_id,
        is_active=True,
        is_chat=False,
        is_embedding=False,
        is_image_generation=is_image_generation,
    )
    db.add(mc); db.commit(); db.refresh(mc)
    return mc


# ---- fixtures --------------------------------------------------------

@pytest.fixture
def client():
    """Plain TestClient (no DB override). Tests use it to exercise auth
    flows. tmp_user is real, so real DB is needed."""
    return _make_client()


@pytest.fixture
def auth_header(tmp_user):
    return _make_auth_header(tmp_user)


@pytest.fixture
def clean_rows():
    """Track (gen_img_ids, mc_ids, user_ids, tenant_ids) for cleanup.

    Pre-cleanup: also wipes any pre-existing ``img_api_mc_*`` noise rows
    that previous test runs left behind. M26 added the
    ``llm_call_logs`` table which holds a FK to ``generated_images``;
    even after the llm_call_logs rows are cleared, these noisy rows
    collide with the unique ``(tenant_id, model_type, model_name)``
    index on ``model_configs`` when subsequent tests try to create
    rows with the same generated name pattern.
    """
    from lumen_core.database import SessionLocal
    from lumen_models.model_config import ModelConfig
    from sqlalchemy import text

    db = SessionLocal()
    try:
        # Clear pre-existing noise with proper FK ordering:
        # llm_call_logs.image_id → generated_images.id → model_configs.id
        db.execute(text(
            "DELETE FROM llm_call_logs WHERE image_id IN ("
            "SELECT id FROM generated_images WHERE model_config_id IN ("
            "SELECT id FROM model_configs WHERE name LIKE 'img_api_mc_%'"
            "))"
        ))
        db.commit()
        db.execute(text(
            "DELETE FROM generated_images WHERE model_config_id IN ("
            "SELECT id FROM model_configs WHERE name LIKE 'img_api_mc_%'"
            ")"
        ))
        db.commit()
        db.execute(text(
            "DELETE FROM model_configs WHERE name LIKE 'img_api_mc_%'"
        ))
        db.commit()
    finally:
        db.close()

    gen_img_ids: list = []
    mc_ids: list = []
    user_ids: list = []
    tenant_ids: list = []
    yield gen_img_ids, mc_ids, user_ids, tenant_ids

    from lumen_core.database import SessionLocal
    from lumen_models.image_generation import GeneratedImage
    from lumen_models.model_config import ModelConfig
    from lumen_models.user import User
    from lumen_models.tenant import Tenant
    from lumen_models.llm_call_log import LLMCallLog

    db = SessionLocal()
    try:
        if gen_img_ids:
            # M26: llm_call_logs.image_id FKs into generated_images, so the
            # image rows must be unhooked from those log rows before the
            # GeneratedImage DELETE below. Otherwise the FK on
            # llm_call_logs.image_id blocks the DELETE (RESTRICT).
            db.query(LLMCallLog).filter(
                LLMCallLog.image_id.in_(gen_img_ids)
            ).delete(synchronize_session=False)
            db.commit()
            db.query(GeneratedImage).filter(
                GeneratedImage.id.in_(gen_img_ids)
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


# ---- tests -----------------------------------------------------------

def test_create_requires_auth(client):
    """No Authorization header → 401 from get_current_user."""
    r = client.post(
        "/api/v1/image-generation/",
        json={"model_config_id": 1, "prompt": "x"},
    )
    assert r.status_code == 401


def test_create_model_not_found(client, tmp_user, auth_header, clean_rows):
    gen_img_ids, mc_ids, user_ids, tenant_ids = clean_rows
    # Default tenant 1 has no matching model_config, so this hits the
    # "Model config not found in this tenant" branch.
    r = client.post(
        "/api/v1/image-generation/",
        json={"model_config_id": 99999, "prompt": "x"},
        headers=auth_header,
    )
    assert r.status_code == 404


def test_create_model_not_image_capable(client, tmp_user, auth_header, clean_rows):
    """ModelConfig.is_image_generation=False → 400 with a clear message."""
    from lumen_core.database import SessionLocal

    gen_img_ids, mc_ids, user_ids, tenant_ids = clean_rows
    db = SessionLocal()
    suffix = uuid.uuid4().hex[:8]
    # Put a non-image-capable MC into the SAME tenant as tmp_user (tenant 1).
    mc = _make_model_config(
        db, tenant_id=tmp_user.tenant_id, is_image_generation=False,
    )
    mc_ids.append(mc.id)
    db.close()

    r = client.post(
        "/api/v1/image-generation/",
        json={"model_config_id": mc.id, "prompt": "x"},
        headers=auth_header,
    )
    assert r.status_code == 400
    assert "image_generation" in r.json()["detail"].lower()


def test_create_success_pending_n1(client, tmp_user, auth_header, clean_rows):
    from lumen_core.database import SessionLocal

    gen_img_ids, mc_ids, user_ids, tenant_ids = clean_rows
    db = SessionLocal()
    suffix = uuid.uuid4().hex[:8]
    mc = _make_model_config(
        db, tenant_id=tmp_user.tenant_id, is_image_generation=True,
    )
    mc_ids.append(mc.id)
    db.close()

    r = client.post(
        "/api/v1/image-generation/",
        json={
            "model_config_id": mc.id,
            "prompt": "a cat",
            "size": "512x512",
        },
        headers=auth_header,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["code"] == 200
    assert body["data"]["status"] == "pending"
    assert body["data"]["batch_id"] is None  # n=1 → no batch
    assert body["data"]["model_config_id"] == mc.id

    gen_img_ids.append(body["data"]["id"])


def test_list_tenant_isolation(client, tmp_user, auth_header, clean_rows):
    """Tenant 1 creates an image; tenant 2 must see 0 rows."""
    from lumen_core.database import SessionLocal

    gen_img_ids, mc_ids, user_ids, tenant_ids = clean_rows
    db = SessionLocal()
    suffix = uuid.uuid4().hex[:8]
    mc = _make_model_config(
        db, tenant_id=tmp_user.tenant_id, is_image_generation=True,
    )
    mc_ids.append(mc.id)

    # Create one image as tenant 1 (tmp_user)
    r = client.post(
        "/api/v1/image-generation/",
        json={"model_config_id": mc.id, "prompt": "x"},
        headers=auth_header,
    )
    assert r.status_code == 200
    gen_img_ids.append(r.json()["data"]["id"])

    # Now create a separate tenant + user and verify they see 0.
    suffix2 = uuid.uuid4().hex[:8]
    t2 = _make_tenant(db, suffix2)
    tenant_ids.append(t2.id)
    u2 = _make_user(db, tenant_id=t2.id, suffix=suffix2)
    user_ids.append(u2.id)
    db.close()

    auth_header2 = _make_auth_header(u2)
    r2 = client.get(
        "/api/v1/image-generation/", headers=auth_header2,
    )
    assert r2.status_code == 200
    body = r2.json()
    assert body["code"] == 200
    # PaginatedResponse shape: {code, message, data: [...items], total, page, page_size}
    assert body["total"] == 0
    assert body["data"] == []


def test_get_detail(client, tmp_user, auth_header, clean_rows):
    from lumen_core.database import SessionLocal

    gen_img_ids, mc_ids, user_ids, tenant_ids = clean_rows
    db = SessionLocal()
    suffix = uuid.uuid4().hex[:8]
    mc = _make_model_config(
        db, tenant_id=tmp_user.tenant_id, is_image_generation=True,
    )
    mc_ids.append(mc.id)
    db.close()

    r = client.post(
        "/api/v1/image-generation/",
        json={"model_config_id": mc.id, "prompt": "show me the cat"},
        headers=auth_header,
    )
    assert r.status_code == 200
    img_id = r.json()["data"]["id"]
    gen_img_ids.append(img_id)

    r2 = client.get(
        f"/api/v1/image-generation/{img_id}", headers=auth_header,
    )
    assert r2.status_code == 200
    detail = r2.json()["data"]
    assert detail["id"] == img_id
    assert detail["prompt"] == "show me the cat"
    assert detail["model_name"] == mc.name
    # 2026-06-17 收口-FA: helper defaults to model_type="stub" (routes
    # to StubImageProvider which completes synchronously). The
    # earlier "minimax" assertion was left over from when the
    # factory had no real provider impl for minimax.
    assert detail["model_type"] == "stub"
    # The background task may have already run; status could be "pending"
    # (task queued but not yet executed) or "completed" (StubImageProvider
    # already finished). Both are valid.
    assert detail["status"] in ("pending", "generating", "completed")


def test_regenerate_creates_new_row(client, tmp_user, auth_header, clean_rows):
    from lumen_core.database import SessionLocal

    gen_img_ids, mc_ids, user_ids, tenant_ids = clean_rows
    db = SessionLocal()
    suffix = uuid.uuid4().hex[:8]
    mc = _make_model_config(
        db, tenant_id=tmp_user.tenant_id, is_image_generation=True,
    )
    mc_ids.append(mc.id)
    db.close()

    r = client.post(
        "/api/v1/image-generation/",
        json={"model_config_id": mc.id, "prompt": "x"},
        headers=auth_header,
    )
    assert r.status_code == 200
    orig_id = r.json()["data"]["id"]
    gen_img_ids.append(orig_id)

    r2 = client.post(
        f"/api/v1/image-generation/{orig_id}/regenerate",
        headers=auth_header,
    )
    assert r2.status_code == 200
    new_id = r2.json()["data"]["id"]
    assert new_id != orig_id
    gen_img_ids.append(new_id)

    # Both rows still readable
    r3 = client.get(
        f"/api/v1/image-generation/{orig_id}", headers=auth_header,
    )
    r4 = client.get(
        f"/api/v1/image-generation/{new_id}", headers=auth_header,
    )
    assert r3.status_code == 200
    assert r4.status_code == 200


def test_delete(client, tmp_user, auth_header, clean_rows, tmp_path, monkeypatch):
    """DELETE /{id} → 204, subsequent GET → 404. Also wipes the file."""
    from lumen_core.database import SessionLocal

    gen_img_ids, mc_ids, user_ids, tenant_ids = clean_rows
    # STORAGE_DIR is a @property — monkeypatch the storage module's
    # ``settings`` reference (T9 pattern).
    monkeypatch.setattr(
        storage, "settings",
        type("S", (), {"STORAGE_DIR": tmp_path})(),
    )

    db = SessionLocal()
    suffix = uuid.uuid4().hex[:8]
    mc = _make_model_config(
        db, tenant_id=tmp_user.tenant_id, is_image_generation=True,
    )
    mc_ids.append(mc.id)
    db.close()

    r = client.post(
        "/api/v1/image-generation/",
        json={"model_config_id": mc.id, "prompt": "x"},
        headers=auth_header,
    )
    assert r.status_code == 200
    img_id = r.json()["data"]["id"]
    gen_img_ids.append(img_id)

    r2 = client.delete(
        f"/api/v1/image-generation/{img_id}", headers=auth_header,
    )
    assert r2.status_code == 204

    r3 = client.get(
        f"/api/v1/image-generation/{img_id}", headers=auth_header,
    )
    assert r3.status_code == 404

    # Track that we no longer need cleanup of the deleted row.
    gen_img_ids.remove(img_id)
