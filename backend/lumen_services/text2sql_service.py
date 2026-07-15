"""Text2SqlService — orchestrates the standalone /text2sql/ask endpoint.

Spec: docs/superpowers/specs/2026-06-20-text2sql-design.md §6

The service is a thin orchestration layer over ``Text2SqlEngine``:

- ``ask`` (sync): runs the engine in-line and returns the result
  with the persisted ``Text2SqlQuery.id`` for the detail view.
- ``ask_async``: persists a ``pending`` row first, schedules the
  engine via FastAPI ``BackgroundTasks``, and returns immediately.
  The caller polls ``GET /history/{id}`` for the result.
- ``list_history`` / ``get`` / ``delete``: standard CRUD with
  tenant scoping.
- ``_run_ask`` (background): opens a fresh session, runs the
  engine, writes the result back to the row, and pushes a
  ``TEXT2SQL_COMPLETED`` / ``TEXT2SQL_FAILED`` WS notification so
  the UI can show a toast.
"""
# mypy: disable-error-code="assignment,arg-type"
# SQLAlchemy ORM column descriptors don't match the Pydantic
# schema's types at assignment sites; runtime is always plain
# Python. Same pattern as M22 image_generation.
from __future__ import annotations

import json
import logging
from typing import List, Optional, Tuple

from fastapi import BackgroundTasks
from sqlalchemy.orm import Session

from lumen_core.database import SessionLocal
from lumen_models.text2sql import Text2SqlDataSource, Text2SqlQuery
from lumen_services.notification_service import NotificationService
from lumen_services.text2sql.data_source_service import Text2SqlDataSourceService
from lumen_services.text2sql.engine import AskResult, Text2SqlEngine


logger = logging.getLogger(__name__)


