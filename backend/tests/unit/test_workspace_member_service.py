"""M38.2.x v2: unit tests for ``WorkspaceMemberService``.

Pure unit tests with fake session — covers spec §8.1:
- _validate_workspace tenant filter
- _validate_permissions 白名单
- invite / update / remove / transfer_ownership 主要路径
- 跨租户拒绝
- UNIQUE conflict → 409
- owner 不可删除/邀请

不需要真 MySQL / FastAPI。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest
from fastapi import HTTPException

from lumen_services.workspace_member_service import WorkspaceMemberService


class _FakeWorkspace:
    def __init__(self, *, id, tenant_id, owner_id):
        self.id = id
        self.tenant_id = tenant_id
        self.owner_id = owner_id
        self.name = "ws"
        self.description = None
        self.icon = None
        self.color = None


class _FakeUser:
    def __init__(self, *, id, tenant_id, username=None, is_superuser=False):
        self.id = id
        self.tenant_id = tenant_id
        self.username = username or f"u{id}"
        self.is_superuser = is_superuser
        self.is_active = True


class _FakePermissionRow:
    """模拟 SQLAlchemy ``Row`` — 既能 .user_id / .permission 属性访问,
    又能 ``for u, p, c in row: ...`` tuple 解包。
    """

    def __init__(self, *, workspace_id, user_id, permission, granted_by=None, created_at=None):
        self.workspace_id = workspace_id
        self.user_id = user_id
        self.permission = permission
        self.granted_by = granted_by
        self.created_at = created_at
        self._tuple = (user_id, permission, created_at)

    def __iter__(self):
        return iter(self._tuple)


class _FakeSelectResult:
    def __init__(self, rows):
        self._rows = rows

    def first(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return self._rows


class _FakeSession:
    """最小 fake:支持 workspace get + member perm CRUD。

    通过 ``integrity_error_on`` 控制 IntegrityError 触发时机。
    """

    def __init__(self, *, workspace=None, users=None, perm_rows=None,
                 integrity_error_on=None, delete_rowcount=1):
        self.workspace = workspace
        self.users = users or {}
        self.perm_rows = perm_rows or []
        self.integrity_error_on = integrity_error_on
        self.delete_rowcount = delete_rowcount
        self.added: List[Any] = []
        self.commits = 0

    def get(self, model, pk):
        name = getattr(model, "__name__", None)
        if name == "Workspace":
            if self.workspace and self.workspace.id == pk:
                return self.workspace
            return None
        if name == "User":
            return self.users.get(pk)
        return None

    def execute(self, stmt):
        s = str(stmt).lower()
        # DELETE rowcount
        if "delete" in s and "workspace_member_permissions" in s:
            class _Result:
                rowcount = self.delete_rowcount
            return _Result()
        # SELECT rows by workspace_id
        if "workspace_id" in s:
            return _FakeSelectResult(self.perm_rows)
        return _FakeSelectResult([])

    def bulk_save_objects(self, rows):
        if self.integrity_error_on == "bulk_save":
            from sqlalchemy.exc import IntegrityError
            raise IntegrityError("mock", {}, None)
        for r in rows:
            self.perm_rows.append(r)

    def add(self, obj):
        self.added.append(obj)

    def flush(self):
        pass

    def refresh(self, obj):
        pass

    def commit(self):
        if self.integrity_error_on == "commit":
            from sqlalchemy.exc import IntegrityError
            raise IntegrityError("mock", {}, None)
        self.commits += 1

    def rollback(self):
        pass


# --- _validate_permissions ----------------------------------------------


def test_validate_permissions_unknown_raises_400():
    with pytest.raises(HTTPException) as exc:
        WorkspaceMemberService._validate_permissions(["kb.read", "kb.foobar"])
    assert exc.value.status_code == 400
    assert "kb.foobar" in str(exc.value.detail)


def test_validate_permissions_dedupes_and_sorts():
    out = WorkspaceMemberService._validate_permissions(
        ["document.update", "kb.read", "document.update"]
    )
    # 去重后排序
    assert out == ["document.update", "kb.read"]


def test_validate_permissions_empty_returns_empty():
    assert WorkspaceMemberService._validate_permissions([]) == []


# --- _validate_workspace ------------------------------------------------


def test_validate_workspace_cross_tenant_404_for_non_admin():
    """spec §6.5:跨租户访问对非 admin 一律 404(防枚举)。"""
    ws = _FakeWorkspace(id=1, tenant_id=1, owner_id=99)
    db = _FakeSession(workspace=ws)
    with pytest.raises(HTTPException) as exc:
        WorkspaceMemberService._validate_workspace(
            db, workspace_id=1, tenant_id=2, is_superuser=False,
        )
    assert exc.value.status_code == 404


def test_validate_workspace_admin_can_see_cross_tenant():
    """admin 跨租户可见。"""
    ws = _FakeWorkspace(id=1, tenant_id=1, owner_id=99)
    db = _FakeSession(workspace=ws)
    out = WorkspaceMemberService._validate_workspace(
        db, workspace_id=1, tenant_id=2, is_superuser=True,
    )
    assert out is ws


def test_validate_workspace_missing_404():
    db = _FakeSession(workspace=None)
    with pytest.raises(HTTPException) as exc:
        WorkspaceMemberService._validate_workspace(
            db, workspace_id=1, tenant_id=1, is_superuser=False,
        )
    assert exc.value.status_code == 404


# --- invite_member ------------------------------------------------------


def test_invite_member_basic():
    ws = _FakeWorkspace(id=10, tenant_id=1, owner_id=1)
    target = _FakeUser(id=42, tenant_id=1)
    actor = _FakeUser(id=1, tenant_id=1)
    db = _FakeSession(workspace=ws, users={42: target})
    svc = WorkspaceMemberService()
    out = svc.invite_member(db, 10, 42, ["kb.read"], actor)
    assert out.user_id == 42
    assert out.permissions == ["kb.read"]
    assert db.commits == 1
    # row 应写入
    assert any(r.user_id == 42 and r.permission == "kb.read" for r in db.perm_rows)


def test_invite_member_cross_tenant_403():
    ws = _FakeWorkspace(id=10, tenant_id=1, owner_id=1)
    target = _FakeUser(id=42, tenant_id=2)  # different tenant
    actor = _FakeUser(id=1, tenant_id=1)
    db = _FakeSession(workspace=ws, users={42: target})
    svc = WorkspaceMemberService()
    with pytest.raises(HTTPException) as exc:
        svc.invite_member(db, 10, 42, ["kb.read"], actor)
    assert exc.value.status_code == 403
    assert "跨租户" in str(exc.value.detail)


def test_invite_member_target_not_found_404():
    ws = _FakeWorkspace(id=10, tenant_id=1, owner_id=1)
    actor = _FakeUser(id=1, tenant_id=1)
    db = _FakeSession(workspace=ws, users={})  # no target user
    svc = WorkspaceMemberService()
    with pytest.raises(HTTPException) as exc:
        svc.invite_member(db, 10, 42, ["kb.read"], actor)
    assert exc.value.status_code == 404


def test_invite_member_target_is_owner_400():
    ws = _FakeWorkspace(id=10, tenant_id=1, owner_id=42)  # owner_id = 42
    target = _FakeUser(id=42, tenant_id=1)
    actor = _FakeUser(id=1, tenant_id=1)
    db = _FakeSession(workspace=ws, users={42: target})
    svc = WorkspaceMemberService()
    with pytest.raises(HTTPException) as exc:
        svc.invite_member(db, 10, 42, ["kb.read"], actor)
    assert exc.value.status_code == 400
    assert "owner" in str(exc.value.detail).lower()


def test_invite_member_unknown_permission_400():
    ws = _FakeWorkspace(id=10, tenant_id=1, owner_id=1)
    target = _FakeUser(id=42, tenant_id=1)
    actor = _FakeUser(id=1, tenant_id=1)
    db = _FakeSession(workspace=ws, users={42: target})
    svc = WorkspaceMemberService()
    with pytest.raises(HTTPException) as exc:
        svc.invite_member(db, 10, 42, ["kb.read", "nope.invalid"], actor)
    assert exc.value.status_code == 400


def test_invite_member_empty_perms_400():
    ws = _FakeWorkspace(id=10, tenant_id=1, owner_id=1)
    target = _FakeUser(id=42, tenant_id=1)
    actor = _FakeUser(id=1, tenant_id=1)
    db = _FakeSession(workspace=ws, users={42: target})
    svc = WorkspaceMemberService()
    with pytest.raises(HTTPException) as exc:
        svc.invite_member(db, 10, 42, [], actor)
    assert exc.value.status_code == 400


def test_invite_member_unique_conflict_409():
    """spec §11:并发插入同一 (ws, user, perm) → IntegrityError → 409。"""
    ws = _FakeWorkspace(id=10, tenant_id=1, owner_id=1)
    target = _FakeUser(id=42, tenant_id=1)
    actor = _FakeUser(id=1, tenant_id=1)
    db = _FakeSession(
        workspace=ws, users={42: target},
        integrity_error_on="bulk_save",
    )
    svc = WorkspaceMemberService()
    with pytest.raises(HTTPException) as exc:
        svc.invite_member(db, 10, 42, ["kb.read"], actor)
    assert exc.value.status_code == 409


# --- update_member ------------------------------------------------------


def test_update_member_replace_perms():
    """整组覆盖:DELETE 全部 + INSERT 新。"""
    ws = _FakeWorkspace(id=10, tenant_id=1, owner_id=1)
    target = _FakeUser(id=42, tenant_id=1)
    actor = _FakeUser(id=1, tenant_id=1)
    db = _FakeSession(workspace=ws, users={42: target})
    svc = WorkspaceMemberService()
    out = svc.update_member(db, 10, 42, ["kb.read", "kb.update"], actor)
    assert sorted(out.permissions) == ["kb.read", "kb.update"]


def test_update_member_clear_all():
    """空 permissions 列表 = 清空所有 grant rows。"""
    ws = _FakeWorkspace(id=10, tenant_id=1, owner_id=1)
    target = _FakeUser(id=42, tenant_id=1)
    actor = _FakeUser(id=1, tenant_id=1)
    db = _FakeSession(workspace=ws, users={42: target})
    svc = WorkspaceMemberService()
    out = svc.update_member(db, 10, 42, [], actor)
    assert out.permissions == []
    # 不应 INSERT 任何 row
    assert not db.perm_rows


# --- remove_member ------------------------------------------------------


def test_remove_member_basic():
    ws = _FakeWorkspace(id=10, tenant_id=1, owner_id=1)
    target = _FakeUser(id=42, tenant_id=1)
    actor = _FakeUser(id=1, tenant_id=1)
    db = _FakeSession(workspace=ws, users={42: target})
    svc = WorkspaceMemberService()
    count = svc.remove_member(db, 10, 42, actor)
    assert count == 1


def test_remove_member_owner_400():
    ws = _FakeWorkspace(id=10, tenant_id=1, owner_id=42)  # 42 is owner
    target = _FakeUser(id=42, tenant_id=1)
    actor = _FakeUser(id=1, tenant_id=1)
    db = _FakeSession(workspace=ws, users={42: target})
    svc = WorkspaceMemberService()
    with pytest.raises(HTTPException) as exc:
        svc.remove_member(db, 10, 42, actor)
    assert exc.value.status_code == 400


def test_remove_member_cross_tenant_404():
    """actor 在不同 tenant → workspace not found(隐藏实体存在性)。"""
    ws = _FakeWorkspace(id=10, tenant_id=1, owner_id=1)
    actor = _FakeUser(id=99, tenant_id=2)
    db = _FakeSession(workspace=ws)
    svc = WorkspaceMemberService()
    with pytest.raises(HTTPException) as exc:
        svc.remove_member(db, 10, 42, actor)
    assert exc.value.status_code == 404


# --- transfer_ownership -------------------------------------------------


def test_transfer_ownership_writes_audit_inline():
    """spec §10:AuditLog 必须同事务 commit,验证 inline add + commit。"""
    ws = _FakeWorkspace(id=10, tenant_id=1, owner_id=1)
    new_owner = _FakeUser(id=2, tenant_id=1)
    actor = _FakeUser(id=1, tenant_id=1)
    db = _FakeSession(workspace=ws, users={2: new_owner})

    # mock workspace_service.get_workspace → 返 ws
    from lumen_services import workspace_service as ws_mod
    original = ws_mod.workspace_service.get_workspace
    ws_mod.workspace_service.get_workspace = lambda *a, **kw: ws
    try:
        svc = WorkspaceMemberService()
        result = svc.transfer_ownership(db, 10, 2, actor)
        assert result.owner_id == 2
        # 验证 AuditLog inline add
        assert len(db.added) == 1
        audit = db.added[0]
        assert audit.action == "workspace.transfer_ownership"
        assert audit.details["from_owner_id"] == 1
        assert audit.details["to_owner_id"] == 2
    finally:
        ws_mod.workspace_service.get_workspace = original


def test_transfer_ownership_cross_tenant_403():
    ws = _FakeWorkspace(id=10, tenant_id=1, owner_id=1)
    new_owner = _FakeUser(id=2, tenant_id=2)  # different tenant
    actor = _FakeUser(id=1, tenant_id=1)
    db = _FakeSession(workspace=ws, users={2: new_owner})
    svc = WorkspaceMemberService()
    with pytest.raises(HTTPException) as exc:
        svc.transfer_ownership(db, 10, 2, actor)
    assert exc.value.status_code == 403


def test_transfer_ownership_new_owner_not_found_404():
    ws = _FakeWorkspace(id=10, tenant_id=1, owner_id=1)
    actor = _FakeUser(id=1, tenant_id=1)
    db = _FakeSession(workspace=ws, users={})  # no new owner
    svc = WorkspaceMemberService()
    with pytest.raises(HTTPException) as exc:
        svc.transfer_ownership(db, 10, 2, actor)
    assert exc.value.status_code == 404


# --- list_members -------------------------------------------------------


def test_list_members_includes_owner_with_all_perms():
    ws = _FakeWorkspace(id=10, tenant_id=1, owner_id=42)
    actor = _FakeUser(id=42, tenant_id=1)
    db = _FakeSession(
        workspace=ws,
        perm_rows=[_FakePermissionRow(workspace_id=10, user_id=42, permission="kb.read")],
        users={42: actor},
    )
    svc = WorkspaceMemberService()
    items = svc.list_members(db, 10, actor)
    # owner 必有,且 permissions = 19 项
    owner_item = next(i for i in items if i.is_owner)
    assert owner_item.user_id == 42
    assert len(owner_item.permissions) == 19


def test_list_members_sorts_owner_first():
    ws = _FakeWorkspace(id=10, tenant_id=1, owner_id=42)
    actor = _FakeUser(id=42, tenant_id=1)
    other = _FakeUser(id=99, tenant_id=1)
    db = _FakeSession(
        workspace=ws,
        perm_rows=[
            _FakePermissionRow(workspace_id=10, user_id=99, permission="kb.read"),
        ],
        users={42: actor, 99: other},
    )
    svc = WorkspaceMemberService()
    items = svc.list_members(db, 10, actor)
    assert items[0].is_owner
    assert items[0].user_id == 42


def test_list_members_empty_returns_only_owner():
    """无 grant row → 只返 owner 一行。"""
    ws = _FakeWorkspace(id=10, tenant_id=1, owner_id=42)
    actor = _FakeUser(id=42, tenant_id=1)
    db = _FakeSession(workspace=ws, users={42: actor})
    svc = WorkspaceMemberService()
    items = svc.list_members(db, 10, actor)
    assert len(items) == 1
    assert items[0].user_id == 42
    assert items[0].is_owner