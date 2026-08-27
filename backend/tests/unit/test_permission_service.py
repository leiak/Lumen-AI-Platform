"""M38.2.x v2: unit tests for ``PermissionService``.

Pure unit tests with a fake Session; covers spec §6:
- superuser 全 perm (1)
- 已知 perm 白名单 (2)
- workspace_id IS NULL 老数据默认 read-class 开放 (3)
- owner 自动全 perm (4)
- 直接 grant 行命中 (5)
- implication 反查 (6)

不需要真 MySQL / 真 FastAPI。
"""
from __future__ import annotations

from typing import Any, Dict, List

import pytest

from lumen_services.permission_service import (
    ALL_PERMISSIONS,
    PermissionService,
    READ_ONLY_PERMISSIONS,
    WRITE_PERMISSIONS,
    _ALL_PERMS,
    _PERM_IMPLIES,
    _READ_ONLY_PERMS,
    _WRITE_PERMS,
    effective_perms,
)


class _FakeRow:
    """模拟一行 grant。"""

    def __init__(self, workspace_id: int, user_id: int, permission: str):
        self.workspace_id = workspace_id
        self.user_id = user_id
        self.permission = permission


class _FakeScalarResult:
    def __init__(self, value: Any):
        self._v = value

    def scalar_one_or_none(self):
        return self._v

    def scalars(self):
        return self

    def all(self):
        return [self._v] if self._v is not None else []


