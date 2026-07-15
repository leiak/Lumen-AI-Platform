"""Tests for the ``get_current_external_app`` FastAPI dependency.

We mount a minimal probe endpoint on the test app to exercise the
dependency in isolation; the real /external/chat/stream endpoint is
covered by integration tests in Task 10.
"""
import pytest
from fastapi import APIRouter, Depends, HTTPException
from fastapi.testclient import TestClient

from lumen_api.v1.deps import get_current_external_app, ExternalAppContext
from lumen_core.database import SessionLocal
from lumen_services.external_auth_service import create_external_token
from lumen_models.external_app import ExternalApp
from lumen_scripts.seed_external_app import seed_dev_external_app


def _build_test_app():
    from fastapi import FastAPI
    app = FastAPI()

    probe = APIRouter()

    @probe.get("/_probe")
    def probe_endpoint(ctx: ExternalAppContext = Depends(get_current_external_app)):
        return {"app_id": ctx.app_id, "visitor_id": ctx.visitor_id, "scopes": ctx.scopes}

    app.include_router(probe)
    return app


def test_dep_no_token_401():
    client = TestClient(_build_test_app())
    r = client.get("/_probe")
    assert r.status_code == 401


def test_dep_invalid_token_401():
    client = TestClient(_build_test_app())
    r = client.get("/_probe", headers={"Authorization": "Bearer not-a-jwt"})
    assert r.status_code == 401


def test_dep_valid_token_returns_context():
    seed_dev_external_app()
    db = SessionLocal()
    try:
        app = db.query(ExternalApp).filter(
            ExternalApp.app_key == "lc_pub_dev_demo_only_replace_in_prod"
        ).first()
        token = create_external_token({
            "app_id": app.id, "tenant_id": app.tenant_id,
            "visitor_id": 1, "visitor_uuid": "u",
            "allowed_agent_ids": app.allowed_agent_ids,
            "allowed_team_ids": app.allowed_team_ids,
            "scopes": ["chat:stream"],
        })
    finally:
        db.close()

    client = TestClient(_build_test_app())
    r = client.get("/_probe", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    body = r.json()
    assert body["app_id"] == app.id
    assert "chat:stream" in body["scopes"]


def test_dep_revoked_app_401():
    """If the app is disabled AFTER the token was issued, the dep must 401."""
    seed_dev_external_app()
    db = SessionLocal()
    try:
        app = db.query(ExternalApp).filter(
            ExternalApp.app_key == "lc_pub_dev_demo_only_replace_in_prod"
        ).first()
        token = create_external_token({
            "app_id": app.id, "tenant_id": app.tenant_id,
            "visitor_id": 1, "visitor_uuid": "u",
            "allowed_agent_ids": [], "allowed_team_ids": [],
            "scopes": ["chat:stream"],
        })
        original = app.is_active
        app.is_active = False
        db.commit()
        try:
            client = TestClient(_build_test_app())
            r = client.get("/_probe", headers={"Authorization": f"Bearer {token}"})
            assert r.status_code == 401
        finally:
            app.is_active = original
            db.commit()
    finally:
        db.close()


def test_dep_unknown_app_id_401():
    """If the JWT contains an app_id that doesn't exist in the DB, the dep must 401.

    This is the security-critical path the 4-test suite misses: a forged
    app_id in a valid-signature token (e.g. from a token-issuance bug)
    must land on the ``if app is None or not app.is_active`` check and
    return 401, not crash with AttributeError on None.is_active.
    """
    token = create_external_token({
        "app_id": 99999,  # non-existent
        "tenant_id": 1, "visitor_id": 1, "visitor_uuid": "u",
        "allowed_agent_ids": [], "allowed_team_ids": [], "scopes": ["chat:stream"],
    })
    client = TestClient(_build_test_app())
    r = client.get("/_probe", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401
    assert r.json()["detail"] == "app revoked"
