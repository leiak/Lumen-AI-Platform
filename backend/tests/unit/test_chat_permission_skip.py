"""M38.2.x v2: per-KB RBAC skip in chat / agent RAG paths。

Unit tests with fake Session — 验证 ``build_agent_kb_context`` 和
``KnowledgeRetrievalNode._run`` 在 user 缺失某 KB 的 ``kb.read`` 时:
1. ``build_agent_kb_context``:该 KB 被静默 skip,其他 KB 仍返 context
2. ``KnowledgeRetrievalNode._run``:返空 result,error="permission_denied"
3. ``user is None``:graceful open(不 skip 任何 KB)
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List

import pytest

from lumen_services.agent_rag import build_agent_kb_context


# --- fakes --------------------------------------------------------------


class _FakeKB:
    def __init__(self, *, id, name, tenant_id=1, status="active", workspace_id=None):
        self.id = id
        self.name = name
        self.tenant_id = tenant_id
        self.status = status
        self.workspace_id = workspace_id


class _FakeAgentKB:
    def __init__(self, kb):
        self.knowledge_base = kb


class _FakeAgent:
    def __init__(self, *, id, tenant_id, kbs, kb_retrieval_config=None):
        self.id = id
        self.tenant_id = tenant_id
        self.knowledge_bases = kbs
        self.kb_retrieval_config = kb_retrieval_config


class _FakeUser:
    def __init__(self, *, id, is_superuser=False):
        self.id = id
        self.is_superuser = is_superuser


class _FakeQuery:
    def __init__(self, agent):
        self._agent = agent

    def filter(self, *a, **kw):
        return self

    def first(self):
        return self._agent

    def all(self):
        return self._agent.knowledge_bases


class _GrantResult:
    """模拟 ``select(1)`` 命中检查的返回值。"""

    def __init__(self, rows):
        self._rows = rows

    def first(self):
        return self._rows[0] if self._rows else None

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None


class _FakeSession:
    """最简 fake:只支持 ``db.get(Agent, id)`` 和 ``PermissionService.check`` 调的 SQL。

    ``granted_perms`` dict: ``{(user_id, workspace_id, permission): True/False}``。
    """

    def __init__(self, *, agent=None, granted_perms=None, is_superuser_user=False):
        self.agent = agent
        self.granted_perms = granted_perms or {}
        self.is_superuser_user = is_superuser_user
        # 不让 real pipeline 跑 — patch 进 _retrieval_svc
        self.pipeline_calls = 0

    def get(self, model, pk):
        name = getattr(model, "__name__", None)
        if name == "Agent" and self.agent and self.agent.id == pk:
            return self.agent
        return None

    def query(self, *a, **kw):
        return _FakeQuery(self.agent)

    def execute(self, stmt):
        s = str(stmt).lower()
        # Workspace owner 查询(返回 owner_id 用于 _is_owner bypass)
        if "owner_id" in s:
            return _GrantResult([])  # 没 owner match
        # WorkspaceMemberPermission SELECT — 走 hint 检测
        # 取 bound params 里的 (user_id, workspace_id, permission)
        try:
            params = stmt.compile().params
        except Exception:
            return _GrantResult([])
        uid = None
        wsid = None
        perm = None
        for k, v in params.items():
            if k.startswith("user_id"):
                uid = v
            elif k.startswith("workspace_id"):
                wsid = v
            elif k.startswith("permission_"):
                perm = v
        if uid is None or wsid is None or perm is None:
            return _GrantResult([])
        # is_superuser bypass
        if self.is_superuser_user:
            return _GrantResult([1])
        key = (uid, wsid, perm)
        return _GrantResult([1] if self.granted_perms.get(key) else [])


# --- helpers ------------------------------------------------------------


def _patch_pipeline_empty(monkeypatch):
    """patch ``_retrieve_kb_chunks_with_ctx`` 让它返空 chunks — 我们只想测 RBAC 过滤逻辑。"""

    import lumen_services.agent_rag as rag_mod

    def _empty(*a, **kw):
        return []

    monkeypatch.setattr(rag_mod, "_retrieve_kb_chunks_with_ctx", _empty)


# --- agent_rag tests ----------------------------------------------------


def test_build_agent_kb_context_skips_unreadable_kb(monkeypatch):
    """user 在 KB-2 没 kb.read → KB-2 被 skip,KB-1 仍返 context。"""
    _patch_pipeline_empty(monkeypatch)

    kb1 = _FakeKB(id=1, name="allowed", workspace_id=10)
    kb2 = _FakeKB(id=2, name="denied", workspace_id=20)
    agent = _FakeAgent(
        id=42, tenant_id=1,
        kbs=[_FakeAgentKB(kb1), _FakeAgentKB(kb2)],
    )
    # user 在 ws=10 有 kb.read,在 ws=20 没
    user = _FakeUser(id=99, is_superuser=False)
    db = _FakeSession(
        agent=agent,
        granted_perms={(99, 10, "kb.read"): True, (99, 20, "kb.read"): False},
    )
    # 直接 mock _retrieve_kb_chunks_with_ctx 让 kb1 返一个 fake chunk
    import lumen_services.agent_rag as rag_mod

    def _fake_retrieve(parent_ctx, kb, query, top_k, tenant_id, db):
        # kb1 → 返 1 chunk,kb2 → 返 1 chunk(如果被调用就是 bug)
        return [{"id": f"c-{kb.id}", "text": f"from {kb.name}", "score": 0.9,
                 "metadata": {"filename": "x.txt", "chunk_index": 0}}]

    monkeypatch.setattr(rag_mod, "_retrieve_kb_chunks_with_ctx", _fake_retrieve)

    ctx = build_agent_kb_context(42, "q", db, user=user)
    assert ctx is not None
    # KB-1 的内容必须在 context 里;KB-2 必须不在
    assert "allowed" in ctx
    assert "denied" not in ctx


def test_build_agent_kb_context_user_none_includes_all(monkeypatch):
    """``user is None`` → graceful open,所有 KB 都进 context。"""
    _patch_pipeline_empty(monkeypatch)

    kb1 = _FakeKB(id=1, name="k1", workspace_id=10)
    kb2 = _FakeKB(id=2, name="k2", workspace_id=20)
    agent = _FakeAgent(
        id=42, tenant_id=1,
        kbs=[_FakeAgentKB(kb1), _FakeAgentKB(kb2)],
    )
    db = _FakeSession(agent=agent)

    import lumen_services.agent_rag as rag_mod

    def _fake_retrieve(parent_ctx, kb, query, top_k, tenant_id, db):
        return [{"id": f"c-{kb.id}", "text": f"from {kb.name}", "score": 0.9,
                 "metadata": {"filename": "x.txt", "chunk_index": 0}}]

    monkeypatch.setattr(rag_mod, "_retrieve_kb_chunks_with_ctx", _fake_retrieve)

    ctx = build_agent_kb_context(42, "q", db, user=None)
    assert ctx is not None
    assert "k1" in ctx
    assert "k2" in ctx


def test_build_agent_kb_context_returns_none_if_no_kb_visible(monkeypatch):
    """所有 KB 都被 skip → None(代表「无 RAG context」)。"""
    _patch_pipeline_empty(monkeypatch)

    kb1 = _FakeKB(id=1, name="denied", workspace_id=10)
    agent = _FakeAgent(
        id=42, tenant_id=1,
        kbs=[_FakeAgentKB(kb1)],
    )
    user = _FakeUser(id=99, is_superuser=False)
    db = _FakeSession(
        agent=agent,
        granted_perms={(99, 10, "kb.read"): False},
    )
    ctx = build_agent_kb_context(42, "q", db, user=user)
    assert ctx is None


def test_build_agent_kb_context_legacy_workspace_none_open(monkeypatch):
    """``workspace_id IS NULL`` 的 KB(spec §6.4)对全员 open,不需 grant。"""
    _patch_pipeline_empty(monkeypatch)

    kb = _FakeKB(id=1, name="legacy", workspace_id=None)  # 老数据
    agent = _FakeAgent(
        id=42, tenant_id=1, kbs=[_FakeAgentKB(kb)],
    )
    user = _FakeUser(id=99, is_superuser=False)
    db = _FakeSession(agent=agent, granted_perms={})  # 没 grant
    import lumen_services.agent_rag as rag_mod

    def _fake_retrieve(parent_ctx, kb, query, top_k, tenant_id, db):
        return [{"id": "c1", "text": "from legacy", "score": 0.9,
                 "metadata": {"filename": "x.txt", "chunk_index": 0}}]

    monkeypatch.setattr(rag_mod, "_retrieve_kb_chunks_with_ctx", _fake_retrieve)
    ctx = build_agent_kb_context(42, "q", db, user=user)
    assert ctx is not None
    assert "legacy" in ctx


def test_build_agent_kb_context_admin_sees_all(monkeypatch):
    """superuser 全 perm,所有 KB 都返。"""
    _patch_pipeline_empty(monkeypatch)

    kb1 = _FakeKB(id=1, name="k1", workspace_id=10)
    kb2 = _FakeKB(id=2, name="k2", workspace_id=20)
    agent = _FakeAgent(
        id=42, tenant_id=1,
        kbs=[_FakeAgentKB(kb1), _FakeAgentKB(kb2)],
    )
    user = _FakeUser(id=99, is_superuser=True)
    db = _FakeSession(agent=agent, is_superuser_user=True)
    import lumen_services.agent_rag as rag_mod

    def _fake_retrieve(parent_ctx, kb, query, top_k, tenant_id, db):
        return [{"id": f"c-{kb.id}", "text": f"from {kb.name}", "score": 0.9,
                 "metadata": {"filename": "x.txt", "chunk_index": 0}}]

    monkeypatch.setattr(rag_mod, "_retrieve_kb_chunks_with_ctx", _fake_retrieve)
    ctx = build_agent_kb_context(42, "q", db, user=user)
    assert "k1" in ctx
    assert "k2" in ctx


# --- knowledge_retrieval node tests -------------------------------------


def test_kb_node_returns_empty_when_user_lacks_kb_read(monkeypatch):
    """Workflow KB 节点:user 无 kb.read → 空 result + error=permission_denied。"""
    from lumen_core.workflow.nodes.knowledge_retrieval import KnowledgeRetrievalNode

    # KB 行 — workspace_id=10
    class _KB:
        id = 5
        tenant_id = 1
        status = "active"
        workspace_id = 10
        embedding_model_config_id = 0

    class _DB:
        def __init__(self):
            self._kb = _KB()

        def query(self, *a, **kw):
            class _Q:
                def filter(self_inner, *a, **kw):
                    return self_inner
                def first(self_inner):
                    return self_inner._db._kb
            return _Q()

        def __getattr__(self, name):
            return getattr(self._kb, name) if name == "_kb" else None

    # 实际写法:用更简单的 fake
    class _DB2:
        def __init__(self):
            self.kb = _KB()

        def query(self, model):
            class _Q:
                def __init__(self_inner):
                    pass
                def filter(self_inner, *a, **kw):
                    return self_inner
                def first(self_inner):
                    return _KB()
            return _Q()

        def execute(self, stmt):
            # WorkspaceMemberPermission 查询 — user 在 ws=10 无 kb.read
            try:
                params = stmt.compile().params
            except Exception:
                return None
            # 返回空
            class _R:
                def first(self_inner):
                    return None
                def scalar_one_or_none(self_inner):
                    return None
            return _R()

    user = _FakeUser(id=42, is_superuser=False)
    db = _DB2()
    pool = __import__("lumen_core.workflow.variable_pool", fromlist=["VariablePool"]).VariablePool()
    n = KnowledgeRetrievalNode(
        node_id="k1",
        config={"kb_id": 5, "query": "q", "top_k": 5},
        pool=pool,
        db=db,
        tenant_id=1,
        user=user,
    )
    result = asyncio.run(n._run())
    assert result.output_values["chunks"] == []
    assert result.output_values["count"] == 0
    assert result.output_values["error"] == "permission_denied"


def test_kb_node_user_none_runs_normally(monkeypatch):
    """``user is None`` 走 graceful open,KB retrieval 不被 RBAC 拦。"""
    from lumen_core.workflow.nodes.knowledge_retrieval import KnowledgeRetrievalNode

    class _KB:
        id = 5
        tenant_id = 1
        status = "active"
        workspace_id = 10
        embedding_model_config_id = 0

    class _DB:
        def __init__(self):
            self.kb = _KB()
            self.pipeline_calls = []

        def query(self, model):
            class _Q:
                def filter(self_inner, *a, **kw):
                    return self_inner
                def first(self_inner):
                    return _KB()
            return _Q()

        def execute(self, stmt):
            try:
                params = stmt.compile().params
            except Exception:
                params = {}
            class _R:
                def first(self_inner):
                    return None
                def scalar_one_or_none(self_inner):
                    return None
            return _R()

    db = _DB()
    pool = __import__("lumen_core.workflow.variable_pool", fromlist=["VariablePool"]).VariablePool()
    n = KnowledgeRetrievalNode(
        node_id="k1",
        config={"kb_id": 5, "query": "q", "top_k": 5},
        pool=pool,
        db=db,
        tenant_id=1,
        user=None,  # graceful open
    )

    # patch pipeline 直接返一个 fake chunk
    import lumen_services.retrieval as svc
    monkeypatch.setattr(
        svc, "get_retrieval_pipeline",
        lambda kb_id, model_config_id, db: type("_P", (), {
            "search": lambda self, **kw: [{"id": "c1", "text": "hello", "score": 0.9, "metadata": {"filename": "x", "chunk_index": 0}}]
        })(),
    )

    result = asyncio.run(n._run())
    assert result.output_values["count"] == 1
    assert "hello" in result.output_values["merged_text"]


def test_kb_node_legacy_workspace_none_open(monkeypatch):
    """KB workspace_id=None 不需 grant,user 没 perm 也通过。"""
    from lumen_core.workflow.nodes.knowledge_retrieval import KnowledgeRetrievalNode

    class _KB:
        id = 5
        tenant_id = 1
        status = "active"
        workspace_id = None  # 老数据
        embedding_model_config_id = 0

    class _DB:
        def query(self, model):
            class _Q:
                def filter(self_inner, *a, **kw):
                    return self_inner
                def first(self_inner):
                    return _KB()
            return _Q()

        def execute(self, stmt):
            class _R:
                def first(self_inner):
                    return None
                def scalar_one_or_none(self_inner):
                    return None
            return _R()

    user = _FakeUser(id=42, is_superuser=False)
    db = _DB()
    pool = __import__("lumen_core.workflow.variable_pool", fromlist=["VariablePool"]).VariablePool()
    n = KnowledgeRetrievalNode(
        node_id="k1",
        config={"kb_id": 5, "query": "q", "top_k": 5},
        pool=pool,
        db=db,
        tenant_id=1,
        user=user,
    )

    import lumen_services.retrieval as svc
    monkeypatch.setattr(
        svc, "get_retrieval_pipeline",
        lambda kb_id, model_config_id, db: type("_P", (), {
            "search": lambda self, **kw: [{"id": "c1", "text": "ok", "score": 0.9, "metadata": {"filename": "x", "chunk_index": 0}}]
        })(),
    )
    result = asyncio.run(n._run())
    assert result.output_values["count"] == 1