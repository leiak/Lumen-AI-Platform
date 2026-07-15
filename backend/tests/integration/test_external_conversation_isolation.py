"""Cross-visitor IDOR + happy-path tests for /external/conversations/*."""
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


# Same MDL-defense fixture as Tasks 10/11 — TestClient + full-app import
# can leak Sessions that hold InnoDB metadata locks on `conversations`.
# See MEMORY.md "TestClient + MDL deadlock".
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
        # Random UUID suffix avoids dev DB pollution collisions
        v_a = ExternalVisitor(app_id=ext_app.id,
                              visitor_id=f"vis-A-{uuid.uuid4().hex[:8]}",
                              first_seen_at=datetime.utcnow(), last_seen_at=datetime.utcnow())
        v_b = ExternalVisitor(app_id=ext_app.id,
                              visitor_id=f"vis-B-{uuid.uuid4().hex[:8]}",
                              first_seen_at=datetime.utcnow(), last_seen_at=datetime.utcnow())
        db.add_all([v_a, v_b])
        db.commit()
        for v in (v_a, v_b):
            db.refresh(v)
        # Return raw ids/strings (not ORM) to avoid DetachedInstanceError
        return (ext_app.id, ext_app.tenant_id,
                v_a.id, v_a.visitor_id, v_b.id, v_b.visitor_id)
    finally:
        db.close()


def _token(app_id, tenant_id, visitor_id, visitor_uuid, scopes=None):
    return create_external_token({
        "app_id": app_id, "tenant_id": tenant_id,
        "visitor_id": visitor_id, "visitor_uuid": visitor_uuid,
        "allowed_agent_ids": [], "allowed_team_ids": [],
        "scopes": scopes or ["chat:stream", "conv:read"],
    })


def test_list_conversations_returns_only_own_visitor():
    app_id, tenant_id, va_id, va_uuid, vb_id, vb_uuid = _setup()
    client = TestClient(app)
    # Create one conv for each (no agent_id — must succeed even with empty whitelist)
    for vis_id, vis_uuid in [(va_id, va_uuid), (vb_id, vb_uuid)]:
        tok = _token(app_id, tenant_id, vis_id, vis_uuid)
        r = client.post("/api/v1/external/conversations",
                        json={"title": f"conv-{vis_uuid[:6]}"},
                        headers={"Authorization": f"Bearer {tok}"})
        assert r.status_code == 200, r.text

    tok_a = _token(app_id, tenant_id, va_id, va_uuid)
    r = client.get("/api/v1/external/conversations",
                   headers={"Authorization": f"Bearer {tok_a}"})
    assert r.status_code == 200
    titles = [c["title"] for c in r.json()["data"]]
    # A's conv present, B's conv NOT present (IDOR defense)
    assert any("conv-" in t and va_uuid[:6] in t for t in titles)
    assert not any("conv-" in t and vb_uuid[:6] in t for t in titles)


def test_get_messages_cross_visitor_404():
    app_id, tenant_id, va_id, va_uuid, vb_id, vb_uuid = _setup()
    client = TestClient(app)
    tok_b = _token(app_id, tenant_id, vb_id, vb_uuid)
    r = client.post("/api/v1/external/conversations", json={"title": "B-conv"},
                    headers={"Authorization": f"Bearer {tok_b}"})
    assert r.status_code == 200, r.text
    b_conv_id = r.json()["data"]["id"]

    tok_a = _token(app_id, tenant_id, va_id, va_uuid)
    r = client.get(f"/api/v1/external/conversations/{b_conv_id}/messages",
                   headers={"Authorization": f"Bearer {tok_a}"})
    assert r.status_code == 404  # not 403 — don't leak existence


def test_delete_conversation_own_works():
    app_id, tenant_id, va_id, va_uuid, vb_id, vb_uuid = _setup()
    client = TestClient(app)
    tok_a = _token(app_id, tenant_id, va_id, va_uuid)
    r = client.post("/api/v1/external/conversations", json={"title": "to-delete"},
                    headers={"Authorization": f"Bearer {tok_a}"})
    assert r.status_code == 200, r.text
    cid = r.json()["data"]["id"]
    r = client.delete(f"/api/v1/external/conversations/{cid}",
                      headers={"Authorization": f"Bearer {tok_a}"})
    assert r.status_code == 200
    # Soft-deleted — list should not include it
    r = client.get("/api/v1/external/conversations",
                   headers={"Authorization": f"Bearer {tok_a}"})
    assert cid not in [c["id"] for c in r.json()["data"]]


def test_delete_cross_visitor_404():
    app_id, tenant_id, va_id, va_uuid, vb_id, vb_uuid = _setup()
    client = TestClient(app)
    tok_b = _token(app_id, tenant_id, vb_id, vb_uuid)
    r = client.post("/api/v1/external/conversations", json={"title": "B-again"},
                    headers={"Authorization": f"Bearer {tok_b}"})
    assert r.status_code == 200, r.text
    cid = r.json()["data"]["id"]
    tok_a = _token(app_id, tenant_id, va_id, va_uuid)
    r = client.delete(f"/api/v1/external/conversations/{cid}",
                      headers={"Authorization": f"Bearer {tok_a}"})
    assert r.status_code == 404
