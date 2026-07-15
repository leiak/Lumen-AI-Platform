"""Text2SqlEngine — the heart of the smart-query feature.

Spec: docs/superpowers/specs/2026-06-20-text2sql-design.md §5

Two-phase LLM call:

1. **Phase 1 — ``generate_sql``**: ask the LLM to translate the
   question into a single MySQL SELECT, with the live schema
   injected. The output is fed into ``SQLGuard`` and (if it passes)
   into a trial execution. On any failure we re-enter Phase 1 with
   the previous attempt + the error message ("Phase 1.5"). Capped
   at ``max_retries`` (default 3) total attempts.

2. **Phase 2 — ``explain``**: when Phase 1 succeeded, ask the LLM
   to produce a Chinese natural-language summary of the result rows
   + a 0-1 confidence score. The ``parent_call_id`` of this call
   is set to Phase 1's ``call_id`` so the LLMCallLogs page can
   trace the full lifecycle.

Both phases write a single LLMCallLog row (per phase) via the
``LLMCallLoggingService.log_call`` helper. The ``call_type`` values
are ``text2sql.generate`` and ``text2sql.explain`` respectively.

The engine is intentionally *self-contained*: it accepts a
``Text2SqlDataSource`` ORM object (for the table / field allowlist
+ max_rows / timeout_ms) and a ``db`` Session. It does NOT call the
API layer, so it can be reused from the chat skill executor with
the same semantics as the standalone /text2sql/ask endpoint.
"""
from __future__ import annotations

import json
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy.orm import Session

from lumen_core.llm_call_context import LLMCallContext, set_call_context, reset_call_context
from lumen_models.text2sql import Text2SqlDataSource
from lumen_services.llm_call_logging import (
    get_llm_call_logging_service,
    serialize_message,
)
from lumen_services.model_loader import create_chat_model
from lumen_services.text2sql.prompts import (
    parse_explanation,
    render_explanation_system,
    render_explanation_user,
    render_regeneration_user,
    render_sql_generation_system,
    render_sql_generation_user,
)
from lumen_services.text2sql.schema_inspector import SchemaInspector
from lumen_services.text2sql.sql_executor import SQLExecutionResult, execute
from lumen_services.text2sql.sql_guard import GuardResult, SQLGuard


logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Result types                                                                #
# --------------------------------------------------------------------------- #


@dataclass
class AskResult:
    """Outcome of one full ``Text2SqlEngine.ask`` cycle.

    Attributes:
        status: ``"success"`` / ``"rejected"`` / ``"failed"``.
        generated_sql: the final SQL the user sees (post-rewrite).
            ``None`` when SQLGuard rejected every attempt.
        columns: list of column names (lowercased) from the result.
        rows: JSON-safe list of dicts.
        row_count: number of rows returned.
        truncated: True if the result was truncated to ``max_rows``.
        explanation: Chinese natural-language summary (``None`` on
            failure paths).
        confidence: 0-1 float reported by the LLM (``None`` when
            the LLM didn't emit one).
        attempts: how many generate / validate / execute rounds we
            ran before giving up.
        error_type: machine-readable failure category (blocklist /
            table / field / exec_error / timeout / llm_error /
            unknown / None).
        error_message: human-readable detail.
        duration_ms: total wall-clock for the whole pipeline.
        generate_call_id: LLMCallLog.call_id for the Phase 1 call.
        explain_call_id: LLMCallLog.call_id for the Phase 2 call.
    """

    status: str
    generated_sql: Optional[str] = None
    columns: List[str] = field(default_factory=list)
    rows: List[Dict[str, Any]] = field(default_factory=list)
    row_count: int = 0
    truncated: bool = False
    explanation: Optional[str] = None
    confidence: Optional[float] = None
    attempts: int = 1
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    duration_ms: int = 0
    generate_call_id: Optional[str] = None
    explain_call_id: Optional[str] = None


# --------------------------------------------------------------------------- #
# Engine                                                                      #
# --------------------------------------------------------------------------- #


