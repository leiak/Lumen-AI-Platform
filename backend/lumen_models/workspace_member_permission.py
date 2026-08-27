"""M38.2.x v2: Workspace RBAC permission grants.

ACL-permission granularity: one row per (workspace, user, permission).
Adding/removing a permission is an INSERT/DELETE — no JSON array
updates. ``UNIQUE (workspace_id, user_id, permission)`` makes invites
idempotent (re-granting the same permission is a no-op-ish 409 that
the API layer maps to ``already_granted``).

Owner bypass is enforced in ``PermissionService.check`` — owners do
NOT get rows inserted; the workspace ``owner_id`` column is the source
of truth for "automatic full permission".

Spec: ``docs-internal/superpowers/specs/2026-08-27-workspace-rbac.md`` § 3.1.
"""
from __future__ import annotations

from sqlalchemy import Column, ForeignKey, Index, Integer, String, UniqueConstraint

from lumen_models.base import BaseModel


class WorkspaceMemberPermission(BaseModel):
    """M38.2.x v2: per-(workspace, user, permission) grant row.

    The 17 permission strings (``workspace.read``,
    ``kb.read`` …) live in
    ``lumen_services.permission_service._PERM_IMPLIES`` — there's no
    enum column so adding a new permission doesn't require a schema
    migration.
    """

    __tablename__ = "workspace_member_permissions"

    workspace_id = Column(
        Integer,
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        comment="FK -> workspaces.id; ON DELETE CASCADE drops the grants with the workspace",
    )
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        comment="FK -> users.id; ON DELETE CASCADE drops the grants when the user is hard-deleted",
    )
    # permission token, e.g. ``kb.read`` / ``document.create``.
    # String(64) per spec §3.1.
    permission = Column(
        String(64),
        nullable=False,
        comment="ACL permission token (e.g. 'kb.read', 'document.create'); see permission_service._PERM_IMPLIES",
    )
    granted_by = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        comment="Who granted the permission (audit trail); nullable + SET NULL so deleting a user does not cascade",
    )

    __table_args__ = (
        # 同 user 在同 workspace 下同 permission 只一行(幂等 + 防 race)
        UniqueConstraint(
            "workspace_id",
            "user_id",
            "permission",
            name="uq_wmp_ws_user_perm",
        ),
        # 反向查「user 能访问哪些 workspace」
        Index("idx_wmp_user", "user_id"),
        Index("idx_wmp_ws", "workspace_id"),
    )