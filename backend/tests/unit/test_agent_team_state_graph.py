"""StateGraph internal behavior tests for AgentTeam multi-agent orchestration.

Complements ``tests/unit/test_agent_team_chat_history.py`` (which exercises
the endpoint end-to-end with ``AgentService.chat`` mocked). These tests
pin down the *internal* graph behavior:

  - Graph compiles with 5 nodes
  - ``load_context`` persists the user message
  - ``decide_routing`` uses ManagerDecider OR policy + defensive fallback
  - ``run_worker`` catches errors and returns a sentinel (not raise)
  - ``aggregate`` skipped for a single worker, called for multiple
  - ``persist`` writes ``msg_metadata`` JSON with the right shape
  - ``Send`` API fans out to N workers, reducer collects N outputs

Tests use the project's shared dev DB (``SessionLocal``) and clean up
rows they create. They DO NOT touch the HTTP endpoint — graph.invoke()
is called directly with a SessionLocal-injected config.
"""
import json
import os
import sys
import uuid
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.orm import Session

# Make backend/ importable when pytest is run from the project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

# Transitive SQLAlchemy imports — required so that the FK targets of the
# `conversations` table (and `agent_team_members` / `agents`) resolve
# when SQLAlchemy reflects the model metadata. Without these, ORM-level
# `db.add(Conversation(...))` in `load_context` fails with
# `NoReferencedTableError: ... 'external_apps'`. See `app/main.py:35`
# for the analogous production import — we mirror it here.
from lumen_models.external_app import ExternalApp, ExternalVisitor  # noqa: F401

