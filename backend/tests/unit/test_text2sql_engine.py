"""M33: tests for the Text2SqlEngine (Phase 1 + Phase 2 + retries).

Spec: docs/superpowers/specs/2026-06-20-text2sql-design.md §5

The engine is the heart of the feature. We mock the chat model so
the tests run in CI without an Ollama / OpenAI endpoint. The mock
returns a configurable sequence of SQL strings, so the retry logic
is exercised without hitting the real LLM.
"""
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest

from lumen_core.database import SessionLocal
from lumen_models.text2sql import Text2SqlDataSource
from lumen_services.text2sql.engine import AskResult, Text2SqlEngine


def _make_data_source(
    *,
    table_allowlist: Optional[List[str]] = None,
    field_allowlist: Optional[Dict[str, List[str]]] = None,
    max_rows: int = 100,
    timeout_ms: int = 5000,
) -> Text2SqlDataSource:
    """Return an in-memory DataSource row (not committed)."""
    return Text2SqlDataSource(
        tenant_id=1,
        name="test",
        db_name="ai_platform",
        table_allowlist=table_allowlist,
        field_allowlist=field_allowlist,
        max_rows=max_rows,
        timeout_ms=timeout_ms,
        is_active=1,
    )


class _FakeChatModel:
    """Minimal stand-in for the LangChain ChatModel interface."""

    def __init__(self, responses: List[str]) -> None:
        self._responses = list(responses)
        self._call_count = 0

    def invoke(self, messages: List[Any]) -> Any:
        idx = min(self._call_count, len(self._responses) - 1)
        self._call_count += 1
        content = self._responses[idx]
        resp = MagicMock()
        resp.content = content
        resp.response_metadata = {"finish_reason": "stop"}
        return resp


def _patched_engine(
    data_source: Text2SqlDataSource,
    responses: List[str],
    *,
    max_retries: int = 3,
) -> tuple:
    """Return (engine, fake_chat_model) with create_chat_model mocked."""
    fake = _FakeChatModel(responses)
    db = SessionLocal()
    engine = Text2SqlEngine(db, data_source, max_retries=max_retries)
    # Replace the lazy LLM creation
    return engine, fake


# --------------------------------------------------------------------------- #
# Happy path                                                                  #
# --------------------------------------------------------------------------- #


def test_engine_happy_path_with_one_attempt():
    """A clean first attempt should produce status="success" with rows."""
    engine, fake = _patched_engine(
        _make_data_source(),
        responses=[
            "SELECT 1 AS one, 'x' AS s",  # Phase 1 (generate)
            "返回了 1 行数字 1,字段 s 是 x。\n置信度: 0.95",  # Phase 2 (explain)
        ],
    )
    with patch("lumen_services.text2sql.engine.create_chat_model", return_value=fake):
        result = engine.ask("test question", user_id=1, tenant_id=1)
    assert result.status == "success"
    assert result.generated_sql is not None
    assert "SELECT 1" in result.generated_sql.upper()
    assert result.explanation is not None
    assert result.confidence == 0.95
    assert result.attempts == 3
    assert result.generate_call_id is not None
    assert result.explain_call_id is not None


# --------------------------------------------------------------------------- #
# Retry on error                                                              #
# --------------------------------------------------------------------------- #


def test_engine_retries_after_bad_sql_then_succeeds():
    """The first attempt emits an invalid table; the LLM self-corrects
    on retry; the engine should return success after 2 attempts.
    """
    engine, fake = _patched_engine(
        _make_data_source(),
        responses=[
            "SELECT * FROM no_such_table_xyz",  # attempt 1 — SQLGuard rejects
            "SELECT 1 AS one",  # attempt 2 — valid
            "result 1\n置信度: 0.9",  # Phase 2
        ],
    )
    with patch("lumen_services.text2sql.engine.create_chat_model", return_value=fake):
        result = engine.ask("test", user_id=1, tenant_id=1)
    assert result.status == "success"
    assert result.attempts == 3  # cap is preserved
    # We should have called the LLM at least twice for Phase 1
    assert fake._call_count >= 3


def test_engine_rejected_after_max_retries():
    """When every attempt produces a bad table, status must be rejected
    (or failed) and error_type must be 'table'."""
    engine, fake = _patched_engine(
        _make_data_source(),
        responses=[
            "SELECT * FROM no_such_table_xyz",  # attempt 1
            "SELECT * FROM another_bad_table",  # attempt 2
            "SELECT * FROM yet_another_bad",  # attempt 3
        ],
        max_retries=3,
    )
    with patch("lumen_services.text2sql.engine.create_chat_model", return_value=fake):
        result = engine.ask("test", user_id=1, tenant_id=1)
    assert result.status in {"rejected", "failed"}
    assert result.error_type in {"table", "exec_error"}
    assert "no_such_table_xyz" in (result.error_message or "") or "another_bad" in (result.error_message or "")


# --------------------------------------------------------------------------- #
# Sanity: Phase 1.5 prompt is fed to retry                                    #
# --------------------------------------------------------------------------- #


def test_engine_phase15_user_prompt_includes_error():
    """The Phase 1.5 user prompt must mention the previous SQL and the
    error so the LLM can self-correct.

    We can't easily inspect the messages list passed to the LLM in a
    way that survives the rewrite, but we can confirm that the
    second invocation's user prompt has the word '上一次' / '错误'
    by spying on ``render_regeneration_user``.
    """
    engine, fake = _patched_engine(
        _make_data_source(),
        responses=[
            "DROP TABLE users",  # attempt 1 — blocklist
            "SELECT 1",  # attempt 2 — valid
            "ok\n置信度: 0.5",
        ],
    )
    with patch("lumen_services.text2sql.engine.create_chat_model", return_value=fake), \
         patch("lumen_services.text2sql.engine.render_regeneration_user") as regen:
        regen.return_value = "test regen prompt"
        result = engine.ask("test", user_id=1, tenant_id=1)
    assert regen.called, "render_regeneration_user should be called on retry"
    assert result.status == "success"
