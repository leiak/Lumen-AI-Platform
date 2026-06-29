"""Happy-path tests for the team chat history feature.

Covers:
  - POST /agent-teams/{team_id}/chat creates a new conversation on the
    first turn and persists user + assistant messages.
  - A second turn with the same conversation_id reuses the row and
    grows the message count to 4.
  - GET /agent-teams/{team_id}/conversations filters by (team, user,
    tenant) and hides soft-deleted rows.
  - GET .../messages returns the assistant message with
    `msg_metadata` deserializable into the worker-output shape.
  - DELETE .../conversations/{id} sets deleted_at and the row is
    filtered out of the list (but remains in the DB).
  - Sending a chat with a conversation_id from a different team
    returns 400 (ownership / binding check).

Scope is intentionally happy-path. Concurrent writes, worker
failure rollback, and cross-tenant isolation are NOT covered here
(the latter is enforced by the standard `tenant_id` filter on every
query but no dedicated test is added in this PR).
"""
from __future__ import annotations

import json
import os
import sys
import uuid
from typing import List
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

# Make backend/ importable when pytest is run from the project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

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


def _make_agent(
    db: Session, *, tenant_id: int, name: str, prompt: str = "you are a helper"
):
    from lumen_models.agent import Agent
    a = Agent(
        name=name,
        prompt_template=prompt,
        model_name="qwen2.5:7b",
        temperature=0,
        tenant_id=tenant_id,
        is_active=True,
    )
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


def _make_team(
    db: Session,
    *,
    tenant_id: int,
    manager: "Agent",
    members: List["Agent"],
    name: str = "test team",
    route_policy: str = "round_robin",
):
    """Create an AgentTeam with a manager + given members."""
    from lumen_models.agent_team import AgentTeam, AgentTeamMember
    team = AgentTeam(
        name=name,
        description="",
        manager_agent_id=manager.id,
        tenant_id=tenant_id,
        is_active=True,
        route_policy=route_policy,
    )
    db.add(team)
    db.commit()
    db.refresh(team)
    for m in members:
        db.add(AgentTeamMember(team_id=team.id, agent_id=m.id, role="worker", priority=100, is_active=True))
    db.commit()
    db.refresh(team)
    return team


@pytest.fixture
def team_with_members(tmp_user):
    """Manager agent + 1 worker agent + 1 team (round_robin).

    Teardown deletes the team / members / agents + any conversations
    the test created against this team, so dev DB doesn't accumulate
    "hello team" pollution across runs. Mirrors the pattern in
    test_agent_team_logs_call.py::team_setup.

    NOTE: the teardown opens a *fresh* SessionLocal(). Reusing the
    setup session would put MySQL InnoDB into REPEATABLE READ on the
    snapshot taken at the start of the first query — and the conv
    written by the API call (in a different session) would be
    invisible. Open a new session to see all committed data.
    """
    from lumen_core.database import SessionLocal
    from lumen_models.agent import Agent
    from lumen_models.agent_team import AgentTeam, AgentTeamMember
    from lumen_models.chat import Conversation, Message
    from lumen_models.llm_call_log import LLMCallLog
    from lumen_models.embedding_call_log import EmbeddingCallLog
    from lumen_models.memory import ConversationMemory

    db = SessionLocal()
    manager = worker = team = None
    try:
        manager = _make_agent(db, tenant_id=tmp_user.tenant_id, name="mgr")
        worker = _make_agent(db, tenant_id=tmp_user.tenant_id, name="worker1")
        team = _make_team(
            db,
            tenant_id=tmp_user.tenant_id,
            manager=manager,
            members=[worker],
            name="history test team",
        )
        yield {"team": team, "manager": manager, "worker": worker, "user": tmp_user}
    finally:
        # Capture the IDs we need from the (about-to-be-detached) setup
        # session, then close it. The teardown uses a fresh session so it
        # can see all rows committed by the test (the API call, the
        # state_graph's load_context, etc.).
        team_id = team.id if team is not None else None
        manager_id = manager.id if manager is not None else None
        worker_id = worker.id if worker is not None else None
        try:
            db.close()
        except Exception:
            pass

        if team_id is None and manager_id is None and worker_id is None:
            return

        db = SessionLocal()
        try:
            if team_id is not None:
                conv_ids = [
                    row.id for row in
                    db.query(Conversation.id).filter(Conversation.team_id == team_id).all()
                ]
                if conv_ids:
                    db.query(LLMCallLog).filter(LLMCallLog.conversation_id.in_(conv_ids)).delete(synchronize_session=False)
                    db.query(EmbeddingCallLog).filter(EmbeddingCallLog.conversation_id.in_(conv_ids)).delete(synchronize_session=False)
                    db.query(ConversationMemory).filter(ConversationMemory.conversation_id.in_(conv_ids)).delete(synchronize_session=False)
                    db.query(Message).filter(Message.conversation_id.in_(conv_ids)).delete(synchronize_session=False)
                    db.query(Conversation).filter(Conversation.id.in_(conv_ids)).delete(synchronize_session=False)
                db.query(AgentTeamMember).filter(AgentTeamMember.team_id == team_id).delete(synchronize_session=False)
                db.query(AgentTeam).filter(AgentTeam.id == team_id).delete()
            for aid in (manager_id, worker_id):
                if aid is not None:
                    db.query(Agent).filter(Agent.id == aid).delete()
            db.commit()
        except Exception:
            db.rollback()
        finally:
            db.close()


