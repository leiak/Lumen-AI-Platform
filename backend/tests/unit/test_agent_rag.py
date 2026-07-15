"""Tests for agent_rag.py — Agent RAG context builder.

M21: per-KB top-k → RRF fusion → markdown context for LLM.
"""
import pytest
import uuid
from typing import Any, Dict
from unittest.mock import MagicMock

from lumen_core.database import SessionLocal
from lumen_models.agent import Agent, AgentKnowledgeBase
from lumen_models.knowledge import KnowledgeBase
from lumen_models.model_config import ModelConfig  # noqa: F401  - register model_configs table metadata
from lumen_models.tenant import Tenant
from lumen_services.agent_rag import _rrf_fuse  # build_agent_kb_context added in T5


@pytest.fixture
def db_session():
    """Yield a fresh SQLAlchemy session.

    Ensures tenant id=1 exists. Caller is responsible for cleaning up
    rows it inserts. Used by T5+ tests that need a real DB session to
    query Agent + KnowledgeBase bindings.
    """
    db = SessionLocal()
    try:
        tenant = db.query(Tenant).filter(Tenant.id == 1).first()
        if not tenant:
            tenant = Tenant(id=1, name="Default Tenant", code="default")
            db.add(tenant)
            db.commit()
            db.refresh(tenant)
        yield db
    finally:
        db.close()


def _make_chunk(vector_id: str) -> Dict[str, Any]:
    """Mock dict-shaped chunk per VectorStoreBase.similarity_search contract.

    Contract keys: "id", "text", "distance", "metadata".
    """
    return {
        "id": vector_id,
        "text": f"content for {vector_id}",
        "distance": 0.1,
        "metadata": {},
    }


def test_rrf_score_formula_known_input():
    """RRF(d) = sum(1 / (k + r)) across all KBs where d appears.

    Example from spec §8.3:
    - KB1 top-3: [A(1), B(2), C(3)]
    - KB2 top-3: [B(1), D(2), E(3)]
    - KB3 top-3: [F(1), C(2), B(3)]
    - rrf_k = 30
    Expected: B(0.0939) > C(0.0616) > A≈F(0.0323) > D(0.0313) > E(0.0303)
    """
    kb1 = [_make_chunk("A"), _make_chunk("B"), _make_chunk("C")]
    kb2 = [_make_chunk("B"), _make_chunk("D"), _make_chunk("E")]
    kb3 = [_make_chunk("F"), _make_chunk("C"), _make_chunk("B")]
    per_kb = {1: kb1, 2: kb2, 3: kb3}

    result = _rrf_fuse(per_kb, rrf_k=30, top_n=10)

    # Top result is B (highest RRF score, 3 KBs)
    assert result[0]["id"] == "B"
    # Second is C (2 KBs)
    assert result[1]["id"] == "C"
    # No duplicates
    assert len(result) == 6
    assert len(set(c["id"] for c in result)) == 6
    # B's score should be highest
    b_score = sum(1 / (30 + r) for r in [2, 1, 3])  # KB1 rank 2, KB2 rank 1, KB3 rank 3
    c_score = sum(1 / (30 + r) for r in [3, 2])  # KB1 rank 3, KB3 rank 2
    assert b_score > c_score


def test_rrf_top_n_cap():
    """top_n caps result count."""
    per_kb = {1: [_make_chunk(f"chunk_{i}") for i in range(20)]}
    result = _rrf_fuse(per_kb, rrf_k=30, top_n=5)
    assert len(result) == 5


def test_rrf_dedup_across_kbs():
    """Same chunk in 2 KBs appears once in result."""
    shared = _make_chunk("shared")
    per_kb = {1: [shared, _make_chunk("a1")], 2: [shared, _make_chunk("a2")]}
    result = _rrf_fuse(per_kb, rrf_k=30, top_n=10)
    assert len(result) == 3  # shared + a1 + a2
    # shared should rank first (sum of 2 ranks)
    assert result[0]["id"] == "shared"


# ---------------------------------------------------------------------------
# T5: build_agent_kb_context basic flow
# ---------------------------------------------------------------------------


