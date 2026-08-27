"""M38.2.x v2: workspace member management schemas.

Request / response shapes for the 5 member-management endpoints:

- ``GET    /api/v1/workspaces/{id}/members``  → ``WorkspaceMemberListResponse``
- ``POST   /api/v1/workspaces/{id}/members``  body: ``WorkspaceMemberInvite``
- ``PUT    /api/v1/workspaces/{id}/members/{user_id}``  body: ``WorkspaceMemberUpdate``
- ``DELETE /api/v1/workspaces/{id}/members/{user_id}``
- ``POST   /api/v1/workspaces/{id}/transfer-ownership``  body: ``WorkspaceTransferOwnership``

The 17 permission tokens live in
``lumen_services.permission_service._PERM_IMPLIES`` — this file only
declares Pydantic containers, never the permission enum, so adding a
new permission does NOT require a schema migration.

Spec: ``docs-internal/superpowers/specs/2026-08-27-workspace-rbac.md`` § 5.1.
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class WorkspaceMemberInvite(BaseModel):
    """Body of ``POST /api/v1/workspaces/{id}/members``.

    ``permissions`` is the initial grant set; duplicate or invalid
    tokens → 400. Re-granting a permission the user already has is a
    no-op (the INSERT 409s are caught and turned into
    ``already_granted`` 409 responses by the service).
    """

    user_id: int = Field(..., description="目标 user.id;必须与 workspace 同 tenant")
    permissions: List[str] = Field(
        default_factory=list,
        description="授予的 permission token 列表(17 项任选)",
    )


class WorkspaceMemberRead(BaseModel):
    """Single member row in the response of ``GET /members``.

    Permission set is denormalized into a sorted list so the frontend
    can render a permission matrix without a second round-trip.
    """

    user_id: int
    username: Optional[str] = None
    permissions: List[str] = Field(default_factory=list)
    granted_at: Optional[datetime] = None
    # Marked True when this user is also the workspace owner — UI uses
    # this to render the owner pill and disable self-removal.
    is_owner: bool = False


class WorkspaceMemberListResponse(BaseModel):
    """Response of ``GET /api/v1/workspaces/{id}/members``.

    Includes the workspace ``id`` (echoed) so the frontend doesn't
    have to thread it through separately.
    """

    workspace_id: int
    items: List[WorkspaceMemberRead] = Field(default_factory=list)


class WorkspaceMemberUpdate(BaseModel):
    """Body of ``PUT /api/v1/workspaces/{id}/members/{user_id}``.

    Whole-set overwrite: rows whose ``permission`` is NOT in the new
    list are deleted; rows whose ``permission`` is in the new list
    but missing are added. This is the "set the user set" pattern —
    explicit deletion of the resource is a separate
    ``DELETE /members/{user_id}`` call.

    An empty list removes ALL grants (effectively same as DELETE on
    the membership row, except DELETE also wipes the audit trail).
    """

    permissions: List[str] = Field(
        default_factory=list,
        description="整组覆盖;在列表外的会被 DELETE,在列表内缺失会被 INSERT",
    )


class WorkspaceTransferOwnership(BaseModel):
    """Body of ``POST /api/v1/workspaces/{id}/transfer-ownership``.

    The new owner auto-grants ALL permissions via the ``owner``
    bypass in ``PermissionService.check`` — no row insertion is
    performed. The old owner keeps their current grants (typically
    full perm if they were already an admin).
    """

    new_owner_id: int = Field(..., description="新 owner 的 users.id;必须同 tenant")