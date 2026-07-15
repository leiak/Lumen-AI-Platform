"""M26 /chat/stream LLMCallLog end-to-end tests.

Pin down the module-1 instrumentation:

- ``LoggingChatModel.astream`` accumulates chunks and writes 1 row at end.
- ``LoggingChatModel.invoke`` writes 1 row per call (sync path).
- Tool-call round trips accumulate tool_calls into a single row's JSON.
- Failure path writes status="failure" with error_type / error_message.
- Without an active context, the wrapper is transparent (no row written).

The ChatService layer is exercised indirectly via the LoggingChatModel
wrapper, which is the single seam for /chat/stream. We don't spin up
FastAPI's TestClient here — that needs a full DB + auth setup, and the
behaviour we care about (write-once-at-end-of-stream) is fully covered
by the wrapper.
"""
import os
import sys
import uuid
from datetime import datetime
from typing import Any, List, Optional
from unittest.mock import MagicMock, AsyncMock

import pytest
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

# FK targets must be registered before SQLAlchemy resolves the metadata.
from lumen_models.image_generation import GeneratedImage  # noqa: F401
from lumen_models.agent import Agent  # noqa: F401
from lumen_models.agent_team import AgentTeam  # noqa: F401
from lumen_models.embedding_call_log import EmbeddingCallLog  # noqa: F401  # WorkflowRun.embedding_calls FK target
from lumen_models.workflow import Workflow, WorkflowRun  # noqa: F401
from lumen_models.chat import Conversation, Message  # noqa: F401
from lumen_models.model_config import ModelConfig  # noqa: F401

from lumen_core.database import SessionLocal
from lumen_core.llm_call_context import (
    LLMCallContext, set_call_context, reset_call_context, get_call_context,
)
from lumen_models.llm_call_log import LLMCallLog
from lumen_services.model_loader import LoggingChatModel


def _make_ctx(call_type: str = "chat", **overrides) -> LLMCallContext:
    base = dict(
        call_id=str(uuid.uuid4()),
        trace_id=str(uuid.uuid4()),
        parent_call_id=None,
        call_type=call_type,
        call_index=0,
        tenant_id=1,
        user_id=1,
        username="tester",
        conversation_id=42,
        client_app="dashboard",
    )
    base.update(overrides)
    return LLMCallContext(**base)


def _delete_call(call_id: str) -> None:
    db = SessionLocal()
    try:
        db.query(LLMCallLog).filter(LLMCallLog.call_id == call_id).delete()
        db.commit()
    finally:
        db.close()


@pytest.mark.asyncio
async def test_astream_writes_one_row_with_full_content():
    """Streaming path: accumulate all chunks → write 1 row at end."""
    ctx = _make_ctx()
    token = set_call_context(ctx)
    try:
        inner = MagicMock()
        async def fake_astream(messages, **kwargs):
            for c in ["He", "llo", "!"]:
                chunk = MagicMock()
                chunk.content = c
                chunk.tool_calls = []
                chunk.response_metadata = {}
                chunk.usage_metadata = None
                yield chunk
        inner.astream = fake_astream

        proxy = LoggingChatModel(
            inner,
            model_type="ollama",
            model_name="qwen2.5:7b",
            temperature=0.7,
        )
        out: List[Any] = []
        async for chunk in proxy.astream([HumanMessage(content="hi")]):
            out.append(chunk)

        assert [c.content for c in out] == ["He", "llo", "!"]

        # Row written
        db = SessionLocal()
        try:
            row = db.query(LLMCallLog).filter(LLMCallLog.call_id == ctx.call_id).first()
            assert row is not None
            assert row.call_type == "chat"
            assert row.trace_id == ctx.trace_id
            assert row.model_name == "qwen2.5:7b"
            assert row.response_content == "Hello!"
            assert row.output_chars == 6
            assert row.status == "success"
            # input_messages includes the user message
            msgs = row.messages
            assert any(m["role"] == "user" and m["content"] == "hi" for m in msgs)
            # First-token latency was recorded (we got content on first chunk)
            assert row.first_token_latency_ms is not None
            assert row.first_token_latency_ms >= 0
        finally:
            db.close()
    finally:
        reset_call_context(token)
        _delete_call(ctx.call_id)


@pytest.mark.asyncio
async def test_astream_no_active_context_is_transparent():
    """Outside a logged request, the wrapper must not write any row."""
    assert get_call_context() is None  # sanity

    inner = MagicMock()
    async def fake_astream(messages, **kwargs):
        chunk = MagicMock()
        chunk.content = "ok"
        chunk.tool_calls = []
        chunk.response_metadata = {}
        chunk.usage_metadata = None
        yield chunk
    inner.astream = fake_astream
    proxy = LoggingChatModel(inner, model_type="ollama", model_name="m")

    # Snapshot all call_ids before — should not grow
    db = SessionLocal()
    try:
        before = db.query(LLMCallLog.call_id).count()
    finally:
        db.close()

    out = []
    async for chunk in proxy.astream([HumanMessage(content="x")]):
        out.append(chunk)

    db = SessionLocal()
    try:
        after = db.query(LLMCallLog.call_id).count()
    finally:
        db.close()
    assert before == after, "wrapper must not write a row without an active context"


