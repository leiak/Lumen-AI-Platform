"""M26 Workflow LLM-node LLMCallLog tests.

Exercises ``LLMNode._run`` end-to-end:

- The wrapper writes one row with ``call_type='workflow.llm'``,
  carrying workflow_id / workflow_run_id / workflow_node_id.
- The simple path reads real ``finish_reason`` and ``usage`` from the
  response (M26 closes the historical hard-coded "stop" / 0-token
  placeholders).
- Tool-loop path also writes a row (the LLMCallLog's tool_calls JSON
  column captures the round, but the underlying response object is
  consumed inside the loop — we accept the MVP trade-off of
  finish_reason="stop" + zero usage on tool-loop rows).

We patch ``create_chat_model`` to return a real ``LoggingChatModel``
wrapping a fake inner — that way the wrapper sees the per-node context
and writes the row.
"""
import os
import sys
import uuid
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

# FK targets must be registered before SQLAlchemy resolves the metadata.
from lumen_models.image_generation import GeneratedImage  # noqa: F401
from lumen_models.agent import Agent  # noqa: F401
from lumen_models.agent_team import AgentTeam  # noqa: F401
from lumen_models.workflow import Workflow, WorkflowRun  # noqa: F401
from lumen_models.chat import Conversation, Message  # noqa: F401
from lumen_models.model_config import ModelConfig  # noqa: F401

from lumen_core.database import SessionLocal
from lumen_core.workflow.variable_pool import VariablePool
from lumen_models.llm_call_log import LLMCallLog
from lumen_services.model_loader import LoggingChatModel


def _cleanup_logs(trace_id: str) -> None:
    db = SessionLocal()
    try:
        db.query(LLMCallLog).filter(LLMCallLog.trace_id == trace_id).delete()
        db.commit()
    finally:
        db.close()


def _make_wrapped_llm(*, content="Hello!", usage=None, finish_reason="stop",
                      raise_exc=None) -> LoggingChatModel:
    inner = MagicMock()
    if raise_exc is not None:
        inner.invoke = MagicMock(side_effect=raise_exc)
    else:
        kwargs = {"content": content}
        if usage is not None:
            kwargs["usage_metadata"] = usage
        if finish_reason is not None:
            kwargs["response_metadata"] = {"finish_reason": finish_reason}
        inner.invoke = MagicMock(return_value=AIMessage(**kwargs))
    return LoggingChatModel(
        inner,
        model_type="ollama",
        model_name="qwen2.5:7b",
        temperature=0.5,
    )


@pytest.mark.asyncio
async def test_llm_node_simple_path_writes_row_and_real_usage():
    """Simple path: row written with call_type=workflow.llm,
    finish_reason + usage read from response (closes the 0-token TODO).

    workflow_id / workflow_run_id are NOT set here — the FK constraint
    would require a real workflows row, and the FK propagation is
    tested elsewhere (see workflow_integration tests). This test pins
    down the LLMNode instrumentation contract.
    """
    from lumen_core.workflow.nodes.llm import LLMNode

    trace_id = str(uuid.uuid4())
    config = {
        "version": "1",
        "model_name": "qwen2.5:7b",
        "prompt": "Say hi",
        "system_prompt": "be friendly",
        "temperature": 0.5,
        "skill_ids": [],
        "tenant_id": 1,
        "workflow_id": None,
        "workflow_run_id": None,
        "trace_id": trace_id,
    }
    pool = VariablePool()
    node = LLMNode(
        node_id="llm-1",
        config=config,
        pool=pool,
        db=MagicMock(),  # not used (no skill_ids)
        tenant_id=1,
    )

    wrapped = _make_wrapped_llm(
        content="Hello!",
        usage={"input_tokens": 5, "output_tokens": 3, "total_tokens": 8},
        finish_reason="stop",
    )

    with patch("lumen_core.workflow.nodes.llm.create_chat_model", return_value=wrapped):
        result = await node._run()

    try:
        # Validate NodeRunResult carries the real values (closes the 0-token TODO)
        assert result.output_values["response"] == "Hello!"
        assert result.output_values["finish_reason"] == "stop"
        assert result.output_values["usage"] == {
            "prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8,
        }

        # Validate the LLMCallLog row
        db = SessionLocal()
        try:
            row = db.query(LLMCallLog).filter(LLMCallLog.trace_id == trace_id).first()
        finally:
            db.close()

        assert row is not None
        assert row.call_type == "workflow.llm"
        assert row.workflow_id is None  # not set in test
        assert row.workflow_run_id is None
        assert row.workflow_node_id == "llm-1"
        assert row.model_name == "qwen2.5:7b"
        assert row.temperature == 0.5
        assert row.response_content == "Hello!"
        assert row.finish_reason == "stop"
        assert row.token_usage == {
            "prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8,
        }
        assert row.tenant_id == 1
        assert row.status == "success"
    finally:
        _cleanup_logs(trace_id)