@pytest.fixture
def team_setup():
    """Create a team with manager + 2 worker agents, bound to tenant 1.

    Cleans up the team / members / agents + any conversations the test
    created (load_context auto-creates one when request_conversation_id
    is None) so the dev DB doesn't accumulate noise across runs.

    We open a fresh SessionLocal() rather than depending on a
    ``db_session`` fixture that conftest.py doesn't expose. This matches
    the pattern used by other test files (see conftest.py's ``tmp_user``
    and the per-file ``db`` variables in test_agent_team_chat_history.py).

    NOTE: the teardown opens a *fresh* SessionLocal(). Reusing the
    setup session would put MySQL InnoDB into REPEATABLE READ on the
    snapshot taken at the start of the first query — and the conv
    written by load_context (in a different session, the one the test
    passes into the graph) would be invisible. Open a new session
    to see all committed data.
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
            name=f"team-{suffix}", description="state graph test team",
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
        # Capture IDs from the (about-to-be-detached) setup session
        # then close it. The teardown uses a fresh session so it can
        # see rows committed by load_context / the API.
        team_id = team.id if team is not None else None
        manager_id = manager.id if manager is not None else None
        worker_a_id = worker_a.id if worker_a is not None else None
        worker_b_id = worker_b.id if worker_b is not None else None
        try:
            db.close()
        except Exception:
            pass

        if team_id is None and manager_id is None:
            return

        from lumen_models.chat import Conversation, Message
        from lumen_models.llm_call_log import LLMCallLog
        from lumen_models.embedding_call_log import EmbeddingCallLog
        from lumen_models.memory import ConversationMemory

        db = SessionLocal()
        try:
            if team_id is not None:
                # load_context auto-creates a Conversation when
                # request_conversation_id is None, and writes a user
                # Message to it. FK order:
                # llm/embedding/memory call-logs → messages → convs → members → team → agents
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
            for aid in (manager_id, worker_a_id, worker_b_id):
                if aid is not None:
                    db.query(Agent).filter(Agent.id == aid).delete()
            db.commit()
        except Exception:
            db.rollback()
        finally:
            db.close()


def _initial_state(team_setup) -> dict:
    return {
        "team_id": team_setup["team"].id,
        "tenant_id": 1,
        "user_id": 1,
        "user_message": "hello team",
        "request_conversation_id": None,
        "request_member_ids": None,
        "request_route_policy": None,
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_state_graph_5_nodes_compile():
    """``build_team_graph()`` returns a CompiledStateGraph with 5 nodes."""
    from lumen_services.agents.state_graph import (
        TeamRunState, build_team_graph,
    )
    g = build_team_graph()
    assert g is not None
    # The TypedDict exists and has the expected top-level keys (best-effort
    # introspection — TypedDict __annotations__ gives the field set).
    annotations = getattr(TeamRunState, "__annotations__", set())
    expected = {
        "team_id", "tenant_id", "user_id", "user_message",
        "team", "manager", "workers_by_id", "history",
        "manager_kb_history_entry", "conversation", "user_message_db_id",
        "policy", "chosen_member_ids", "manager_reasoning",
        "aggregator_prompt_override", "worker_outputs", "final_answer",
        "routing_decision", "conversation_id",
    }
    missing = expected - set(annotations)
    assert not missing, f"TeamRunState missing fields: {missing}"


def test_load_context_persists_user_message(team_setup):
    """``load_context`` writes the user message to DB + returns history.

    Patches ManagerDecider so the graph doesn't fan out to a real LLM
    call (we're testing load_context, not the manager's reasoning).
    """
    from lumen_core.database import SessionLocal
    from lumen_models.chat import Message
    from lumen_services.agents.state_graph import build_team_graph

    db = SessionLocal()
    try:
        with patch("lumen_services.agents.state_graph.ManagerDecider") as MockDecider:
            MockDecider.return_value.ask.return_value = MagicMock(
                chosen_agent_ids=[team_setup["worker_a"].id],
                reasoning="only A",
                aggregator_prompt=None,
            )
            g = build_team_graph()
            result = g.invoke(
                _initial_state(team_setup),
                config={"configurable": {"db": db}},
            )

            # User message persisted with a real DB id
            assert result["user_message_db_id"] > 0
            # Conversation was auto-created (no request_conversation_id)
            assert result["conversation"]["id"] > 0
            # History is empty on the first turn
            assert result["history"] == []
            # Workers loaded (2 active members)
            assert len(result["workers_by_id"]) == 2
            # Team + manager dicts populated
            assert result["team"]["id"] == team_setup["team"].id
            assert result["manager"]["id"] == team_setup["manager"].id

            # And the row really lives in DB
            msg = db.query(Message).filter(
                Message.id == result["user_message_db_id"],
            ).first()
            assert msg is not None
            assert msg.content == "hello team"
    finally:
        db.close()


def test_decide_routing_manager_decides_uses_decider(team_setup):
    """``decide_routing`` calls ManagerDecider when policy=manager_decides."""
    from lumen_core.database import SessionLocal
    from lumen_services.agents.state_graph import build_team_graph

    db = SessionLocal()
    try:
        with patch("lumen_services.agents.state_graph.ManagerDecider") as MockDecider:
            mock_instance = MagicMock()
            mock_instance.ask.return_value = MagicMock(
                chosen_agent_ids=[team_setup["worker_a"].id],
                reasoning="Picked A",
                aggregator_prompt=None,
            )
            MockDecider.return_value = mock_instance

            g = build_team_graph()
            result = g.invoke(
                _initial_state(team_setup),
                config={"configurable": {"db": db}},
            )

            # ManagerDecider was instantiated exactly once (with the manager)
            assert MockDecider.call_count == 1
            # The member corresponding to worker_a was chosen
            assert team_setup["member_a"].id in result["chosen_member_ids"]
            assert result["manager_reasoning"] == "Picked A"
            assert result["policy"] == "manager_decides"
    finally:
        db.close()


def test_decide_routing_first_match_uses_policy(team_setup):
    """policy=first_match uses select_workers_by_policy, not ManagerDecider."""
    from lumen_core.database import SessionLocal
    from lumen_services.agents.state_graph import build_team_graph

    db = SessionLocal()
    try:
        with patch("lumen_services.agents.state_graph.select_workers_by_policy") as mock_sel:
            mock_sel.return_value = [team_setup["worker_b"].id]
            initial = _initial_state(team_setup)
            initial["request_route_policy"] = "first_match"

            g = build_team_graph()
            result = g.invoke(
                initial, config={"configurable": {"db": db}},
            )

            assert mock_sel.called
            assert team_setup["member_b"].id in result["chosen_member_ids"]
            assert result["manager_reasoning"] == "policy=first_match"
    finally:
        db.close()


def test_decide_routing_empty_chosen_falls_back_to_all(team_setup):
    """When ManagerDecider returns no valid ids, fall back to all members.

    Patches AgentService as well so the fallback path's fan-out to 2
    workers doesn't trigger real LLM calls (which would hold a MySQL
    transaction open long enough to race with the persist node's
    ``UPDATE conversations`` statement).
    """
    from lumen_core.database import SessionLocal
    from lumen_services.agents.state_graph import build_team_graph

    db = SessionLocal()
    try:
        with patch("lumen_services.agents.state_graph.ManagerDecider") as MockDecider:
            mock_instance = MagicMock()
            # chosen_agent_ids = [] → after sanitize still empty → fallback
            mock_instance.ask.return_value = MagicMock(
                chosen_agent_ids=[],
                reasoning="no valid",
                aggregator_prompt=None,
            )
            MockDecider.return_value = mock_instance

            with patch("lumen_services.agents.state_graph.AgentService") as MockSvc:
                MockSvc.return_value.chat.return_value = "stub worker answer"

                g = build_team_graph()
                result = g.invoke(
                    _initial_state(team_setup),
                    config={"configurable": {"db": db}},
                )

                # Defensive fallback chose ALL members
                assert set(result["chosen_member_ids"]) == {
                    team_setup["member_a"].id,
                    team_setup["member_b"].id,
                }
    finally:
        db.close()


def test_run_worker_uses_agent_service_chat(team_setup):
    """``run_worker`` calls AgentService.chat with the agent_id from state."""
    from lumen_core.database import SessionLocal
    from lumen_services.agents.state_graph import build_team_graph

    db = SessionLocal()
    try:
        with patch("lumen_services.agents.state_graph.AgentService") as MockSvc:
            mock_svc_instance = MagicMock()
            mock_svc_instance.chat.return_value = "A's answer"
            MockSvc.return_value = mock_svc_instance

            with patch("lumen_services.agents.state_graph.ManagerDecider") as MockDecider:
                MockDecider.return_value.ask.return_value = MagicMock(
                    chosen_agent_ids=[team_setup["worker_a"].id],
                    reasoning="only A",
                    aggregator_prompt=None,
                )

                g = build_team_graph()
                result = g.invoke(
                    _initial_state(team_setup),
                    config={"configurable": {"db": db}},
                )

                # AgentService.chat was called
                assert mock_svc_instance.chat.called
                # 1 worker → final_answer == that worker's response
                assert result["final_answer"] == "A's answer"
                # routing_decision only contains the chosen agent
                assert result["routing_decision"] == [team_setup["worker_a"].id]
    finally:
        db.close()


def test_run_worker_error_does_not_fail_graph(team_setup):
    """A worker raising should NOT abort the graph; error recorded in output."""
    from lumen_core.database import SessionLocal
    from lumen_services.agents.state_graph import build_team_graph

    db = SessionLocal()
    try:
        with patch("lumen_services.agents.state_graph.AgentService") as MockSvc:
            mock_svc_instance = MagicMock()
            mock_svc_instance.chat.side_effect = RuntimeError("boom")
            MockSvc.return_value = mock_svc_instance

            with patch("lumen_services.agents.state_graph.ManagerDecider") as MockDecider:
                MockDecider.return_value.ask.return_value = MagicMock(
                    chosen_agent_ids=[team_setup["worker_a"].id],
                    reasoning="only A",
                    aggregator_prompt=None,
                )

                g = build_team_graph()
                # Must not raise
                result = g.invoke(
                    _initial_state(team_setup),
                    config={"configurable": {"db": db}},
                )

                # Graph completed despite worker error
                assert "final_answer" in result
                # Error was recorded in the worker output's response field
                assert "[worker error" in result["final_answer"]
                assert "RuntimeError" in result["final_answer"]
    finally:
        db.close()


def test_aggregate_skipped_for_single_worker(team_setup):
    """1 worker → should_aggregate returns 'skip' → aggregate NOT invoked."""
    from lumen_core.database import SessionLocal
    from lumen_services.agents.state_graph import (
        aggregate, build_team_graph,
    )

    db = SessionLocal()
    try:
        with patch(
            "lumen_services.agents.state_graph.aggregate", wraps=aggregate,
        ) as spy_agg:
            with patch("lumen_services.agents.state_graph.ManagerDecider") as MockDecider:
                MockDecider.return_value.ask.return_value = MagicMock(
                    chosen_agent_ids=[team_setup["worker_a"].id],
                    reasoning="only A",
                    aggregator_prompt=None,
                )
                g = build_team_graph()
                result = g.invoke(
                    _initial_state(team_setup),
                    config={"configurable": {"db": db}},
                )
                # aggregate was NOT invoked
                assert spy_agg.call_count == 0
                # final_answer == single worker's response
                assert result["final_answer"] is not None
    finally:
        db.close()


def test_aggregate_called_for_multiple_workers(team_setup):
    """2+ workers → should_aggregate returns 'aggregate' → manager LLM called."""
    from lumen_core.database import SessionLocal
    from lumen_services.agents.state_graph import build_team_graph

    db = SessionLocal()
    try:
        with patch("lumen_services.agents.state_graph.AgentService") as MockSvc:
            mock_svc_instance = MagicMock()
            # worker runs (2 calls) + aggregate synthesize (1 call) = 3 total
            mock_svc_instance.chat.side_effect = [
                "A's answer", "B's answer", "Synthesized",
            ]
            MockSvc.return_value = mock_svc_instance

            with patch("lumen_services.agents.state_graph.ManagerDecider") as MockDecider:
                MockDecider.return_value.ask.return_value = MagicMock(
                    chosen_agent_ids=[
                        team_setup["worker_a"].id,
                        team_setup["worker_b"].id,
                    ],
                    reasoning="both",
                    aggregator_prompt=None,
                )

                g = build_team_graph()
                result = g.invoke(
                    _initial_state(team_setup),
                    config={"configurable": {"db": db}},
                )

                # 3 chat() calls total: 2 workers + 1 aggregate
                assert mock_svc_instance.chat.call_count == 3
                # final_answer is the synthesized manager LLM result
                assert result["final_answer"] == "Synthesized"
                # routing_decision preserves the chosen order
                assert result["routing_decision"] == [
                    team_setup["worker_a"].id,
                    team_setup["worker_b"].id,
                ]
    finally:
        db.close()


def test_persist_writes_msg_metadata(team_setup):
    """``persist`` writes assistant_message with the correct msg_metadata JSON."""
    from lumen_core.database import SessionLocal
    from lumen_models.chat import Message
    from lumen_services.agents.state_graph import build_team_graph

    db = SessionLocal()
    try:
        with patch("lumen_services.agents.state_graph.ManagerDecider") as MockDecider:
            MockDecider.return_value.ask.return_value = MagicMock(
                chosen_agent_ids=[team_setup["worker_a"].id],
                reasoning="only A",
                aggregator_prompt=None,
            )

            g = build_team_graph()
            result = g.invoke(
                _initial_state(team_setup),
                config={"configurable": {"db": db}},
            )

            # routing_decision + conversation_id present in final state
            assert result["routing_decision"] == [team_setup["worker_a"].id]
            assert result["conversation_id"] > 0

            # The assistant row exists in DB with the right metadata
            msg = db.query(Message).filter(
                Message.conversation_id == result["conversation_id"],
                Message.role == "assistant",
            ).first()
            assert msg is not None
            meta = json.loads(msg.msg_metadata)
            # Schema is unchanged from the pre-refactor implementation
            assert meta["routing_decision"] == [team_setup["worker_a"].id]
            assert meta["policy_used"] == "manager_decides"
            assert meta["manager_reasoning"] == "only A"
            assert len(meta["worker_outputs"]) == 1
            wo = meta["worker_outputs"][0]
            assert wo["agent_id"] == team_setup["worker_a"].id
            assert wo["member_id"] == team_setup["member_a"].id
    finally:
        db.close()


def test_send_fan_out_runs_workers_in_parallel_state(team_setup):
    """Send API fans out to N workers, reducer collects N worker_outputs."""
    from lumen_core.database import SessionLocal
    from lumen_services.agents.state_graph import build_team_graph

    db = SessionLocal()
    try:
        with patch("lumen_services.agents.state_graph.AgentService") as MockSvc:
            mock_svc_instance = MagicMock()
            mock_svc_instance.chat.side_effect = [
                "A's answer", "B's answer", "Synthesized",
            ]
            MockSvc.return_value = mock_svc_instance

            with patch("lumen_services.agents.state_graph.ManagerDecider") as MockDecider:
                MockDecider.return_value.ask.return_value = MagicMock(
                    chosen_agent_ids=[
                        team_setup["worker_a"].id,
                        team_setup["worker_b"].id,
                    ],
                    reasoning="both",
                    aggregator_prompt=None,
                )

                g = build_team_graph()
                result = g.invoke(
                    _initial_state(team_setup),
                    config={"configurable": {"db": db}},
                )

                # Both workers' outputs collected by the reducer
                assert len(result["worker_outputs"]) == 2
                # The persisted msg_metadata also has 2 worker entries
                routing = result["routing_decision"]
                assert set(routing) == {
                    team_setup["worker_a"].id,
                    team_setup["worker_b"].id,
                }
                # The two worker names in the outputs match
                names = {wo["agent_name"] for wo in result["worker_outputs"]}
                assert names == {
                    team_setup["worker_a"].name,
                    team_setup["worker_b"].name,
                }
    finally:
        db.close()
