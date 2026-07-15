"""SSE endpoint tests for ``POST /api/v1/agent-teams/{id}/chat/stream``.

Complements ``tests/unit/test_agent_team_chat_history.py`` (which tests
the non-streaming endpoint end-to-end). These tests pin down the SSE
behaviour:

  - Event sequence matches the 5 graph nodes (plus done)
  - Each event payload includes the right delta + trace_id
  - ``event: done`` carries final_answer + conversation_id
  - Error path emits ``event: error`` instead of raising 500
  - All events under one request share the same trace_id
  - Multi-worker path runs aggregate and synthesizes a final answer
"""
import json
import os
import sys
import uuid
from typing import List
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# Make backend/ importable when pytest is run from the project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

# Transitive SQLAlchemy imports — required so the FK targets of the
# ``conversations`` table resolve when the request is handled. Mirror
# of test_agent_team_state_graph.py and app/main.py:35.
from lumen_models.external_app import ExternalApp, ExternalVisitor  # noqa: F401


# ---------------------------------------------------------------------------
# SSE parser
# ---------------------------------------------------------------------------

def _parse_sse_events(text: str) -> List[dict]:
    """Parse raw SSE response text into [{event, data}, ...] dicts.

    Only handles the shape we emit — one event per blank line, with
    exactly one ``event:`` line and one ``data:`` line per event. We
    don't need to support SSE comments (``id:`` / ``retry:`` etc).
    """
    events: List[dict] = []
    cur_event: str | None = None
    cur_data_lines: List[str] = []
    for line in text.splitlines():
        if line.startswith("event: "):
            if cur_event is not None and cur_data_lines:
                events.append({
                    "event": cur_event,
                    "data": json.loads("\n".join(cur_data_lines)),
                })
            cur_event = line[len("event: "):]
            cur_data_lines = []
        elif line.startswith("data: "):
            cur_data_lines.append(line[len("data: "):])
        elif line == "":
            if cur_event is not None and cur_data_lines:
                events.append({
                    "event": cur_event,
                    "data": json.loads("\n".join(cur_data_lines)),
                })
                cur_event = None
                cur_data_lines = []
    # Trailing event without blank line
    if cur_event is not None and cur_data_lines:
        events.append({
            "event": cur_event,
            "data": json.loads("\n".join(cur_data_lines)),
        })
    return events


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def client():
    """FastAPI TestClient for the live app. Pattern mirrors
    test_agent_team_chat_history.py.
    """
    from lumen_main import app
    return TestClient(app)


