"""Smoke test for ChatService.stream_for_external.

We mock the heavy LLM call (``service.stream_chat_messages``) and
assert the SSE event sequence + DB writes match the internal chat
contract. The full end-to-end test (with a real Ollama round-trip)
lives in ``tests/integration/test_external_chat_stream_e2e.py``.
"""
import gc
import json

import pytest
from datetime import datetime
from unittest.mock import patch

from lumen_core.database import SessionLocal, engine
from lumen_models.agent import Agent
from lumen_models.external_app import ExternalApp
# Import so SQLAlchemy Base.metadata knows about the team table when the
# Conversation ORM is first instantiated — Conversation.team_id FKs
# agent_teams.id and the mapper needs the table registered. Production
# code paths already load this via app.main / get_db, but the test
# process invokes the ORM directly without the app lifespan.
from lumen_models.agent_team import AgentTeam  # noqa: F401
from lumen_scripts.seed_external_app import seed_dev_external_app


@pytest.fixture(autouse=True)
def _dispose_engine_after_test():
    """Force-close all pooled connections after each test.

    Mirrors the workaround in ``test_chat_user_id_nullable_regression.py`` /
    ``test_external_token_endpoint.py``: the autouse ``get_db`` FastAPI
    dependency calls ``db.close()`` in its finally block, but the DBAPI
    connection's transaction state (and any InnoDB metadata lock it
    holds) can survive the close because the ``Session`` object is still
    alive in a generator-local frame that hasn't been garbage-collected
    yet. ``gc.collect()`` finalises the unreferenced ``Session`` objects
    and ``engine.dispose()`` closes the checked-in connections.
    """
    yield
    gc.collect()
    engine.dispose()


def _make_tenant_agent_visitor(prompt_template: str = "p"):
    """Create the full fixture graph in ONE session.

    The plan's test code opened three separate SessionLocal() blocks
    and tried to mutate ``ext_app.tenant_id`` + read ``ext_app.id`` after
    the session was closed → ``DetachedInstanceError``. Capture all
    integer ids in-session and return them as plain ints.

    ``prompt_template`` is plumbed through to the Agent row so the
    system-prompt injection tests in M16 (2026-06-10) can exercise the
    empty / whitespace / non-empty branches. Default "p" matches the
    original M14 test setup (and ``agents.prompt_template`` is NOT NULL).
    """
    if prompt_template is None:
        # agents.prompt_template is NOT NULL; treat None as "p" (original
        # M14 behavior). The M16 no-agent-bound test passes an explicit
        # string and then forces conv.agent_id=None, so it doesn't hit this
        # branch.
        prompt_template = "p"
    db = SessionLocal()
    try:
        from lumen_models.tenant import Tenant
        from lumen_models.external_app import ExternalVisitor
        ext_app = db.query(ExternalApp).filter(
            ExternalApp.app_key == "lc_pub_dev_demo_only_replace_in_prod"
        ).first()
        assert ext_app is not None, "seed_dev_external_app must have run first"

        v = ExternalVisitor(
            app_id=ext_app.id,
            visitor_id=f"vis-cs-{datetime.utcnow().timestamp()}",
            first_seen_at=datetime.utcnow(),
            last_seen_at=datetime.utcnow(),
        )
        db.add(v)
        db.commit()
        db.refresh(v)

        # Tenant.status is Column(Boolean, default=True) and max_users
        # has a default; do NOT pass them in test fixtures (Task 9
        # implementation note: prior plan code used status="active" +
        # max_users=5 which would fail the Boolean column type).
        t = Tenant(name="t-cs", code=f"cs-{datetime.utcnow().timestamp()}")
        db.add(t)
        db.commit()
        db.refresh(t)

        a = Agent(
            name="ext-chat-agent", prompt_template=prompt_template,
            model_name="qwen2.5:7b", temperature=0,
            tenant_id=t.id, is_active=True,
        )
        db.add(a)
        db.commit()
        db.refresh(a)

        # Realign the dev external app's tenant_id to this test's tenant
        # so the model's filter (``tenant_id == ctx.tenant_id``) can find
        # the just-created ModelConfig (or, in the MVP, the global
        # tenant's defaults).
        ext_app.tenant_id = t.id
        db.commit()

        from lumen_models.chat import Conversation
        c = Conversation(
            title="ext",
            tenant_id=t.id,
            agent_id=a.id,
            user_id=None,
            external_app_id=ext_app.id,
            external_visitor_id=v.id,
        )
        db.add(c)
        db.commit()
        db.refresh(c)

        # Return ONLY plain ints / strings; the SQLAlchemy session is
        # about to close and we MUST NOT leak ORM instances out.
        return {
            "app_id": ext_app.id,
            "tenant_id": t.id,
            "agent_id": a.id,
            "visitor_id": v.id,
            "conv_id": c.id,
        }
    finally:
        db.close()


