"""End-to-end test: full /external/chat/stream round-trip with mocked LLM.

Exercises the auth dep + endpoint + ChatService.stream_for_external in
one go; asserts SSE event sequence + that the conversation was
persisted with the external_app_id FK set.
"""
import json
import uuid
import pytest
from datetime import datetime
from unittest.mock import patch
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from lumen_core.database import SessionLocal
from lumen_main import app
from lumen_models.agent import Agent
from lumen_models.chat import Conversation, Message as MessageModel
from lumen_models.external_app import ExternalApp, ExternalVisitor
from lumen_models.tenant import Tenant
from lumen_scripts.seed_external_app import seed_dev_external_app
from lumen_services.external_auth_service import create_external_token


# CRITICAL: without this fixture, the next migration test (e.g.
# test_database_migrations.py::test_ensure_conversations_user_id_nullable_is_idempotent)
# hangs at the MODIFY COLUMN for ~50s because leaked Session objects
# hold the InnoDB metadata lock on `conversations`. The fixture forces
# the orphaned Sessions to finalize (returning their connections to
# the pool), then disposes the engine to close checked-in connections.
# See MEMORY.md "TestClient + MDL deadlock" for full diagnosis.
@pytest.fixture(autouse=True)
def _dispose_engine_after_test():
    yield
    from lumen_core.database import engine
    import gc
    gc.collect()
    engine.dispose()


def _setup(allow_team_id: int | None = None):
    """Create a tenant-aligned dev app + agent + visitor.

    Returns a tuple of plain ints/strings (NOT ORM instances) so the
    caller can use them after the local Session closes — the agents
    would otherwise become detached and raise DetachedInstanceError on
    attribute access.

    Also wires the new agent into the app's whitelist, because the
    seed sets ``allowed_agent_ids=[]`` and the endpoint's whitelist
    gate would otherwise 403 every request.

    Each call uses a fresh UUID-suffixed visitor_id so the (app_id,
    visitor_id) unique constraint is satisfied even when the dev DB
    has rows from prior test runs. We do NOT try to clean up the
    pre-existing visitors because the FK from
    ``conversations.external_visitor_id`` blocks ON DELETE — leaving
    stale rows is the right trade-off; these tests intentionally
    pollute the dev DB and the dev DB is single-tenant.
    """
    seed_dev_external_app()
    db: Session = SessionLocal()
    try:
        t = db.query(Tenant).first()
        ext_app = db.query(ExternalApp).filter(
            ExternalApp.app_key == "lc_pub_dev_demo_only_replace_in_prod"
        ).first()
        ext_app.tenant_id = t.id  # align
        # Wipe rate-limit state by using a fresh app_id-based bucket
        a = Agent(
            name="ext-agent-e2e", prompt_template="p",
            model_name="qwen2.5:7b", temperature=0,
            tenant_id=t.id, is_active=True,
        )
        db.add(a)
        db.commit()
        db.refresh(a)
        ext_app.allowed_agent_ids = [a.id]
        # Optionally also whitelist a team — needed by the
        # "both agent_id and team_id" test which expects the endpoint
        # to reach the mutually-exclusive check (400) rather than the
        # team-whitelist gate (403).
        ext_app.allowed_team_ids = [allow_team_id] if allow_team_id is not None else []
        db.commit()
        # Unique visitor per call (uuid4 -> "vis-e2e-<short-uuid>")
        visitor_uuid = f"vis-e2e-{uuid.uuid4().hex[:12]}"
        v = ExternalVisitor(
            app_id=ext_app.id, visitor_id=visitor_uuid,
            first_seen_at=datetime.utcnow(), last_seen_at=datetime.utcnow(),
        )
        db.add(v)
        db.commit()
        db.refresh(v)
        return ext_app.id, ext_app.tenant_id, a.id, v.id, v.visitor_id
    finally:
        db.close()