@pytest.fixture
def auth_header(tmp_user):
    """Bearer token for the tmp_user created by the conftest fixture.

    Mirrors the helper in test_agent_team_chat_history.py so the SSE
    endpoint can resolve the same ``current_user`` instance.
    """
    from lumen_services.auth_service import create_access_token
    token = create_access_token(
        data={"sub": tmp_user.username, "user_id": tmp_user.id}
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def team_setup():
    """Create a team with manager + 2 worker agents, bound to tenant 1.

    Same pattern as test_agent_team_state_graph.py — see that file for
    the rationale around the ``external_app`` transitive import and the
    use of ``SessionLocal()`` directly (no ``db_session`` fixture in
    conftest).
    """
    from lumen_core.database import SessionLocal
    from lumen_models.agent import Agent
    from lumen_models.agent_team import AgentTeam, AgentTeamMember

    db = SessionLocal()
    manager = worker_a = worker_b = team = ma = mb = None
    try:
        suffix = uuid.uuid4().hex[:8]
        manager = Agent(
            name=f"manager-{suffix}", description="team manager",
            prompt_template="You manage.", model_name="qwen2.5:0.5b",
            tenant_id=1, is_active=True,
        )
        worker_a = Agent(
            name=f"worker-a-{suffix}", description="worker A",
            prompt_template="You are A.", model_name="qwen2.5:0.5b",
            tenant_id=1, is_active=True,
        )
        worker_b = Agent(
            name=f"worker-b-{suffix}", description="worker B",
            prompt_template="You are B.", model_name="qwen2.5:0.5b",
            tenant_id=1, is_active=True,
        )
        db.add_all([manager, worker_a, worker_b])
        db.commit()
        for a in (manager, worker_a, worker_b):
            db.refresh(a)

        team = AgentTeam(
            name=f"team-{suffix}", description="SSE test team",
            manager_agent_id=manager.id, tenant_id=1, is_active=True,
            route_policy="manager_decides",
        )
        db.add(team); db.commit(); db.refresh(team)

        ma = AgentTeamMember(
            team_id=team.id, agent_id=worker_a.id, role="a", is_active=True,
        )
        mb = AgentTeamMember(
            team_id=team.id, agent_id=worker_b.id, role="b", is_active=True,
        )
        db.add_all([ma, mb]); db.commit()
        for m in (ma, mb):
            db.refresh(m)

        yield {
            "team": team, "manager": manager,
            "worker_a": worker_a, "worker_b": worker_b,
            "member_a": ma, "member_b": mb,
        }
    finally:
        try:
            if ma and mb and team:
                db.query(AgentTeamMember).filter(
                    AgentTeamMember.team_id == team.id
                ).delete()
                db.delete(team)
            if manager and worker_a and worker_b:
                for a in (manager, worker_a, worker_b):
                    db.delete(a)
            db.commit()
        except Exception:
            db.rollback()
        finally:
            db.close()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_sse_endpoint_streams_event_sequence(client, auth_header, team_setup):
    """5 node events + done event in the right order, error event absent."""
    with patch("lumen_services.agents.state_graph.ManagerDecider") as MockDecider:
        MockDecider.return_value.ask.return_value = MagicMock(
            chosen_agent_ids=[team_setup["worker_a"].id],
            reasoning="only A", aggregator_prompt=None,
        )
        with patch("lumen_services.agents.state_graph.AgentService") as MockSvc:
            MockSvc.return_value.chat.return_value = "stub"

            resp = client.post(
                f"/api/v1/agent-teams/{team_setup['team'].id}/chat/stream",
                json={"message": "hello"},
                headers=auth_header,
            )
    assert resp.status_code == 200
    events = _parse_sse_events(resp.text)
    event_names = [e["event"] for e in events]
    # Expected node events
    assert "load_context" in event_names
    assert "decide_routing" in event_names
    assert "run_worker" in event_names
    assert "persist" in event_names
    assert "done" in event_names
    # Done should be the last event
    assert event_names[-1] == "done"
    # No error event on the happy path
    assert "error" not in event_names


def test_sse_event_load_context_has_conversation_id(client, auth_header, team_setup):
    """load_context event payload contains conversation_id + workers_count."""
    with patch("lumen_services.agents.state_graph.ManagerDecider") as MockDecider:
        MockDecider.return_value.ask.return_value = MagicMock(
            chosen_agent_ids=[team_setup["worker_a"].id],
            reasoning="only A", aggregator_prompt=None,
        )
        with patch("lumen_services.agents.state_graph.AgentService") as MockSvc:
            MockSvc.return_value.chat.return_value = "stub"
            resp = client.post(
                f"/api/v1/agent-teams/{team_setup['team'].id}/chat/stream",
                json={"message": "hi"},
                headers=auth_header,
            )
    events = _parse_sse_events(resp.text)
    load_ctx = next(e for e in events if e["event"] == "load_context")
    assert load_ctx["data"]["conversation_id"] > 0
    assert load_ctx["data"]["workers_count"] == 2


def test_sse_event_decide_routing_has_policy_and_chosen_count(client, auth_header, team_setup):
    """decide_routing event payload contains policy + chosen_count + reasoning."""
    with patch("lumen_services.agents.state_graph.ManagerDecider") as MockDecider:
        MockDecider.return_value.ask.return_value = MagicMock(
            chosen_agent_ids=[team_setup["worker_a"].id],
            reasoning="only A", aggregator_prompt=None,
        )
        with patch("lumen_services.agents.state_graph.AgentService") as MockSvc:
            MockSvc.return_value.chat.return_value = "stub"
            resp = client.post(
                f"/api/v1/agent-teams/{team_setup['team'].id}/chat/stream",
                json={"message": "hi"},
                headers=auth_header,
            )
    events = _parse_sse_events(resp.text)
    dr = next(e for e in events if e["event"] == "decide_routing")
    assert dr["data"]["policy"] == "manager_decides"
    assert dr["data"]["chosen_count"] == 1
    assert dr["data"]["manager_reasoning"] == "only A"


def test_sse_event_run_worker_per_member(client, auth_header, team_setup):
    """N workers chosen → N run_worker events (one per Send API invocation)."""
    with patch("lumen_services.agents.state_graph.ManagerDecider") as MockDecider:
        MockDecider.return_value.ask.return_value = MagicMock(
            chosen_agent_ids=[
                team_setup["worker_a"].id, team_setup["worker_b"].id
            ],
            reasoning="both", aggregator_prompt=None,
        )
        with patch("lumen_services.agents.state_graph.AgentService") as MockSvc:
            MockSvc.return_value.chat.side_effect = ["A", "B", "synth"]
            resp = client.post(
                f"/api/v1/agent-teams/{team_setup['team'].id}/chat/stream",
                json={"message": "hi"},
                headers=auth_header,
            )
    events = _parse_sse_events(resp.text)
    rw_events = [e for e in events if e["event"] == "run_worker"]
    assert len(rw_events) == 2
    # Each carries the right agent_id
    agent_ids = {e["data"]["agent_id"] for e in rw_events}
    assert agent_ids == {
        team_setup["worker_a"].id, team_setup["worker_b"].id
    }


def test_sse_event_persist_has_routing_decision(client, auth_header, team_setup):
    """persist event payload contains routing_decision list + final_answer."""
    with patch("lumen_services.agents.state_graph.ManagerDecider") as MockDecider:
        MockDecider.return_value.ask.return_value = MagicMock(
            chosen_agent_ids=[team_setup["worker_a"].id],
            reasoning="only A", aggregator_prompt=None,
        )
        with patch("lumen_services.agents.state_graph.AgentService") as MockSvc:
            MockSvc.return_value.chat.return_value = "stub"
            resp = client.post(
                f"/api/v1/agent-teams/{team_setup['team'].id}/chat/stream",
                json={"message": "hi"},
                headers=auth_header,
            )
    events = _parse_sse_events(resp.text)
    persist = next(e for e in events if e["event"] == "persist")
    assert persist["data"]["routing_decision"] == [team_setup["worker_a"].id]
    assert "final_answer" in persist["data"]


def test_sse_event_done_has_final_answer(client, auth_header, team_setup):
    """done event payload carries final_answer + conversation_id."""
    with patch("lumen_services.agents.state_graph.ManagerDecider") as MockDecider:
        MockDecider.return_value.ask.return_value = MagicMock(
            chosen_agent_ids=[team_setup["worker_a"].id],
            reasoning="only A", aggregator_prompt=None,
        )
        with patch("lumen_services.agents.state_graph.AgentService") as MockSvc:
            MockSvc.return_value.chat.return_value = "the final answer"
            resp = client.post(
                f"/api/v1/agent-teams/{team_setup['team'].id}/chat/stream",
                json={"message": "hi"},
                headers=auth_header,
            )
    events = _parse_sse_events(resp.text)
    done = next(e for e in events if e["event"] == "done")
    assert done["data"]["final_answer"] == "the final answer"
    assert done["data"]["conversation_id"] > 0


def test_sse_event_error_on_invalid_team(client, auth_header):
    """Non-existent team → error event (no 500 raise)."""
    resp = client.post(
        "/api/v1/agent-teams/999999/chat/stream",
        json={"message": "hi"},
                headers=auth_header,
    )
    assert resp.status_code == 200  # SSE stream is 200; error in payload
    events = _parse_sse_events(resp.text)
    error_events = [e for e in events if e["event"] == "error"]
    assert len(error_events) == 1
    assert "Team not found" in error_events[0]["data"]["error"]


def test_sse_each_event_has_trace_id(client, auth_header, team_setup):
    """Every event payload under one request shares the same trace_id."""
    with patch("lumen_services.agents.state_graph.ManagerDecider") as MockDecider:
        MockDecider.return_value.ask.return_value = MagicMock(
            chosen_agent_ids=[team_setup["worker_a"].id],
            reasoning="only A", aggregator_prompt=None,
        )
        with patch("lumen_services.agents.state_graph.AgentService") as MockSvc:
            MockSvc.return_value.chat.return_value = "stub"
            resp = client.post(
                f"/api/v1/agent-teams/{team_setup['team'].id}/chat/stream",
                json={"message": "hi"},
                headers=auth_header,
            )
    events = _parse_sse_events(resp.text)
    trace_ids = {e["data"].get("trace_id") for e in events}
    # All events share the same trace_id
    assert len(trace_ids) == 1
    assert None not in trace_ids
    # And it's a valid UUID string
    uuid.UUID(next(iter(trace_ids)))


def test_sse_final_answer_synthesized_for_multiple_workers(client, auth_header, team_setup):
    """>1 worker → aggregate runs → final_answer is the manager-synthesized text."""
    with patch("lumen_services.agents.state_graph.ManagerDecider") as MockDecider:
        MockDecider.return_value.ask.return_value = MagicMock(
            chosen_agent_ids=[
                team_setup["worker_a"].id, team_setup["worker_b"].id
            ],
            reasoning="both", aggregator_prompt=None,
        )
        with patch("lumen_services.agents.state_graph.AgentService") as MockSvc:
            # worker A, worker B, aggregate manager
            MockSvc.return_value.chat.side_effect = [
                "A's answer", "B's answer", "Synthesized final",
            ]
            resp = client.post(
                f"/api/v1/agent-teams/{team_setup['team'].id}/chat/stream",
                json={"message": "hi"},
                headers=auth_header,
            )
    events = _parse_sse_events(resp.text)
    done = next(e for e in events if e["event"] == "done")
    # final_answer is the synthesized text (last AgentService.chat call)
    assert done["data"]["final_answer"] == "Synthesized final"
    # aggregate event also carries a preview
    agg = next(e for e in events if e["event"] == "aggregate")
    assert "Synthesized" in agg["data"]["final_answer_preview"]
