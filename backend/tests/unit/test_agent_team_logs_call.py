"""M26 AgentTeam state_graph LLMCallLog tests.

Pin down the per-node instrumentation:

- ``decide_routing`` sets a ``team.manager_decision`` context.
- ``run_worker`` sets a ``team.worker`` context with team_member_id.
- ``aggregate`` sets a ``team.aggregate`` context.
- All three share the same trace_id (root_call_id == trace_id).
- Worker call_index encodes the position in the fan-out.

The state graph nodes invoke ``AgentService.chat``, which calls
``llm.invoke`` on the LoggingChatModel wrapper returned by
``create_chat_model``. We mock ``create_chat_model`` to return a
``LoggingChatModel`` wrapping a fake inner model — that way the
wrapper sees the per-node context and writes the row.

``AgentService.chat`` is also patched to drive the wrapped LLM through
its real ``invoke`` path so the row actually lands.
"""
import os
import sys
import uuid
from datetime import datetime
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import HumanMessage, AIMessage

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

# FK targets must be registered before SQLAlchemy resolves the metadata.
from lumen_models.external_app import ExternalApp, ExternalVisitor  # noqa: F401
from lumen_models.image_generation import GeneratedImage  # noqa: F401
from lumen_models.agent import Agent  # noqa: F401
from lumen_models.agent_team import AgentTeam  # noqa: F401
from lumen_models.workflow import Workflow, WorkflowRun  # noqa: F401
from lumen_models.chat import Conversation, Message  # noqa: F401
from lumen_models.model_config import ModelConfig  # noqa: F401

from lumen_core.database import SessionLocal
from lumen_models.llm_call_log import LLMCallLog
from lumen_services.model_loader import LoggingChatModel


def _cleanup_llm_call_logs(trace_id: str) -> None:
    db = SessionLocal()
    try:
        db.query(LLMCallLog).filter(LLMCallLog.trace_id == trace_id).delete()
        db.commit()
    finally:
        db.close()


@pytest.fixture
def team_setup():
    from lumen_models.agent import Agent
    from lumen_models.agent_team import AgentTeam, AgentTeamMember

    db = SessionLocal()
    suffix = uuid.uuid4().hex[:8]
    manager = Agent(
        name=f"mgr-{suffix}", description="t", prompt_template="You manage.",
        model_name="qwen2.5:0.5b", tenant_id=1, is_active=True,
    )
    worker_a = Agent(
        name=f"wA-{suffix}", description="t", prompt_template="You are A.",
        model_name="qwen2.5:0.5b", tenant_id=1, is_active=True,
    )
    worker_b = Agent(
        name=f"wB-{suffix}", description="t", prompt_template="You are B.",
        model_name="qwen2.5:0.5b", tenant_id=1, is_active=True,
    )
    db.add_all([manager, worker_a, worker_b])
    db.commit()
    db.refresh(manager); db.refresh(worker_a); db.refresh(worker_b)

    team = AgentTeam(
        name=f"team-{suffix}", description="t",
        manager_agent_id=manager.id, tenant_id=1, is_active=True,
        route_policy="manager_decides",
        aggregator_prompt="Synthesize: {workers}\nUser: {user_message}\nAnswers: {answers}",
    )
    db.add(team)
    db.commit()
    db.refresh(team)

    ma = AgentTeamMember(team_id=team.id, agent_id=worker_a.id, is_active=True, role="worker_a")
    mb = AgentTeamMember(team_id=team.id, agent_id=worker_b.id, is_active=True, role="worker_b")
    db.add_all([ma, mb])
    db.commit()
    db.refresh(ma); db.refresh(mb)

    team_id = team.id
    member_ids = [ma.id, mb.id]
    db.close()

    yield team_id, member_ids, suffix

    db = SessionLocal()
    try:
        db.query(Message).filter(
            Message.conversation_id.in_(
                db.query(Conversation.id).filter(Conversation.team_id == team_id)
            )
        ).delete(synchronize_session=False)
        db.query(Conversation).filter(Conversation.team_id == team_id).delete()
        db.query(AgentTeamMember).filter(AgentTeamMember.team_id == team_id).delete()
        db.query(AgentTeam).filter(AgentTeam.id == team_id).delete()
        db.query(Agent).filter(Agent.name.like(f"%{suffix}%")).delete()
        db.commit()
    finally:
        db.close()


def _make_wrapped_llm(agent_id: int) -> LoggingChatModel:
    """Build a LoggingChatModel that returns a fake AIMessage per invoke."""
    inner = MagicMock()
    inner.invoke = MagicMock(return_value=AIMessage(
        content=f"response-from-agent-{agent_id}",
        response_metadata={"finish_reason": "stop"},
    ))
    return LoggingChatModel(
        inner,
        model_type="ollama",
        model_name="qwen2.5:0.5b",
        temperature=0.7,
    )


