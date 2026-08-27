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

M38.2.x v2: all 6 endpoints挂 RBAC check(spec §5.2):

- list  → 过滤 user 有 workspace.read 的 workspace(替代 M38.2 「全员可见」语义)
- GET   → workspace.read
- POST  → 无 check(创建者自动 owner,等同 admin)
- PUT   → workspace.update
- DELETE → workspace.delete
- tree  → workspace.read
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
from lumen_services.permission_service import (
    PermissionService,
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
    """List workspaces visible to the current user.

    M38.2.x v2: non-admin callers see only workspaces they have
    ``workspace.read`` permission on (filtered via the bulk
    pre-loader to avoid N+1). Admin (``is_superuser``) sees all
    workspaces in the requested tenant.
    """
    effective_tenant = current_user.tenant_id
    if tenant_id is not None and _is_admin(current_user):
        effective_tenant = tenant_id
    items, total = workspace_service.list_workspaces(
        db, tenant_id=effective_tenant, page=page, page_size=page_size,
    )
    if _is_admin(current_user):
        # admin 直通
        return PaginatedResponse[WorkspaceRead](
            data=items,
            total=total,
            page=page,
            page_size=page_size,
        )
    # M38.2.x v2: 非 admin 按 workspace.read 过滤。
    # 用 page+1 拉全集,然后按 perm 过滤,再分页 —— 简单可靠;如果数据集大可改
    # load_user_workspace_permissions 全量预加载后 IN-memory filter。
    if total == 0:
        return PaginatedResponse[WorkspaceRead](
            data=[],
            total=0,
            page=page,
            page_size=page_size,
        )
    # 一次性拉到全集(不分页),再 filter → 再分页。
    all_items, _ = workspace_service.list_workspaces(
        db, tenant_id=effective_tenant, page=1, page_size=max(total, 1),
    )
    svc = PermissionService()
    visible = [
        ws for ws in all_items
        if svc.check(db, current_user, "workspace.read", ws.id)
    ]
    start = (page - 1) * page_size
    end = start + page_size
    return PaginatedResponse[WorkspaceRead](
        data=visible[start:end],
        total=len(visible),
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
    """Create a workspace in the caller's tenant.

    M38.2.x v2: no permission check — the creator is the new owner,
    which grants them all permissions by the ``_is_owner`` bypass.
    """
    ws = workspace_service.create_workspace(
        db,
        tenant_id=current_user.tenant_id,
        data=payload,
        owner_id=current_user.id,
    )
    return SingleResponse(data=ws)


# -- 3. single get -------------------------------------------------------


@router.get(
    "/{workspace_id}",
    response_model=SingleResponse[WorkspaceRead],
)
def get_workspace(
    workspace_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Single workspace; 404 for cross-tenant access.

    M38.2.x v2: ``workspace.read`` permission is required
    (admins / owners bypass via ``PermissionService.check``).
    Permission check happens AFTER tenant-scoped lookup so
    cross-tenant reads return 404 (don't leak existence) rather
    than 403.
    """
    ws = workspace_service.get_workspace(
        db,
        workspace_id=workspace_id,
        tenant_id=current_user.tenant_id,
        is_superuser=_is_admin(current_user),
    )
    if ws is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    if not PermissionService().check(db, current_user, "workspace.read", workspace_id):
        raise HTTPException(
            status_code=403,
            detail=f"无权限: workspace.read",
        )
    return SingleResponse(data=ws)


# -- 4. update -----------------------------------------------------------


@router.put(
    "/{workspace_id}",
    response_model=SingleResponse[WorkspaceRead],
)
def update_workspace(
    workspace_id: int,
    payload: WorkspaceUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Patch a workspace.

    M38.2.x v2: ``workspace.update`` permission is required.
    Owner / superuser bypass via ``PermissionService.check``.
    Permission check happens AFTER tenant-scoped lookup so
    cross-tenant updates return 404 (don't leak existence).
    """
    ws = workspace_service.update_workspace(
        db,
        workspace_id=workspace_id,
        tenant_id=current_user.tenant_id,
        data=payload,
        is_superuser=_is_admin(current_user),
    )
    if ws is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    if not PermissionService().check(db, current_user, "workspace.update", workspace_id):
        raise HTTPException(
            status_code=403,
            detail=f"无权限: workspace.update",
        )
    return SingleResponse(data=ws)


# -- 5. delete -----------------------------------------------------------


@router.delete(
    "/{workspace_id}",
)
def delete_workspace(
    workspace_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Hard-delete a workspace; KBs hang off the tenant directly after.

    M38.2.x v2: ``workspace.delete`` permission is required.
    Permission check happens AFTER tenant-scoped lookup so
    cross-tenant deletes return 404 (don't leak existence).

    Returns ``{"deleted": true/false}`` for symmetry with the
    other admin endpoints (no envelope on the response body —
    the spec only requires the side-effect).
    """
    # 先 tenant 隔离查找 — 跨租户返 404(spec §6.4 不 leak 存在性)
    ws = workspace_service.get_workspace(
        db,
        workspace_id=workspace_id,
        tenant_id=current_user.tenant_id,
        is_superuser=_is_admin(current_user),
    )
    if ws is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    if not PermissionService().check(db, current_user, "workspace.delete", workspace_id):
        raise HTTPException(
            status_code=403,
            detail=f"无权限: workspace.delete",
        )
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
    """Single round-trip tree response for the sidebar.

    M38.2.x v2: ``workspace.read`` permission is required.
    Permission check happens AFTER tree lookup so cross-tenant
    access returns 404 (don't leak existence).
    """
    tree = workspace_service.get_workspace_tree(
        db,
        workspace_id=workspace_id,
        tenant_id=current_user.tenant_id,
        is_superuser=_is_admin(current_user),
    )
    if tree is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    if not PermissionService().check(db, current_user, "workspace.read", workspace_id):
        raise HTTPException(
            status_code=403,
            detail=f"无权限: workspace.read",
        )
    return SingleResponse(data=tree)
