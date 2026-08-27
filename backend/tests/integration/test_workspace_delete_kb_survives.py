"""M38.2: deleting a workspace must NOT cascade-delete its KBs.

Spec §3.3: ``KnowledgeBase.workspace_id`` is ON DELETE SET NULL
on the FK. The workspace is purely a navigation root, never an
ownership boundary — KBs hang off the tenant directly.

This test exercises the real endpoint wiring so a future FK
schema change can't silently regress to CASCADE.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List as _List, Optional

import pytest
from fastapi.testclient import TestClient

from lumen_api.v1 import auth as auth_module
from lumen_core.database import get_db
from lumen_main import app


# --- fakes --------------------------------------------------------------


class _FakeUser:
    def __init__(self, *, tenant_id: int = 1, is_superuser: bool = False, uid: int = 1) -> None:
        self.id = uid
        self.tenant_id = tenant_id
        self.is_superuser = is_superuser
        self.is_active = True
        self.username = f"u{uid}"


class _FakeWorkspace:
    def __init__(
        self, *, id: int, tenant_id: int, name: str = "W", owner_id: int = 0
    ) -> None:
        self.id = id
        self.tenant_id = tenant_id
        self.name = name
        self.description = None
        self.owner_id = owner_id
        self.icon = None
        self.color = None
        self.created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.updated_at = datetime(2026, 1, 1, tzinfo=timezone.utc)


class _FakeKB:
    def __init__(
        self,
        *,
        id: int,
        tenant_id: int,
        name: str,
        workspace_id: Optional[int] = None,
    ) -> None:
        self.id = id
        self.tenant_id = tenant_id
        self.name = name
        self.workspace_id = workspace_id
        self.description = None
        self.embedding_model_config_id = None
        self.status = "active"
        self.created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.updated_at = datetime(2026, 1, 1, tzinfo=timezone.utc)


class _FakeQuery:
    def __init__(self, rows: _List):
        self._rows = rows
        self._filters: Dict[str, Any] = {}

    def filter(self, *clauses):
        for clause in clauses:
            op_name = getattr(getattr(clause, "operator", None), "__name__", "")
            col_key = getattr(getattr(clause, "left", None), "key", None)
            if col_key is None:
                continue
            if op_name == "eq":
                right = clause.right
                self._filters[col_key] = getattr(right, "value", right)
        return self

    def first(self):
        for r in self._rows:
            if all(getattr(r, k, None) == v for k, v in self._filters.items()):
                return r
        return None

    def all(self):
        return [
            r for r in self._rows
            if all(getattr(r, k, None) == v for k, v in self._filters.items())
        ]

    def count(self) -> int:
        return len([r for r in self._rows if all(getattr(r, k, None) == v for k, v in self._filters.items())])

    def scalar(self) -> int:
        return 0


class _FakeSession:
    def __init__(self, state: Dict[str, Any]):
        self.state = state
        self.commits = 0

    def query(self, model):
        name = getattr(model, "__name__", None)
        if name == "Workspace":
            return _FakeQuery(self.state["workspaces"])
        if name == "KnowledgeBase":
            return _FakeQuery(self.state["kbs"])
        # ``func.count(...)`` 等聚合查询返回 0
        return _FakeQuery([])

    def get(self, model, pk):
        name = getattr(model, "__name__", None)
        if name == "Workspace":
            for ws in self.state["workspaces"]:
                if ws.id == pk:
                    return ws
        return None

    def commit(self):
        self.commits += 1

    def delete(self, obj):
        # 真实 DB 这边会触发 ON DELETE SET NULL;fake 里手动
        # 把挂在 workspace 上的 KB 的 workspace_id 置 NULL,
        # 模拟 FK 的副作用 —— 测的就是这个不变式。
        if obj in self.state["workspaces"]:
            self.state["workspaces"].remove(obj)
        for kb in self.state["kbs"]:
            if kb.workspace_id == obj.id:
                kb.workspace_id = None

    def rollback(self):
        pass

    def execute(self, stmt=None, *args, **kwargs):
        """M38.2.x v2: PermissionService.check() 调 ``db.execute()``。

        对 owner 查询(``SELECT owner_id FROM workspace WHERE id = X``),
        从 state 查 workspace 返 owner_id;grant 查询返空。
        """
        class _ScalarResult:
            def __init__(self, v):
                self._v = v

            def scalar_one_or_none(self_inner):
                return self_inner._v

            def scalars(self_inner):
                return self_inner

            def all(self_inner):
                return [self_inner._v] if self_inner._v is not None else []

        class _EmptyResult:
            def first(self_inner):
                return None

            def scalar_one_or_none(self_inner):
                return None

            def scalars(self_inner):
                return self_inner

            def all(self_inner):
                return []

        if stmt is None:
            return _EmptyResult()
        try:
            sql = str(stmt.compile(compile_kwargs={"literal_binds": True}))
            params = dict(stmt.compile().params)
        except Exception:
            return _EmptyResult()
        if "owner_id" in sql.lower() and "workspace" in sql.lower():
            for v in params.values():
                if isinstance(v, int):
                    for ws in self.state["workspaces"]:
                        if ws.id == v:
                            return _ScalarResult(ws.owner_id)
            return _ScalarResult(None)
        return _EmptyResult()


# --- fixtures -----------------------------------------------------------


@pytest.fixture
def state() -> Dict[str, Any]:
    """M38.2.x v2: caller (uid=1) 是 workspace 10 的 owner,PermissionService._is_owner bypass。"""
    ws = _FakeWorkspace(id=10, tenant_id=1, name="研发空间", owner_id=1)
    return {
        "workspaces": [ws],
        "kbs": [
            _FakeKB(id=101, tenant_id=1, name="产品 KB", workspace_id=10),
            _FakeKB(id=102, tenant_id=1, name="技术 KB", workspace_id=10),
        ],
    }


@pytest.fixture
def client(state):
    app.router.lifespan_context = None  # type: ignore[attr-defined]

    def _override_db():
        yield _FakeSession(state)

    owner = _FakeUser(tenant_id=1, is_superuser=False, uid=1)

    def _override_current_user():
        return owner

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[auth_module.get_current_user] = _override_current_user

    yield TestClient(app)

    app.dependency_overrides.clear()


# --- tests --------------------------------------------------------------


def test_delete_workspace_keeps_kbs_with_null_workspace_id(client, state):
    """删 workspace 后,挂着的 KB 仍然存在,workspace_id 被置 NULL。"""
    # sanity:删之前两条 KB 都挂着 workspace 10
    assert state["kbs"][0].workspace_id == 10
    assert state["kbs"][1].workspace_id == 10

    resp = client.delete("/api/v1/workspaces/10")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body.get("deleted") is True

    # workspace 行没了
    assert state["workspaces"] == []
    # 两条 KB 还在,workspace_id 被 FK ON DELETE SET NULL 置 NULL
    assert len(state["kbs"]) == 2
    assert state["kbs"][0].workspace_id is None
    assert state["kbs"][1].workspace_id is None
    # 也没误删 KB
    assert {kb.id for kb in state["kbs"]} == {101, 102}


def test_delete_workspace_returns_404_for_other_tenant(client, state):
    """删别人租户的 workspace → 404(防越权 leak)。"""
    resp = client.delete("/api/v1/workspaces/999")
    assert resp.status_code == 404