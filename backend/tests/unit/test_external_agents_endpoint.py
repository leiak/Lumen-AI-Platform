"""GET /api/v1/external/agents endpoint tests.

The endpoint returns the union of ``ExternalApp.allowed_agent_ids`` and
``ExternalApp.allowed_team_ids`` filtered by ``is_active=True``. The
response is denormalized (agents AND teams in the same list,
distinguished by the ``type`` field) so the widget's agent switcher can
render a single dropdown.

The whitelist is read from the live DB row, not the JWT payload — so
admin edits to the whitelist take effect on the very next request.
"""
import uuid
import pytest
from datetime import datetime
from fastapi.testclient import TestClient

from lumen_core.database import SessionLocal
from lumen_main import app
from lumen_models.agent import Agent
from lumen_models.agent_team import AgentTeam
from lumen_models.external_app import ExternalApp, ExternalVisitor
from lumen_models.tenant import Tenant
from lumen_scripts.seed_external_app import seed_dev_external_app
from lumen_services.external_auth_service import create_external_token


# Same MDL-defense fixture as Tasks 10/11/12 — TestClient + full-app
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
        a1 = Agent(name="alpha", prompt_template="p", model_name="qwen2.5:7b",
                   temperature=0, tenant_id=t.id, is_active=True)
        a2 = Agent(name="beta", prompt_template="p", model_name="qwen2.5:7b",
                   temperature=0, tenant_id=t.id, is_active=True)
        inactive = Agent(name="inactive", prompt_template="p", model_name="qwen2.5:7b",
                         temperature=0, tenant_id=t.id, is_active=False)
        db.add_all([a1, a2, inactive])
        db.commit()
        for x in (a1, a2, inactive):
            db.refresh(x)
        team = AgentTeam(name="sales", tenant_id=t.id, manager_agent_id=a1.id, is_active=True)
        db.add(team)
        db.commit()
        db.refresh(team)
        # Whitelist a1 + team; inactive must NOT appear
        ext_app.allowed_agent_ids = [a1.id]
        ext_app.allowed_team_ids = [team.id]
        db.commit()
        # Random UUID suffix avoids dev DB pollution collisions
        v = ExternalVisitor(
            app_id=ext_app.id,
            visitor_id=f"vis-ag-{uuid.uuid4().hex[:8]}",
            first_seen_at=datetime.utcnow(), last_seen_at=datetime.utcnow(),
        )
        db.add(v)
        db.commit()
        db.refresh(v)
        # Return raw ids (not ORM) to avoid DetachedInstanceError
        return (ext_app.id, ext_app.tenant_id, v.id, v.visitor_id,
                a1.id, a2.id, inactive.id, team.id)
    finally:
        db.close()


def _token(app_id, tenant_id, visitor_id, visitor_uuid, allowed_agent_ids, allowed_team_ids):
    return create_external_token({
        "app_id": app_id, "tenant_id": tenant_id,
        "visitor_id": visitor_id, "visitor_uuid": visitor_uuid,
        "allowed_agent_ids": allowed_agent_ids,
        "allowed_team_ids": allowed_team_ids,
        "scopes": ["chat:stream"],
    })


def test_agents_returns_only_whitelisted_and_active():
    (app_id, tenant_id, vis_id, vis_uuid,
     a1_id, a2_id, inactive_id, team_id) = _setup()
    token = _token(app_id, tenant_id, vis_id, vis_uuid,
                   allowed_agent_ids=[a1_id], allowed_team_ids=[team_id])
    client = TestClient(app)
    r = client.get("/api/v1/external/agents",
                   headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    body = r.json()
    items = body["data"]
    agent_names = [i["name"] for i in items if i["type"] == "agent"]
    team_names = [i["name"] for i in items if i["type"] == "team"]
    assert "alpha" in agent_names
    assert "beta" not in agent_names       # not in whitelist
    assert "inactive" not in agent_names   # is_active=False
    assert "sales" in team_names


def test_agents_requires_auth():
    client = TestClient(app)
    r = client.get("/api/v1/external/agents")
    assert r.status_code == 401