def _make_agent_with_kbs(db_session, kb_specs):
    """Helper: create Agent with KB bindings.

    kb_specs: list of dicts with keys (name, status, embedding_model_config_id).
    Returns (agent, list of KB).

    Uses uuid-suffixed names to avoid collisions across reruns.
    """
    tenant_id = 1
    suffix = uuid.uuid4().hex[:6]
    agent = Agent(
        name=f"test-agent-{suffix}",
        prompt_template="You are a test agent",
        model_name="gpt-4o",
        temperature=0,
        tenant_id=tenant_id,
        kb_retrieval_config={"top_k": 3, "rrf_k": 30},
    )
    db_session.add(agent)
    db_session.flush()

    kbs = []
    for spec in kb_specs:
        kb = KnowledgeBase(
            name=f"{spec['name']}-{suffix}",
            description="",
            tenant_id=tenant_id,
            status=spec.get("status", "active"),
            # NB: leave embedding_model_config_id NULL by default — we
            # mock VectorStoreFactory in tests that need retrieval, so no
            # real model_configs row is required. The plan's default of 1
            # only applies when the test env has a matching row.
            embedding_model_config_id=spec.get("embedding_model_config_id"),
        )
        db_session.add(kb)
        db_session.flush()
        agent.knowledge_bases.append(
            AgentKnowledgeBase(knowledge_base_id=kb.id)
        )
        kbs.append(kb)
    db_session.commit()
    db_session.refresh(agent)
    return agent, kbs


def test_build_context_with_no_bindings(db_session):
    """M21: agent 0 KB → 返 None."""
    from lumen_services.agent_rag import build_agent_kb_context

    suffix = uuid.uuid4().hex[:6]
    agent = Agent(
        name=f"empty-{suffix}",
        prompt_template="x",
        model_name="gpt-4o",
        temperature=0,
        tenant_id=1,
    )
    db_session.add(agent)
    db_session.commit()
    db_session.refresh(agent)

    result = build_agent_kb_context(agent.id, "test query", db_session)
    assert result is None


def test_build_context_with_inactive_kb_only(db_session):
    """M21: agent 只绑 inactive KB → 返 None(inactive 跳过)。"""
    from lumen_services.agent_rag import build_agent_kb_context

    agent, _ = _make_agent_with_kbs(db_session, [
        {"name": "Inactive KB", "status": "inactive"},
    ])
    result = build_agent_kb_context(agent.id, "test query", db_session)
    assert result is None


def test_build_context_with_single_active_kb(db_session, monkeypatch):
    """M21: 1 active KB → markdown 字符串包含 [Source: ...]."""
    from lumen_services.agent_rag import build_agent_kb_context

    agent, kbs = _make_agent_with_kbs(db_session, [
        {"name": "Sales Manual", "status": "active"},
    ])
    # Real dict-shaped chunk per VectorStoreBase.similarity_search contract.
    # This exercises the production code path (chunk["id"], chunk["text"], etc.)
    # — MagicMock would auto-create attributes and hide dict-access bugs.
    chunk = {
        "id": "v1",
        "text": "Sales process is...",
        "distance": 0.1,
        "metadata": {
            "kb_id": kbs[0].id,
            "filename": "sales.pdf",
            "chunk_index": 0,
        },
    }

    fake_store = MagicMock()
    fake_store.similarity_search.return_value = [chunk]
    monkeypatch.setattr(
        "lumen_services.agent_rag.VectorStoreFactory.get_store",
        lambda kb_id, mcid, db: fake_store,
    )

    result = build_agent_kb_context(agent.id, "how to sell?", db_session)
    assert result is not None
    assert "## Knowledge Context" in result
    assert "[Source: Sales Manual" in result
    assert "sales.pdf" in result  # Document filename from metadata
    assert "Sales process is..." in result  # chunk text
    # 验证 similarity_search 收到正确的 filter
    call_args = fake_store.similarity_search.call_args
    assert f"kb_id == {kbs[0].id}" in str(call_args)


def test_build_context_uses_per_kb_filter(db_session, monkeypatch):
    """M21: filter_expr=f'kb_id == {kb_id}' 防止全库搜索。"""
    from lumen_services.agent_rag import build_agent_kb_context

    agent, kbs = _make_agent_with_kbs(db_session, [
        {"name": "KB1", "status": "active"},
        {"name": "KB2", "status": "active"},
    ])
    fake_store = MagicMock()
    fake_store.similarity_search.return_value = []
    monkeypatch.setattr(
        "lumen_services.agent_rag.VectorStoreFactory.get_store",
        lambda kb_id, mcid, db: fake_store,
    )

    build_agent_kb_context(agent.id, "query", db_session)
    # 验证两次 similarity_search 调用各自带正确的 filter
    assert fake_store.similarity_search.call_count == 2
    for call in fake_store.similarity_search.call_args_list:
        filter_expr = call.kwargs.get("filter_expr", "")
        assert "tenant_id ==" in filter_expr
        assert "kb_id ==" in filter_expr