class Text2SqlService:
    """High-level orchestration for /text2sql/ask and history APIs."""

    @staticmethod
    def ask(
        db: Session,
        *,
        tenant_id: int,
        user_id: int,
        data_source_id: int,
        question: str,
    ) -> Tuple[Optional[Text2SqlQuery], Optional[str]]:  # type: ignore[return-value]
        """Run the engine synchronously and persist the result.

        Returns ``(query, error_message)``. ``error_message`` is
        non-None when the engine couldn't even start (e.g. the
        data source doesn't exist for this tenant).
        """
        ds = Text2SqlDataSourceService.get(
            db, tenant_id=tenant_id, data_source_id=data_source_id
        )
        if ds is None:
            return None, f"Data source {data_source_id} not found for tenant {tenant_id}"

        # Persist the pending row first so the detail view has
        # something to show even if the engine crashes mid-flight.
        row = Text2SqlQuery(
            tenant_id=tenant_id,
            user_id=user_id,
            data_source_id=data_source_id,
            question=question,
            status="generating",
            attempts=0,
        )
        db.add(row)
        db.commit()
        db.refresh(row)

        result = Text2SqlEngine(db, ds).ask(
            question,
            user_id=user_id,
            tenant_id=tenant_id,
        )
        Text2SqlService._apply_result_to_row(db, row, result)
        db.commit()
        db.refresh(row)
        return row, None

    @staticmethod
    def ask_async(
        db: Session,
        background_tasks: BackgroundTasks,
        *,
        tenant_id: int,
        user_id: int,
        data_source_id: int,
        question: str,
    ) -> Tuple[Optional[Text2SqlQuery], Optional[str]]:  # type: ignore[return-value]
        """Persist a pending row and schedule the engine in background."""
        ds = Text2SqlDataSourceService.get(
            db, tenant_id=tenant_id, data_source_id=data_source_id
        )
        if ds is None:
            return None, f"Data source {data_source_id} not found for tenant {tenant_id}"
        row = Text2SqlQuery(
            tenant_id=tenant_id,
            user_id=user_id,
            data_source_id=data_source_id,
            question=question,
            status="pending",
            attempts=0,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        background_tasks.add_task(
            Text2SqlService._run_ask,
            row.id,  # type: ignore[arg-type]
            data_source_id,
            tenant_id,
            user_id,
            question,
        )
        return row, None

    @staticmethod
    def _run_ask(
        query_id: int,
        data_source_id: int,
        tenant_id: int,
        user_id: int,
        question: str,
    ) -> None:
        """Background worker: open a fresh session, run engine, write back."""
        db = SessionLocal()
        try:
            ds = (
                db.query(Text2SqlDataSource)
                .filter(
                    Text2SqlDataSource.tenant_id == tenant_id,
                    Text2SqlDataSource.id == data_source_id,
                )
                .first()
            )
            if ds is None:
                logger.warning(
                    "Text2SqlService._run_ask: data source %s vanished for tenant %s",
                    data_source_id, tenant_id,
                )
                return
            row = (
                db.query(Text2SqlQuery)
                .filter(Text2SqlQuery.id == query_id)
                .first()
            )
            if row is None:
                logger.warning("Text2SqlService._run_ask: row %s gone", query_id)
                return
            row.status = "generating"  # type: ignore[assignment]
            db.commit()
            result = Text2SqlEngine(db, ds).ask(
                question,
                user_id=user_id,
                tenant_id=tenant_id,
            )
            Text2SqlService._apply_result_to_row(db, row, result)
            db.commit()
            db.refresh(row)
            # Push WS notification
            try:
                notif_type = (
                    "TEXT2SQL_COMPLETED" if result.status == "success"
                    else "TEXT2SQL_FAILED"
                )
                NotificationService.publish_event(
                    db,
                    user_id=user_id,
                    type=notif_type,
                    title=(
                        f"智能问数 {'完成' if result.status == 'success' else '失败'}"
                    ),
                    body=(result.explanation if result.status == "success"
                          else result.error_message),
                    resource_type="text2sql_query",
                    resource_id=row.id,  # type: ignore[arg-type]
                    metadata={
                        "query_id": row.id,
                        "status": result.status,
                        "row_count": result.row_count,
                    },
                )
            except Exception as exc:  # pragma: no cover — defensive
                logger.warning("Text2Sql notification publish failed: %s", exc)
        except Exception as exc:  # pragma: no cover — defensive
            logger.exception("Text2SqlService._run_ask failed: %s", exc)
            try:
                db.rollback()
            except Exception:
                pass
        finally:
            db.close()

    @staticmethod
    def _apply_result_to_row(
        db: Session,
        row: Text2SqlQuery,
        result: AskResult,
    ) -> None:
        """Copy fields from an ``AskResult`` onto the persisted row.

        The assignments are ``Column[X] = X``-style which mypy
        can't see through (the descriptor type is invariant). At
        runtime these are all plain Python type assignments.
        """
        row.status = result.status  # type: ignore[assignment]
        row.attempts = result.attempts  # type: ignore[assignment]
        row.generated_sql = result.generated_sql  # type: ignore[assignment]
        row.rows_json = result.rows  # type: ignore[assignment]
        row.columns_json = result.columns  # type: ignore[assignment]
        row.row_count = result.row_count  # type: ignore[assignment]
        row.truncated = 1 if result.truncated else 0  # type: ignore[assignment]
        row.explanation = result.explanation  # type: ignore[assignment]
        row.confidence = (  # type: ignore[assignment]
            int(round(result.confidence * 100)) if result.confidence is not None
            else None
        )
        row.error_type = result.error_type  # type: ignore[assignment]
        row.error_message = result.error_message  # type: ignore[assignment]
        row.duration_ms = result.duration_ms  # type: ignore[assignment]
        row.generate_call_id = result.generate_call_id  # type: ignore[assignment]
        row.explain_call_id = result.explain_call_id  # type: ignore[assignment]

    # ------------------------------------------------------------------ #
    # History CRUD                                                        #
    # ------------------------------------------------------------------ #

    @staticmethod
    def list_history(
        db: Session,
        *,
        tenant_id: int,
        page: int = 1,
        page_size: int = 20,
        status: Optional[str] = None,
        keyword: Optional[str] = None,
    ) -> Tuple[List[Text2SqlQuery], int]:
        """List historical queries. Returns ``(rows, total)``."""
        q = db.query(Text2SqlQuery).filter(Text2SqlQuery.tenant_id == tenant_id)
        if status:
            q = q.filter(Text2SqlQuery.status == status)
        if keyword:
            like = f"%{keyword}%"
            q = q.filter(Text2SqlQuery.question.like(like))
        total = q.count()
        rows = (
            q.order_by(Text2SqlQuery.id.desc())
            .offset(max(0, (page - 1) * page_size))
            .limit(page_size)
            .all()
        )
        return rows, total

    @staticmethod
    def get(
        db: Session,
        *,
        tenant_id: int,
        query_id: int,
    ) -> Optional[Text2SqlQuery]:
        return (
            db.query(Text2SqlQuery)
            .filter(
                Text2SqlQuery.tenant_id == tenant_id,
                Text2SqlQuery.id == query_id,
            )
            .first()
        )

    @staticmethod
    def delete(
        db: Session,
        *,
        tenant_id: int,
        query_id: int,
    ) -> bool:
        row = Text2SqlService.get(
            db, tenant_id=tenant_id, query_id=query_id
        )
        if row is None:
            return False
        db.delete(row)
        db.commit()
        return True