def _make_ctx(app_id, tenant_id, visitor_id, agent_id):
    from lumen_api.v1.deps import ExternalAppContext
    return ExternalAppContext(
        app_id=app_id, tenant_id=tenant_id,
        visitor_id=visitor_id, visitor_uuid="v",
        allowed_agent_ids=[agent_id], allowed_team_ids=[],
        scopes=["chat:stream"],
    )


@pytest.mark.asyncio
async def test_stream_for_external_emits_done_with_conversation_id():
    seed_dev_external_app()
    ids = _make_tenant_agent_visitor()
    ctx = _make_ctx(ids["app_id"], ids["tenant_id"],
                    ids["visitor_id"], ids["agent_id"])

    from lumen_schemas.external import ExternalChatRequest
    req = ExternalChatRequest(
        message="hello", agent_id=ids["agent_id"],
        conversation_id=ids["conv_id"],
    )

    # Mock the inner ChatService.stream_chat_messages to return two chunks
    from lumen_services.chat_service import ChatService
    async def fake_stream(msgs):
        yield "hi"
        yield " there"
    with patch.object(ChatService, "stream_chat_messages", side_effect=fake_stream):
        gen = ChatService().stream_for_external(ctx, req)
        events = []
        async for raw in gen:
            events.append(raw)

    # 2 content events + 1 done event
    assert len(events) == 3
    assert json.loads(events[0].removeprefix("data: ").strip())["content"] == "hi"
    last = json.loads(events[-1].removeprefix("data: ").strip())
    assert last["done"] is True
    assert last["conversation_id"] == ids["conv_id"]


@pytest.mark.asyncio
async def test_stream_for_external_persists_assistant_message_with_no_user_id():
    """The assistant Message row should be persistable with conversation_id
    only — user_id is NULL because this is an external chat."""
    seed_dev_external_app()
    ids = _make_tenant_agent_visitor()
    ctx = _make_ctx(ids["app_id"], ids["tenant_id"],
                    ids["visitor_id"], ids["agent_id"])

    from lumen_schemas.external import ExternalChatRequest
    from lumen_services.chat_service import ChatService
    from lumen_models.chat import Message as MessageModel
    req = ExternalChatRequest(
        message="ping", agent_id=ids["agent_id"],
        conversation_id=ids["conv_id"],
    )

    async def fake_stream(msgs):
        yield "pong"
    with patch.object(ChatService, "stream_chat_messages", side_effect=fake_stream):
        async for _ in ChatService().stream_for_external(ctx, req):
            pass

    db = SessionLocal()
    try:
        msgs = db.query(MessageModel).filter(
            MessageModel.conversation_id == ids["conv_id"]
        ).order_by(MessageModel.created_at.asc()).all()
        # 1 user + 1 assistant
        assert len(msgs) == 2
        assert msgs[0].role == "user"
        assert msgs[1].role == "assistant"
        assert msgs[1].content == "pong"
    finally:
        db.close()


@pytest.mark.asyncio
async def test_stream_for_external_injects_system_prompt_when_agent_has_template():
    """M16 (2026-06-10): when the bound Agent has a non-empty prompt_template,
    stream_for_external must pass it as the first message (role=system) to
    stream_chat_messages. This is the fix for the bug where widget chats
    ignored the agent's role entirely."""
    seed_dev_external_app()
    ids = _make_tenant_agent_visitor(prompt_template="你只回答 pong")
    ctx = _make_ctx(ids["app_id"], ids["tenant_id"],
                    ids["visitor_id"], ids["agent_id"])

    from lumen_schemas.external import ExternalChatRequest
    from lumen_services.chat_service import ChatService
    req = ExternalChatRequest(
        message="hi", agent_id=ids["agent_id"],
        conversation_id=ids["conv_id"],
    )

    captured: list[list[dict]] = []
    async def fake_stream(msgs):
        captured.append(msgs)
        yield "pong"
    with patch.object(ChatService, "stream_chat_messages", side_effect=fake_stream):
        async for _ in ChatService().stream_for_external(ctx, req):
            pass

    assert len(captured) == 1, "stream_chat_messages should be called exactly once"
    messages = captured[0]
    assert messages[0] == {"role": "system", "content": "你只回答 pong"}, (
        f"first message must be the agent's prompt_template as system role; got {messages[0]!r}"
    )
    # User message still last
    assert messages[-1] == {"role": "user", "content": "hi"}


