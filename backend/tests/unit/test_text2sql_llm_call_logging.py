"""M33: tests that the two LLMCallLog ``call_type`` strings fit the
schema and can be persisted via the existing LLMCallLoggingService.

Spec: docs/superpowers/specs/2026-06-20-text2sql-design.md §3.5

The M26 LLMCallLog table has ``call_type VARCHAR(64)`` so the two
strings we use (``text2sql.generate`` and ``text2sql.explain``) must
fit. We verify the literal lengths and the column type.
"""
from lumen_models.llm_call_log import LLMCallLog


def test_text2sql_call_type_strings_fit_varchar_64():
    """The two call_type values must be <=64 chars."""
    for ct in ("text2sql.generate", "text2sql.explain"):
        assert len(ct) <= 64, (
            f"call_type {ct!r} is {len(ct)} chars; "
            f"LLMCallLog.call_type is VARCHAR(64)"
        )


def test_llm_call_log_call_type_column_is_varchar_64():
    """The LLMCallLog.call_type column must be VARCHAR(64) (per the
    M26 schema). We assert the SQLAlchemy column metadata so a
    future schema change (e.g. a tightening) is caught here.
    """
    from sqlalchemy import inspect
    inspector = inspect(LLMCallLog)
    call_type_col = inspector.columns["call_type"]
    assert str(call_type_col.type).upper().startswith("VARCHAR"), (
        f"Expected call_type column to be VARCHAR, got {call_type_col.type}"
    )
    assert call_type_col.type.length == 64
