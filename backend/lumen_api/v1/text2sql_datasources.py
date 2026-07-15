"""M33: /api/v1/text2sql/datasources/* CRUD endpoints.

Spec: docs/superpowers/specs/2026-06-20-text2sql-design.md §6.1
"""
# mypy: disable-error-code="arg-type,assignment,union-attr"
# Same Column[X] vs X gap as in text2sql.py; Pydantic + SQLAlchemy
# ORM descriptors don't agree on the type and the runtime is
# always plain Python. See text2sql.py for the rationale.
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from lumen_api.v1.auth import get_current_user
from lumen_core.database import get_db
from lumen_models.user import User
from lumen_schemas.common import PaginatedResponse, SingleResponse
from lumen_schemas.text2sql import (
    Text2SqlDataSourceCreate,
    Text2SqlDataSourceRead,
    Text2SqlDataSourceUpdate,
)
from lumen_services.text2sql.data_source_service import Text2SqlDataSourceService


router = APIRouter(prefix="/text2sql/datasources", tags=["text2sql"])


def _to_read(ds) -> Text2SqlDataSourceRead:
    return Text2SqlDataSourceRead(
        id=ds.id,
        tenant_id=ds.tenant_id,
        name=ds.name,
        db_name=ds.db_name,
        table_allowlist=ds.table_allowlist,
        field_allowlist=ds.field_allowlist,
        max_rows=ds.max_rows,
        timeout_ms=ds.timeout_ms,
        description=ds.description,
        is_active=bool(ds.is_active),
        created_at=ds.created_at,
        updated_at=ds.updated_at,
    )


@router.get("", response_model=PaginatedResponse[Text2SqlDataSourceRead])
def list_data_sources(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    include_inactive: bool = Query(False),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = Text2SqlDataSourceService.list_for_tenant(
        db,
        tenant_id=int(current_user.tenant_id),  # type: ignore[arg-type]
        include_inactive=include_inactive,
    )
    total = len(rows)
    start = (page - 1) * page_size
    items = [_to_read(r) for r in rows[start:start + page_size]]
    return PaginatedResponse(
        data=items, total=total, page=page, page_size=page_size,
    )


@router.post("", response_model=SingleResponse[Text2SqlDataSourceRead], status_code=201)
def create_data_source(
    body: Text2SqlDataSourceCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ds = Text2SqlDataSourceService.create(
        db,
        tenant_id=int(current_user.tenant_id),  # type: ignore[arg-type]
        name=body.name,
        db_name=body.db_name,
        table_allowlist=body.table_allowlist,
        field_allowlist=body.field_allowlist,
        max_rows=body.max_rows,
        timeout_ms=body.timeout_ms,
        description=body.description,
        is_active=body.is_active,
    )
    return SingleResponse(data=_to_read(ds))


@router.put("/{data_source_id}", response_model=SingleResponse[Text2SqlDataSourceRead])
def update_data_source(
    data_source_id: int,
    body: Text2SqlDataSourceUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    fields = body.model_dump(exclude_unset=True)
    ds = Text2SqlDataSourceService.update(
        db,
        tenant_id=int(current_user.tenant_id),  # type: ignore[arg-type]
        data_source_id=data_source_id, fields=fields,
    )
    if ds is None:
        raise HTTPException(status_code=404, detail="Data source not found")
    return SingleResponse(data=_to_read(ds))


@router.delete("/{data_source_id}", status_code=204)
def delete_data_source(
    data_source_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    deleted, count = Text2SqlDataSourceService.delete(
        db,
        tenant_id=int(current_user.tenant_id),  # type: ignore[arg-type]
        data_source_id=data_source_id,
    )
    if not deleted:
        if count is None:
            raise HTTPException(status_code=404, detail="Data source not found")
        # 422 with the list of blocking query ids so the UI can show them
        ids = Text2SqlDataSourceService.list_referencing_query_ids(
            db, data_source_id=data_source_id, limit=10
        )
        raise HTTPException(
            status_code=422,
            detail={
                "message": f"Data source has {count} historical queries; cannot delete",
                "query_ids": ids,
                "query_count": count,
            },
        )
    return None