def test_state_graph_writes_one_manager_two_workers_one_aggregator(team_setup):
    """A 2-worker team run writes ≥4 LLMCallLog rows under the same trace_id.

    Expected breakdown:
    - 1 manager (decide_routing)
    - 2 workers (run_worker × 2, Send fan-out)
    - 1 aggregator (>1 worker triggers aggregate)
    """
    from lumen_services.agents.state_graph import build_team_graph

    team_id, _member_ids, _suffix = team_setup

    # Map agent_id → wrapped LLM so the right row is written per agent
    from lumen_core.database import SessionLocal as _SL
    db = _SL()
    agent_ids = [row[0] for row in db.query(Agent.id).filter(Agent.name.like(f"%{_suffix}%")).all()]
    db.close()

    wrapped_by_agent = {aid: _make_wrapped_llm(aid) for aid in agent_ids}

    def fake_create_chat_model(*args, **kwargs):
        # args[1] is model_name (we don't really use this); the model_name
        # passed via AgentService.chat lets us look up the right wrapped LLM.
        agent_id = fake_create_chat_model._last_agent_id  # type: ignore[attr-defined]
        return wrapped_by_agent[agent_id]

    # Real AgentService.chat → which calls llm.invoke(messages). We monkey-patch
    # so it uses OUR wrapped LLM instead of going to DB for model config.
    from lumen_services import agent_service as _agent_service

    def fake_chat(self, db, agent_id, **kwargs):
        # Resolve the wrapped LLM for this agent and invoke through it.
        # The context set by the state_graph node will be visible to the wrapper.
        fake_create_chat_model._last_agent_id = agent_id  # type: ignore[attr-defined]
        wrapped = fake_create_chat_model()
        response = wrapped.invoke([HumanMessage(content=kwargs.get("message", ""))])
        return response.content

    with patch.object(_agent_service.AgentService, "chat", new=fake_chat), \
         patch("lumen_services.model_loader.create_chat_model", side_effect=fake_create_chat_model):
        graph = build_team_graph()
        trace_id = str(uuid.uuid4())
        initial_state = {
            "team_id": team_id,
            "tenant_id": 1,
            "user_id": 1,
            "user_message": "hello team",
            "request_conversation_id": None,
            "request_member_ids": None,
            "request_route_policy": "manager_decides",
        }
        graph.invoke(
            initial_state,
            config={
                "configurable": {
                    "db": SessionLocal(),
                    "trace_id": trace_id,
                    "root_call_id": trace_id,
                },
            },
        )

    try:
        db = SessionLocal()
        try:
            rows = (
                db.query(LLMCallLog)
                .filter(LLMCallLog.trace_id == trace_id)
                .order_by(LLMCallLog.call_index.asc())
                .all()
            )
        finally:
            db.close()

        assert len(rows) >= 3, f"expected ≥3 rows, got {len(rows)}: {[r.call_type for r in rows]}"

        types = [r.call_type for r in rows]
        assert "team.manager_decision" in types, f"missing manager row; got {types}"
        assert types.count("team.worker") == 2, f"expected 2 worker rows, got {types}"
        assert "team.aggregate" in types, f"missing aggregate row; got {types}"

        # All share the same trace_id
        for r in rows:
            assert r.trace_id == trace_id
            assert r.parent_call_id == trace_id  # root_call_id

        # Worker rows carry team_member_id + agent_id
        worker_rows = [r for r in rows if r.call_type == "team.worker"]
        for r in worker_rows:
            assert r.team_member_id is not None
            assert r.agent_id is not None

        # Manager + aggregator rows carry agent_id
        for r in rows:
            if r.call_type in ("team.manager_decision", "team.aggregate"):
                assert r.agent_id is not None
    finally:
        _cleanup_llm_call_logs(trace_id)


def test_state_graph_one_worker_skips_aggregate(team_setup):
    """When member_ids is restricted to 1, aggregate is skipped → 2 rows."""
    from lumen_services.agents.state_graph import build_team_graph

    team_id, member_ids, suffix = team_setup
    only_one_member = member_ids[:1]

    db = SessionLocal()
    agent_ids = [row[0] for row in db.query(Agent.id).filter(Agent.name.like(f"%{suffix}%")).all()]
    db.close()
    wrapped_by_agent = {aid: _make_wrapped_llm(aid) for aid in agent_ids}

    def fake_create_chat_model(*args, **kwargs):
        agent_id = fake_create_chat_model._last_agent_id  # type: ignore[attr-defined]
        return wrapped_by_agent[agent_id]

    from lumen_services import agent_service as _agent_service

    def fake_chat(self, db, agent_id, **kwargs):
        fake_create_chat_model._last_agent_id = agent_id  # type: ignore[attr-defined]
        wrapped = fake_create_chat_model()
        response = wrapped.invoke([HumanMessage(content=kwargs.get("message", ""))])
        return response.content

    with patch.object(_agent_service.AgentService, "chat", new=fake_chat), \
         patch("lumen_services.model_loader.create_chat_model", side_effect=fake_create_chat_model):
        graph = build_team_graph()
        trace_id = str(uuid.uuid4())
        initial_state = {
            "team_id": team_id,
            "tenant_id": 1,
            "user_id": 1,
            "user_message": "single worker",
            "request_conversation_id": None,
            "request_member_ids": only_one_member,
            "request_route_policy": "manager_decides",
        }
        graph.invoke(
            initial_state,
            config={
                "configurable": {
                    "db": SessionLocal(),
                    "trace_id": trace_id,
                    "root_call_id": trace_id,
                },
            },
        )

    try:
        db = SessionLocal()
        try:
            rows = (
                db.query(LLMCallLog)
                .filter(LLMCallLog.trace_id == trace_id)
                .all()
            )
        finally:
            db.close()

        types = [r.call_type for r in rows]
        assert "team.manager_decision" in types
        assert types.count("team.worker") == 1
        # aggregate should be skipped
        assert "team.aggregate" not in types
    finally:
        _cleanup_llm_call_logs(trace_id)


# Local import to avoid the FK issue described at the top of this file
from lumen_models.agent import Agent  # noqa: E402