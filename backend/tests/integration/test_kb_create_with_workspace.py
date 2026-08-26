"""M38.2: KB create with ``workspace_id`` binding.

Verifies the spec §4 contract that a KB can optionally hang
off a workspace, and that the workspace must belong to the
caller's tenant (cross-tenant binding → 403).

Uses ``dependency_overrides`` + ``monkeypatch`` so the suite
runs without a live MySQL / Ollama / uvicorn — pattern lifted
from ``tests/integration/test_storage_api.py``.

Note: ``KnowledgeService.create_knowledge_base`` probes the
embedder up-front (calls Ollama) — we monkeypatch it to a
no-op so the API-level workspace-binding assertions can
exercise the real endpoint wiring.
"""
from __future__ import annotations

from typing import Any, Dict, List as _List, Optional

import pytest
from fastapi.testclient import TestClient

from lumen_api.v1 import auth as auth_module
from lumen_core.database import get_db
from lumen_main import app
from lumen_services import knowledge_service as ks_module


# --- fakes --------------------------------------------------------------


class _FakeUser:
    def __init__(self, *, tenant_id: int = 1, is_superuser: bool = False, uid: int = 1) -> None:
        self.id = uid
        self.tenant_id = tenant_id
        self.is_superuser = is_superuser
        self.is_active = True
        self.username = f"u{uid}"


class _FakeWorkspace:
    def __init__(self, *, id: int, tenant_id: int, name: str = "W") -> None:
        self.id = id
        self.tenant_id = tenant_id
        self.name = name
        self.description = None
        self.owner_id = None
        self.icon = None
        self.color = None


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
        self.embedding_model_config_id = None
        self.status = "active"
        self.description = None
        self.created_at = None
        self.updated_at = None


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


class _FakeSession:
    def __init__(self, state: Dict[str, Any]):
        self.state = state

    def query(self, model):
        name = getattr(model, "__name__", None)
        if name == "Workspace":
            return _FakeQuery(self.state["workspaces"])
        return _FakeQuery(self.state["kbs"])

    def get(self, model, pk):
        name = getattr(model, "__name__", None)
        if name == "Workspace":
            for ws in self.state["workspaces"]:
                if ws.id == pk:
                    return ws
        if name == "KnowledgeBase":
            for kb in self.state["kbs"]:
                if kb.id == pk:
                    return kb
        return None

    def add(self, obj):
        obj.id = self.state["next_kb_id"]
        self.state["next_kb_id"] += 1
        self.state["kbs"].append(obj)

    def commit(self):
        pass

    def refresh(self, obj):
        from datetime import datetime, timezone
        if getattr(obj, "created_at", None) is None:
            obj.created_at = datetime.now(timezone.utc)
        if getattr(obj, "updated_at", None) is None:
            obj.updated_at = obj.created_at


# --- fixtures -----------------------------------------------------------


@pytest.fixture
def kb_state() -> Dict[str, Any]:
    return {
        "workspaces": [
            _FakeWorkspace(id=1, tenant_id=1, name="T1"),
            _FakeWorkspace(id=2, tenant_id=2, name="T2"),
        ],
        "kbs": [],
        "next_kb_id": 100,
    }


@pytest.fixture
def client(monkeypatch, kb_state):
    """TestClient with FastAPI deps overridden — no MySQL needed."""
    app.router.lifespan_context = None  # type: ignore[attr-defined]

    def _override_db():
        yield _FakeSession(kb_state)

    tenant1_user = _FakeUser(tenant_id=1, is_superuser=False, uid=11)

    def _override_current_user():
        return tenant1_user

    # 跳过 embedder probe — 这条路径在真实 service 里会调 Ollama
    def _fake_create_kb(self, db, tenant_id, data):
        kb = _FakeKB(id=100, tenant_id=tenant_id, name=data.name)
        db.add(kb)
        db.commit()
        db.refresh(kb)
        return kb

    monkeypatch.setattr(ks_module.KnowledgeService, "create_knowledge_base", _fake_create_kb)

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[auth_module.get_current_user] = _override_current_user

    yield TestClient(app)

    app.dependency_overrides.clear()


# --- tests --------------------------------------------------------------


def test_create_kb_with_own_tenant_workspace_succeeds(client, kb_state):
    """Happy path: KB binds to workspace in caller's tenant → 200."""
    resp = client.post(
        "/api/v1/knowledge/",
        params={"workspace_id": 1},
        json={"name": "研发", "embedding_model_config_id": 1},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["code"] == 200
    # 真实写回 store,workspace_id 被设置到 KB 行
    assert len(kb_state["kbs"]) == 1
    assert kb_state["kbs"][0].workspace_id == 1


def test_create_kb_with_unknown_workspace_returns_400(client):
    """workspace_id 不存在 → 400,不静默写 NULL。"""
    resp = client.post(
        "/api/v1/knowledge/",
        params={"workspace_id": 999},
        json={"name": "orphan", "embedding_model_config_id": 1},
    )
    assert resp.status_code == 400
    assert "不存在" in resp.json()["detail"]


def test_create_kb_with_cross_tenant_workspace_returns_403(client):
    """workspace 属于别的租户 → 403,防越权挂载。"""
    resp = client.post(
        "/api/v1/knowledge/",
        params={"workspace_id": 2},  # tenant 2 的 workspace
        json={"name": "should-not-create", "embedding_model_config_id": 1},
    )
    assert resp.status_code == 403
    assert "租户" in resp.json()["detail"]


def test_create_kb_without_workspace_works(client, kb_state):
    """workspace_id 缺省 → KB 不挂 workspace,workspace_id 留 NULL。"""
    resp = client.post(
        "/api/v1/knowledge/",
        json={"name": "naked-kb", "embedding_model_config_id": 1},
    )
    assert resp.status_code == 200, resp.text
    assert kb_state["kbs"][0].workspace_id is None