class _FakeQuery:
    def __init__(self, rows: List[_FakeRow]):
        self._rows = list(rows)

    def filter(self, *args, **kwargs):
        # M38.2.x v2: 测试只关心「给定 (user_id, workspace_id, permission) 是否命中」,
        # 这里直接按"任意一行匹配"返回。
        return _FakeResult(self._rows)

    def where(self, *args):
        return _FakeResult(self._rows)

    def limit(self, n):
        return self

    def all(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None


class _FakeResult:
    def __init__(self, rows: List[_FakeRow]):
        self._rows = rows

    def first(self):
        # 仅返回"任意一行存在性"信号 — 真实 service 走 .first() 看是否 truthy
        return self._rows[0] if self._rows else None

    def scalars(self):
        return self

    def all(self):
        return self._rows


class _FakeSession:
    """最小 Session fake,服务 ``PermissionService.check`` 调的所有 SQL。

    通过 ``grant_rows`` / ``owner_id`` / ``is_superuser_user`` 控制 mock 行为。
    """

    def __init__(self, *, grant_rows=None, owner_id=None, is_superuser_user=False):
        self.grant_rows = grant_rows or []
        self.owner_id = owner_id
        self.is_superuser_user = is_superuser_user
        self.executed: List[Any] = []

    def execute(self, *args, **kwargs):
        self.executed.append((args, kwargs))
        # 第一个 SELECT 通常是 Workspace owner 查询;第二个是 member perm
        # lookup。我们看返回的 SELECT 内容是不是 owner 查询 → 返 owner_id。
        # 简化策略:只让 check() 内部需要的两次查询走 _resolve_select_response
        return _FakeScalarResult(self.owner_id)

    def _resolve_response(self, stmt):
        # 走 Workspace.owner_id SELECT — 简单的 hint 检测
        s = str(stmt).lower()
        if "workspace" in s and "owner_id" in s:
            return _FakeScalarResult(self.owner_id)
        # 走 WorkspaceMemberPermission 查询 — 检查 user_id + workspace_id + permission
        return _FakeResult(self.grant_rows)

    # overwrite execute to use _resolve_response
    def __getattr__(self, name):
        # catch-all: 真正 execute 走的还是 execute() 方法
        raise AttributeError(name)


class _FakeUser:
    def __init__(self, id: int = 1, is_superuser: bool = False, tenant_id: int = 1):
        self.id = id
        self.is_superuser = is_superuser
        self.tenant_id = tenant_id


# --- 1. permission token 白名单 -------------------------------------------


def test_all_perms_count_is_19():
    """Spec §6.1 规定 19 个 permission token。"""
    assert len(_ALL_PERMS) == 19


def test_read_only_subset():
    assert _READ_ONLY_PERMS == {"workspace.read", "kb.read", "folder.read", "document.read"}


def test_write_subset_includes_read():
    """Spec: write = read + create/update/move。delete / manage 不在内。"""
    assert _READ_ONLY_PERMS.issubset(_WRITE_PERMS)
    assert "workspace.delete" not in _WRITE_PERMS
    assert "kb.delete" not in _WRITE_PERMS
    assert "folder.delete" not in _WRITE_PERMS
    assert "document.delete" not in _WRITE_PERMS


def test_all_implied_targets_are_known_perms():
    """Implication 反查目标必须是已知 perm token(否则 typo 不会拦截)。"""
    for source, targets in _PERM_IMPLIES.items():
        assert source in _ALL_PERMS, f"unknown source: {source}"
        for t in targets:
            assert t in _ALL_PERMS, f"unknown implied target: {t}"


# --- 2. effective_perms: implication chain --------------------------------


def test_effective_perms_simple():
    """kb.update → kb.read + document.read。"""
    eff = effective_perms({"kb.update"})
    assert "kb.update" in eff
    assert "kb.read" in eff
    assert "document.read" in eff


def test_effective_perms_transitive():
    """workspace.update → workspace.read,再多一层就是 (workspace.read 不 imply 别的)。"""
    eff = effective_perms({"workspace.update"})
    assert eff == {"workspace.update", "workspace.read"}


def test_effective_perms_document_move():
    """document.move → folder.read + folder.update。"""
    eff = effective_perms({"document.move"})
    assert "document.move" in eff
    assert "folder.read" in eff
    assert "folder.update" in eff


def test_effective_perms_chained():
    """kb.delete → kb.read → document.read (两跳 transitive)。"""
    eff = effective_perms({"kb.delete"})
    assert "kb.delete" in eff
    assert "kb.read" in eff
    assert "document.read" in eff


# --- 3. PermissionService.check 主逻辑 ------------------------------------


def test_check_user_none_returns_true():
    """``user is None`` 走 graceful open(spec §6.4)。"""
    # 即便 session 是 None 也要能调 — service 先 short-circuit user is None
    svc = PermissionService()
    assert svc.check(db=None, user=None, permission="kb.read", workspace_id=1) is True


def test_check_superuser_returns_true():
    """superuser 全 perm,不看 workspace_id。"""
    svc = PermissionService()
    u = _FakeUser(is_superuser=True)
    assert svc.check(db=None, user=u, permission="kb.delete", workspace_id=1) is True
    assert svc.check(db=None, user=u, permission="workspace.transfer_ownership", workspace_id=None) is True


def test_check_unknown_permission_returns_false():
    """typo perm 不在白名单 → False(防 typo 静默放行)。"""
    svc = PermissionService()
    u = _FakeUser(is_superuser=False)
    assert svc.check(db=None, user=u, permission="kb.foobar", workspace_id=1) is False


def test_check_workspace_id_none_read_class_open():
    """spec §6.4:workspace_id IS NULL KB 的 read-class perm 对全员 in-tenant 开放。"""
    svc = PermissionService()
    u = _FakeUser(is_superuser=False)
    for perm in ("workspace.read", "kb.read", "folder.read", "document.read"):
        assert svc.check(db=None, user=u, permission=perm, workspace_id=None) is True, perm
    # 写操作仍要 superuser
    for perm in ("kb.update", "kb.delete", "kb.create", "folder.create", "folder.delete",
                 "document.create", "document.update", "document.delete", "document.move"):
        assert svc.check(db=None, user=u, permission=perm, workspace_id=None) is False, perm


def test_check_workspace_id_none_write_requires_superuser():
    """workspace_id None + 写操作 + 非 superuser → False。"""
    svc = PermissionService()
    u = _FakeUser(is_superuser=False)
    assert svc.check(db=None, user=u, permission="kb.update", workspace_id=None) is False


# --- 4. owner / direct grant / implication 反查 需要真 session ----------

# 下面的测试用 _FakeSessionWithSelects 替代 PermissionService 调的两次 SQL:
# 1) ``Workspace.owner_id`` 查询(判 owner)
# 2) ``WorkspaceMemberPermission`` 行查询(判 direct grant)
# 3) implication 反查:对 _PERM_IMPLIES 每条 entry 重跑 (2)


class _FakeSelectResult:
    """模拟 SQLAlchemy ``Engine.execute(...).first()`` / ``.all()`` / ``.scalar_one_or_none()``。"""

    def __init__(self, rows):
        self._rows = list(rows)

    def first(self):
        return self._rows[0] if self._rows else None

    def scalar_one_or_none(self):
        """PermissionService._is_owner 用 ``scalar_one_or_none()`` 拉 owner_id。"""
        return self._rows[0] if self._rows else None

    def scalars(self):
        return self

    def all(self):
        return self._rows

    def limit(self, n):
        return self


class _OwnerAwareSession:
    """模拟 PermissionService.check 调的所有 SQL。

    SQL 走 bound parameter (``'kb.read'`` 在字符串里被替换成 ``:permission_1``),
    不能用字符串 hint 推断。我们拦截 ``execute``:
    - ``Workspace.id`` SELECT + ``owner_id ==`` filter → 返 owner 拥有的 ws ids
    - ``Workspace.owner_id`` SELECT(只取 scalar) → 返 owner_id
    - ``WorkspaceMemberPermission`` SELECT + ``permission ==`` → 返命中行
    """

    def __init__(self, *, owner_id=None, grants=None, ws_ids=None):
        # grants: list of (workspace_id, user_id, permission)
        self.owner_id = owner_id
        self.grants = grants or []
        # ws_ids: 传给 load_user_workspace_permissions 的 workspace_ids 列表
        self.ws_ids = ws_ids or []
        self._call_count = 0

    def execute(self, stmt):
        self._call_count += 1
        s = str(stmt).lower()
        # 模式 A:``Workspace.id`` SELECT + ``owner_id ==`` filter → load_user_workspace_permissions
        # 找 owner 拥有的 ws ids。SQL 渲染是 ``workspaces.id``,没有 limit 子句
        if "owner_id" in s and "limit :" not in s and "permission" not in s:
            # owner_id 命中 → 所有 ws_ids 都是 owner 的
            if self.owner_id is not None:
                return _FakeSelectResult(self.ws_ids)
            return _FakeSelectResult([])
        # 模式 B:``Workspace.owner_id`` scalar SELECT + limit → _is_owner
        if "owner_id" in s and "limit :" in s:
            return _FakeSelectResult([self.owner_id] if self.owner_id is not None else [])
        # 模式 C:WorkspaceMemberPermission grant 查询
        target_permission = self._extract_permission(stmt)
        if target_permission is None:
            return _FakeSelectResult([])
        for ws_id, user_id, perm in self.grants:
            if perm == target_permission:
                return _FakeSelectResult([1])
        # implication 反查
        from lumen_services.permission_service import _PERM_IMPLIES
        for source, implied in _PERM_IMPLIES.items():
            if target_permission in implied:
                for ws_id, user_id, perm in self.grants:
                    if perm == source:
                        return _FakeSelectResult([1])
        return _FakeSelectResult([])

    @staticmethod
    def _extract_permission(stmt):
        """从 ``select(1).where(... permission == X ...).limit(1)`` 提取 X。"""
        try:
            params = stmt.compile().params
        except Exception:
            return None
        for k, v in params.items():
            if k.startswith("permission_"):
                return v
        return None


def test_check_owner_bypass():
    """owner auto 全 perm,无须 grant 行。"""
    svc = PermissionService()
    u = _FakeUser(id=42, is_superuser=False)
    db = _OwnerAwareSession(owner_id=42, grants=[])
    # 即便没 grant 行,owner 仍 True
    assert svc.check(db, u, "kb.delete", workspace_id=10) is True


def test_check_direct_grant_hit():
    """直接 grant 行命中 → True,不管 implication。"""
    svc = PermissionService()
    u = _FakeUser(id=42, is_superuser=False)
    db = _OwnerAwareSession(owner_id=999, grants=[(10, 42, "kb.read")])
    assert svc.check(db, u, "kb.read", workspace_id=10) is True


def test_check_implication_reverse_lookup():
    """user 有 ``kb.update``  → 自动有 ``kb.read`` (implication)。"""
    svc = PermissionService()
    u = _FakeUser(id=42, is_superuser=False)
    db = _OwnerAwareSession(owner_id=999, grants=[(10, 42, "kb.update")])
    # 直接查 kb.read 不在 grants,但 kb.update → kb.read 的 implication 应命中
    assert svc.check(db, u, "kb.read", workspace_id=10) is True


def test_check_no_grant_no_owner_returns_false():
    """既非 owner 也无 grant → False。"""
    svc = PermissionService()
    u = _FakeUser(id=42, is_superuser=False)
    db = _OwnerAwareSession(owner_id=999, grants=[])
    assert svc.check(db, u, "kb.read", workspace_id=10) is False


# --- 5. load_user_workspace_permissions 批量 -----------------------------


def test_load_user_workspace_permissions_admin_returns_all():
    """admin 在所有 workspace 上拿全 perm。"""
    svc = PermissionService()
    u = _FakeUser(is_superuser=True)
    db = _OwnerAwareSession()
    out = svc.load_user_workspace_permissions(db, u, [1, 2, 3])
    assert set(out.keys()) == {1, 2, 3}
    for ws_id, perms in out.items():
        assert perms == set(_ALL_PERMS)


def test_load_user_workspace_permissions_user_none_returns_all():
    """``user is None`` 全开。"""
    svc = PermissionService()
    db = _OwnerAwareSession()
    out = svc.load_user_workspace_permissions(db, None, [1, 2])
    assert set(out.keys()) == {1, 2}
    for perms in out.values():
        assert perms == set(_ALL_PERMS)


def test_load_user_workspace_permissions_owner_returns_all():
    """owner 自动全 perm。"""
    svc = PermissionService()
    u = _FakeUser(id=99, is_superuser=False)
    db = _OwnerAwareSession(owner_id=99, grants=[], ws_ids=[5])
    out = svc.load_user_workspace_permissions(db, u, [5])
    assert 5 in out
    assert out[5] == set(_ALL_PERMS)


def test_load_user_workspace_permissions_empty():
    """空 workspace_ids → 空 dict。"""
    svc = PermissionService()
    u = _FakeUser(is_superuser=False)
    db = _OwnerAwareSession()
    assert svc.load_user_workspace_permissions(db, u, []) == {}


# --- 6. public API 导出常量 ----------------------------------------------


def test_public_constants_exported():
    """``ALL_PERMISSIONS`` / ``READ_ONLY_PERMISSIONS`` / ``WRITE_PERMISSIONS``
    是命名别名,跟内部 frozenset 相等(spec §6.1 锁定)。
    """
    assert ALL_PERMISSIONS == _ALL_PERMS
    assert READ_ONLY_PERMISSIONS == _READ_ONLY_PERMS
    assert WRITE_PERMISSIONS == _WRITE_PERMS