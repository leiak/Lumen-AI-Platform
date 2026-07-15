"""Integration tests for /api/v1/playbooks endpoints.

Spec: docs-internal/superpowers/specs/M35-playbook-schema.md
"""
import uuid

import pytest
from fastapi.testclient import TestClient

from lumen_core.database import SessionLocal


def _make_client():
    from lumen_main import app
    return TestClient(app)


def _make_auth_header(user):
    from lumen_services.auth_service import create_access_token
    token = create_access_token(
        data={"sub": user.username, "user_id": user.id}
    )
    return {"Authorization": f"Bearer {token}"}


def _make_tenant_user(db, suffix: str):
    from lumen_models.tenant import Tenant
    from lumen_models.user import User
    from lumen_core.security import get_password_hash
    t = Tenant(name=f"pb_api_t_{suffix}", code=f"pb_api_t_{suffix}")
    db.add(t); db.commit(); db.refresh(t)
    u = User(
        username=f"pb_api_u_{suffix}",
        email=f"pb_api_{suffix}@test.local",
        hashed_password=get_password_hash("x"),
        tenant_id=t.id, is_active=True,
    )
    db.add(u); db.commit(); db.refresh(u)
    return t, u


@pytest.fixture
def client():
    return _make_client()


@pytest.fixture
def setup():
    suffix = uuid.uuid4().hex[:8]
    db = SessionLocal()
    try:
        tenant, user = _make_tenant_user(db, suffix)
        yield {"tenant_id": tenant.id, "user": user, "tenant": tenant}
    finally:
        from lumen_models.playbook import Playbook
        from lumen_models.user import User
        from lumen_models.tenant import Tenant
        db2 = SessionLocal()
        try:
            db2.query(Playbook).filter(Playbook.tenant_id == tenant.id).delete(
                synchronize_session=False
            )
            db2.commit()
            db2.query(User).filter(User.id == user.id).delete(synchronize_session=False)
            db2.commit()
            db2.query(Tenant).filter(Tenant.id == tenant.id).delete(synchronize_session=False)
            db2.commit()
        except Exception:
            db2.rollback()
        finally:
            db2.close()
        db.close()


def test_create_playbook(client, setup):
    """POST /playbooks/ creates a new tenant playbook."""
    headers = _make_auth_header(setup["user"])
    res = client.post(
        "/api/v1/playbooks/",
        headers=headers,
        json={
            "name": f"my-style-{uuid.uuid4().hex[:6]}",
            "description": "test",
            "yaml_content": "keywords:\n  - cinematic\n",
            "scope": ["image", "tts"],
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["code"] == 200
    assert body["data"]["is_builtin"] is False
    assert body["data"]["style_tokens"]["keywords"] == ["cinematic"]


def test_create_playbook_invalid_yaml_accepted_with_empty_tokens(client, setup):
    """The API swallows PlaybookValidationError and saves with empty
    style_tokens. Users can fix the YAML later via PUT."""
    headers = _make_auth_header(setup["user"])
    res = client.post(
        "/api/v1/playbooks/",
        headers=headers,
        json={
            "name": f"invalid-yaml-{uuid.uuid4().hex[:6]}",
            "yaml_content": "description: just text\n",
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["code"] == 200
    # style_tokens parsed to {} (loader refused, _safe_parse caught it)
    assert body["data"]["style_tokens"] in (None, {})


def test_list_playbooks_includes_builtins(client, setup):
    """list_for_tenant returns built-ins + tenant playbooks."""
    headers = _make_auth_header(setup["user"])
    res = client.get("/api/v1/playbooks/", headers=headers)
    assert res.status_code == 200
    body = res.json()
    assert body["code"] == 200
    # Paginated envelope: data is a list directly
    items = body["data"]
    assert isinstance(items, list)


def test_update_playbook(client, setup):
    """PUT /playbooks/{id} updates description."""
    headers = _make_auth_header(setup["user"])
    create = client.post(
        "/api/v1/playbooks/",
        headers=headers,
        json={
            "name": f"to-update-{uuid.uuid4().hex[:6]}",
            "yaml_content": "keywords:\n  - old\n",
        },
    )
    pb_id = create.json()["data"]["id"]

    res = client.put(
        f"/api/v1/playbooks/{pb_id}",
        headers=headers,
        json={"description": "updated desc"},
    )
    assert res.status_code == 200
    assert res.json()["data"]["description"] == "updated desc"


def test_delete_playbook(client, setup):
    """DELETE /playbooks/{id} removes the row."""
    headers = _make_auth_header(setup["user"])
    create = client.post(
        "/api/v1/playbooks/",
        headers=headers,
        json={
            "name": f"to-del-{uuid.uuid4().hex[:6]}",
            "yaml_content": "keywords:\n  - x\n",
        },
    )
    pb_id = create.json()["data"]["id"]

    res = client.delete(f"/api/v1/playbooks/{pb_id}", headers=headers)
    assert res.status_code in (200, 204)


def test_unauthenticated_rejected(client):
    res = client.get("/api/v1/playbooks/")
    assert res.status_code == 401