"""M26 service-level tests for llm_call_logging helpers.

Covers:

- ``extract_usage`` — both LangChain 1.0 ``usage_metadata`` and
  ``response_metadata.usage`` shapes, plus the None case (Ollama).
- ``extract_finish_reason`` — provider-reported + tool_calls fallback + None.
- ``serialize_message`` / ``serialize_messages`` — handles HumanMessage /
  SystemMessage / AIMessage / AIMessage-with-tool_calls / ToolMessage,
  including the structured content (list-of-parts) case.
- ``serialize_tools`` — BaseTool with Pydantic args_schema + fallback
  to ``args`` dict.
- ``LLMCallLoggingService.log_call`` — happy path + hard-failure path
  (must NOT bubble up the error so observability can't break the
  actual LLM stream).
"""
import os
import sys
import uuid
from datetime import datetime
from typing import Any, Dict, List
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import (
    AIMessage, HumanMessage, SystemMessage, ToolMessage,
)
from pydantic import BaseModel

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

# FK targets must be registered before SQLAlchemy resolves the metadata.
from lumen_models.image_generation import GeneratedImage  # noqa: F401
from lumen_models.agent import Agent  # noqa: F401
from lumen_models.agent_team import AgentTeam  # noqa: F401
from lumen_models.workflow import Workflow, WorkflowRun  # noqa: F401
from lumen_models.chat import Conversation, Message  # noqa: F401
from lumen_models.model_config import ModelConfig  # noqa: F401

from lumen_core.llm_call_context import LLMCallContext
from lumen_services.llm_call_logging import (
    LLMCallLoggingService,
    extract_usage,
    extract_finish_reason,
    serialize_message,
    serialize_messages,
    serialize_tools,
)
from lumen_core.database import SessionLocal
from lumen_models.llm_call_log import LLMCallLog


# ---------------------------------------------------------------------------
# extract_usage
# ---------------------------------------------------------------------------

def test_extract_usage_langchain_standard():
    resp = AIMessage(
        content="hello",
        usage_metadata={"input_tokens": 7, "output_tokens": 3, "total_tokens": 10},
    )
    assert extract_usage(resp) == {
        "prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10,
    }


def test_extract_usage_response_metadata():
    resp = AIMessage(
        content="hello",
        response_metadata={"usage": {"prompt_tokens": 20, "completion_tokens": 5, "total_tokens": 25}},
    )
    assert extract_usage(resp) == {
        "prompt_tokens": 20, "completion_tokens": 5, "total_tokens": 25,
    }


def test_extract_usage_response_metadata_token_usage_key():
    resp = AIMessage(
        content="hello",
        response_metadata={"token_usage": {"prompt_tokens": 11, "completion_tokens": 4, "total_tokens": 15}},
    )
    assert extract_usage(resp) == {
        "prompt_tokens": 11, "completion_tokens": 4, "total_tokens": 15,
    }


def test_extract_usage_returns_none_for_ollama():
    resp = AIMessage(content="hello")
    assert extract_usage(resp) is None


def test_extract_usage_returns_none_for_none():
    assert extract_usage(None) is None


# ---------------------------------------------------------------------------
# extract_finish_reason
# ---------------------------------------------------------------------------

def test_extract_finish_reason_from_response_metadata():
    resp = AIMessage(content="hi", response_metadata={"finish_reason": "stop"})
    assert extract_finish_reason(resp) == "stop"


def test_extract_finish_reason_anthropic_style():
    resp = AIMessage(content="hi", response_metadata={"stop_reason": "end_turn"})
    assert extract_finish_reason(resp) == "end_turn"


def test_extract_finish_reason_inferred_from_tool_calls():
    resp = AIMessage(
        content="",
        tool_calls=[{"id": "c1", "name": "search", "args": {}}],
    )
    assert extract_finish_reason(resp) == "tool_calls"


def test_extract_finish_reason_none_when_silent():
    resp = AIMessage(content="hi")
    assert extract_finish_reason(resp) is None


def test_extract_finish_reason_none_for_none_response():
    assert extract_finish_reason(None) is None


# ---------------------------------------------------------------------------
# serialize_message / serialize_messages
# ---------------------------------------------------------------------------

def test_serialize_human_message():
    msg = HumanMessage(content="hi")
    out = serialize_message(msg)
    assert out["role"] == "user"
    assert out["content"] == "hi"


def test_serialize_system_message():
    msg = SystemMessage(content="be helpful")
    out = serialize_message(msg)
    assert out["role"] == "system"
    assert out["content"] == "be helpful"


def test_serialize_ai_message_with_tool_calls():
    msg = AIMessage(
        content="calling",
        tool_calls=[{"id": "c1", "name": "search", "args": {"q": "x"}}],
    )
    out = serialize_message(msg)
    assert out["role"] == "assistant"
    assert out["content"] == "calling"
    assert out["tool_calls"] == [
        {"id": "c1", "name": "search", "args": {"q": "x"}}
    ]


def test_serialize_tool_message():
    msg = ToolMessage(content="42", tool_call_id="call_xyz")
    out = serialize_message(msg)
    assert out["role"] == "tool"
    assert out["content"] == "42"
    assert out["tool_call_id"] == "call_xyz"


def test_serialize_message_structured_content_list():
    msg = AIMessage(content=[
        {"type": "text", "text": "hello "},
        {"type": "text", "text": "world"},
    ])
    out = serialize_message(msg)
    assert out["content"] == "hello world"


def test_serialize_message_filters_response_metadata_keys():
    msg = AIMessage(
        content="hi",
        response_metadata={
            "model": "gpt-4",
            "finish_reason": "stop",
            "raw_http_request": "<huge blob>",
        },
    )
    out = serialize_message(msg)
    rm = out["response_metadata"]
    assert rm == {"model": "gpt-4", "finish_reason": "stop"}
    assert "raw_http_request" not in rm


