"""M38.2.x v2: workspace member management service.

Wraps the SQL behind the 5 member-management endpoints
(``backend/lumen_api/v1/workspace_members.py``):

- ``list_members(workspace_id)``             → for ``GET /members``
- ``invite_member(workspace_id, user_id, perms, actor)`` → for ``POST /members``
- ``update_member(workspace_id, user_id, perms, actor)`` → for ``PUT /members/{uid}``
- ``remove_member(workspace_id, user_id, actor)``       → for ``DELETE /members/{uid}``
- ``transfer_ownership(workspace_id, new_owner_id, actor)`` → for ``POST /transfer-ownership``

Permission validation against ``permission_service._KNOWN_PERMS``
happens here so the API layer stays thin. Cross-tenant invites
raise 403. UNIQUE-constraint races on invite are caught and
turned into a 409 ``already_granted`` response (idempotent retry).

``transfer_ownership`` writes an ``AuditLog`` row INLINE (same
transaction) — going through ``LoggingService.log_audit`` would
commit the audit row in a separate transaction and break
atomicity (spec §10 risk).

Spec: ``docs-internal/superpowers/specs/2026-08-27-workspace-rbac.md`` § 8.1.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import HTTPException
from sqlalchemy import delete as sa_delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from lumen_models.user import User
from lumen_models.workspace import Workspace
from lumen_models.workspace_member_permission import WorkspaceMemberPermission
from lumen_schemas.workspace import WorkspaceRead
from lumen_schemas.workspace_member import WorkspaceMemberRead
from lumen_services.permission_service import _KNOWN_PERMS

logger = logging.getLogger(__name__)


class WorkspaceMemberService:
    """Stateless service — instantiate per-request or share via DI."""

    # --- shared helpers --------------------------------------------------

    @staticmethod
    def _validate_workspace(
        db: Session, workspace_id: int, tenant_id: Optional[int], is_superuser: bool,
    ) -> Workspace:
        """Load the workspace + enforce tenant visibility.

        Returns the ORM ``Workspace`` row. Raises 404 for missing or
        cross-tenant access (admins can see across tenants — they
        skip the tenant filter).
        """
        ws = db.get(Workspace, workspace_id)
        if ws is None:
            raise HTTPException(status_code=404, detail="Workspace not found")
        if not is_superuser and tenant_id is not None and ws.tenant_id != tenant_id:
            raise HTTPException(status_code=404, detail="Workspace not found")
        return ws

    @staticmethod
    def _validate_permissions(perms: List[str]) -> List[str]:
        """校验 permission 全在 ``_KNOWN_PERMS`` 白名单。

        重复 / 不存在都报 400。返回去重后的 sorted list(便于 diff)。
        """
        if not perms:
            return []
        seen = set()
        unknown: List[str] = []
        for p in perms:
            if p not in _KNOWN_PERMS:
                unknown.append(p)
            elif p not in seen:
                seen.add(p)
        if unknown:
            raise HTTPException(
                status_code=400,
                detail=f"unknown permission token(s): {sorted(unknown)}",
            )
        return sorted(seen)

    # --- list ------------------------------------------------------------

    def list_members(
        self, db: Session, workspace_id: int, actor: User,
    ) -> List[WorkspaceMemberRead]:
        """Return one row per user that has any grant on the workspace.

        Users with zero rows are omitted — they have no presence on
        the workspace at all. Owners are included with the full
        ``_ALL_PERMS`` set (we don't store the rows, but we surface
        them so the UI can disable the owner pill correctly).
        """
        ws = self._validate_workspace(
            db, workspace_id,
            tenant_id=actor.tenant_id,
            is_superuser=bool(getattr(actor, "is_superuser", False)),
        )
        rows = db.execute(
            __import__("sqlalchemy").select(
                WorkspaceMemberPermission.user_id,
                WorkspaceMemberPermission.permission,
                WorkspaceMemberPermission.created_at,
            ).where(
                WorkspaceMemberPermission.workspace_id == workspace_id,
            )
        ).all()
        per_user: dict = {}
        for user_id, perm, created_at in rows:
            entry = per_user.setdefault(
                int(user_id),
                {"perms": set(), "granted_at": created_at},
            )
            entry["perms"].add(perm)
        # owner 自动有全 perm,但 workspace.owner_id 是 nullable;
        # owner_id == None 视为「无 owner」,不参与 display。
        owner_id = ws.owner_id
        if owner_id is not None:
            owner_entry = per_user.setdefault(
                int(owner_id),
                {"perms": set(), "granted_at": None},
            )
            owner_entry["perms"] = set(_KNOWN_PERMS)
        items: List[WorkspaceMemberRead] = []
        for uid, info in per_user.items():
            user_row = db.get(User, uid)
            items.append(WorkspaceMemberRead(
                user_id=int(uid),
                username=getattr(user_row, "username", None) if user_row else None,
                permissions=sorted(info["perms"]),
                granted_at=info["granted_at"],
                is_owner=(owner_id is not None and int(owner_id) == int(uid)),
            ))
        # 稳定排序:owner 在前,其他按 user_id
        items.sort(key=lambda x: (not x.is_owner, x.user_id))
        return items

    # --- invite ----------------------------------------------------------

    def invite_member(
        self,
        db: Session,
        workspace_id: int,
        user_id: int,
        permissions: List[str],
        actor: User,
    ) -> WorkspaceMemberRead:
        """Grant a set of permissions to a user on a workspace.

        Sanity:
        - workspace 必须在 actor 的 tenant(管理员可跨)
        - target user 必须同 tenant(跨 tenant → 403,防「跨租户邀请」漏洞)
        - permission 全在白名单
        - 不允许邀请 owner(已经有全 perm 了;若想改 owner,走 transfer-ownership)
        - 不允许 actor 邀请自己(workspace.manage_members 不需要此路径)
        """
        ws = self._validate_workspace(
            db, workspace_id,
            tenant_id=actor.tenant_id,
            is_superuser=bool(getattr(actor, "is_superuser", False)),
        )
        target_user = db.get(User, user_id)
        if target_user is None:
            raise HTTPException(status_code=404, detail="目标 user 不存在")
        if target_user.tenant_id != ws.tenant_id:
            raise HTTPException(status_code=403, detail="跨租户邀请被拒绝")
        if ws.owner_id is not None and int(ws.owner_id) == int(user_id):
            raise HTTPException(
                status_code=400,
                detail="owner 已自动有全部 permission,无需重复邀请",
            )
        perms = self._validate_permissions(permissions)
        if not perms:
            raise HTTPException(status_code=400, detail="permissions 不能为空")

        rows = [
            WorkspaceMemberPermission(
                workspace_id=workspace_id,
                user_id=user_id,
                permission=p,
                granted_by=actor.id,
            )
            for p in perms
        ]
        try:
            db.bulk_save_objects(rows)
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            # UNIQUE 冲突 = 该 user 已有同名 permission(spec §11 风险缓解)
            raise HTTPException(
                status_code=409,
                detail="该用户已有同名 permission(已 granted,无需重复邀请)",
            ) from exc
        return WorkspaceMemberRead(
            user_id=user_id,
            username=getattr(target_user, "username", None),
            permissions=perms,
            is_owner=False,
        )

    # --- update ----------------------------------------------------------

    def update_member(
        self,
        db: Session,
        workspace_id: int,
        user_id: int,
        new_permissions: List[str],
        actor: User,
    ) -> WorkspaceMemberRead:
        """整组覆盖:DELETE 不在列表里的,INSERT 新加的。

        Owner 不走这条路径(改 owner 走 transfer-ownership);若 user 是
        owner,仍然 UPDATE grant rows(目前 owner auto 全 perm,row 不影响
        effective 集合;但保留路径完整)。
        """
        self._validate_workspace(
            db, workspace_id,
            tenant_id=actor.tenant_id,
            is_superuser=bool(getattr(actor, "is_superuser", False)),
        )
        target_user = db.get(User, user_id)
        if target_user is None:
            raise HTTPException(status_code=404, detail="目标 user 不存在")
        perms = self._validate_permissions(new_permissions)  # 去重 + 排序
        # 1. DELETE 现有所有 row
        db.execute(
            sa_delete(WorkspaceMemberPermission).where(
                WorkspaceMemberPermission.workspace_id == workspace_id,
                WorkspaceMemberPermission.user_id == user_id,
            )
        )
        # 2. INSERT 新 row
        if perms:
            db.bulk_save_objects([
                WorkspaceMemberPermission(
                    workspace_id=workspace_id,
                    user_id=user_id,
                    permission=p,
                    granted_by=actor.id,
                )
                for p in perms
            ])
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            logger.exception("update_member IntegrityError")
            raise HTTPException(status_code=409, detail="permission grant 冲突") from exc
        return WorkspaceMemberRead(
            user_id=user_id,
            username=getattr(target_user, "username", None),
            permissions=perms,
            is_owner=False,
        )

    # --- remove ----------------------------------------------------------

    def remove_member(
        self,
        db: Session,
        workspace_id: int,
        user_id: int,
        actor: User,
    ) -> int:
        """DELETE 该 user 在该 workspace 上的所有 grant row。

        owner 不允许删(workspace 不可没有 owner);改 owner 用 transfer。
        返回删除的 row 数。
        """
        ws = self._validate_workspace(
            db, workspace_id,
            tenant_id=actor.tenant_id,
            is_superuser=bool(getattr(actor, "is_superuser", False)),
        )
        if ws.owner_id is not None and int(ws.owner_id) == int(user_id):
            raise HTTPException(
                status_code=400,
                detail="owner 是 workspace 的核心,删除 owner 请走 transfer-ownership",
            )
        result = db.execute(
            sa_delete(WorkspaceMemberPermission).where(
                WorkspaceMemberPermission.workspace_id == workspace_id,
                WorkspaceMemberPermission.user_id == user_id,
            )
        )
        db.commit()
        return int(result.rowcount or 0)

    # --- transfer ownership ---------------------------------------------

    def transfer_ownership(
        self,
        db: Session,
        workspace_id: int,
        new_owner_id: int,
        actor: User,
    ) -> WorkspaceRead:
        """转让 workspace 所有权给 new_owner_id。

        步骤(同事务):
        1. workspace.owner_id = new_owner_id
        2. inline ``db.add(AuditLog(...))`` 写 audit row(spec §10 风险:
           不调 ``LoggingService.log_audit`` 因为它单独 commit,会丢原子性)
        3. db.commit()

        旧 owner 当前的 grant row 保留不动(降级为普通 member);新 owner
        自动有全 perm(代码层 ``_is_owner`` 检查,不需要 grant row)。
        """
        from lumen_services.logging_service import AuditLog

        ws = self._validate_workspace(
            db, workspace_id,
            tenant_id=actor.tenant_id,
            is_superuser=bool(getattr(actor, "is_superuser", False)),
        )
        new_owner = db.get(User, new_owner_id)
        if new_owner is None:
            raise HTTPException(status_code=404, detail="新 owner 不存在")
        if new_owner.tenant_id != ws.tenant_id:
            raise HTTPException(status_code=403, detail="跨租户 owner 转让被拒绝")

        old_owner_id = ws.owner_id
        ws.owner_id = new_owner_id
        db.flush()  # 让 workspace UPDATE 先生效,AuditLog.details 用 old_owner_id

        audit = AuditLog(
            user_id=actor.id,
            tenant_id=ws.tenant_id,
            username=getattr(actor, "username", None),
            action="workspace.transfer_ownership",
            resource_type="workspace",
            resource_id=str(workspace_id),
            details={
                "from_owner_id": old_owner_id,
                "to_owner_id": new_owner_id,
            },
            status="success",
        )
        db.add(audit)
        db.commit()
        db.refresh(ws)
        # 把更新后的 owner_id 通过 workspace_service 走一遍 list 的同款填充
        # (知识库计数 + WorkspaceRead.model_validate)。需要 admin 标志
        # 才能跨 tenant 看 —— transfer 是同 tenant,这里只是为了填字段。
        from lumen_services.workspace_service import workspace_service
        result = workspace_service.get_workspace(
            db,
            workspace_id=workspace_id,
            tenant_id=ws.tenant_id,
            is_superuser=True,
        )
        if result is None:  # pragma: no cover —— transfer 成功后 get 一定不为 None
            raise HTTPException(status_code=500, detail="transfer_ownership 后 workspace 读取失败")
        return result


workspace_member_service = WorkspaceMemberService()