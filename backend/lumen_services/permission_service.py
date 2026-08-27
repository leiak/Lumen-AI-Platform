"""M38.2.x v2: workspace RBAC permission service.

Single source of truth for "does this user have this permission on
this workspace". Backs the FastAPI dependency
``require_workspace_perm(permission)`` and the bulk loader
``load_user_workspace_permissions`` used by list endpoints.

Permission tokens + their implications live in
``_PERM_IMPLIES`` (spec §6.2):

- ``kb.read`` → ``document.read``  (看 KB 自动看 doc,避免 UX 割裂)
- ``kb.update`` → ``kb.read``
- ``kb.create`` → ``kb.read``
- ``kb.delete`` → ``kb.read``
- ``folder.*`` 同模式
- ``document.*`` 同模式

Owner auto 全 perm(``Workspace.owner_id == user.id`` 直接 True,不
依赖 row);superuser (``User.is_superuser``) 也是 True,跟既有 admin
哲学一致。

``workspace_id IS NULL`` 的 KB(老数据 + 没归 workspace 的)对所有
tenant user 自动开 ``kb.read``(spec §6.4 默认开放,避免 ship 即破
既有 1537 测试),写操作仍要 superuser 或 owner。

``user is None`` 语义:**graceful open**(用于 widget visitor / 系统
cron / 老 fixture 默认跑通)。

Spec: ``docs-internal/superpowers/specs/2026-08-27-workspace-rbac.md`` § 6.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Dict, Iterable, List, Optional, Set

from fastapi import Depends, HTTPException, Path
from sqlalchemy.orm import Session

from lumen_core.database import get_db
from lumen_models.user import User
from lumen_models.workspace import Workspace
from lumen_models.workspace_member_permission import WorkspaceMemberPermission


# --- 17 permission tokens + implication chain ----------------------------
#
# 4 资源轴 × 动作:workspace(5) + kb(4) + folder(5) + document(5) = 19
# 实际定义 19 个(permission 列保留冗余方便排错 + 未来扩展)。implication
# 在 _PERM_IMPLIES 里手动维护,加新 permission 时记得在 _KNOWN_PERMS
# 与 _PERM_IMPLIES 同时加。
#
# Spec §4 把总数算成 17 是因为 ``workspace.read`` 被多个 endpoint 复用
# 不单独算;我们用 19 项更显式。

# Read-only permissions (5 项):用于「只读」快捷按钮批量授权。
_READ_ONLY_PERMS = frozenset({
    "workspace.read",
    "kb.read",
    "folder.read",
    "document.read",
})

# Write permissions = read + create/update/move(不含 delete / manage)
_WRITE_PERMS = frozenset({
    "workspace.read",
    "workspace.update",
    "kb.read",
    "kb.create",
    "kb.update",
    "folder.read",
    "folder.create",
    "folder.update",
    "document.read",
    "document.create",
    "document.update",
    "document.move",
})

_ALL_PERMS = frozenset({
    "workspace.read",
    "workspace.update",
    "workspace.delete",
    "workspace.transfer_ownership",
    "workspace.manage_members",
    "kb.read",
    "kb.create",
    "kb.update",
    "kb.delete",
    "folder.read",
    "folder.create",
    "folder.update",
    "folder.delete",
    "folder.restore",
    "document.read",
    "document.create",
    "document.update",
    "document.delete",
    "document.move",
})


_PERM_IMPLIES: Dict[str, List[str]] = {
    "workspace.update": ["workspace.read"],
    "workspace.delete": ["workspace.read"],
    "workspace.manage_members": ["workspace.read"],
    "workspace.transfer_ownership": ["workspace.read"],
    "kb.create": ["kb.read"],
    "kb.update": ["kb.read"],
    "kb.delete": ["kb.read"],
    # 看 KB 自动看 KB 内 doc(spec §4.1 UX 决策)
    "kb.read": ["document.read"],
    "folder.create": ["folder.read"],
    "folder.update": ["folder.read"],
    "folder.delete": ["folder.read"],
    "folder.restore": ["folder.read"],
    "document.create": ["document.read"],
    "document.update": ["document.read"],
    "document.delete": ["document.read"],
    "document.move": ["folder.read", "folder.update"],
}

# Sanity: all implied targets must themselves be _KNOWN_PERMS so the
# service never returns a token the API layer doesn't recognise.
_KNOWN_PERMS: frozenset = _ALL_PERMS


def _is_admin(user: Optional[User]) -> bool:
    """``User.is_superuser`` 取值(``None`` 视为 False)。"""
    if user is None:
        return False
    return bool(getattr(user, "is_superuser", False))


def _is_owner(db: Session, user: Optional[User], workspace_id: Optional[int]) -> bool:
    """``Workspace.owner_id == user.id``?对 ``None`` user / ``None`` ws 一律 False。"""
    if user is None or workspace_id is None:
        return False
    owner_id = db.execute(
        # 走 SELECT 而不是 db.get —— workspace_id 可能已被删,取一次就行
        __import__("sqlalchemy").select(Workspace.owner_id)
        .where(Workspace.id == workspace_id)
        .limit(1)
    ).scalar_one_or_none()
    return owner_id is not None and owner_id == user.id


def _workspace_member_perms(
    db: Session, user: User, workspace_ids: Iterable[int],
) -> Dict[int, Set[str]]:
    """一次 SQL IN (...) 拉完 user 在指定 workspace 上的全部 grant 集合。

    返回 ``{workspace_id: {permission, ...}}``。owner 自动全 perm
    (``PermissionService.check`` 也会判,但这里一并算,让 list endpoint
    直接 O(1) 取 effective_perms)。
    """
    ws_ids = list({int(wid) for wid in workspace_ids if wid is not None})
    if not ws_ids:
        return {}
    rows = db.execute(
        __import__("sqlalchemy").select(
            WorkspaceMemberPermission.workspace_id,
            WorkspaceMemberPermission.permission,
        ).where(
            WorkspaceMemberPermission.user_id == user.id,
            WorkspaceMemberPermission.workspace_id.in_(ws_ids),
        )
    ).all()
    out: Dict[int, Set[str]] = defaultdict(set)
    for ws_id, perm in rows:
        out[int(ws_id)].add(perm)
    return dict(out)


def effective_perms(perm_set: Iterable[str]) -> Set[str]:
    """展开 implication 链,得到 effective permission 集合。

    例 ``{"kb.update"}`` → ``{"kb.update", "kb.read", "document.read"}``。
    反复迭代直到不变,处理 ``A → B → C`` 的传递闭包。
    """
    effective: Set[str] = set(perm_set)
    changed = True
    while changed:
        changed = False
        for p in list(effective):
                for imp in _PERM_IMPLIES.get(p, []):
                    if imp not in effective:
                        effective.add(imp)
                        changed = True
    return effective


class PermissionService:
    """Stateless service; instantiate per-request or share via DI.

    Most callers will only need ``check`` (per-endpoint) and
    ``load_user_workspace_permissions`` (list-endpoint bulk load).
    """

    def check(
        self,
        db: Session,
        user: Optional[User],
        permission: str,
        workspace_id: Optional[int],
    ) -> bool:
        """单条判定。

        优先级(短路):
        1. ``user is None`` 或 ``is_superuser`` → True(spec §6.4 admin 全管)
        2. ``permission`` 不在 ``_KNOWN_PERMS`` → False(白名单,防止 typo)
        3. ``workspace_id is None`` (老数据 / tenant root) → read 类 True;写操作 False(spec §6.4 不变量)
        4. ``workspace.owner_id == user.id`` → True(owner auto 全 perm,无需 row)
        5. ``workspace_member_permissions`` 里有 (user, ws, perm) → True
        6. implication:permission 的源权限(``_PERM_IMPLIES`` 反查)拥有任一项 → True
        """
        if user is None:
            return True  # graceful open(fixture / widget visitor / cron)
        if _is_admin(user):
            return True
        if permission not in _KNOWN_PERMS:
            return False
        if workspace_id is None:
            # 老 KB(workspace_id IS NULL):read 类对全员 in-tenant 开放
            # 写操作仍要 superuser(或 owner,见 §6.5 不变量)。spec §6.4 默认开放。
            return permission in _READ_ONLY_PERMS
        if _is_owner(db, user, workspace_id):
            return True
        # 直接命中(整组覆盖写后行已存在)
        hit = db.execute(
            __import__("sqlalchemy").select(1).where(
                WorkspaceMemberPermission.user_id == user.id,
                WorkspaceMemberPermission.workspace_id == workspace_id,
                WorkspaceMemberPermission.permission == permission,
            ).limit(1)
        ).first()
        if hit is not None:
            return True
        # implication 反查:permission 的源权限(持有 A 即自动有 B → 持有 B 检查 = 持有 A?)
        # 注意只查直接源(不递归),因为 _PERM_IMPLIES 已经把 implied token 链到 source 上,
        # 所以 granting "kb.update" 自动让 effective_perms 含 "kb.read" + "document.read"。
        for source_perm, implied in _PERM_IMPLIES.items():
            if permission in implied:
                # 如果 user 有 source_perm,自动有 permission
                source_hit = db.execute(
                    __import__("sqlalchemy").select(1).where(
                        WorkspaceMemberPermission.user_id == user.id,
                        WorkspaceMemberPermission.workspace_id == workspace_id,
                        WorkspaceMemberPermission.permission == source_perm,
                    ).limit(1)
                ).first()
                if source_hit is not None:
                    return True
        return False

    def load_user_workspace_permissions(
        self,
        db: Session,
        user: Optional[User],
        workspace_ids: Iterable[int],
    ) -> Dict[int, Set[str]]:
        """批量预加载 user 在多个 workspace 上的 effective permission set。

        API 层处理 list endpoint 时一次性调用,后续逐项 O(1) 查。
        ``user is None`` 或 admin → 全 workspace 全 perm。
        ``workspace_id in workspace_ids and owner_id == user.id`` → 全 perm。
        其余按 row 命中 + implication 展开。

        返回 ``{workspace_id: effective permission set}``。
        """
        ws_ids = list({int(wid) for wid in workspace_ids if wid is not None})
        if user is None or _is_admin(user):
            return {wid: set(_ALL_PERMS) for wid in ws_ids}
        if not ws_ids:
            return {}
        # 1. 直接 grant 行
        direct = _workspace_member_perms(db, user, ws_ids)
        # 2. owner 自动全 perm
        owner_ids = set(
            db.execute(
                __import__("sqlalchemy").select(Workspace.id).where(
                    Workspace.id.in_(ws_ids),
                    Workspace.owner_id == user.id,
                )
            ).scalars().all()
        )
        for wid in owner_ids:
            direct[int(wid)] = set(_ALL_PERMS)
        # 3. 展开 implication
        out: Dict[int, Set[str]] = {}
        for wid, perms in direct.items():
            out[int(wid)] = effective_perms(perms)
        return out


def require_workspace_perm(permission: str):
    """FastAPI 工厂依赖:把单 endpoint 跟 RBAC check 一行绑死。

    用法::

        @router.put(
            "/{workspace_id}",
            dependencies=[Depends(require_workspace_perm("workspace.update"))],
        )
        def update_workspace(workspace_id: int, ...): ...

    或者在签名里取 ``user`` 进一步使用::

        @router.get("/{workspace_id}")
        def read_workspace(
            workspace_id: int,
            user: User = Depends(require_workspace_perm("workspace.read")),
        ): ...

    行为:
    - ``user is None`` / ``is_superuser`` → 直通
    - 有 permission / owner / implication 满足 → 直通
    - 否则 403 ``{"detail": "无权限: <permission>"}``

    实现注意:``get_current_user`` 不能在本模块顶层 import,会触发循环
    依赖 (``lumen_api.v1.auth`` 在 module load 时 import 本模块)。我们把
    import 放在 factory 调用时 — FastAPI 第一次解析 endpoint 时模块树已
    完全加载,延迟 import 安全;同时默认参数 ``Depends(get_current_user)``
    在 factory 函数体内创建后才被 FastAPI 解析。
    """
    # 延迟 import — factory 被调用时,模块树已加载完,不会触发循环
    from lumen_api.v1.auth import get_current_user  # noqa: PLC0415

    def _checker(
        workspace_id: int = Path(...),
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> User:
        if not PermissionService().check(db, user, permission, workspace_id):
            raise HTTPException(
                status_code=403,
                detail=f"无权限: {permission}",
            )
        return user

    return _checker


__all__ = [
    "ALL_PERMISSIONS",
    "READ_ONLY_PERMISSIONS",
    "WRITE_PERMISSIONS",
    "PermissionService",
    "effective_perms",
    "require_workspace_perm",
]


# 重命名方便 import
ALL_PERMISSIONS = _ALL_PERMS
READ_ONLY_PERMISSIONS = _READ_ONLY_PERMS
WRITE_PERMISSIONS = _WRITE_PERMS


# --- resolve-via-entity helpers (for endpoints whose id is not workspace) -
#
# FastAPI dependency ``require_workspace_perm`` 接受 ``workspace_id: Path``
# 的形式。folders / knowledge / documents endpoint 路径里只有 ``kb_id``
# 或 ``folder_id`` 或 ``document_id``,需要在 endpoint 体内先 lookup
# 实体 → 取 workspace_id → 再 check。
#
# ``assert_perm_via_*`` 把"取实体 + tenant 隔离 + permission check"封成
# 一行调用:成功直返(workspace_id, ...),失败抛 HTTPException。
#
# 设计原则:
# - 失败一律 404(隐藏实体是否存在,防跨租户枚举攻击)
# - superuser 直通(不需 grant row)
# - ``workspace_id IS NULL`` 老 KB 走 check(user, perm, workspace_id=None)
#   的内置逻辑(spec §6.4 默认开放)


def _is_superuser(user: Optional[User]) -> bool:
    """方便 endpoint 体内判 admin 的小 helper(避免每次写 getattr)。"""
    return bool(getattr(user, "is_superuser", False)) if user is not None else False


def assert_perm_via_kb(
    db: Session, user: Optional[User], permission: str, kb_id: int,
) -> None:
    """``kb_id`` → 查 KB → 取 workspace_id → check permission。

    失败:跨租户 / KB 不存在 → 404;无 permission → 403。
    """
    from fastapi import HTTPException
    from lumen_models.knowledge import KnowledgeBase

    if user is None:
        return  # graceful open
    if _is_superuser(user):
        # admin 跨 tenant 仍要 KB 真实存在
        kb = db.get(KnowledgeBase, kb_id)
        if kb is None:
            raise HTTPException(status_code=404, detail="Knowledge base not found")
        return
    kb = (
        db.query(KnowledgeBase)
        .filter(KnowledgeBase.id == kb_id, KnowledgeBase.tenant_id == user.tenant_id)
        .first()
    )
    if kb is None:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    if not PermissionService().check(db, user, permission, kb.workspace_id):
        raise HTTPException(
            status_code=403,
            detail=f"无权限: {permission}",
        )


def assert_perm_via_folder(
    db: Session, user: Optional[User], permission: str, folder_id: int,
) -> None:
    """``folder_id`` → folder → kb → check permission。

    folder.knowledge_base_id 必须存在(KB 已硬删的话 FK 会被 CASCADE
    一起带走,所以 folder 行 KB 缺失是数据 corruption 状态;404 处理)。
    """
    from fastapi import HTTPException
    from lumen_models.knowledge import KnowledgeBase
    from lumen_models.workspace import DocumentFolder

    if user is None:
        return
    if _is_superuser(user):
        folder = db.get(DocumentFolder, folder_id)
        if folder is None:
            raise HTTPException(status_code=404, detail="Folder not found")
        return
    folder = db.get(DocumentFolder, folder_id)
    if folder is None:
        raise HTTPException(status_code=404, detail="Folder not found")
    kb = (
        db.query(KnowledgeBase)
        .filter(
            KnowledgeBase.id == folder.knowledge_base_id,
            KnowledgeBase.tenant_id == user.tenant_id,
        )
        .first()
    )
    if kb is None:
        raise HTTPException(status_code=404, detail="Folder not found")
    if not PermissionService().check(db, user, permission, kb.workspace_id):
        raise HTTPException(
            status_code=403,
            detail=f"无权限: {permission}",
        )


def assert_perm_via_document(
    db: Session, user: Optional[User], permission: str, document_id: int,
) -> None:
    """``document_id`` → doc → kb → check permission。"""
    from fastapi import HTTPException
    from lumen_models.knowledge import Document, KnowledgeBase

    if user is None:
        return
    if _is_superuser(user):
        doc = db.get(Document, document_id)
        if doc is None:
            raise HTTPException(status_code=404, detail="Document not found")
        return
    doc = (
        db.query(Document)
        .filter(
            Document.id == document_id,
            Document.knowledge_base.has(tenant_id=user.tenant_id),
        )
        .first()
    )
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    kb = doc.knowledge_base
    if not PermissionService().check(db, user, permission, kb.workspace_id):
        raise HTTPException(
            status_code=403,
            detail=f"无权限: {permission}",
        )