# ---------------------------------------------------------------------------
# T6: build_agent_kb_context 多 KB RRF 融合 (dedup + top_n)
# ---------------------------------------------------------------------------


def test_build_context_rrf_fusion_dedup(db_session, monkeypatch):
    """M21: 2 KB 都返回同一 chunk → RRF 提权。"""
    from lumen_services.agent_rag import build_agent_kb_context

    agent, kbs = _make_agent_with_kbs(db_session, [
        {"name": "KB1", "status": "active"},
        {"name": "KB2", "status": "active"},
    ])
    shared_chunk = {
        "id": "shared",
        "text": "shared content",
        "distance": 0.1,
        "metadata": {"kb_id": kbs[0].id, "filename": "f.pdf", "chunk_index": 0},
    }

    other_chunk = {
        "id": "other",
        "text": "other content",
        "distance": 0.2,
        "metadata": {"kb_id": kbs[1].id, "filename": "g.pdf", "chunk_index": 0},
    }

    def make_store(kb_id, mcid, db):
        store = MagicMock()
        if kb_id == kbs[0].id:
            store.similarity_search.return_value = [shared_chunk, other_chunk]
        else:
            store.similarity_search.return_value = [shared_chunk]
        return store

    monkeypatch.setattr(
        "lumen_services.agent_rag.VectorStoreFactory.get_store", make_store
    )

    result = build_agent_kb_context(agent.id, "q", db_session)
    assert result is not None
    # shared 出现 2 次(每个 KB 一次),RRF 提权,排第一
    assert result.count("[Source:") >= 2
    # shared 出现位置应该在 other 之前
    shared_pos = result.find("shared content")
    other_pos = result.find("other content")
    assert shared_pos < other_pos


def test_build_context_rrf_top_n_cap(db_session, monkeypatch):
    """M21: 2 KB × 8 chunks = 16,top_n=10 → 只返 10。"""
    from lumen_services.agent_rag import build_agent_kb_context

    agent, kbs = _make_agent_with_kbs(db_session, [
        {"name": "KB1", "status": "active"},
        {"name": "KB2", "status": "active"},
    ])

    def make_store(kb_id, mcid, db):
        store = MagicMock()
        chunks = []
        for i in range(8):
            chunks.append({
                "id": f"k{kb_id}_c{i}",
                "text": f"k{kb_id}_c{i}_content",
                "distance": 0.1 + i * 0.01,
                "metadata": {"kb_id": kb_id, "filename": "f.pdf", "chunk_index": i},
            })
        store.similarity_search.return_value = chunks
        return store

    monkeypatch.setattr(
        "lumen_services.agent_rag.VectorStoreFactory.get_store", make_store
    )

    result = build_agent_kb_context(agent.id, "q", db_session)
    assert result is not None
    # count occurrences of [Source: should be 10 (top_n)
    assert result.count("[Source:") == 10


# ---------------------------------------------------------------------------
# T7: build_agent_kb_context graceful degradation (1 KB 抛错不影响其他 KB)
# ---------------------------------------------------------------------------


def test_build_context_graceful_kb_failure(db_session, monkeypatch):
    """M21: 一 KB similarity_search 抛错,其他 KB 仍工作。"""
    from lumen_services.agent_rag import build_agent_kb_context

    agent, kbs = _make_agent_with_kbs(db_session, [
        {"name": "Good KB", "status": "active"},
        {"name": "Bad KB", "status": "active"},
    ])

    good_chunk = {
        "id": "good",
        "text": "good content",
        "distance": 0.1,
        "metadata": {"kb_id": kbs[0].id, "filename": "f.pdf", "chunk_index": 0},
    }

    def make_store(kb_id, mcid, db):
        store = MagicMock()
        if kb_id == kbs[0].id:
            store.similarity_search.return_value = [good_chunk]
        else:
            store.similarity_search.side_effect = RuntimeError("embedding provider down")
        return store

    monkeypatch.setattr(
        "lumen_services.agent_rag.VectorStoreFactory.get_store", make_store
    )

    result = build_agent_kb_context(agent.id, "q", db_session)
    assert result is not None
    assert "good content" in result
    # Bad KB 的内容不应出现
    assert "bad content" not in result
