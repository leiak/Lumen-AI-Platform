"""M38.2: workspace tenant-isolation contract.

Verifies spec §1.3: workspace list/get/update/create must all
respect tenant boundaries. Non-admin callers can NEVER see or
modify a workspace in another tenant — admin can opt in via
``?tenant_id=`` for the list endpoint, but never see another
tenant's workspace by id without explicit admin path.

Cross-tenant reads return 404 (not 403) to avoid leaking the
existence of rows the caller doesn't own.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List as _List

import pytest
from fastapi.testclient import TestClient

from lumen_api.v1 import auth as auth_module
from lumen_core.database import get_db
from lumen_main import app


# --- fakes --------------------------------------------------------------


class _FakeUser:
    def __init__(
        self, *, tenant_id: int, is_superuser: bool = False, uid: int = 1
    ) -> None:
        self.id = uid
        self.tenant_id = tenant_id
        self.is_superuser = is_superuser
        self.is_active = True
        self.username = f"u{uid}"


class _FakeWorkspace:
    def __init__(
        self,
        *,
        id: int,
        tenant_id: int,
        name: str,
        owner_id: int = 0,
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


class _FakeQuery:
    def __init__(self, rows: _List, scalar: int = 0):
        self._rows = rows
        self._filters: Dict[str, Any] = {}
        self._scalar = scalar

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
        return len([
            r for r in self._rows
            if all(getattr(r, k, None) == v for k, v in self._filters.items())
        ])

    def order_by(self, *args):
        return self

    def offset(self, n: int):
        return self

    def limit(self, n: int):
        return self

    def group_by(self, *args):
        return _FakeQuery([], scalar=0)

    def scalar(self) -> int:
        return self._scalar


class _FakeSession:
    def __init__(self, state: Dict[str, Any]):
        self.state = state

    def query(self, *models):
        model = models[0]
        name = getattr(model, "__name__", None)
        if name == "Workspace":
            return _FakeQuery(self.state["workspaces"])
        # 多 model / 聚合查询返回空集
        return _FakeQuery([], scalar=0)

    def get(self, model, pk):
        if getattr(model, "__name__", None) == "Workspace":
            for ws in self.state["workspaces"]:
                if ws.id == pk:
                    return ws
        return None

    def add(self, obj):
        obj.id = self.state["next_ws_id"]
        self.state["next_ws_id"] += 1
        self.state["workspaces"].append(obj)

    def commit(self):
        pass

    def rollback(self):
        pass

    def refresh(self, obj):
        from datetime import datetime, timezone
        if getattr(obj, "created_at", None) is None:
            obj.created_at = datetime.now(timezone.utc)
        if getattr(obj, "updated_at", None) is None:
            obj.updated_at = obj.created_at


# --- fixtures -----------------------------------------------------------


@pytest.fixture
def state() -> Dict[str, Any]:
    return {
        "workspaces": [
            _FakeWorkspace(id=1, tenant_id=1, name="T1-A"),
            _FakeWorkspace(id=2, tenant_id=1, name="T1-B", owner_id=11),
            _FakeWorkspace(id=3, tenant_id=2, name="T2-A"),
        ],
        "next_ws_id": 100,
    }


@pytest.fixture
def client(state):
    """Default: non-admin tenant-1 caller."""
    app.router.lifespan_context = None  # type: ignore[attr-defined]

    def _override_db():
        yield _FakeSession(state)

    caller = _FakeUser(tenant_id=1, is_superuser=False, uid=11)

    def _override_current_user():
        return caller

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[auth_module.get_current_user] = _override_current_user

    yield TestClient(app)
    app.dependency_overrides.clear()


# --- list ---------------------------------------------------------------


def test_list_workspaces_filters_to_caller_tenant(client, state):
    """GET /workspaces — 默认只看自己租户的 workspace。"""
    resp = client.get("/api/v1/workspaces")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    items = body["data"]
    assert {ws["id"] for ws in items} == {1, 2}  # 没漏出 tenant 2 的 id=3


def test_list_workspaces_admin_can_query_other_tenant(client, monkeypatch, state):
    """admin 调 ?tenant_id=2 → 能看到 tenant 2 的 workspace。"""
    # 把 caller 换成 admin tenant 1
    admin = _FakeUser(tenant_id=1, is_superuser=True, uid=1)

    def _override_current_user():
        return admin

    monkeypatch.setitem(
        app.dependency_overrides, auth_module.get_current_user, _override_current_user
    )

    resp = client.get("/api/v1/workspaces", params={"tenant_id": 2})
    assert resp.status_code == 200
    items = resp.json()["data"]
    assert {ws["id"] for ws in items} == {3}


def test_list_workspaces_non_admin_tenant_id_query_is_ignored(client):
    """非 admin 即便传 ?tenant_id=2 也只看自己租户。"""
    resp = client.get("/api/v1/workspaces", params={"tenant_id": 2})
    assert resp.status_code == 200
    items = resp.json()["data"]
    assert {ws["id"] for ws in items} == {1, 2}


# --- single get / update / delete ---------------------------------------


def test_get_workspace_other_tenant_returns_404(client):
    """GET 别人租户的 workspace → 404,不 leak 存在性。"""
    resp = client.get("/api/v1/workspaces/3")  # tenant 2 的 ws
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Workspace not found"


def test_update_workspace_other_tenant_returns_404(client):
    """PUT 别人租户的 workspace → 404。"""
    resp = client.put(
        "/api/v1/workspaces/3",
        json={"name": "hacked"},
    )
    assert resp.status_code == 404


def test_delete_workspace_other_tenant_returns_404(client):
    """DELETE 别人租户的 workspace → 404,KB 不被误删。"""
    resp = client.delete("/api/v1/workspaces/3")
    assert resp.status_code == 404


def test_update_workspace_non_owner_non_admin_returns_403(client, state):
    """非 owner 非 admin 改别人 workspace → 403。
    workspace id=2 的 owner_id=11,但 caller uid=999 → 拒。
    """
    # 换 caller 成同租户但非 owner
    other = _FakeUser(tenant_id=1, is_superuser=False, uid=999)

    def _override_current_user():
        return other

    app.dependency_overrides[auth_module.get_current_user] = _override_current_user
    try:
        resp = client.put(
            "/api/v1/workspaces/2",
            json={"name": "by-non-owner"},
        )
        assert resp.status_code == 403
        assert "owner" in resp.json()["detail"] or "创建人" in resp.json()["detail"]
    finally:
        # restore
        caller = _FakeUser(tenant_id=1, is_superuser=False, uid=11)

        def _override_current_user_default():
            return caller

        app.dependency_overrides[auth_module.get_current_user] = _override_current_user_default


# --- create -------------------------------------------------------------


def test_create_workspace_lands_in_caller_tenant(client, state):
    """POST /workspaces — 新建一定挂在调用者的租户,不能指定别人的。"""
    resp = client.post("/api/v1/workspaces", json={"name": "T1-new"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["data"]["tenant_id"] == 1  # caller 的租户
    assert body["data"]["name"] == "T1-new"