# ---------------------------------------------------------------------------
# Patch helper — avoid real LLM calls
# ---------------------------------------------------------------------------

def _patch_worker_chat(return_text: str = "ok from worker"):
    """Patch AgentService.chat to a fake so the team run doesn't hit
    Ollama. We patch the symbol that's bound at the import site
    (`app.services.agents.team.AgentService`) — that's what the team
    service actually calls."""
    from lumen_services.agent_service import AgentService

    def fake_chat(self, *, db, agent_id, tenant_id, message, history=None):
        return return_text

    return patch.object(AgentService, "chat", new=fake_chat)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_post_chat_creates_conversation_when_no_id(
    client, auth_header, team_with_members
):
    """First turn without conversation_id: backend creates a new
    team-scoped Conversation and writes user + assistant messages."""
    team = team_with_members["team"]
    db = team_with_members["user"]  # not used; placeholder for type clarity
    from lumen_core.database import SessionLocal
    from lumen_models.chat import Conversation, Message

    with _patch_worker_chat("worker says hi"):
        r = client.post(
            f"/api/v1/agent-teams/{team.id}/chat",
            headers=auth_header,
            json={"message": "hello team", "route_policy": "round_robin"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["code"] == 200
    data = body["data"]
    assert data["final_answer"] == "worker says hi"
    assert isinstance(data["conversation_id"], int)
    conv_id = data["conversation_id"]

    # Verify DB state
    s = SessionLocal()
    try:
        conv = s.query(Conversation).filter(Conversation.id == conv_id).first()
        assert conv is not None
        assert conv.team_id == team.id
        assert conv.user_id == team_with_members["user"].id
        assert conv.title == "hello team"  # first 50 chars

        msgs = (
            s.query(Message)
            .filter(Message.conversation_id == conv_id)
            .order_by(Message.created_at.asc())
            .all()
        )
        assert len(msgs) == 2
        assert msgs[0].role == "user"
        assert msgs[0].content == "hello team"
        assert msgs[1].role == "assistant"
        assert msgs[1].content == "worker says hi"
    finally:
        s.close()


def test_post_chat_with_existing_conv_appends(
    client, auth_header, team_with_members
):
    """Second turn with conversation_id: same conv, 4 messages now."""
    team = team_with_members["team"]
    from lumen_core.database import SessionLocal
    from lumen_models.chat import Message

    # First turn
    with _patch_worker_chat("first reply"):
        r1 = client.post(
            f"/api/v1/agent-teams/{team.id}/chat",
            headers=auth_header,
            json={"message": "first question", "route_policy": "round_robin"},
        )
    assert r1.status_code == 200
    conv_id = r1.json()["data"]["conversation_id"]

    # Second turn reuses the conv
    with _patch_worker_chat("second reply"):
        r2 = client.post(
            f"/api/v1/agent-teams/{team.id}/chat",
            headers=auth_header,
            json={
                "message": "second question",
                "route_policy": "round_robin",
                "conversation_id": conv_id,
            },
        )
    assert r2.status_code == 200
    assert r2.json()["data"]["conversation_id"] == conv_id

    s = SessionLocal()
    try:
        msgs = (
            s.query(Message)
            .filter(Message.conversation_id == conv_id)
            .order_by(Message.created_at.asc())
            .all()
        )
        assert len(msgs) == 4
        assert [m.role for m in msgs] == ["user", "assistant", "user", "assistant"]
        assert [m.content for m in msgs] == [
            "first question",
            "first reply",
            "second question",
            "second reply",
        ]
    finally:
        s.close()


def test_list_conversations_filters_by_team_and_user(
    client, auth_header, team_with_members, tmp_user
):
    """List shows ONLY current user's conversations for THIS team —
    a separate team's conv and a separate user's conv are filtered
    out."""
    from lumen_core.database import SessionLocal
    from lumen_models.chat import Conversation
    from lumen_models.user import User
    from lumen_core.security import get_password_hash

    s = SessionLocal()
    try:
        # 1) A second team with its own conv (same user)
        mgr2 = _make_agent(s, tenant_id=tmp_user.tenant_id, name="mgr2")
        worker2 = _make_agent(s, tenant_id=tmp_user.tenant_id, name="worker2")
        other_team = _make_team(
            s, tenant_id=tmp_user.tenant_id, manager=mgr2, members=[worker2],
            name="other team",
        )
        other_team_conv = Conversation(
            title="other team conv",
            user_id=tmp_user.id,
            tenant_id=tmp_user.tenant_id,
            team_id=other_team.id,
        )
        s.add(other_team_conv)
        s.commit()
        s.refresh(other_team_conv)

        # 2) A different user in the same tenant with a conv in OUR team
        suffix = uuid.uuid4().hex[:8]
        other_user = User(
            username=f"other_user_{suffix}",
            email=f"other_{suffix}@test.local",
            hashed_password=get_password_hash("x"),
            tenant_id=tmp_user.tenant_id,
            is_active=True,
        )
        s.add(other_user)
        s.commit()
        s.refresh(other_user)
        other_user_conv = Conversation(
            title="other user's conv",
            user_id=other_user.id,
            tenant_id=tmp_user.tenant_id,
            team_id=team_with_members["team"].id,
        )
        s.add(other_user_conv)
        s.commit()
        s.refresh(other_user_conv)

        # 3) OUR conv in OUR team
        our_conv = Conversation(
            title="our conv",
            user_id=tmp_user.id,
            tenant_id=tmp_user.tenant_id,
            team_id=team_with_members["team"].id,
        )
        s.add(our_conv)
        s.commit()
        s.refresh(our_conv)

        # Act: list the team's conversations as tmp_user
        r = client.get(
            f"/api/v1/agent-teams/{team_with_members['team'].id}/conversations",
            headers=auth_header,
        )
        assert r.status_code == 200
        body = r.json()
        assert body["code"] == 200
        ids = {c["id"] for c in body["data"]}
        # ours is in, both foreign ones are out
        assert our_conv.id in ids
        assert other_team_conv.id not in ids
        assert other_user_conv.id not in ids
    finally:
        s.close()


def test_get_messages_returns_assistant_metadata(
    client, auth_header, team_with_members
):
    """GET .../messages returns assistant messages with msg_metadata
    deserialized to a dict that contains routing_decision /
    worker_outputs / policy_used."""
    team = team_with_members["team"]
    from lumen_core.database import SessionLocal
    from lumen_models.chat import Message

    with _patch_worker_chat("with meta"):
        r = client.post(
            f"/api/v1/agent-teams/{team.id}/chat",
            headers=auth_header,
            json={"message": "show me the meta", "route_policy": "round_robin"},
        )
    assert r.status_code == 200
    conv_id = r.json()["data"]["conversation_id"]

    r2 = client.get(
        f"/api/v1/agent-teams/{team.id}/conversations/{conv_id}/messages",
        headers=auth_header,
    )
    assert r2.status_code == 200
    msgs = r2.json()["data"]
    assert len(msgs) == 2
    asst = next(m for m in msgs if m["role"] == "assistant")
    # The schema alias maps msg_metadata -> metadata (see schemas/chat.py:33)
    meta = asst.get("metadata")
    assert meta is not None
    assert meta["policy_used"] == "round_robin"
    assert isinstance(meta["routing_decision"], list)
    assert len(meta["worker_outputs"]) >= 1
    # worker_outputs[0] mirrors the WorkerOutput schema
    wo = meta["worker_outputs"][0]
    assert wo["response"] == "with meta"
    assert "agent_id" in wo


def test_delete_team_conversation_soft_deletes(
    client, auth_header, team_with_members
):
    """DELETE sets deleted_at, list filters the row out, but the row
    is still findable in the DB (soft delete, not hard delete)."""
    team = team_with_members["team"]
    from lumen_core.database import SessionLocal
    from lumen_models.chat import Conversation

    s = SessionLocal()
    try:
        conv = Conversation(
            title="to be deleted",
            user_id=team_with_members["user"].id,
            tenant_id=team_with_members["user"].tenant_id,
            team_id=team.id,
        )
        s.add(conv)
        s.commit()
        s.refresh(conv)
        conv_id = conv.id
    finally:
        s.close()

    # Before delete: visible in list
    r1 = client.get(
        f"/api/v1/agent-teams/{team.id}/conversations", headers=auth_header
    )
    assert r1.status_code == 200
    assert conv_id in {c["id"] for c in r1.json()["data"]}

    # Delete
    r_del = client.delete(
        f"/api/v1/agent-teams/{team.id}/conversations/{conv_id}",
        headers=auth_header,
    )
    assert r_del.status_code == 200
    assert r_del.json()["code"] == 200

    # After delete: not in list, but row still exists with deleted_at
    r2 = client.get(
        f"/api/v1/agent-teams/{team.id}/conversations", headers=auth_header
    )
    assert r2.status_code == 200
    assert conv_id not in {c["id"] for c in r2.json()["data"]}

    s = SessionLocal()
    try:
        row = s.query(Conversation).filter(Conversation.id == conv_id).first()
        assert row is not None
        assert row.deleted_at is not None
    finally:
        s.close()


def test_chat_with_conv_id_from_other_team_400(
    client, auth_header, team_with_members, tmp_user
):
    """Using a conversation_id that belongs to a different team
    should be rejected with 400 (the service layer raises ValueError
    which the endpoint maps to 400)."""
    from lumen_core.database import SessionLocal
    from lumen_models.chat import Conversation

    s = SessionLocal()
    try:
        # Build a second team in the same tenant and create a conv there
        mgr2 = _make_agent(s, tenant_id=tmp_user.tenant_id, name="mgr3")
        worker3 = _make_agent(s, tenant_id=tmp_user.tenant_id, name="worker3")
        other_team = _make_team(
            s, tenant_id=tmp_user.tenant_id, manager=mgr2, members=[worker3],
            name="yet another team",
        )
        other_conv = Conversation(
            title="foreign conv",
            user_id=tmp_user.id,
            tenant_id=tmp_user.tenant_id,
            team_id=other_team.id,
        )
        s.add(other_conv)
        s.commit()
        s.refresh(other_conv)
        foreign_id = other_conv.id
    finally:
        s.close()

    # Use foreign conv id while targeting the original team
    team = team_with_members["team"]
    r = client.post(
        f"/api/v1/agent-teams/{team.id}/chat",
        headers=auth_header,
        json={
            "message": "hello",
            "route_policy": "round_robin",
            "conversation_id": foreign_id,
        },
    )
    assert r.status_code == 400
    assert "not bound to this team" in r.json().get("detail", "")
