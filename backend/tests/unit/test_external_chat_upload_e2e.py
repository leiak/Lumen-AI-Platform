"""External upload endpoint tests."""
import io
import uuid
import pytest
from datetime import datetime
from fastapi.testclient import TestClient

from lumen_core.database import SessionLocal
from lumen_main import app
from lumen_models.external_app import ExternalApp, ExternalVisitor
from lumen_models.tenant import Tenant
from lumen_scripts.seed_external_app import seed_dev_external_app
from lumen_services.external_auth_service import create_external_token


# Same MDL-defense fixture as Task 10's test file — TestClient + full-app
# import can leak Sessions that hold InnoDB metadata locks on
# `conversations`. See MEMORY.md "TestClient + MDL deadlock".
@pytest.fixture(autouse=True)
def _dispose_engine_after_test():
    yield
    from lumen_core.database import engine
    import gc
    gc.collect()
    engine.dispose()


def _setup():
    seed_dev_external_app()
    db = SessionLocal()
    try:
        t = db.query(Tenant).first()
        ext_app = db.query(ExternalApp).filter(
            ExternalApp.app_key == "lc_pub_dev_demo_only_replace_in_prod"
        ).first()
        ext_app.tenant_id = t.id
        # Random UUID suffix avoids collisions with dev DB pollution
        v = ExternalVisitor(
            app_id=ext_app.id,
            visitor_id=f"vis-up-{uuid.uuid4().hex[:8]}",
            first_seen_at=datetime.utcnow(), last_seen_at=datetime.utcnow(),
        )
        db.add(v)
        db.commit()
        db.refresh(v)
        # Return raw ids/strings (not ORM) to avoid DetachedInstanceError
        return ext_app.id, ext_app.tenant_id, v.id, v.visitor_id
    finally:
        db.close()


def test_upload_txt_returns_content_text():
    app_id, tenant_id, visitor_id, visitor_uuid = _setup()
    token = create_external_token({
        "app_id": app_id, "tenant_id": tenant_id,
        "visitor_id": visitor_id, "visitor_uuid": visitor_uuid,
        "allowed_agent_ids": [], "allowed_team_ids": [],
        "scopes": ["chat:upload"],
    })
    client = TestClient(app)
    r = client.post(
        "/api/v1/external/chat/upload",
        files={"file": ("hello.txt", b"hello world from widget", "text/plain")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["code"] == 200
    data = body["data"]
    assert data["name"] == "hello.txt"
    assert "hello world" in data["content_text"]


def test_upload_rejects_unsupported_extension():
    app_id, tenant_id, visitor_id, visitor_uuid = _setup()
    token = create_external_token({
        "app_id": app_id, "tenant_id": tenant_id,
        "visitor_id": visitor_id, "visitor_uuid": visitor_uuid,
        "allowed_agent_ids": [], "allowed_team_ids": [],
        "scopes": ["chat:upload"],
    })
    client = TestClient(app)
    r = client.post(
        "/api/v1/external/chat/upload",
        files={"file": ("virus.exe", b"MZ", "application/octet-stream")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 415


def test_upload_requires_auth():
    client = TestClient(app)
    r = client.post(
        "/api/v1/external/chat/upload",
        files={"file": ("hello.txt", b"hi", "text/plain")},
    )
    assert r.status_code == 401
