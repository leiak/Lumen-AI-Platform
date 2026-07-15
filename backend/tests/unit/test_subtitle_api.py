"""Integration tests for /api/v1/subtitles endpoints.

Spec: docs-internal/superpowers/specs/M35-overview.md §5
"""
import uuid

import pytest
from fastapi.testclient import TestClient

from lumen_core.database import SessionLocal


def _make_client():
    from lumen_main import app
    return TestClient(app)


def _make_auth_header(user_id: int, username: str):
    from lumen_services.auth_service import create_access_token
    token = create_access_token(
        data={"sub": username, "user_id": user_id}
    )
    return {"Authorization": f"Bearer {token}"}


def _make_setup(suffix: str):
    """Create tenant + user, return their primary keys (not ORM objects
    that would be detached when the session closes)."""
    from lumen_models.tenant import Tenant
    from lumen_models.user import User
    from lumen_core.security import get_password_hash
    db = SessionLocal()
    try:
        t = Tenant(name=f"sub_api_t_{suffix}", code=f"sub_api_t_{suffix}")
        db.add(t); db.commit(); db.refresh(t)
        u = User(
            username=f"sub_api_u_{suffix}",
            email=f"sub_api_{suffix}@test.local",
            hashed_password=get_password_hash("x"),
            tenant_id=t.id, is_active=True,
        )
        db.add(u); db.commit(); db.refresh(u)
        # Return raw primary keys + username (needed for token)
        return t.id, u.id, u.username
    finally:
        db.close()


@pytest.fixture
def client():
    return _make_client()


@pytest.fixture
def setup():
    suffix = uuid.uuid4().hex[:8]
    tenant_id, user_id, username = _make_setup(suffix)
    yield {"tenant_id": tenant_id, "user_id": user_id, "username": username}
    from lumen_models.subtitle import Subtitle
    from lumen_models.user import User
    from lumen_models.tenant import Tenant
    db2 = SessionLocal()
    try:
        db2.query(Subtitle).filter(Subtitle.tenant_id == tenant_id).delete(
            synchronize_session=False
        )
        db2.commit()
        db2.query(User).filter(User.id == user_id).delete(synchronize_session=False)
        db2.commit()
        db2.query(Tenant).filter(Tenant.id == tenant_id).delete(synchronize_session=False)
        db2.commit()
    except Exception:
        db2.rollback()
    finally:
        db2.close()


def test_create_subtitle(client, setup):
    """POST /subtitles/ builds SRT and persists row."""
    headers = _make_auth_header(setup["user_id"], setup["username"])
    res = client.post(
        "/api/v1/subtitles/",
        headers=headers,
        json={
            "script": "你好世界。这是第二句。",
            "total_duration_ms": 4000,
            "language": "zh-CN",
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["code"] == 200
    sub_id = body["data"]["id"]
    assert body["data"]["cue_count"] == 2
    assert body["data"]["duration_ms"] == 4000


def test_create_subtitle_invalid_duration_rejected(client, setup):
    """Duration < 1000 → 422."""
    headers = _make_auth_header(setup["user_id"], setup["username"])
    res = client.post(
        "/api/v1/subtitles/",
        headers=headers,
        json={"script": "x", "total_duration_ms": 500},
    )
    assert res.status_code == 422


def test_get_subtitle_content(client, setup):
    """GET /subtitles/{id}/content returns text/plain SRT."""
    headers = _make_auth_header(setup["user_id"], setup["username"])
    create = client.post(
        "/api/v1/subtitles/",
        headers=headers,
        json={"script": "测试。", "total_duration_ms": 1000},
    )
    sub_id = create.json()["data"]["id"]

    res = client.get(f"/api/v1/subtitles/{sub_id}/content", headers=headers)
    assert res.status_code == 200
    assert "-->" in res.text
    assert "测试" in res.text


def test_list_subtitles(client, setup):
    """GET /subtitles/ returns paginated list."""
    headers = _make_auth_header(setup["user_id"], setup["username"])
    res = client.get("/api/v1/subtitles/", headers=headers)
    assert res.status_code == 200
    body = res.json()
    assert body["code"] == 200
    # Paginated envelope: data is a list directly
    assert isinstance(body["data"], list)


def test_unauthenticated_rejected(client):
    res = client.get("/api/v1/subtitles/")
    assert res.status_code == 401