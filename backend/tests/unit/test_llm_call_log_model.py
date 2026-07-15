"""M26 model-level tests for ``llm_call_logs``.

Pin down:

- ORM model construction with required + optional fields
- JSON column round-trip (messages / tool_calls / system_messages /
  tools / token_usage / extra) — these are stored as JSON in MySQL and
  the Python side must be willing to serialise + deserialise arbitrary
  dicts.
- Table exists after ``ensure_llm_call_logs_table()`` runs (the
  migration helper is the public entrypoint; this test is the
  regression guard for that helper).

Mirrors the pattern of other model-level tests in the suite (see
``test_image_generation_model.py``-style — adapt as needed).
"""
import json
import os
import sys
import uuid
from datetime import datetime

import pytest
from sqlalchemy import inspect

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

# FK targets must be registered before SQLAlchemy resolves the metadata;
# mirrors the main.py:35-53 import ordering.
from lumen_models.image_generation import GeneratedImage  # noqa: F401
from lumen_models.agent import Agent  # noqa: F401
from lumen_models.agent_team import AgentTeam  # noqa: F401
from lumen_models.workflow import Workflow, WorkflowRun  # noqa: F401
from lumen_models.chat import Conversation, Message  # noqa: F401
from lumen_models.model_config import ModelConfig  # noqa: F401
from lumen_core.database import SessionLocal, ensure_llm_call_logs_table, engine
from lumen_models.llm_call_log import LLMCallLog


def test_table_created_with_expected_columns():
    """ensure_llm_call_logs_table() creates the table with all M26 columns."""
    ensure_llm_call_logs_table()
    insp = inspect(engine)
    cols = {c["name"]: c for c in insp.get_columns("llm_call_logs")}
    expected = [
        "call_id", "parent_call_id", "trace_id", "call_type", "call_index",
        "tenant_id", "user_id", "username", "client_app",
        "conversation_id", "message_id", "agent_id",
        "team_id", "team_member_id", "workflow_id", "workflow_run_id",
        "workflow_node_id", "image_id",
        "model_type", "model_name", "model_config_id",
        "temperature", "max_tokens",
        "system_messages", "user_message", "messages", "tools",
        "extra_params", "input_chars", "input_tokens_estimate",
        "response_content", "finish_reason", "tool_calls",
        "output_chars", "output_tokens_estimate", "token_usage",
        "started_at", "finished_at", "duration_ms",
        "first_token_latency_ms", "status", "error_type", "error_message",
        "retry_count", "request_ip", "user_agent", "extra",
        # From BaseModel
        "id", "created_at", "updated_at",
    ]
    for col in expected:
        assert col in cols, f"missing column: {col}"


def test_migration_is_idempotent():
    """Running ensure_llm_call_logs_table() twice must not raise."""
    ensure_llm_call_logs_table()
    ensure_llm_call_logs_table()
    ensure_llm_call_logs_table()
    # No exception = pass


def test_insert_and_fetch_row_basic():
    """Round-trip: insert a minimal row, fetch by call_id, check fields."""
    call_id = f"test-{uuid.uuid4().hex[:8]}"
    trace_id = f"trace-{uuid.uuid4().hex[:8]}"
    db = SessionLocal()
    try:
        row = LLMCallLog(
            call_id=call_id,
            trace_id=trace_id,
            call_type="chat",
            call_index=0,
            tenant_id=1,
            user_id=1,
            username="tester",
            model_name="qwen2.5:7b",
            started_at=datetime.utcnow(),
            status="success",
            duration_ms=42,
        )
        db.add(row)
        db.commit()
        db.refresh(row)

        fetched = db.query(LLMCallLog).filter(LLMCallLog.call_id == call_id).first()
        assert fetched is not None
        assert fetched.call_id == call_id
        assert fetched.trace_id == trace_id
        assert fetched.call_type == "chat"
        assert fetched.tenant_id == 1
        assert fetched.duration_ms == 42
        assert fetched.status == "success"
        assert fetched.id is not None  # autoincrement
    finally:
        db.query(LLMCallLog).filter(LLMCallLog.call_id == call_id).delete()
        db.commit()
        db.close()


def test_insert_and_fetch_row_json_fields():
    """JSON columns (messages / tool_calls / system_messages / tools / token_usage / extra)
    must round-trip arbitrary dicts."""
    call_id = f"test-{uuid.uuid4().hex[:8]}"
    db = SessionLocal()
    try:
        messages = [
            {"role": "system", "content": "You are a helper."},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi!", "tool_calls": [
                {"id": "call_1", "name": "add", "args": {"a": 1, "b": 2}}
            ]},
            {"role": "tool", "content": "3", "tool_call_id": "call_1"},
        ]
        system_messages = [{"role": "system", "content": "You are a helper.", "layer": "agent_prompt"}]
        tool_calls = [
            {"name": "add", "args": {"a": 1, "b": 2}, "result": "3",
             "tool_call_id": "call_1", "round": 1, "latency_ms": 12}
        ]
        tools = [{"name": "add", "description": "Add two numbers",
                  "parameters_schema": {"type": "object",
                                        "properties": {"a": {"type": "number"}}}}]
        token_usage = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
        extra = {"visitor_id": "v-12345", "kb_ids": [1, 2, 3]}

        row = LLMCallLog(
            call_id=call_id,
            trace_id="trace-xyz",
            call_type="widget",
            model_name="qwen2.5:7b",
            started_at=datetime.utcnow(),
            finished_at=datetime.utcnow(),
            duration_ms=120,
            messages=messages,
            system_messages=system_messages,
            tools=tools,
            tool_calls=tool_calls,
            token_usage=token_usage,
            extra=extra,
            status="success",
        )
        db.add(row)
        db.commit()
        db.refresh(row)

        fetched = db.query(LLMCallLog).filter(LLMCallLog.call_id == call_id).first()
        assert fetched.messages == messages
        assert fetched.system_messages == system_messages
        assert fetched.tools == tools
        assert fetched.tool_calls == tool_calls
        assert fetched.token_usage == token_usage
        assert fetched.extra == extra
    finally:
        db.query(LLMCallLog).filter(LLMCallLog.call_id == call_id).delete()
        db.commit()
        db.close()


def test_unique_call_id_constraint():
    """call_id has a UNIQUE constraint — duplicate insert must fail."""
    call_id = f"test-dup-{uuid.uuid4().hex[:8]}"
    db = SessionLocal()
    try:
        a = LLMCallLog(call_id=call_id, trace_id="t1", call_type="chat",
                       model_name="m", started_at=datetime.utcnow())
        db.add(a)
        db.commit()
        b = LLMCallLog(call_id=call_id, trace_id="t2", call_type="chat",
                       model_name="m", started_at=datetime.utcnow())
        db.add(b)
        with pytest.raises(Exception):
            db.commit()
        db.rollback()
    finally:
        db.query(LLMCallLog).filter(LLMCallLog.call_id == call_id).delete()
        db.commit()
        db.close()


def test_composite_indexes_exist():
    """The 7 composite indexes from the spec must be created."""
    ensure_llm_call_logs_table()
    insp = inspect(engine)
    indexes = {ix["name"]: ix for ix in insp.get_indexes("llm_call_logs")}
    expected = [
        "idx_lcl_tenant_time", "idx_lcl_module_time", "idx_lcl_model_time",
        "idx_lcl_conv_time", "idx_lcl_workflow", "idx_lcl_trace",
        "idx_lcl_status_time",
    ]
    for ix in expected:
        assert ix in indexes, f"missing composite index: {ix}"