@pytest.mark.asyncio
async def test_llm_node_ollama_no_usage_yields_null_token_usage():
    """Ollama doesn't report usage → row's token_usage is None (UI shows 'N/A')."""
    from lumen_core.workflow.nodes.llm import LLMNode

    trace_id = str(uuid.uuid4())
    config = {
        "version": "1",
        "model_name": "qwen2.5:7b",
        "prompt": "Hi",
        "system_prompt": "",
        "temperature": 0.7,
        "skill_ids": [],
        "tenant_id": 1,
        "workflow_id": None,
        "workflow_run_id": None,
        "trace_id": trace_id,
    }
    pool = VariablePool()
    node = LLMNode(
        node_id="llm-ollama",
        config=config,
        pool=pool,
        db=MagicMock(),
        tenant_id=1,
    )

    # Ollama-style: AIMessage with no usage_metadata + no finish_reason in metadata
    wrapped = _make_wrapped_llm(content="ollama hi", usage=None, finish_reason=None)

    with patch("lumen_core.workflow.nodes.llm.create_chat_model", return_value=wrapped):
        result = await node._run()

    try:
        # finish_reason still defaults to "stop" when not reported (existing
        # NodeRunResult contract)
        assert result.output_values["finish_reason"] == "stop"
        # usage falls back to zeros for the NodeRunResult (MVP trade-off)
        assert result.output_values["usage"] == {
            "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
        }

        db = SessionLocal()
        try:
            row = db.query(LLMCallLog).filter(LLMCallLog.trace_id == trace_id).first()
        finally:
            db.close()

        assert row is not None
        # The LLMCallLog row's token_usage is None — UI displays "N/A"
        assert row.token_usage is None
    finally:
        _cleanup_logs(trace_id)


@pytest.mark.asyncio
async def test_llm_node_failure_path_writes_failure_row():
    """LLM raises → LLMCallLog status=failure + error_type / error_message."""
    from lumen_core.workflow.nodes.llm import LLMNode

    trace_id = str(uuid.uuid4())
    config = {
        "version": "1",
        "model_name": "qwen2.5:7b",
        "prompt": "x",
        "system_prompt": "",
        "temperature": 0.7,
        "skill_ids": [],
        "tenant_id": 1,
        "workflow_id": None,
        "workflow_run_id": None,
        "trace_id": trace_id,
    }
    pool = VariablePool()
    node = LLMNode(
        node_id="llm-fail",
        config=config,
        pool=pool,
        db=MagicMock(),
        tenant_id=1,
    )

    wrapped = _make_wrapped_llm(raise_exc=RuntimeError("upstream connection refused"))

    with patch("lumen_core.workflow.nodes.llm.create_chat_model", return_value=wrapped):
        with pytest.raises(RuntimeError):
            await node._run()

    try:
        db = SessionLocal()
        try:
            row = db.query(LLMCallLog).filter(LLMCallLog.trace_id == trace_id).first()
        finally:
            db.close()

        assert row is not None
        assert row.status == "failure"
        assert row.error_type == "RuntimeError"
        assert "upstream connection refused" in (row.error_message or "")
        assert row.workflow_node_id == "llm-fail"
    finally:
        _cleanup_logs(trace_id)