"""Integration tests for /api/v1/tts endpoints.

Spec: docs-internal/superpowers/specs/M35-overview.md §4 + §8
"""
import uuid

import pytest
from fastapi.testclient import TestClient

from lumen_core.database import SessionLocal


# ---- module-level helpers --------------------------------------------------

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
    t = Tenant(name=f"tts_api_t_{suffix}", code=f"tts_api_t_{suffix}")
    db.add(t); db.commit(); db.refresh(t)
    return t


def _make_user(db, *, tenant_id: int, suffix: str):
    from lumen_core.security import get_password_hash
    from lumen_models.user import User
    u = User(
        username=f"tts_api_u_{suffix}",
        email=f"tts_api_{suffix}@test.local",
        hashed_password=get_password_hash("x"),
        tenant_id=tenant_id, is_active=True,
    )
    db.add(u); db.commit(); db.refresh(u)
    return u


def _make_tts_model_config(db, *, tenant_id: int):
    from lumen_models.model_config import ModelConfig
    mc = ModelConfig(
        name=f"tts_api_mc_{uuid.uuid4().hex[:6]}",
        model_type="stub",  # dev DB has no real network → stub provider
        model_name="stub-tts",
        tenant_id=tenant_id,
        is_active=True,
        is_chat=False,
        is_embedding=False,
        is_image_generation=False,
        is_tts=True,
    )
    db.add(mc); db.commit(); db.refresh(mc)
    return mc


# ---- fixtures --------------------------------------------------------------

@pytest.fixture
def client():
    return _make_client()


@pytest.fixture
def tts_setup():
    """Create tenant + user + tts model; cleanup via fresh SessionLocal."""
    suffix = uuid.uuid4().hex[:8]
    db = SessionLocal()
    try:
        tenant = _make_tenant(db, suffix)
        user = _make_user(db, tenant_id=tenant.id, suffix=suffix)
        mc = _make_tts_model_config(db, tenant_id=tenant.id)
        yield {"tenant_id": tenant.id, "user_id": user.id, "mc_id": mc.id, "user": user}
    finally:
        # Cleanup
        from lumen_models.tts import GeneratedAudio
        from lumen_models.model_config import ModelConfig
        from lumen_models.user import User
        from lumen_models.tenant import Tenant
        db2 = SessionLocal()
        try:
            db2.query(GeneratedAudio).filter(
                GeneratedAudio.tenant_id == tenant.id
            ).delete(synchronize_session=False)
            db2.commit()
            db2.query(ModelConfig).filter(ModelConfig.id == mc.id).delete(
                synchronize_session=False
            )
            db2.commit()
            db2.query(User).filter(User.id == user.id).delete(
                synchronize_session=False
            )
            db2.commit()
            db2.query(Tenant).filter(Tenant.id == tenant.id).delete(
                synchronize_session=False
            )
            db2.commit()
        except Exception:
            db2.rollback()
        finally:
            db2.close()
        db.close()


# ---- tests -----------------------------------------------------------------

def test_create_tts_job_returns_id(client, tts_setup):
    """POST /tts/jobs returns {id, status: pending}."""
    headers = _make_auth_header(tts_setup["user"])
    res = client.post(
        "/api/v1/tts/jobs/",
        headers=headers,
        json={
            "model_config_id": tts_setup["mc_id"],
            "text": "hello world",
            "voice": "default",
            "format": "mp3",
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["code"] == 200
    assert "id" in body["data"]
    assert body["data"]["status"] in ("pending", "running", "completed")


def test_create_tts_job_text_too_long_rejected(client, tts_setup):
    """POST /tts/jobs with >10000 chars returns 422."""
    headers = _make_auth_header(tts_setup["user"])
    res = client.post(
        "/api/v1/tts/jobs/",
        headers=headers,
        json={
            "model_config_id": tts_setup["mc_id"],
            "text": "x" * 10001,
            "voice": "default",
        },
    )
    assert res.status_code == 422


def test_list_tts_jobs(client, tts_setup):
    """GET /tts/jobs/ returns paginated list."""
    headers = _make_auth_header(tts_setup["user"])
    res = client.get("/api/v1/tts/jobs/", headers=headers)
    assert res.status_code == 200
    body = res.json()
    assert body["code"] == 200
    # Paginated envelope: {code, data: [...], total, page, page_size}
    assert isinstance(body["data"], list)
    assert "total" in body
    assert "page" in body


def test_get_tts_job_detail(client, tts_setup):
    """GET /tts/jobs/{id} returns row envelope."""
    headers = _make_auth_header(tts_setup["user"])
    # Create one
    create_res = client.post(
        "/api/v1/tts/jobs/",
        headers=headers,
        json={
            "model_config_id": tts_setup["mc_id"],
            "text": "detail test",
        },
    )
    audio_id = create_res.json()["data"]["id"]

    res = client.get(f"/api/v1/tts/jobs/{audio_id}", headers=headers)
    assert res.status_code == 200
    body = res.json()
    assert body["code"] == 200
    assert body["data"]["id"] == audio_id
    assert body["data"]["text"] == "detail test"


def test_tts_unauthenticated_rejected(client, tts_setup):
    """Endpoints require Bearer auth."""
    res = client.post(
        "/api/v1/tts/jobs/",
        json={
            "model_config_id": tts_setup["mc_id"],
            "text": "x",
        },
    )
    assert res.status_code == 401


def test_list_tts_voices_for_stub(client, tts_setup):
    """GET /tts/voices returns at least 1 voice for stub provider."""
    headers = _make_auth_header(tts_setup["user"])
    res = client.get(
        f"/api/v1/tts/voices?model_config_id={tts_setup['mc_id']}",
        headers=headers,
    )
    assert res.status_code == 200
    body = res.json()
    assert body["code"] == 200
    assert isinstance(body["data"], list)
    assert len(body["data"]) >= 1