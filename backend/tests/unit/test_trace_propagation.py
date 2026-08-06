"""M26 end-to-end trace_id propagation tests.

Verifies that the ContextVar-based trace_id flows correctly through:

- Module 1 (chat): the LLMCallContext set at the endpoint entry is
  visible inside ``LoggingChatModel.astream`` / ``invoke`` so the
  resulting row carries the same trace_id.
- Module 3 (agent_team): the trace_id passed via
  ``config['configurable']['trace_id']`` is propagated to per-node
  contexts and is visible inside ``AgentService.chat``.
- Nested context (within one node): parent_call_id is the trace_id
  root, so all rows in a single team run share the same root parent.

These tests don't spin up FastAPI — they directly verify the
ContextVar mechanism that the wrapper / state_graph rely on.
"""
import os
import sys
import uuid

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

# FK targets must be registered before SQLAlchemy resolves the metadata.
from lumen_models.image_generation import GeneratedImage  # noqa: F401
from lumen_models.agent import Agent  # noqa: F401
from lumen_models.agent_team import AgentTeam  # noqa: F401
from lumen_models.workflow import Workflow, WorkflowRun  # noqa: F401
from lumen_models.chat import Conversation, Message  # noqa: F401
from lumen_models.model_config import ModelConfig  # noqa: F401
from lumen_models.knowledge import KnowledgeBase  # noqa: F401
from lumen_models.tenant import Tenant  # noqa: F401
from lumen_models.user import User  # noqa: F401
from lumen_models.external_app import ExternalApp, ExternalVisitor  # noqa: F401


def test_context_set_and_reset_round_trip():
    """set_call_context / reset_call_context round-trip preserves the context
    inside the active scope and clears it after."""
    from lumen_core.llm_call_context import (
        LLMCallContext, set_call_context, get_call_context, reset_call_context,
    )

    assert get_call_context() is None  # baseline
    ctx = LLMCallContext(
        call_id=str(uuid.uuid4()),
        trace_id="trace-A",
        parent_call_id=None,
        call_type="chat",
        call_index=0,
        tenant_id=1,
    )
    token = set_call_context(ctx)
    try:
        active = get_call_context()
        assert active is not None
        assert active.trace_id == "trace-A"
        assert active.call_type == "chat"
    finally:
        reset_call_context(token)
    assert get_call_context() is None


def test_nested_context_restores_outer():
    """Nested set_call_context overwrites inside the inner scope and restores
    the outer value after the inner reset_call_context."""
    from lumen_core.llm_call_context import (
        LLMCallContext, set_call_context, get_call_context, reset_call_context,
    )

    outer = LLMCallContext(
        call_id="outer", trace_id="trace-outer", parent_call_id=None,
        call_type="chat", call_index=0, tenant_id=1,
    )
    inner = LLMCallContext(
        call_id="inner", trace_id="trace-inner", parent_call_id="outer",
        call_type="team.worker", call_index=1, tenant_id=1,
    )
    outer_token = set_call_context(outer)
    try:
        assert get_call_context().trace_id == "trace-outer"
        inner_token = set_call_context(inner)
        try:
            assert get_call_context().trace_id == "trace-inner"
            assert get_call_context().parent_call_id == "outer"
        finally:
            reset_call_context(inner_token)
        # Outer restored
        assert get_call_context().trace_id == "trace-outer"
    finally:
        reset_call_context(outer_token)


def test_default_is_none():
    """get_call_context returns None when no context is set."""
    from lumen_core.llm_call_context import get_call_context

    assert get_call_context() is None


