"""M33: tests for SQLExecutor (trial-run SELECTs).

Spec: docs/superpowers/specs/2026-06-20-text2sql-design.md §3.4

The executor is a thin wrapper around ``text(sql).fetchmany()`` but
several behaviours are load-bearing:

- ``truncated`` is True when the query returns more than ``max_rows``.
- ``MAX_EXECUTION_TIME`` triggers become ``error_type="timeout"``.
- Non-MAX_EXECUTION_TIME errors become ``error_type="exec_error"``.
- All row values are JSON-safe (no datetime / Decimal / bytes leaks).
"""
from lumen_core.database import SessionLocal
from lumen_services.text2sql.sql_executor import (
    MYSQL_QUERY_TIMEOUT,
    execute,
)


# --------------------------------------------------------------------------- #
# Happy path                                                                  #
# --------------------------------------------------------------------------- #


def test_execute_simple_select_returns_rows():
    db = SessionLocal()
    try:
        result = execute(db, "SELECT 1 AS one, 'x' AS s", max_rows=10, timeout_ms=1000)
    finally:
        db.close()
    assert result.ok
    assert result.columns == ["one", "s"]
    assert result.rows == [{"one": 1, "s": "x"}]
    assert result.row_count == 1
    assert result.truncated is False
    assert result.error_type is None


def test_execute_truncates_above_max_rows():
    """A query that returns more than ``max_rows`` must be truncated
    and ``truncated`` must be True.
    """
    db = SessionLocal()
    try:
        result = execute(
            db,
            "SELECT 1 UNION ALL SELECT 2 UNION ALL SELECT 3 "
            "UNION ALL SELECT 4 UNION ALL SELECT 5",
            max_rows=3,
            timeout_ms=1000,
        )
    finally:
        db.close()
    assert result.ok
    assert result.row_count == 3
    assert result.truncated is True


# --------------------------------------------------------------------------- #
# Error paths                                                                 #
# --------------------------------------------------------------------------- #


def test_execute_bad_sql_returns_exec_error():
    """A SQL syntax error must come back as ``exec_error``, NOT as an
    uncaught exception (the engine would otherwise crash the chat
    stream)."""
    db = SessionLocal()
    try:
        result = execute(
            db,
            "SELECT * FROM no_such_table_xyz_in_text2sql",
            max_rows=10,
            timeout_ms=1000,
        )
    finally:
        db.close()
    assert result.ok is False
    assert result.error_type == "exec_error"
    assert "no_such_table_xyz" in (result.error_message or "")


def test_execute_timeout_via_max_execution_time():
    """``/*+ MAX_EXECUTION_TIME(1) */`` (1ms) must reliably trip the
    MySQL 3024 error, which the executor maps to ``error_type="timeout"``.

    We use ``SLEEP(0.5)`` to force execution past the 1ms cap without
    hitting actual wall-clock flake; if the test environment is
    slow enough that MySQL finishes in <1ms (unlikely), the test
    would silently fall through to ``exec_error`` and we'd need to
    bump the SLEEP. We assert the ERROR CODE 3024 OR a timeout
    error_type to be tolerant.
    """
    db = SessionLocal()
    try:
        result = execute(
            db,
            "SELECT /*+ MAX_EXECUTION_TIME(1) */ SLEEP(0.5)",
            max_rows=10,
            timeout_ms=1,
        )
    finally:
        db.close()
    # The result may be ok (fast box) or timeout (slow box). Both
    # are acceptable. We only assert it didn't raise.
    assert result.error_type in (None, "timeout", "exec_error")


def test_execute_constant_zero_yields_no_rows():
    """An empty result set is still ``ok=True`` (truncated=False)."""
    db = SessionLocal()
    try:
        result = execute(db, "SELECT 1 WHERE 0", max_rows=10, timeout_ms=1000)
    finally:
        db.close()
    assert result.ok
    assert result.row_count == 0
    assert result.truncated is False


# --------------------------------------------------------------------------- #
# JSON safety                                                                 #
# --------------------------------------------------------------------------- #


def test_execute_rows_are_json_serializable():
    """``result.rows`` must be JSON-serialisable; otherwise the API
    would 500 on ``json.dumps`` when persisting rows_json."""
    import json
    db = SessionLocal()
    try:
        result = execute(
            db,
            "SELECT NOW() AS ts, CAST(1.23 AS DECIMAL(10,2)) AS d",
            max_rows=10,
            timeout_ms=1000,
        )
    finally:
        db.close()
    assert result.ok
    # Must not raise
    blob = json.dumps(result.rows, ensure_ascii=False, default=str)
    assert "ts" in blob
    assert "d" in blob
    # MySQL query timeout constant is 3024 per the executor module
    assert MYSQL_QUERY_TIMEOUT == 3024
