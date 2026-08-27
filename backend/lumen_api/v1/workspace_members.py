"""M38.2.x v2: workspace member management endpoints.

5 endpoints mounted under ``/api/v1/workspaces/{workspace_id}/...``:

- ``GET    /workspaces/{workspace_id}/members`` → ``WorkspaceMemberListResponse``
- ``POST   /workspaces/{workspace_id}/members`` body ``WorkspaceMemberInvite``
- ``PUT    /workspaces/{workspace_id}/members/{user_id}`` body ``WorkspaceMemberUpdate``
- ``DELETE /workspaces/{workspace_id}/members/{user_id}``
- ``POST   /workspaces/{workspace_id}/transfer-ownership`` body ``WorkspaceTransferOwnership``

All endpoints rely on ``require_workspace_perm`` for the RBAC check
(spec §5.1.1):

- list    → ``workspace.read`` + ``workspace.manage_members`` (取较严格那个)
- invite  → ``workspace.manage_members``
- update  → ``workspace.manage_members``
- remove  → ``workspace.manage_members``
- transfer → ``workspace.transfer_ownership``

Mounted in ``lumen_api/v1/__init__.py``.

Spec: ``docs-internal/superpowers/specs/2026-08-27-workspace-rbac.md`` § 5.1.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from lumen_api.v1.auth import get_current_user
from lumen_core.database import get_db
from lumen_models.user import User
from lumen_schemas.common import SingleResponse
from lumen_schemas.workspace import WorkspaceRead
from lumen_schemas.workspace_member import (
    WorkspaceMemberInvite,
    WorkspaceMemberListResponse,
    WorkspaceMemberRead,
    WorkspaceMemberUpdate,
    WorkspaceTransferOwnership,
)
from lumen_services.permission_service import require_workspace_perm
from lumen_services.workspace_member_service import workspace_member_service

# ``prefix`` 留空 — 我们已经在 endpoint 上写完整路径(便于 include_router
# 时扁平挂在 v1 root,与 workspace.py 同款)。
router = APIRouter(tags=["workspace-members"])


# --- 1. list members ----------------------------------------------------


@router.get(
    "/workspaces/{workspace_id}/members",
    response_model=SingleResponse[WorkspaceMemberListResponse],
    dependencies=[Depends(require_workspace_perm("workspace.read"))],
)
def list_members(
    workspace_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all members + their permission set on the workspace.

    Owner is included with the full effective permission set (we
    surface this even though no row exists, so the UI can render the
    owner pill and disable the remove button).
    """
    items = workspace_member_service.list_members(
        db,
        workspace_id=workspace_id,
        actor=current_user,
    )
    return SingleResponse(
        data=WorkspaceMemberListResponse(
            workspace_id=workspace_id,
            items=items,
        ),
    )


# --- 2. invite ----------------------------------------------------------


@router.post(
    "/workspaces/{workspace_id}/members",
    response_model=SingleResponse[WorkspaceMemberRead],
    dependencies=[Depends(require_workspace_perm("workspace.manage_members"))],
)
def invite_member(
    workspace_id: int,
    payload: WorkspaceMemberInvite,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Invite a user + grant initial permission set.

    Cross-tenant invite → 403; unknown permission → 400; UNIQUE race
    on (user, ws, perm) → 409 ``already_granted``.
    """
    member = workspace_member_service.invite_member(
        db,
        workspace_id=workspace_id,
        user_id=payload.user_id,
        permissions=payload.permissions,
        actor=current_user,
    )
    return SingleResponse(data=member)


# --- 3. update ----------------------------------------------------------


@router.put(
    "/workspaces/{workspace_id}/members/{user_id}",
    response_model=SingleResponse[WorkspaceMemberRead],
    dependencies=[Depends(require_workspace_perm("workspace.manage_members"))],
)
def update_member(
    workspace_id: int,
    user_id: int,
    payload: WorkspaceMemberUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Whole-set overwrite the member's permission list."""
    member = workspace_member_service.update_member(
        db,
        workspace_id=workspace_id,
        user_id=user_id,
        new_permissions=payload.permissions,
        actor=current_user,
    )
    return SingleResponse(data=member)


# --- 4. remove ----------------------------------------------------------


@router.delete(
    "/workspaces/{workspace_id}/members/{user_id}",
    response_model=SingleResponse[dict],
    dependencies=[Depends(require_workspace_perm("workspace.manage_members"))],
)
def remove_member(
    workspace_id: int,
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Drop ALL grants for a user on this workspace.

    Owner cannot be removed (use transfer-ownership). Returns
    ``{"deleted_rows": N}`` for client telemetry.
    """
    deleted = workspace_member_service.remove_member(
        db,
        workspace_id=workspace_id,
        user_id=user_id,
        actor=current_user,
    )
    return SingleResponse(data={"deleted_rows": deleted})


# --- 5. transfer ownership ---------------------------------------------


@router.post(
    "/workspaces/{workspace_id}/transfer-ownership",
    response_model=SingleResponse[WorkspaceRead],
    dependencies=[Depends(require_workspace_perm("workspace.transfer_ownership"))],
)
def transfer_ownership(
    workspace_id: int,
    payload: WorkspaceTransferOwnership,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Hand the workspace to a new owner.

    Old owner's permission rows are NOT changed (they keep their
    current grants, now demoted to "member"). New owner auto-grants
    full permission via the owner bypass (``_is_owner`` check in
    ``PermissionService.check``) — no row insertion.

    Writes an ``AuditLog`` row INLINE so the audit + workspace UPDATE
    commit atomically (spec §10 risk; ``LoggingService.log_audit``
    would commit separately and break atomicity).
    """
    ws = workspace_member_service.transfer_ownership(
        db,
        workspace_id=workspace_id,
        new_owner_id=payload.new_owner_id,
        actor=current_user,
    )
    return SingleResponse(data=ws)