def test_module_1_chat_trace_propagates_through_wrapper():
    """A module-1 chat request: trace_id set at endpoint → same trace_id
    ends up on the LLMCallLog row."""
    from unittest.mock import MagicMock
    from langchain_core.messages import AIMessage

    from lumen_core.llm_call_context import (
        LLMCallContext, set_call_context, reset_call_context,
    )
    from lumen_core.database import SessionLocal
    from lumen_models.agent import Agent
    from lumen_models.chat import Conversation
    from lumen_models.llm_call_log import LLMCallLog
    from lumen_services.model_loader import LoggingChatModel

    # 在 dev DB 上硬编码 id=42 / agent_id=7 容易因 teardown 失效。
    # 这里动态查一个真实存在的 conversation 和 agent,FK 不会卡。
    setup_db = SessionLocal()
    conv = None
    agent = None
    try:
        conv = setup_db.query(Conversation).filter(
            Conversation.user_id == 1
        ).order_by(Conversation.id.asc()).first()
        agent = setup_db.query(Agent).filter(
            Agent.is_active == True  # noqa: E712
        ).order_by(Agent.id.asc()).first()
        conv_id = int(conv.id) if conv is not None else None
        agent_id = int(agent.id) if agent is not None else None
    finally:
        setup_db.close()

    trace_id = str(uuid.uuid4())
    ctx = LLMCallContext(
        call_id=trace_id,  # root call_id == trace_id for chat path
        trace_id=trace_id,
        parent_call_id=None,
        call_type="chat",
        call_index=0,
        tenant_id=1,
        conversation_id=conv_id,
        agent_id=agent_id,
    )
    token = set_call_context(ctx)
    try:
        # The wrapped LLM is what chat_service.stream_chat_messages uses
        inner = MagicMock()
        inner.invoke = MagicMock(return_value=AIMessage(
            content="trace-test-response",
            usage_metadata={"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
            response_metadata={"finish_reason": "stop"},
        ))
        wrapped = LoggingChatModel(inner, model_type="ollama", model_name="m")

        result = wrapped.invoke("hi")
        assert result.content == "trace-test-response"

        # Verify the LLMCallLog row carries the same trace_id
        db = SessionLocal()
        try:
            row = db.query(LLMCallLog).filter(LLMCallLog.call_id == trace_id).first()
        finally:
            db.close()

        assert row is not None
        assert row.trace_id == trace_id
        assert row.call_type == "chat"
        assert row.conversation_id == conv_id
        assert row.agent_id == agent_id
        assert row.call_index == 0
    finally:
        reset_call_context(token)
        # Cleanup
        db = SessionLocal()
        try:
            db.query(LLMCallLog).filter(LLMCallLog.call_id == trace_id).delete()
            db.commit()
        finally:
            db.close()


def test_module_3_team_trace_propagates_via_state_graph():
    """A module-3 team run: trace_id passed via state_graph config →
    all 4 nodes (1 manager + 2 workers + 1 aggregator) write rows under
    that same trace_id (already covered in test_agent_team_logs_call.py;
    this one is a smoke check that the trace_id is stable across all
    rows)."""
    from unittest.mock import MagicMock, patch
    from langchain_core.messages import HumanMessage, AIMessage

    from lumen_core.database import SessionLocal
    from lumen_models.agent import Agent
    from lumen_models.agent_team import AgentTeam, AgentTeamMember
    from lumen_models.llm_call_log import LLMCallLog
    from lumen_services.agents.state_graph import build_team_graph
    from lumen_services.model_loader import LoggingChatModel

    # Build a tiny team. We use expire_on_commit=False so accessing
    # attributes after commit doesn't trigger a lazy-load SELECT (which
    # would fail on a closed session).
    setup_db = SessionLocal(expire_on_commit=False)
    suffix = uuid.uuid4().hex[:8]
    manager = Agent(
        name=f"trace-mgr-{suffix}", description="t",
        prompt_template="You manage.",
        model_name="qwen2.5:0.5b", tenant_id=1, is_active=True,
    )
    w = Agent(
        name=f"trace-w-{suffix}", description="t",
        prompt_template="You work.",
        model_name="qwen2.5:0.5b", tenant_id=1, is_active=True,
    )
    setup_db.add_all([manager, w])
    setup_db.commit()

    team = AgentTeam(
        name=f"trace-team-{suffix}", description="t",
        manager_agent_id=manager.id, tenant_id=1, is_active=True,
        route_policy="manager_decides",
        aggregator_prompt="Syn: {workers}\nUser: {user_message}\nAnswers: {answers}",
    )
    setup_db.add(team)
    setup_db.commit()

    member = AgentTeamMember(team_id=team.id, agent_id=w.id, is_active=True)
    setup_db.add(member)
    setup_db.commit()

    # Capture all primitive IDs we need before closing setup_db.
    manager_id = int(manager.id)
    worker_id = int(w.id)
    team_id = int(team.id)
    member_id = int(member.id)
    setup_db.close()

    wrapped_by_agent = {
        manager_id: LoggingChatModel(
            MagicMock(invoke=MagicMock(return_value=AIMessage(content="mgr"))),
            model_type="ollama", model_name="m",
        ),
        worker_id: LoggingChatModel(
            MagicMock(invoke=MagicMock(return_value=AIMessage(content="wkr"))),
            model_type="ollama", model_name="m",
        ),
    }

    def fake_create_chat_model(*args, **kwargs):
        agent_id = fake_create_chat_model._last_agent_id
        return wrapped_by_agent[agent_id]

    from lumen_services import agent_service as _agent_service

    def fake_chat(self, db, agent_id, **kwargs):
        fake_create_chat_model._last_agent_id = agent_id
        wrapped = fake_create_chat_model()
        return wrapped.invoke([HumanMessage(content=kwargs.get("message", ""))]).content

    trace_id = str(uuid.uuid4())
    try:
        with patch.object(_agent_service.AgentService, "chat", new=fake_chat), \
             patch("lumen_services.model_loader.create_chat_model", side_effect=fake_create_chat_model):
            graph = build_team_graph()
            # The session passed via config is the SAME session the
            # graph uses; closing setup_db first avoids cross-session
            # detachment because all ORM objects the graph sees are
            # freshly re-fetched via this db.
            graph_db = SessionLocal()
            try:
                initial_state = {
                    "team_id": team_id,
                    "tenant_id": 1,
                    "user_id": 1,
                    "user_message": "hi",
                    "request_conversation_id": None,
                    "request_member_ids": [member_id],
                    "request_route_policy": "manager_decides",
                }
                graph.invoke(
                    initial_state,
                    config={
                        "configurable": {
                            "db": graph_db,
                            "trace_id": trace_id,
                            "root_call_id": trace_id,
                        },
                    },
                )
            finally:
                graph_db.close()

        # Verify all rows share the trace_id
        db = SessionLocal()
        try:
            rows = (
                db.query(LLMCallLog)
                .filter(LLMCallLog.trace_id == trace_id)
                .all()
            )
        finally:
            db.close()

        assert len(rows) >= 2
        for r in rows:
            assert r.trace_id == trace_id
            assert r.parent_call_id == trace_id
    finally:
        # Cleanup logs + team (order matters for FKs)
        db = SessionLocal()
        try:
            db.query(LLMCallLog).filter(LLMCallLog.trace_id == trace_id).delete()
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


# Local import for FK target referenced in cleanup
from lumen_models.chat import Conversation, Message  # noqa: E402