def test_serialize_messages_list():
    msgs = [SystemMessage(content="sys"), HumanMessage(content="hi")]
    out = serialize_messages(msgs)
    assert len(out) == 2
    assert out[0]["role"] == "system"
    assert out[1]["role"] == "user"


# ---------------------------------------------------------------------------
# serialize_tools
# ---------------------------------------------------------------------------

def test_serialize_tools_with_pydantic_schema():
    class _AddInput(BaseModel):
        a: int
        b: int

    tool = MagicMock()
    tool.name = "add"
    tool.description = "Add two ints"
    tool.args_schema = _AddInput
    # No legacy ``args`` attribute on this mock
    del tool.args

    out = serialize_tools([tool])
    assert out == [
        {
            "name": "add",
            "description": "Add two ints",
            "parameters_schema": _AddInput.model_json_schema(),
        }
    ]


def test_serialize_tools_empty_list():
    assert serialize_tools(None) == []
    assert serialize_tools([]) == []


def test_serialize_tools_falls_back_to_args_dict():
    """Older tools without a Pydantic schema use the ``args`` dict."""

    class _OldStyleTool:
        name = "echo"
        description = "Echo"
        # No ``args_schema`` attribute at all.
        args = {"text": {"type": "string", "description": "text to echo"}}

    tool = _OldStyleTool()
    out = serialize_tools([tool])
    assert out[0]["name"] == "echo"
    assert out[0]["parameters_schema"] == {
        "type": "object",
        "properties": {"text": {"type": "string", "description": "text to echo"}},
    }


# ---------------------------------------------------------------------------
# LLMCallLoggingService.log_call
# ---------------------------------------------------------------------------

def _make_ctx(**overrides) -> LLMCallContext:
    base = dict(
        call_id=str(uuid.uuid4()),
        trace_id=str(uuid.uuid4()),
        parent_call_id=None,
        call_type="chat",
        call_index=0,
        tenant_id=1,
        user_id=1,
        username="tester",
        conversation_id=None,
        agent_id=None,
        client_app="dashboard",
    )
    base.update(overrides)
    return LLMCallContext(**base)


def test_log_call_happy_path_writes_row():
    ctx = _make_ctx()
    db = SessionLocal()
    try:
        svc = LLMCallLoggingService()
        row = svc.log_call(
            db,
            ctx=ctx,
            model_type="ollama",
            model_name="qwen2.5:7b",
            temperature=0.7,
            max_tokens=None,
            system_messages=[{"role": "system", "content": "be helpful"}],
            user_message="hello",
            messages=[
                {"role": "system", "content": "be helpful"},
                {"role": "user", "content": "hello"},
            ],
            tools=None,
            extra_params=None,
            response_content="hi there",
            finish_reason="stop",
            tool_calls=None,
            token_usage={"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6},
            started_at=datetime.utcnow(),
            finished_at=datetime.utcnow(),
            duration_ms=42,
            status="success",
        )
        assert row is not None
        assert row.call_id == ctx.call_id
        assert row.trace_id == ctx.trace_id
        assert row.call_type == "chat"
        assert row.model_name == "qwen2.5:7b"
        assert row.temperature == 0.7
        assert row.response_content == "hi there"
        assert row.finish_reason == "stop"
        assert row.token_usage == {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6}
        assert row.duration_ms == 42
        assert row.status == "success"
        assert row.input_chars > 0
        assert row.input_tokens_estimate > 0
        assert row.output_chars == len("hi there")
    finally:
        db.query(LLMCallLog).filter(LLMCallLog.call_id == ctx.call_id).delete()
        db.commit()
        db.close()


def test_log_call_failure_status_writes_error():
    ctx = _make_ctx(call_type="team.worker")
    db = SessionLocal()
    try:
        svc = LLMCallLoggingService()
        row = svc.log_call(
            db,
            ctx=ctx,
            model_type="ollama",
            model_name="qwen2.5:7b",
            temperature=None,
            max_tokens=None,
            system_messages=None,
            user_message="hi",
            messages=[{"role": "user", "content": "hi"}],
            tools=None,
            extra_params=None,
            response_content=None,
            finish_reason=None,
            tool_calls=None,
            token_usage=None,
            started_at=datetime.utcnow(),
            finished_at=datetime.utcnow(),
            duration_ms=10,
            status="failure",
            error_type="ConnectionError",
            error_message="upstream model unavailable",
        )
        assert row is not None
        assert row.status == "failure"
        assert row.error_type == "ConnectionError"
        assert row.error_message == "upstream model unavailable"
        assert row.call_type == "team.worker"
    finally:
        db.query(LLMCallLog).filter(LLMCallLog.call_id == ctx.call_id).delete()
        db.commit()
        db.close()


def test_log_call_does_not_bubble_up_db_error():
    """A broken payload must NOT raise — observability can't break LLM."""
    class _BrokenSession:
        def add(self, _):
            raise RuntimeError("simulated DB failure")
        def commit(self):
            raise RuntimeError("simulated DB failure")
        def rollback(self):
            pass
        def refresh(self, _):
            pass

    ctx = _make_ctx()
    # No exception should escape:
    row = LLMCallLoggingService().log_call(
        _BrokenSession(),
        ctx=ctx,
        model_type="ollama",
        model_name="m",
        temperature=None,
        max_tokens=None,
        system_messages=None,
        user_message=None,
        messages=[],
        response_content=None,
        finish_reason=None,
        started_at=datetime.utcnow(),
        finished_at=datetime.utcnow(),
        duration_ms=0,
        status="success",
    )
    assert row is None