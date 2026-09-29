"""T1.5 AgentRun ORM model tests.

Pin down the contract for M39 multi-agent-team upgrade §3.1:

- AgentRunStatus enum string values (the public wire format)
- AgentRun table columns (everything required by checkpointing + HiTL + metrics)
- Composite indexes for thread lookups + run listing
- status default is "running"

Spec: docs-internal/superpowers/specs/2026-09-29-multi-agent-team-upgrade-design.md §3.1
"""
from datetime import datetime

from lumen_models.agent_team_run import AgentRun, AgentRunStatus


def test_status_enum_values():
    assert AgentRunStatus.RUNNING == "running"
    assert AgentRunStatus.AWAITING_PLAN == "awaiting_plan"
    assert AgentRunStatus.AWAITING_RESULT == "awaiting_result"
    assert AgentRunStatus.COMPLETED == "completed"
    assert AgentRunStatus.FAILED == "failed"
    assert AgentRunStatus.CANCELLED == "cancelled"


def test_tablename_and_required_columns():
    cols = {c.name for c in AgentRun.__table__.columns}
    must = {"team_id", "conversation_id", "user_id", "tenant_id",
            "thread_id", "checkpoint_ns", "status", "interrupt_payload",
            "final_answer", "msg_metadata", "latest_checkpoint_id",
            "awaiting_since_at", "token_count", "latency_ms",
            "error_message", "created_at", "updated_at"}
    assert must.issubset(cols), f"missing: {must - cols}"


def test_thread_id_index_present():
    idx_cols = []
    for idx in AgentRun.__table__.indexes:
        idx_cols.extend(idx.columns.keys())
    assert "tenant_id" in idx_cols and "thread_id" in idx_cols


def test_default_status_is_running():
    assert AgentRun.status.default.arg == "running"
