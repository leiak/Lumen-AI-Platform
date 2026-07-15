"""Tests for binding a Conversation to an optional Agent.

Covers:
  - list endpoint returns agent_name (LEFT JOIN agents)
  - POST /chat/conversations returns agent_name (regression for
    silent-from_attributes drop — see _serialize_conversation helper)
  - PATCH /chat/conversations/{id} binds / unbinds agent
  - PATCH rejects cross-tenant / inactive / other-user
  - PATCH partial body is a no-op
  - stream endpoint auto-resolves agent_id from conv when request omits it
"""
import pytest
from fastapi.testclient import TestClient


# Shared helpers (make_conv, make_agent) live in tests/conftest.py to
# avoid duplicating the same boilerplate across multiple chat test
# modules. The names are public (no leading underscore) so they read
# like normal library functions in the test bodies.
from tests.conftest import make_conv, make_agent, make_team


@pytest.fixture
def client():
    from lumen_main import app
    return TestClient(app)


@pytest.fixture
def auth_header(tmp_user):
    from lumen_services.auth_service import create_access_token
    token = create_access_token(
        data={"sub": tmp_user.username, "user_id": tmp_user.id}
    )
    return {"Authorization": f"Bearer {token}"}


def test_list_conversations_returns_agent_name(client, auth_header, tmp_user):
    """list endpoint joins agents.name for each conv."""
    from lumen_core.database import SessionLocal

    db = SessionLocal()
    try:
        agent = make_agent(db, tenant_id=tmp_user.tenant_id, name="translator")
        make_conv(db, user_id=tmp_user.id, tenant_id=tmp_user.tenant_id,
                  agent_id=agent.id, title="with-agent")
        make_conv(db, user_id=tmp_user.id, tenant_id=tmp_user.tenant_id,
                  agent_id=None, title="default-only")
    finally:
        db.close()

    r = client.get("/api/v1/chat/conversations", headers=auth_header)
    assert r.status_code == 200
    body = r.json()
    assert body["code"] == 200
    by_title = {c["title"]: c for c in body["data"]}
    assert by_title["with-agent"]["agent_id"] is not None
    assert by_title["with-agent"]["agent_name"] == "translator"
    assert by_title["default-only"]["agent_id"] is None
    assert by_title["default-only"]["agent_name"] is None