def _token(app_id, tenant_id, agent_id, visitor_id, visitor_uuid, teams):
    return create_external_token({
        "app_id": app_id, "tenant_id": tenant_id,
        "visitor_id": visitor_id, "visitor_uuid": visitor_uuid,
        "allowed_agent_ids": [agent_id], "allowed_team_ids": teams,
        "scopes": ["chat:stream"],
    })


def test_chat_stream_e2e():
    app_id, tenant_id, agent_id, visitor_id, visitor_uuid = _setup()
    token = _token(app_id, tenant_id, agent_id, visitor_id, visitor_uuid, teams=[])

    # Mock the LLM stream
    from lumen_services.chat_service import ChatService
    async def fake_stream(msgs):
        yield "pong"
    with patch.object(ChatService, "stream_chat_messages", side_effect=fake_stream):
        client = TestClient(app)
        r = client.post(
            "/api/v1/external/chat/stream",
            json={"message": "ping", "agent_id": agent_id},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/event-stream")
    raw = r.text
    # Parse SSE events
    events = []
    for chunk in raw.split("\n\n"):
        chunk = chunk.strip()
        if chunk.startswith("data: "):
            events.append(json.loads(chunk[6:]))
    # 1 content event + 1 done event
    assert any(e.get("content") == "pong" for e in events)
    done = [e for e in events if e.get("done") is True]
    assert len(done) == 1
    assert done[0]["conversation_id"] > 0

    # DB assertion — find the conversation that the endpoint just
    # created (filter by visitor AND app, not just app, because the dev
    # DB is shared and previous test runs may have left stale rows
    # with a different visitor_id).
    db = SessionLocal()
    try:
        conv = (
            db.query(Conversation)
            .filter(
                Conversation.external_app_id == app_id,
                Conversation.external_visitor_id == visitor_id,
            )
            .order_by(Conversation.id.desc())
            .first()
        )
        assert conv is not None
        assert conv.user_id is None
        assert conv.external_visitor_id == visitor_id
        msgs = db.query(MessageModel).filter(
            MessageModel.conversation_id == conv.id
        ).all()
        assert len(msgs) == 2
    finally:
        db.close()


def test_chat_stream_rejects_agent_not_in_whitelist():
    app_id, tenant_id, agent_id, visitor_id, visitor_uuid = _setup()
    other_agent_id = agent_id + 9999  # not in whitelist
    token = _token(app_id, tenant_id, agent_id, visitor_id, visitor_uuid, teams=[])
    client = TestClient(app)
    r = client.post(
        "/api/v1/external/chat/stream",
        json={"message": "x", "agent_id": other_agent_id},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 403


def test_chat_stream_rejects_both_agent_and_team():
    # Whitelist team 1 so the endpoint reaches the mutually-exclusive
    # check (400) instead of the team-whitelist gate (403).
    app_id, tenant_id, agent_id, visitor_id, visitor_uuid = _setup(allow_team_id=1)
    token = _token(app_id, tenant_id, agent_id, visitor_id, visitor_uuid, teams=[1])
    client = TestClient(app)
    r = client.post(
        "/api/v1/external/chat/stream",
        json={"message": "x", "agent_id": agent_id, "team_id": 1},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 400


def test_chat_stream_falls_back_to_first_whitelisted_agent():
    """No agent_id supplied — server picks allowed_agents[0]."""
    app_id, tenant_id, agent_id, visitor_id, visitor_uuid = _setup()
    token = _token(app_id, tenant_id, agent_id, visitor_id, visitor_uuid, teams=[])
    from lumen_services.chat_service import ChatService
    async def fake_stream(msgs):
        yield "ok"
    with patch.object(ChatService, "stream_chat_messages", side_effect=fake_stream):
        client = TestClient(app)
        r = client.post(
            "/api/v1/external/chat/stream",
            json={"message": "hi"},  # no agent_id
            headers={"Authorization": f"Bearer {token}"},
        )
    assert r.status_code == 200
    assert "ok" in r.text
