"""Trial executor for the text2sql engine.

The executor is deliberately *small*. Its only job is to take a
SQLGuard-rewritten SELECT, run it against the live database, and
return a JSON-safe result envelope (``SQLExecutionResult``). All
safety / parsing / rewriting lives in ``sql_guard.py``; this module
is the bridge to MySQL.

Why not use SQLAlchemy ORM?

- We want to run *arbitrary* SELECTs the LLM produced. The ORM
  forces a model class per table and we don't have that.
- We want to read the column names as strings (for the JSON
  response), not bind them to ORM attributes.
- We want to enforce a hard row cap (``fetchmany(max_rows + 1)``)
  *after* execution — fetching the full result into memory first
  defeats the LIMIT injection we just did.

The error taxonomy mirrors what the LLM retries on:

- ``"timeout"`` — MySQL 3024 (MAX_EXECUTION_TIME triggered)
- ``"exec_error"`` — ProgrammingError, OperationalError (other)
- ``"unknown"`` — anything else (still surfaced, but as a soft fail
  so the engine can decide whether to retry)

Datetime / Decimal / bytes values are JSON-coerced so the
``Text2SqlQuery.rows_json`` column can store the result verbatim.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.orm import Session

# MySQL error code raised when MAX_EXECUTION_TIME fires.
MYSQL_QUERY_TIMEOUT = 3024
# MySQL error code raised when the user lacks the privilege.
MYSQL_ACCESS_DENIED = 1045


@dataclass
class SQLExecutionResult:
    """Outcome of one trial execution.

    Attributes:
        columns: column names in select order, lowercase, original case.
        rows: list of dicts (column name → value). Values are
            JSON-safe primitives (str / int / float / bool / None);
            datetimes are ISO-formatted strings, decimals are floats.
        row_count: number of rows actually returned (post-truncation).
        truncated: ``True`` when the query returned more than
            ``max_rows`` and the extra rows were dropped.
        duration_ms: wall-clock time for the execute + fetch, in ms.
        error_type: ``"timeout"`` / ``"exec_error"`` / ``"unknown"`` /
            ``None`` on success.
        error_message: human-readable error detail, suitable for the
            LLM retry prompt.
    """

    columns: List[str] = field(default_factory=list)
    rows: List[Dict[str, Any]] = field(default_factory=list)
    row_count: int = 0
    truncated: bool = False
    duration_ms: int = 0
    error_type: Optional[str] = None
    error_message: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.error_type is None


def _jsonable(value: Any) -> Any:
    """Coerce a MySQL value into a JSON-safe Python primitive.

    Datetime / date → ISO 8601 string. Decimal → float. bytes →
    latin-1 decode (best effort; some blob columns would lose data,
    but we never let the LLM select blobs because the field
    allowlist / column validator is the only path here).
    """
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (bytes, bytearray)):
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError:
            return value.decode("latin-1", errors="replace")
    # Fallback: best-effort str() so json.dumps doesn't blow up.
    return str(value)


def execute(
    db: Session,
    sql: str,
    *,
    max_rows: int = 100,
    timeout_ms: int = 5000,  # noqa: ARG001 — timeout is enforced by SQLGuard
) -> SQLExecutionResult:
    """Run ``sql`` and return a JSON-safe ``SQLExecutionResult``.

    Args:
        db: open ``Session``.
        sql: a SELECT statement that has already passed SQLGuard and
            has its LIMIT / MAX_EXECUTION_TIME hint baked in.
        max_rows: hard cap on rows returned. Used to set the
            ``fetchmany`` size and to detect truncation.

    Returns:
        ``SQLExecutionResult`` with either populated ``columns`` /
        ``rows`` (on success) or ``error_type`` + ``error_message``
        (on failure). The caller decides what to do with the error.
    """
    result = SQLExecutionResult()
    start = time.perf_counter()
    try:
        cursor = db.execute(text(sql))
    except OperationalError as exc:
        result.duration_ms = int((time.perf_counter() - start) * 1000)
        # MySQL 3024: query interrupted by MAX_EXECUTION_TIME
        err_code = getattr(getattr(exc, "orig", None), "args", [None])[0]
        if err_code == MYSQL_QUERY_TIMEOUT:
            result.error_type = "timeout"
            result.error_message = (
                f"Query exceeded the {timeout_ms}ms MAX_EXECUTION_TIME limit"
            )
        else:
            result.error_type = "exec_error"
            result.error_message = _format_exc(exc)
        return result
    except ProgrammingError as exc:
        result.duration_ms = int((time.perf_counter() - start) * 1000)
        result.error_type = "exec_error"
        result.error_message = _format_exc(exc)
        return result
    except Exception as exc:  # pragma: no cover — defensive
        result.duration_ms = int((time.perf_counter() - start) * 1000)
        result.error_type = "unknown"
        result.error_message = _format_exc(exc)
        return result

    try:
        columns: List[str] = list(cursor.keys() or [])
        # Fetch max_rows + 1 so we can detect truncation without
        # loading the whole result.
        rows_iter = cursor.fetchmany(max_rows + 1)
    except OperationalError as exc:
        result.duration_ms = int((time.perf_counter() - start) * 1000)
        err_code = getattr(getattr(exc, "orig", None), "args", [None])[0]
        if err_code == MYSQL_QUERY_TIMEOUT:
            result.error_type = "timeout"
            result.error_message = (
                f"Query exceeded the {timeout_ms}ms MAX_EXECUTION_TIME limit"
            )
        else:
            result.error_type = "exec_error"
            result.error_message = _format_exc(exc)
        return result
    except ProgrammingError as exc:
        result.duration_ms = int((time.perf_counter() - start) * 1000)
        result.error_type = "exec_error"
        result.error_message = _format_exc(exc)
        return result

    duration_ms = int((time.perf_counter() - start) * 1000)
    result.duration_ms = duration_ms

    # Detect truncation: +1 row means the LIMIT fired in MySQL but
    # we asked for max_rows + 1, so the extra row signals "there's
    # more" without paying the full cost.
    truncated = len(rows_iter) > max_rows
    if truncated:
        rows_iter = rows_iter[:max_rows]

    result.columns = [c.lower() for c in columns]
    result.truncated = truncated
    result.rows = [
        {col: _jsonable(val) for col, val in zip(columns, row)}
        for row in rows_iter
    ]
    result.row_count = len(result.rows)
    return result


def _format_exc(exc: BaseException) -> str:
    """Best-effort error formatter that keeps the MySQL error code visible."""
    msg = str(exc).strip()
    orig = getattr(exc, "orig", None)
    if orig is not None and str(orig) and str(orig) not in msg:
        msg = f"{msg} ({orig})"
    if len(msg) > 1000:
        msg = msg[:1000] + "...(truncated)"
    return msg


# --------------------------------------------------------------------------- #
# Convenience: serialise a SQLExecutionResult for the API response.           #
# --------------------------------------------------------------------------- #


def to_json_payload(result: SQLExecutionResult) -> Dict[str, Any]:
    """Convert a ``SQLExecutionResult`` to the API response shape."""
    return {
        "columns": list(result.columns),
        "rows": list(result.rows),
        "row_count": result.row_count,
        "truncated": result.truncated,
        "duration_ms": result.duration_ms,
    }