def test_create_conversation_returns_agent_name(client, auth_header, tmp_user):
    """Regression: POST /chat/conversations previously relied on
    Pydantic from_attributes to bind agent_name from the ORM row, but
    Conversation has no agent_name column → it silently came back None
    even when agent_id was set. POST must fetch the joined agent.name
    and include it in the response.
    """
    from lumen_core.database import SessionLocal

    db = SessionLocal()
    try:
        agent = make_agent(db, tenant_id=tmp_user.tenant_id, name="post-agent")
    finally:
        db.close()

    r = client.post(
        "/api/v1/chat/conversations",
        headers=auth_header,
        json={"title": "hi", "agent_id": agent.id},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["code"] == 200
    assert body["data"]["agent_id"] == agent.id
    assert body["data"]["agent_name"] == "post-agent"


def test_create_conversation_without_agent_returns_none_name(client, auth_header):
    """When agent_id is omitted, the new conv's agent_name is None —
    not a 500 and not a stringified empty value."""
    r = client.post(
        "/api/v1/chat/conversations",
        headers=auth_header,
        json={"title": "plain"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["code"] == 200
    assert body["data"]["agent_id"] is None
    assert body["data"]["agent_name"] is None


def test_update_conversation_binds_agent(client, auth_header, tmp_user):
    """PATCH {agent_id: X} sets conv.agent_id and returns updated row."""
    from lumen_core.database import SessionLocal
    db = SessionLocal()
    try:
        agent = make_agent(db, tenant_id=tmp_user.tenant_id, name="helper")
        # Capture the scalar id BEFORE the session closes; once the
        # session is gone, accessing agent.id raises DetachedInstanceError.
        agent_id = agent.id
        conv = make_conv(db, user_id=tmp_user.id, tenant_id=tmp_user.tenant_id)
    finally:
        db.close()

    r = client.patch(
        f"/api/v1/chat/conversations/{conv.id}",
        json={"agent_id": agent_id},
        headers=auth_header,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["code"] == 200
    assert body["data"]["agent_id"] == agent_id
    assert body["data"]["agent_name"] == "helper"


def test_update_conversation_unbinds_with_null(client, auth_header, tmp_user):
    """PATCH {agent_id: null} clears conv.agent_id (back to default)."""
    from lumen_core.database import SessionLocal
    db = SessionLocal()
    try:
        agent = make_agent(db, tenant_id=tmp_user.tenant_id)
        conv = make_conv(db, user_id=tmp_user.id, tenant_id=tmp_user.tenant_id, agent_id=agent.id)
    finally:
        db.close()

    r = client.patch(
        f"/api/v1/chat/conversations/{conv.id}",
        json={"agent_id": None},
        headers=auth_header,
    )
    assert r.status_code == 200
    assert r.json()["data"]["agent_id"] is None
    assert r.json()["data"]["agent_name"] is None


def test_update_conversation_rejects_other_tenant_agent(client, auth_header, tmp_user):
    """PATCH cannot bind an agent from a different tenant (404)."""
    from lumen_core.database import SessionLocal
    from lumen_models.tenant import Tenant
    db = SessionLocal()
    try:
        # Create a separate tenant + agent
        other_tenant = Tenant(name="other-tenant", code=f"other-{tmp_user.id}")
        db.add(other_tenant)
        db.commit()
        db.refresh(other_tenant)
        other_agent = make_agent(db, tenant_id=other_tenant.id, name="cross-tenant")
        # Capture the scalar id BEFORE the session closes; once the
        # session is gone, accessing other_agent.id raises DetachedInstanceError.
        other_agent_id = other_agent.id
        conv = make_conv(db, user_id=tmp_user.id, tenant_id=tmp_user.tenant_id)
    finally:
        db.close()

    r = client.patch(
        f"/api/v1/chat/conversations/{conv.id}",
        json={"agent_id": other_agent_id},
        headers=auth_header,
    )
    assert r.status_code == 404


def test_update_conversation_rejects_inactive_agent(client, auth_header, tmp_user):
    """PATCH rejects agents with is_active=False (404)."""
    from lumen_core.database import SessionLocal
    db = SessionLocal()
    try:
        agent = make_agent(db, tenant_id=tmp_user.tenant_id, is_active=False, name="off")
        # Capture the scalar id BEFORE the session closes; once the
        # session is gone, accessing agent.id raises DetachedInstanceError.
        agent_id = agent.id
        conv = make_conv(db, user_id=tmp_user.id, tenant_id=tmp_user.tenant_id)
    finally:
        db.close()

    r = client.patch(
        f"/api/v1/chat/conversations/{conv.id}",
        json={"agent_id": agent_id},
        headers=auth_header,
    )
    assert r.status_code == 404


def test_update_conversation_rejects_other_users_conv(client, tmp_user):
    """User A cannot patch user B's conversation (404 via verify_conversation)."""
    import uuid as _uuid
    from lumen_core.database import SessionLocal
    from lumen_models.user import User
    from lumen_services.auth_service import create_access_token

    db = SessionLocal()
    try:
        suffix = _uuid.uuid4().hex[:8]
        other = User(
            username=f"other_{suffix}", email=f"other_{suffix}@x.com",
            hashed_password="x", tenant_id=tmp_user.tenant_id, is_active=True,
        )
        db.add(other); db.commit(); db.refresh(other)
        conv = make_conv(db, user_id=other.id, tenant_id=tmp_user.tenant_id)
        token = create_access_token(data={"sub": tmp_user.username, "user_id": tmp_user.id})
    finally:
        db.close()

    r = client.patch(
        f"/api/v1/chat/conversations/{conv.id}",
        json={"agent_id": None},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 404


def test_update_conversation_empty_body_clears_agent_id(client, auth_header, tmp_user):
    """PATCH with empty body returns the current conv state (Pydantic default
    is None for Optional fields, so the endpoint clears agent_id; we just
    verify response shape is correct and the row is consistent)."""
    from lumen_core.database import SessionLocal
    db = SessionLocal()
    try:
        agent = make_agent(db, tenant_id=tmp_user.tenant_id, name="present")
        conv = make_conv(db, user_id=tmp_user.id, tenant_id=tmp_user.tenant_id, agent_id=agent.id)
    finally:
        db.close()

    # Send empty body — Pydantic will default agent_id=None; the test
    # documents the current behaviour: empty body == explicit null == clear.
    # If we ever want to distinguish, change to a sentinel (see spec §6).
    r = client.patch(
        f"/api/v1/chat/conversations/{conv.id}",
        json={},
        headers=auth_header,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["code"] == 200
    # Documented in spec: empty body clears agent_id (Pydantic default)
    assert body["data"]["agent_id"] is None


def test_update_conversation_rejects_agent_when_team_bound(client, auth_header, tmp_user):
    """M30 P1-5: per spec §6 risk #3, conversations are bound to EITHER
    an agent OR a team, never both. PATCH /conversations/{id} on a
    team-bound conv must 409 rather than silently create a mixed-mode
    row. Uses the new ``make_team`` helper to create a real team row
    (the conversations.team_id FK enforces it)."""
    from lumen_core.database import SessionLocal, engine
    from sqlalchemy import text as _text

    db = SessionLocal()
    try:
        agent = make_agent(db, tenant_id=tmp_user.tenant_id, name="x-agt")
        team = make_team(db, tenant_id=tmp_user.tenant_id, name="x-team")
        # Capture ids before closing the session so we don't hit a
        # DetachedInstanceError reading .id afterwards.
        agent_id = agent.id
        team_id = team.id
        conv = make_conv(db, user_id=tmp_user.id, tenant_id=tmp_user.tenant_id)
        conv_id = conv.id
    finally:
        db.close()

    with engine.begin() as conn:
        conn.execute(
            _text("UPDATE conversations SET team_id = :tid WHERE id = :id"),
            {"tid": team_id, "id": conv_id},
        )

    token = auth_header
    r = client.patch(
        f"/api/v1/chat/conversations/{conv_id}",
        json={"agent_id": agent_id},
        headers=token,
    )
    assert r.status_code == 409, r.text
    assert "team" in r.json()["detail"].lower()


def test_update_conversation_team_bound_can_clear_agent_id(client, auth_header, tmp_user):
    """M30 P1-5: PATCH {agent_id: null} (clearing) on a team-bound conv
    is still allowed — the conv stays team-bound, just with no
    override agent. The guard only rejects the dual-binding direction
    (setting agent on a team-bound conv)."""
    from lumen_core.database import SessionLocal, engine
    from sqlalchemy import text as _text

    db = SessionLocal()
    try:
        agent = make_agent(db, tenant_id=tmp_user.tenant_id, name="x2-agt")
        team = make_team(db, tenant_id=tmp_user.tenant_id, name="x2-team")
        conv = make_conv(db, user_id=tmp_user.id, tenant_id=tmp_user.tenant_id, agent_id=agent.id)
        agent_id = agent.id
        team_id = team.id
        conv_id = conv.id
    finally:
        db.close()

    with engine.begin() as conn:
        conn.execute(
            _text("UPDATE conversations SET team_id = :tid WHERE id = :id"),
            {"tid": team_id, "id": conv_id},
        )

    token = auth_header
    r = client.patch(
        f"/api/v1/chat/conversations/{conv_id}",
        json={"agent_id": None},
        headers=token,
    )
    # Pydantic sets agent_id=None on the row (default), no exception
    # should fire — the conv remains team-bound.
    assert r.status_code == 200, r.text
    with engine.connect() as conn:
        row = conn.execute(
            _text("SELECT team_id FROM conversations WHERE id = :id"),
            {"id": conv_id},
        ).fetchone()
        assert row[0] == team_id


def test_stream_auto_resolves_agent_from_conversation(client, auth_header, tmp_user):
    """When request.agent_id is None but conv.agent_id is set, the stream
    endpoint must load the agent's model and use it (not fall through to
    the default model config)."""
    from lumen_core.database import SessionLocal
    from unittest.mock import patch

    db = SessionLocal()
    try:
        agent = make_agent(
            db, tenant_id=tmp_user.tenant_id, name="auto-resolver",
            model_name="auto-resolved-model-xyz",
        )
        conv = make_conv(
            db, user_id=tmp_user.id, tenant_id=tmp_user.tenant_id,
            agent_id=agent.id, title="auto",
        )
    finally:
        db.close()

    # Patch ChatService.set_model to record the kwargs it gets called with,
    # and patch stream_chat_messages to return a fake async generator so
    # the SSE loop terminates quickly.
    captured: dict = {}

    class FakeService:
        def set_model(self, **kwargs):
            captured.update(kwargs)
        async def stream_chat_messages(self, messages):
            for chunk in ["hello"]:
                yield chunk

    with patch("lumen_api.v1.chat.ChatService", return_value=FakeService()):
        # agent_id omitted; conversation_id provided
        r = client.post(
            "/api/v1/chat/stream",
            json={"message": "hi", "conversation_id": conv.id, "stream": True},
            headers=auth_header,
        )

    assert r.status_code == 200
    # The auto-resolved model_name should be the agent's, NOT the default
    assert captured.get("model_name") == "auto-resolved-model-xyz", (
        f"expected auto-resolved agent's model, got {captured}"
    )
