"""M33: integration test — engine writes 2 LLMCallLog rows on success,
1 on guard-rejected failure.

Spec: docs/superpowers/specs/2026-06-20-text2sql-design.md §5

We exercise the real LLMCallLoggingService + the real DB so the
integration contract is locked: the call_type strings fit, the
trace_id is shared, and parent_call_id links Phase 2 to Phase 1.
"""
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

# FK targets must be registered before SQLAlchemy resolves the
# LLMCallLog metadata (mirrors the main.py:35-53 pattern).
from lumen_models.llm_call_log import LLMCallLog  # noqa: F401
from lumen_models.embedding_call_log import EmbeddingCallLog  # noqa: F401
from lumen_models.agent import Agent  # noqa: F401
from lumen_models.agent_team import AgentTeam  # noqa: F401
from lumen_models.workflow import Workflow, WorkflowRun  # noqa: F401
from lumen_models.chat import Conversation, Message  # noqa: F401
from lumen_models.text2sql import Text2SqlDataSource  # noqa: F401
from lumen_models.image_generation import GeneratedImage  # noqa: F401
from lumen_models.model_config import ModelConfig  # noqa: F401
from lumen_models.skill_marketplace import SkillMarketplace  # noqa: F401

from lumen_core.database import SessionLocal
from lumen_services.text2sql.engine import Text2SqlEngine


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #


def _make_data_source() -> Text2SqlDataSource:
    return Text2SqlDataSource(
        tenant_id=1,
        name="intg_test",
        db_name="ai_platform",
        max_rows=10,
        timeout_ms=1000,
        is_active=1,
    )


class _FakeChatModel:
    """Sequence-based fake; the engine asks it for the n-th response."""

    def __init__(self, responses: List[str]) -> None:
        self._responses = list(responses)
        self._call_count = 0

    def invoke(self, messages: List[Any]) -> Any:
        idx = min(self._call_count, len(self._responses) - 1)
        self._call_count += 1
        resp = MagicMock()
        resp.content = self._responses[idx]
        resp.response_metadata = {"finish_reason": "stop"}
        return resp


def _count_logs(trace_id: str, call_type: str) -> int:
    db = SessionLocal()
    try:
        return (
            db.query(LLMCallLog)
            .filter(
                LLMCallLog.trace_id == trace_id,
                LLMCallLog.call_type == call_type,
            )
            .count()
        )
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# Tests                                                                       #
# --------------------------------------------------------------------------- #


@pytest.mark.usefixtures("tmp_user")
def test_engine_writes_two_llm_logs_on_success():
    """On a successful ask, exactly one ``text2sql.generate`` row AND
    one ``text2sql.explain`` row must be persisted under the same
    trace_id; the explain row's parent_call_id is the generate
    row's call_id.
    """
    import uuid
    trace_id = f"m33-trace-{uuid.uuid4().hex[:8]}"
    db = SessionLocal()
    try:
        engine = Text2SqlEngine(db, _make_data_source(), max_retries=3)
        fake = _FakeChatModel(
            responses=[
                "SELECT 1 AS one",  # generate
                "一行一列,值 1。\n置信度: 0.9",  # explain
            ]
        )
        with patch(
            "lumen_services.text2sql.engine.create_chat_model", return_value=fake
        ):
            result = engine.ask(
                "test",
                user_id=1,
                tenant_id=1,
                trace_id=trace_id,
            )
        assert result.status == "success"
        assert result.generate_call_id is not None
        assert result.explain_call_id is not None

        # Verify LLMCallLog rows
        assert _count_logs(trace_id, "text2sql.generate") == 1
        assert _count_logs(trace_id, "text2sql.explain") == 1

        # Verify parent_call_id linkage
        db.expire_all()
        explain_row = (
            db.query(LLMCallLog)
            .filter(
                LLMCallLog.trace_id == trace_id,
                LLMCallLog.call_type == "text2sql.explain",
            )
            .first()
        )
        generate_row = (
            db.query(LLMCallLog)
            .filter(
                LLMCallLog.trace_id == trace_id,
                LLMCallLog.call_type == "text2sql.generate",
            )
            .first()
        )
        assert explain_row.parent_call_id == generate_row.call_id
    finally:
        db.close()


@pytest.mark.usefixtures("tmp_user")
def test_engine_writes_one_llm_log_on_rejection():
    """When SQLGuard vetoes every attempt, we must write N generate rows
    (one per retry — the LLM is called max_retries times) and 0
    explain rows (Phase 2 never started because Phase 1 never
    produced a valid SQL).
    """
    import uuid
    trace_id = f"m33-trace-{uuid.uuid4().hex[:8]}"
    db = SessionLocal()
    try:
        # max_retries=2 → 2 LLM calls in Phase 1, 0 in Phase 2
        engine = Text2SqlEngine(db, _make_data_source(), max_retries=2)
        fake = _FakeChatModel(
            responses=[
                "SELECT * FROM no_such_table_xyz",  # attempt 1
                "SELECT * FROM another_bad",  # attempt 2
            ]
        )
        with patch(
            "lumen_services.text2sql.engine.create_chat_model", return_value=fake
        ):
            result = engine.ask(
                "test",
                user_id=1,
                tenant_id=1,
                trace_id=trace_id,
            )
        assert result.status in {"rejected", "failed"}
        assert _count_logs(trace_id, "text2sql.generate") == 2
        assert _count_logs(trace_id, "text2sql.explain") == 0
    finally:
        db.close()