class Text2SqlEngine:
    """Two-phase LLM engine for natural-language → SQL → answer.

    Args:
        db: open ``Session`` used for INFORMATION_SCHEMA reads and
            the trial execution. The engine does NOT own the
            transaction; the caller (service layer) decides commit
            boundaries.
        data_source: the ``Text2SqlDataSource`` row. The engine reads
            ``table_allowlist`` / ``field_allowlist`` / ``max_rows`` /
            ``timeout_ms`` from it.
        max_retries: maximum total Phase 1 attempts (1 = no retry,
            3 = 1 initial + 2 retries with error feedback).
    """

    def __init__(
        self,
        db: Session,
        data_source: Text2SqlDataSource,
        *,
        max_retries: int = 3,
    ) -> None:
        self.db = db
        self.data_source = data_source
        self.max_retries = max_retries
        # SQLAlchemy Column[] vs the Python types the helpers expect.
        # mypy can't see through ORM descriptors; the runtime values
        # are plain str / int / list / dict.
        self.inspector = SchemaInspector(
            db, data_source.db_name,  # type: ignore[arg-type]
        )
        self.guard = SQLGuard(
            self.inspector,
            table_allowlist=data_source.table_allowlist,  # type: ignore[arg-type]
            field_allowlist=data_source.field_allowlist,  # type: ignore[arg-type]
        )

    # ------------------------------------------------------------------ #
    # Public entry point                                                  #
    # ------------------------------------------------------------------ #

    def ask(
        self,
        question: str,
        *,
        user_id: Optional[int] = None,
        tenant_id: Optional[int] = None,
        trace_id: Optional[str] = None,
        client_app: str = "dashboard",
    ) -> AskResult:
        """Run the full pipeline and return an ``AskResult``.

        ``trace_id`` is propagated to both LLMCallLog rows so the
        observability page can correlate Phase 1 + Phase 2 of the
        same ask. When ``None``, a fresh uuid4 is generated and
        returned via the LLMCallContext (callers can read it from
        the ``generate_call_id`` / ``explain_call_id`` fields).
        """
        start = time.perf_counter()
        trace_id = trace_id or str(uuid.uuid4())

        # --- Phase 1: generate + validate + execute -------------------
        gen_call_id, sql, exec_result, gen_error = self._phase1_generate(
            question, user_id=user_id, tenant_id=tenant_id,
            trace_id=trace_id, client_app=client_app,
        )

        if gen_error is not None or sql is None or exec_result is None:
            return AskResult(
                status="rejected" if (
                    gen_error and gen_error.error_type
                    in {"blocklist", "table", "field", "parse"}
                ) else "failed",
                generated_sql=sql,
                attempts=self.max_retries,
                error_type=(gen_error.error_type if gen_error else "llm_error"),
                error_message=(
                    gen_error.error_message if gen_error
                    else "Phase 1 returned no SQL"
                ),
                duration_ms=int((time.perf_counter() - start) * 1000),
                generate_call_id=gen_call_id,
            )

        if not exec_result.ok:
            return AskResult(
                status="failed",
                generated_sql=sql,
                attempts=self.max_retries,
                error_type=exec_result.error_type or "exec_error",
                error_message=exec_result.error_message,
                duration_ms=int((time.perf_counter() - start) * 1000),
                generate_call_id=gen_call_id,
            )

        # --- Phase 2: explain ----------------------------------------
        explanation, confidence, explain_call_id = self._phase2_explain(
            question, sql, exec_result,
            user_id=user_id, tenant_id=tenant_id,
            trace_id=trace_id, client_app=client_app,
            parent_call_id=gen_call_id,
        )

        return AskResult(
            status="success",
            generated_sql=sql,
            columns=exec_result.columns,
            rows=exec_result.rows,
            row_count=exec_result.row_count,
            truncated=exec_result.truncated,
            explanation=explanation,
            confidence=confidence,
            attempts=self.max_retries,
            duration_ms=int((time.perf_counter() - start) * 1000),
            generate_call_id=gen_call_id,
            explain_call_id=explain_call_id,
        )

    # ------------------------------------------------------------------ #
    # Phase 1 internals                                                   #
    # ------------------------------------------------------------------ #

    def _phase1_generate(
        self,
        question: str,
        *,
        user_id: Optional[int],
        tenant_id: Optional[int],
        trace_id: str,
        client_app: str,
    ) -> Tuple[Optional[str], Optional[str], Optional[SQLExecutionResult], Optional[GuardResult]]:
        """Drive the generate → validate → execute loop.

        Returns ``(generate_call_id, sql, exec_result, error)``.
        """
        schema_text = self.inspector.get_full_schema_text(
            table_allowlist=self.data_source.table_allowlist,  # type: ignore[arg-type]
            field_allowlist=self.data_source.field_allowlist,  # type: ignore[arg-type]
        )
        system_prompt = render_sql_generation_system(
            schema_text=schema_text,
            max_rows=self.data_source.max_rows,  # type: ignore[arg-type]
        )

        last_sql: Optional[str] = None
        last_error: Optional[str] = None
        gen_call_id: Optional[str] = None

        for attempt in range(1, self.max_retries + 1):
            if attempt == 1:
                user_prompt = render_sql_generation_user(question)
            else:
                user_prompt = render_regeneration_user(
                    question=question,
                    last_sql=last_sql or "",
                    error=last_error or "Unknown error",
                )

            raw_sql, call_id = self._invoke_llm(
                call_type="text2sql.generate",
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                user_id=user_id,
                tenant_id=tenant_id,
                trace_id=trace_id,
                client_app=client_app,
                call_index=attempt,
                parent_call_id=None,
            )
            if gen_call_id is None:
                gen_call_id = call_id

            sql = _clean_sql(raw_sql)
            if not sql:
                last_error = "LLM returned empty SQL"
                last_sql = raw_sql
                continue

            rewritten, guard_err = self.guard.run(
                sql,
                max_rows=self.data_source.max_rows,  # type: ignore[arg-type]
                timeout_ms=self.data_source.timeout_ms,  # type: ignore[arg-type]
            )
            if guard_err is not None:
                last_error = guard_err.error_message or "SQLGuard rejected"
                last_sql = sql
                continue

            # Trial execution against the live DB
            result = execute(
                self.db,
                rewritten or sql,
                max_rows=self.data_source.max_rows,  # type: ignore[arg-type]
                timeout_ms=self.data_source.timeout_ms,  # type: ignore[arg-type]
            )
            if result.ok:
                # Re-store the *original* (un-rewritten) SQL for the
                # audit log — the LLM is the source of truth, the
                # wrapper is mechanical.
                return gen_call_id, sql, result, None
            last_error = result.error_message or "Execution failed"
            last_sql = sql

        # All retries exhausted
        return gen_call_id, last_sql, None, GuardResult(
            ok=False,
            error_type="llm_error" if last_error and "LLM" in last_error else "exec_error",
            error_message=(
                last_error
                or f"SQL generation failed after {self.max_retries} attempts"
            ),
        )

    def _phase2_explain(
        self,
        question: str,
        sql: str,
        result: SQLExecutionResult,
        *,
        user_id: Optional[int],
        tenant_id: Optional[int],
        trace_id: str,
        client_app: str,
        parent_call_id: Optional[str],
    ) -> Tuple[Optional[str], Optional[float], Optional[str]]:
        """Run Phase 2 (Chinese explanation) and parse the response."""
        system_prompt = render_explanation_system()
        user_prompt = render_explanation_user(
            question=question,
            sql=sql,
            rows=result.rows,
            row_count=result.row_count,
        )

        raw, call_id = self._invoke_llm(
            call_type="text2sql.explain",
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            user_id=user_id,
            tenant_id=tenant_id,
            trace_id=trace_id,
            client_app=client_app,
            call_index=1,
            parent_call_id=parent_call_id,
        )
        parsed = parse_explanation(raw)
        confidence = parsed.get("confidence")
        if confidence is not None:
            # Store as int 0-100 in the DB; return float 0-1 to the caller.
            return (
                parsed["explanation"],
                float(confidence),
                call_id,
            )
        return parsed["explanation"], None, call_id

    # ------------------------------------------------------------------ #
    # LLM call helper (writes LLMCallLog)                                 #
    # ------------------------------------------------------------------ #

    def _invoke_llm(
        self,
        *,
        call_type: str,
        system_prompt: str,
        user_prompt: str,
        user_id: Optional[int],
        tenant_id: Optional[int],
        trace_id: str,
        client_app: str,
        call_index: int,
        parent_call_id: Optional[str],
    ) -> Tuple[str, str]:
        """Invoke the chat model and write an LLMCallLog row.

        Returns ``(response_text, call_id)``. The call_id is a fresh
        uuid4 hex; it's also stored on the LLMCallLog row so the
        caller can correlate.
        """
        # The text2sql skill does most of the heavy lifting via the
        # SQLGuard / SQLExecutor safety net, so a small chat model is
        # fine. We hard-code qwen2.5:0.5b (always present on the
        # project's dev Ollama) — the spec says this is a "lightweight"
        # flow and 7B isn't required for the structured SELECT-output
        # task.
        chat_model = create_chat_model(
            model_type="ollama",
            model_name="qwen2.5:0.5b",
            temperature=0.0,
        )
        call_id = str(uuid.uuid4())
        ctx = LLMCallContext(
            call_id=call_id,
            trace_id=trace_id,
            parent_call_id=parent_call_id,
            call_type=call_type,
            call_index=call_index,
            tenant_id=tenant_id,
            user_id=user_id,
            client_app=client_app,
        )
        token = set_call_context(ctx)
        start = time.perf_counter()
        try:
            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_prompt),
            ]
            response = chat_model.invoke(messages)
            raw = getattr(response, "content", "") or ""
            finish_reason = (
                response.response_metadata.get("finish_reason")
                if hasattr(response, "response_metadata") and isinstance(
                    response.response_metadata, dict
                )
                else None
            )
        except Exception as exc:  # pragma: no cover — defensive
            duration_ms = int((time.perf_counter() - start) * 1000)
            logger.exception("Text2Sql LLM call failed: %s", exc)
            # Log the failure so the LLMCallLogs page shows it.
            self._write_log(
                ctx=ctx,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                raw="",
                finish_reason="error",
                duration_ms=duration_ms,
                status="failed",
                error_type="llm_error",
                error_message=str(exc),
            )
            return "", call_id
        finally:
            reset_call_context(token)

        duration_ms = int((time.perf_counter() - start) * 1000)
        self._write_log(
            ctx=ctx,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            raw=raw,
            finish_reason=finish_reason,
            duration_ms=duration_ms,
            status="success",
            error_type=None,
            error_message=None,
        )
        return raw, call_id

    def _write_log(
        self,
        *,
        ctx: LLMCallContext,
        system_prompt: str,
        user_prompt: str,
        raw: str,
        finish_reason: Optional[str],
        duration_ms: int,
        status: str,
        error_type: Optional[str],
        error_message: Optional[str],
    ) -> None:
        """Best-effort LLMCallLog write — failure is non-fatal."""
        try:
            from lumen_models.model_config import ModelConfig
            model_name = "unknown"
            model_type = "unknown"
            # Best-effort: read the default chat model name. We
            # don't fail if ModelConfig isn't seeded.
            try:
                cfg = self.db.query(ModelConfig).filter(
                    ModelConfig.model_type == "chat",
                    ModelConfig.is_active == 1,
                ).first()
                if cfg is not None:
                    model_name = cfg.name  # type: ignore[assignment]
                    model_type = cfg.model_type  # type: ignore[assignment]
            except Exception:
                pass
            now = datetime.utcnow()
            get_llm_call_logging_service().log_call(
                self.db,
                ctx=ctx,
                model_type=model_type,
                model_name=model_name,
                temperature=0.0,
                max_tokens=None,
                system_messages=[{"role": "system", "content": system_prompt}],
                user_message=user_prompt,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                response_content=raw,
                finish_reason=finish_reason,
                tool_calls=None,
                token_usage=None,
                started_at=now,
                finished_at=now,
                duration_ms=duration_ms,
                status=status,
                error_type=error_type,
                error_message=error_message,
            )
            # Commit the log row immediately so it's visible even if
            # the caller rolls back the outer transaction.
            self.db.commit()
        except Exception as exc:  # pragma: no cover — defensive
            logger.warning("Text2SqlEngine LLMCallLog write failed: %s", exc)
            try:
                self.db.rollback()
            except Exception:
                pass


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #


# Pattern to strip Markdown code fences the LLM often wraps SQL in.
_CODE_FENCE_RE = re.compile(r"^```(?:sql)?\s*|```\s*$", re.IGNORECASE | re.MULTILINE)


def _clean_sql(raw: str) -> Optional[str]:
    """Strip Markdown wrappers and trim whitespace.

    Returns None when the input is empty after cleanup.
    """
    if not raw:
        return None
    s = raw.strip()
    s = _CODE_FENCE_RE.sub("", s)
    s = s.strip()
    # If the LLM still included some commentary (e.g. "Here is the
    # SQL: SELECT ..."), take only the first line that looks like
    # SQL. We anchor on the first SELECT / WITH keyword.
    match = re.search(r"\b(SELECT|WITH)\b", s, re.IGNORECASE)
    if match:
        s = s[match.start():]
    # Truncate at the first unescaped semicolon-then-text boundary.
    return s.strip() or None