@pytest.mark.asyncio
async def test_astream_with_tool_calls_records_tool_calls_json():
    """Tool-calling round trips: tool_calls JSON column has the calls."""
    ctx = _make_ctx(call_type="chat")
    token = set_call_context(ctx)
    try:
        inner = MagicMock()
        async def fake_astream(messages, **kwargs):
            # First chunk: emits a tool_call
            c1 = MagicMock()
            c1.content = ""
            c1.tool_calls = [{"id": "tc1", "name": "search", "args": {"q": "weather"}}]
            c1.response_metadata = {}
            c1.usage_metadata = None
            yield c1
            # Second chunk: the actual response text
            c2 = MagicMock()
            c2.content = "Sunny."
            c2.tool_calls = []
            c2.response_metadata = {"finish_reason": "stop"}
            c2.usage_metadata = {"input_tokens": 5, "output_tokens": 2, "total_tokens": 7}
            yield c2
        inner.astream = fake_astream

        proxy = LoggingChatModel(inner, model_type="ollama", model_name="m")
        async for _ in proxy.astream([HumanMessage(content="weather?")]):
            pass

        db = SessionLocal()
        try:
            row = db.query(LLMCallLog).filter(LLMCallLog.call_id == ctx.call_id).first()
            assert row is not None
            assert row.tool_calls is not None
            assert len(row.tool_calls) >= 1
            names = [tc.get("name") for tc in row.tool_calls]
            assert "search" in names
            assert row.finish_reason == "stop"
            assert row.token_usage == {
                "prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7,
            }
        finally:
            db.close()
    finally:
        reset_call_context(token)
        _delete_call(ctx.call_id)


@pytest.mark.asyncio
async def test_astream_failure_writes_failure_row():
    """Upstream exception → status=failure + error_type + error_message."""
    ctx = _make_ctx(call_type="chat")
    token = set_call_context(ctx)
    try:
        inner = MagicMock()
        async def fake_astream(messages, **kwargs):
            yield MagicMock(content="partial", tool_calls=[], response_metadata={}, usage_metadata=None)
            raise ConnectionError("upstream timeout")
        inner.astream = fake_astream

        proxy = LoggingChatModel(inner, model_type="ollama", model_name="m")
        with pytest.raises(ConnectionError):
            async for _ in proxy.astream([HumanMessage(content="x")]):
                pass

        db = SessionLocal()
        try:
            row = db.query(LLMCallLog).filter(LLMCallLog.call_id == ctx.call_id).first()
            assert row is not None
            assert row.status == "failure"
            assert row.error_type == "ConnectionError"
            assert "upstream timeout" in (row.error_message or "")
            # Accumulated content preserved
            assert row.response_content == "partial"
        finally:
            db.close()
    finally:
        reset_call_context(token)
        _delete_call(ctx.call_id)


@pytest.mark.asyncio
async def test_invoke_writes_one_row():
    """Sync .invoke path: writes 1 row with response + usage."""
    ctx = _make_ctx(call_type="chat")
    token = set_call_context(ctx)
    try:
        inner = MagicMock()
        resp = AIMessage(
            content="sync-hello",
            usage_metadata={"input_tokens": 3, "output_tokens": 2, "total_tokens": 5},
            response_metadata={"finish_reason": "stop"},
        )
        inner.invoke = MagicMock(return_value=resp)
        proxy = LoggingChatModel(inner, model_type="ollama", model_name="m", temperature=0.5)

        result = proxy.invoke([HumanMessage(content="hi")])
        assert result is resp

        db = SessionLocal()
        try:
            row = db.query(LLMCallLog).filter(LLMCallLog.call_id == ctx.call_id).first()
            assert row is not None
            assert row.response_content == "sync-hello"
            assert row.token_usage == {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}
            assert row.finish_reason == "stop"
            assert row.temperature == 0.5
        finally:
            db.close()
    finally:
        reset_call_context(token)
        _delete_call(ctx.call_id)


@pytest.mark.asyncio
async def test_invoke_failure_writes_failure_row():
    """Sync .invoke path on exception → status=failure."""
    ctx = _make_ctx(call_type="chat")
    token = set_call_context(ctx)
    try:
        inner = MagicMock()
        inner.invoke = MagicMock(side_effect=ValueError("bad prompt"))
        proxy = LoggingChatModel(inner, model_type="ollama", model_name="m")

        with pytest.raises(ValueError):
            proxy.invoke([HumanMessage(content="x")])

        db = SessionLocal()
        try:
            row = db.query(LLMCallLog).filter(LLMCallLog.call_id == ctx.call_id).first()
            assert row is not None
            assert row.status == "failure"
            assert row.error_type == "ValueError"
            assert "bad prompt" in (row.error_message or "")
        finally:
            db.close()
    finally:
        reset_call_context(token)
        _delete_call(ctx.call_id)


@pytest.mark.asyncio
async def test_bind_tools_returns_wrapped_proxy():
    """bind_tools on LoggingChatModel returns another LoggingChatModel (so the
    tool-call loop in chat_service.py stays instrumented)."""
    inner = MagicMock()
    inner.bind_tools = MagicMock(return_value=MagicMock())
    proxy = LoggingChatModel(inner, model_type="ollama", model_name="m")
    bound = proxy.bind_tools([])
    assert isinstance(bound, LoggingChatModel)