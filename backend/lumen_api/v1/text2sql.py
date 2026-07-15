"""M33: /api/v1/text2sql/* endpoints.

Spec: docs/superpowers/specs/2026-06-20-text2sql-design.md §6

Endpoints (9 total):

- ``POST   /ask``               — sync ask, returns full result
- ``GET    /history``           — paginated history list
- ``GET    /history/{id}``      — full detail (with rows / explanation)
- ``DELETE /history/{id}``      — delete a historical query
- ``GET    /schema``            — browse the LLM-ready schema for a data source

The CRUD for data sources lives in ``text2sql_datasources.py`` to keep
this module focused on the ask / history workflow.
"""
# mypy: disable-error-code="arg-type,assignment,union-attr"
# The Pydantic schema model + the SQLAlchemy ORM columns don't
# agree on the descriptor types (Column[str] vs str) and the
# mismatch is uniform across the file. M22 image_generation
# followed the same pattern — type: ignore noise on every
# assignment is a poor trade for cleanliness here.
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from lumen_api.v1.auth import get_current_user
from lumen_core.database import get_db
from lumen_models.user import User
from lumen_schemas.common import PaginatedResponse, SingleResponse
from lumen_schemas.text2sql import (
    Text2SqlAskRequest,
    Text2SqlAskResponse,
    Text2SqlDetail,
    Text2SqlHistoryItem,
    Text2SqlSchemaResponse,
)
from lumen_services.text2sql.data_source_service import Text2SqlDataSourceService
from lumen_services.text2sql.schema_inspector import SchemaInspector
from lumen_services.text2sql_service import Text2SqlService


router = APIRouter(prefix="/text2sql", tags=["text2sql"])


# --------------------------------------------------------------------------- #
# ask                                                                         #
# --------------------------------------------------------------------------- #


@router.post("/ask", response_model=SingleResponse[Text2SqlAskResponse])
def ask_text2sql(
    body: Text2SqlAskRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Run a natural-language query and return the result.

    When ``async_run=True``, returns immediately with a ``pending``
    row id; the engine runs in the background and the caller polls
    ``GET /history/{id}``. The sync path waits for the engine.
    """
    tenant_id = int(current_user.tenant_id)  # type: ignore[arg-type]
    user_id = int(current_user.id)  # type: ignore[arg-type]
    if body.async_run:
        row, err = Text2SqlService.ask_async(
            db,
            background_tasks,
            tenant_id=tenant_id,
            user_id=user_id,
            data_source_id=body.data_source_id,
            question=body.question,
        )
        if err is not None:
            raise HTTPException(status_code=404, detail=err)
        if row is None:
            raise HTTPException(status_code=500, detail="Failed to create query row")
        # Pending row — return id and a hint to poll.
        return SingleResponse(
            data=Text2SqlAskResponse(
                query_id=int(row.id),  # type: ignore[arg-type]
                status="pending",
                generated_sql=None,
                columns=[],
                rows=[],
                row_count=0,
                attempts=0,
            )
        )
    # Sync path
    row, err = Text2SqlService.ask(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        data_source_id=body.data_source_id,
        question=body.question,
    )
    if err is not None:
        raise HTTPException(status_code=404, detail=err)
    if row is None:
        raise HTTPException(status_code=500, detail="Internal: no row returned")
    return SingleResponse(
        data=Text2SqlAskResponse(
            query_id=int(row.id),  # type: ignore[arg-type]
            status=row.status,  # type: ignore[arg-type]
            generated_sql=row.generated_sql,  # type: ignore[arg-type]
            columns=row.columns_json or [],
            rows=row.rows_json or [],
            row_count=row.row_count or 0,
            truncated=bool(row.truncated),
            explanation=row.explanation,
            confidence=row.confidence,
            attempts=row.attempts,
            error_type=row.error_type,
            error_message=row.error_message,
            duration_ms=row.duration_ms,
        )
    )


# --------------------------------------------------------------------------- #
# history                                                                     #
# --------------------------------------------------------------------------- #


@router.get("/history", response_model=PaginatedResponse[Text2SqlHistoryItem])
def list_history(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[str] = Query(None),
    keyword: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows, total = Text2SqlService.list_history(
        db,
        tenant_id=int(current_user.tenant_id),  # type: ignore[arg-type]
        page=page,
        page_size=page_size,
        status=status,
        keyword=keyword,
    )
    items = []
    for r in rows:
        preview = r.question
        if len(preview) > 80:
            preview = preview[:80] + "..."
        items.append(
            Text2SqlHistoryItem(
                id=r.id,  # type: ignore[arg-type]
                data_source_id=r.data_source_id,  # type: ignore[arg-type]
                question=r.question,
                question_preview=preview,
                status=r.status,  # type: ignore[arg-type]
                row_count=r.row_count,
                attempts=r.attempts,
                duration_ms=r.duration_ms,
                error_type=r.error_type,
                created_at=r.created_at,
            )
        )
    return PaginatedResponse(
        data=items, total=total, page=page, page_size=page_size,
    )


@router.get("/history/{query_id}", response_model=SingleResponse[Text2SqlDetail])
def get_history_detail(
    query_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = Text2SqlService.get(
        db,
        tenant_id=int(current_user.tenant_id),  # type: ignore[arg-type]
        query_id=query_id,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Text2SqlQuery not found")
    return SingleResponse(
        data=Text2SqlDetail(
            id=row.id,  # type: ignore[arg-type]
            tenant_id=row.tenant_id,
            user_id=row.user_id,
            data_source_id=row.data_source_id,
            question=row.question,
            generated_sql=row.generated_sql,
            status=row.status,
            attempts=row.attempts,
            error_type=row.error_type,
            error_message=row.error_message,
            columns=row.columns_json or [],
            rows=row.rows_json or [],
            row_count=row.row_count,
            truncated=bool(row.truncated),
            explanation=row.explanation,
            confidence=row.confidence,
            duration_ms=row.duration_ms,
            generate_call_id=row.generate_call_id,
            explain_call_id=row.explain_call_id,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
    )


@router.delete("/history/{query_id}", status_code=204)
def delete_history(
    query_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ok = Text2SqlService.delete(
        db,
        tenant_id=int(current_user.tenant_id),  # type: ignore[arg-type]
        query_id=query_id,
    )
    if not ok:
        raise HTTPException(status_code=404, detail="Text2SqlQuery not found")
    return None


# --------------------------------------------------------------------------- #
# schema browser                                                              #
# --------------------------------------------------------------------------- #


@router.get("/schema", response_model=SingleResponse[Text2SqlSchemaResponse])
def get_schema(
    data_source_id: int = Query(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return the LLM-ready schema text + table list for a data source.

    The UI uses this to power the "Schema 浏览" tab.
    """
    ds = Text2SqlDataSourceService.get(
        db,
        tenant_id=int(current_user.tenant_id),  # type: ignore[arg-type]
        data_source_id=data_source_id,
    )
    if ds is None:
        raise HTTPException(status_code=404, detail="Data source not found")
    inspector = SchemaInspector(db, ds.db_name)
    tables = inspector.list_tables(allowlist=ds.table_allowlist)
    schema_text = inspector.get_full_schema_text(
        table_allowlist=ds.table_allowlist,
        field_allowlist=ds.field_allowlist,
    )
    return SingleResponse(
        data=Text2SqlSchemaResponse(
            data_source_id=data_source_id,
            db_name=ds.db_name,
            table_count=len(tables),
            schema_text=schema_text,
            tables=tables,
        )
    )