@pytest.mark.asyncio
async def test_stream_for_external_skips_system_prompt_when_template_empty():
    """Empty prompt_template → no system message injected (regression guard
    for agents that never set a prompt)."""
    seed_dev_external_app()
    ids = _make_tenant_agent_visitor(prompt_template="")
    ctx = _make_ctx(ids["app_id"], ids["tenant_id"],
                    ids["visitor_id"], ids["agent_id"])

    from lumen_schemas.external import ExternalChatRequest
    from lumen_services.chat_service import ChatService
    req = ExternalChatRequest(
        message="hi", agent_id=ids["agent_id"],
        conversation_id=ids["conv_id"],
    )

    captured: list[list[dict]] = []
    async def fake_stream(msgs):
        captured.append(msgs)
        yield "pong"
    with patch.object(ChatService, "stream_chat_messages", side_effect=fake_stream):
        async for _ in ChatService().stream_for_external(ctx, req):
            pass

    messages = captured[0]
    assert not any(m.get("role") == "system" for m in messages), (
        f"empty prompt_template must NOT inject a system message; got {messages!r}"
    )


@pytest.mark.asyncio
async def test_stream_for_external_skips_system_prompt_when_template_whitespace():
    """Whitespace-only prompt_template → treated as empty, no system message."""
    seed_dev_external_app()
    ids = _make_tenant_agent_visitor(prompt_template="   \n  \t")
    ctx = _make_ctx(ids["app_id"], ids["tenant_id"],
                    ids["visitor_id"], ids["agent_id"])

    from lumen_schemas.external import ExternalChatRequest
    from lumen_services.chat_service import ChatService
    req = ExternalChatRequest(
        message="hi", agent_id=ids["agent_id"],
        conversation_id=ids["conv_id"],
    )

    captured: list[list[dict]] = []
    async def fake_stream(msgs):
        captured.append(msgs)
        yield "pong"
    with patch.object(ChatService, "stream_chat_messages", side_effect=fake_stream):
        async for _ in ChatService().stream_for_external(ctx, req):
            pass

    messages = captured[0]
    assert not any(m.get("role") == "system" for m in messages), (
        f"whitespace-only prompt_template must NOT inject a system message; got {messages!r}"
    )


@pytest.mark.asyncio
async def test_stream_for_external_skips_system_prompt_when_no_agent_bound():
    """conv.agent_id is NULL → no agent → no system message (regression guard
    for conversations created via team chat or direct user chat)."""
    seed_dev_external_app()
    # Create agent (for fixture) but we'll force conv.agent_id=None
    ids = _make_tenant_agent_visitor()
    from lumen_models.chat import Conversation
    db = SessionLocal()
    try:
        c = db.query(Conversation).filter(Conversation.id == ids["conv_id"]).first()
        c.agent_id = None
        db.commit()
    finally:
        db.close()

    ctx = _make_ctx(ids["app_id"], ids["tenant_id"],
                    ids["visitor_id"], ids["agent_id"])

    from lumen_schemas.external import ExternalChatRequest
    from lumen_services.chat_service import ChatService
    req = ExternalChatRequest(
        message="hi", agent_id=ids["agent_id"],
        conversation_id=ids["conv_id"],
    )

    captured: list[list[dict]] = []
    async def fake_stream(msgs):
        captured.append(msgs)
        yield "pong"
    with patch.object(ChatService, "stream_chat_messages", side_effect=fake_stream):
        async for _ in ChatService().stream_for_external(ctx, req):
            pass

    messages = captured[0]
    assert not any(m.get("role") == "system" for m in messages), (
        f"no agent bound must NOT inject a system message; got {messages!r}"
    )
