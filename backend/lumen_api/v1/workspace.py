"""M38.2: workspace admin endpoints.

Six endpoints covering the spec §4.1 surface:

- ``GET  /api/v1/workspaces`` — paginated list of workspaces in
  the current tenant (admin can opt into a cross-tenant view by
  passing ``?tenant_id=``; the spec doesn't mandate this but the
  endpoint honours it for parity with the rest of the API).
- ``POST /api/v1/workspaces`` — create.
- ``GET  /api/v1/workspaces/{id}`` — single read.
- ``PUT  /api/v1/workspaces/{id}`` — patch (name/desc/icon/color).
- ``DELETE /api/v1/workspaces/{id}`` — hard-delete; KBs hanging
  off it survive (``workspace_id`` becomes NULL via the FK ON
  DELETE SET NULL).
- ``GET  /api/v1/workspaces/{id}/tree`` — single round-trip
  tree response consumed by the sidebar.

Spec: ``docs-internal/superpowers/specs/2026-08-26-kb-workspace-folder.md``
§ 4.1.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from lumen_api.v1.auth import get_current_user
from lumen_core.database import get_db
from lumen_models.user import User
from lumen_schemas.common import PaginatedResponse, SingleResponse
from lumen_schemas.workspace import (
    WorkspaceCreate,
    WorkspaceRead,
    WorkspaceTreeResponse,
    WorkspaceUpdate,
)
from lumen_services.workspace_service import workspace_service

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


def _is_admin(user: User) -> bool:
    """Convenience for the workspace endpoints.

    Mirrors the admin override pattern used in
    ``lumen_api/v1/storage.py`` — ``is_superuser`` is the only
    flag we need; ``is_active`` is enforced upstream by
    ``get_current_user``.
    """
    return bool(getattr(user, "is_superuser", False))


# -- 1. list -------------------------------------------------------------


@router.get("", response_model=PaginatedResponse[WorkspaceRead])
def list_workspaces(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    tenant_id: Optional[int] = Query(
        None,
        description="Admin override; ignored for non-admin callers.",
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List workspaces.

    Non-admin callers always see their own tenant; admins can
    request another tenant via ``?tenant_id=``.
    """
    effective_tenant = current_user.tenant_id
    if tenant_id is not None and _is_admin(current_user):
        effective_tenant = tenant_id
    items, total = workspace_service.list_workspaces(
        db, tenant_id=effective_tenant, page=page, page_size=page_size,
    )
    return PaginatedResponse[WorkspaceRead](
        data=items,
        total=total,
        page=page,
        page_size=page_size,
    )


# -- 2. create -----------------------------------------------------------


@router.post("", response_model=SingleResponse[WorkspaceRead])
def create_workspace(
    payload: WorkspaceCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a workspace in the caller's tenant."""
    ws = workspace_service.create_workspace(
        db,
        tenant_id=current_user.tenant_id,
        data=payload,
        owner_id=current_user.id,
    )
    return SingleResponse(data=ws)


# -- 3. single get -------------------------------------------------------


@router.get("/{workspace_id}", response_model=SingleResponse[WorkspaceRead])
def get_workspace(
    workspace_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Single workspace; 404 for cross-tenant access."""
    ws = workspace_service.get_workspace(
        db,
        workspace_id=workspace_id,
        tenant_id=current_user.tenant_id,
        is_superuser=_is_admin(current_user),
    )
    if ws is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return SingleResponse(data=ws)


# -- 4. update -----------------------------------------------------------


@router.put("/{workspace_id}", response_model=SingleResponse[WorkspaceRead])
def update_workspace(
    workspace_id: int,
    payload: WorkspaceUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Patch a workspace.

    Spec §4.1: "PUT ... (仅 owner 或 admin)". The ownership check
    is done here rather than in the service layer because the
    service is shared between ``PUT`` and the admin-only
    cross-tenant path.
    """
    existing = workspace_service.get_workspace(
        db,
        workspace_id=workspace_id,
        tenant_id=current_user.tenant_id,
        is_superuser=_is_admin(current_user),
    )
    if existing is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    if not _is_admin(current_user):
        # ``WorkspaceRead.owner_id`` survives the get; surface it.
        owner_id = getattr(existing, "owner_id", None)
        if owner_id is not None and owner_id != current_user.id:
            raise HTTPException(
                status_code=403,
                detail="仅 workspace 创建人或管理员可修改",
            )
    ws = workspace_service.update_workspace(
        db,
        workspace_id=workspace_id,
        tenant_id=current_user.tenant_id,
        data=payload,
        is_superuser=_is_admin(current_user),
    )
    if ws is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return SingleResponse(data=ws)


# -- 5. delete -----------------------------------------------------------


@router.delete("/{workspace_id}")
def delete_workspace(
    workspace_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Hard-delete a workspace; KBs hang off the tenant directly after.

    Returns ``{"deleted": true/false}`` for symmetry with the
    other admin endpoints (no envelope on the response body —
    the spec only requires the side-effect).
    """
    deleted = workspace_service.delete_workspace(
        db,
        workspace_id=workspace_id,
        tenant_id=current_user.tenant_id,
        is_superuser=_is_admin(current_user),
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return {"deleted": True}


# -- 6. tree -------------------------------------------------------------


@router.get(
    "/{workspace_id}/tree",
    response_model=SingleResponse[WorkspaceTreeResponse],
)
def get_workspace_tree(
    workspace_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Single round-trip tree response for the sidebar."""
    tree = workspace_service.get_workspace_tree(
        db,
        workspace_id=workspace_id,
        tenant_id=current_user.tenant_id,
        is_superuser=_is_admin(current_user),
    )
    if tree is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return SingleResponse(data=tree)
