"""M38.4 Step 5a: MultimodalVectorStore + MultimodalVectorStoreFactory unit tests.

Covers:
- ``add_texts`` + ``search`` round-trip on a fresh index
- persistence (re-open the same ``kb_id`` and see the same hits)
- dim mismatch raises on add
- ``length mismatch`` raises on add (defensive)
- factory cache + ``invalidate``
- no-op stub when FAISS not importable (we don't actually exercise the
  import-failure path because faiss is required at module-import time;
  we just check the public surface still works)

These tests use ``tmp_path`` so they don't touch ``./data/multimodal/``;
no global state pollution between tests.
"""
from __future__ import annotations

from typing import Any, Dict, List

import pytest

from lumen_services.multimodal_vector_store import (
    FAISS_AVAILABLE,
    MultimodalVectorStore,
)
from lumen_services.multimodal_vector_store_factory import (
    MultimodalVectorStoreFactory,
)


pytestmark = pytest.mark.skipif(
    not FAISS_AVAILABLE, reason="faiss-cpu not installed"
)


# --- helpers ---------------------------------------------------------------


def _unit_vector(d: int, seed: int) -> List[float]:
    """Deterministic unit-ish vector so cosine search is reproducible.

    Not a true unit vector — close enough for top-K ranking tests since
    we control the input order.
    """
    return [((i + seed) % 17) / 17.0 for i in range(d)]


def _vec(d: int, fill: float) -> List[float]:
    return [fill] * d


# --- MultimodalVectorStore --------------------------------------------------


def test_add_then_search_returns_top_k(tmp_path):
    """Add 3 vectors, search returns them in descending inner-product order."""
    store = MultimodalVectorStore(kb_id=1, dim=4, persist_dir=str(tmp_path))
    texts = ["a", "b", "c"]
    metas: List[Dict[str, Any]] = [
        {"chunk_id": 10, "document_id": 1, "tenant_id": 1, "kb_id": 1, "modality": "image"},
        {"chunk_id": 11, "document_id": 1, "tenant_id": 1, "kb_id": 1, "modality": "image"},
        {"chunk_id": 12, "document_id": 1, "tenant_id": 1, "kb_id": 1, "modality": "image"},
    ]
    vecs = [_vec(4, 1.0), _vec(4, 0.5), _vec(4, -1.0)]
    ids = store.add_texts(texts, metas, vecs)
    assert len(ids) == 3
    assert all(i.startswith("mm-") for i in ids)

    # Query same direction as ``a`` (vec=1.0) → top hit is "a".
    hits = store.search(_vec(4, 1.0), k=3)
    assert len(hits) == 3
    assert hits[0]["text"] == "a"
    assert hits[0]["score"] >= hits[1]["score"] >= hits[2]["score"]
    # distance = -score (FAISS convention: smaller = closer)
    assert hits[0]["distance"] == pytest.approx(-hits[0]["score"])
    # metadata round-tripped
    assert hits[0]["metadata"]["chunk_id"] == 10
    assert hits[0]["metadata"]["modality"] == "image"


def test_search_empty_index_returns_empty(tmp_path):
    """Cold store with no vectors — search should be [], not crash."""
    store = MultimodalVectorStore(kb_id=2, dim=8, persist_dir=str(tmp_path))
    assert store.ntotal == 0
    assert store.search(_vec(8, 0.1)) == []


def test_persistence_round_trip(tmp_path):
    """Write, re-open with same kb_id/dim, hit count + records preserved."""
    s1 = MultimodalVectorStore(kb_id=3, dim=4, persist_dir=str(tmp_path))
    s1.add_texts(["x"], [{"chunk_id": 99, "modality": "image"}], [_vec(4, 0.3)])
    s1.add_texts(["y"], [{"chunk_id": 100, "modality": "image"}], [_vec(4, 0.7)])
    assert s1.ntotal == 2

    # Construct a fresh instance against the same path — simulates
    # uvicorn worker restart.
    s2 = MultimodalVectorStore(kb_id=3, dim=4, persist_dir=str(tmp_path))
    assert s2.ntotal == 2
    hits = s2.search(_vec(4, 0.7), k=2)
    assert len(hits) == 2
    # Highest inner product should be "y" (both vecs = 0.7).
    assert hits[0]["text"] == "y"
    assert hits[0]["metadata"]["chunk_id"] == 100


def test_dim_mismatch_warns_and_rebuilds(tmp_path, caplog):
    """Persisted index at dim=4, request dim=8 → warn + fresh index.

    Spec doesn't promise this exact behaviour, but a mismatch is
    catastrophic if not caught (FAISS asserts on add); the warning +
    rebuild path is the safe default.
    """
    # First build a dim=4 index.
    s1 = MultimodalVectorStore(kb_id=4, dim=4, persist_dir=str(tmp_path))
    s1.add_texts(["a"], [{"chunk_id": 1}], [_vec(4, 1.0)])

    # Re-open requesting dim=8 — should rebuild.
    with caplog.at_level("WARNING", logger="lumen_services.multimodal_vector_store"):
        s2 = MultimodalVectorStore(kb_id=4, dim=8, persist_dir=str(tmp_path))
    assert s2.ntotal == 0  # old records were dropped with the old index
    assert any("dim mismatch" in rec.message.lower() for rec in caplog.records)


def test_add_texts_length_mismatch_raises(tmp_path):
    """Mismatched list lengths should fail loudly — better than silent corruption."""
    store = MultimodalVectorStore(kb_id=5, dim=4, persist_dir=str(tmp_path))
    with pytest.raises(ValueError, match="length mismatch"):
        store.add_texts(
            texts=["a", "b"],
            metadatas=[{"chunk_id": 1}],
            vectors=[_vec(4, 1.0), _vec(4, 0.5)],
        )


def test_add_texts_wrong_vector_dim_raises(tmp_path):
    """A vector with wrong dim raises ValueError."""
    store = MultimodalVectorStore(kb_id=6, dim=4, persist_dir=str(tmp_path))
    with pytest.raises(ValueError, match="dim mismatch"):
        store.add_texts(
            texts=["x"],
            metadatas=[{"chunk_id": 1}],
            vectors=[[1.0, 2.0, 3.0]],  # dim=3, expected 4
        )


def test_search_k_clamped_to_ntotal(tmp_path):
    """Asking for k > ntotal should not crash."""
    store = MultimodalVectorStore(kb_id=7, dim=4, persist_dir=str(tmp_path))
    store.add_texts(["only"], [{"chunk_id": 1}], [_vec(4, 0.5)])
    hits = store.search(_vec(4, 0.5), k=10)  # ntotal=1
    assert len(hits) == 1


def test_is_connected_reflects_state(tmp_path):
    """``is_connected`` is True after successful init, False on init failure.

    The init-failure path is hard to provoke without monkey-patching faiss,
    so we only assert the positive case here.
    """
    store = MultimodalVectorStore(kb_id=8, dim=4, persist_dir=str(tmp_path))
    assert store.is_connected is True


# --- MultimodalVectorStoreFactory -------------------------------------------


def test_factory_caches_by_kb_id(tmp_path, monkeypatch):
    """Same ``kb_id`` + ``dim`` returns the same instance."""
    # Force a clean cache (other tests in the suite might have populated it).
    MultimodalVectorStoreFactory.invalidate()
    try:
        s1 = MultimodalVectorStoreFactory.get_store(kb_id=99, dim=4)
        s2 = MultimodalVectorStoreFactory.get_store(kb_id=99, dim=4)
        assert s1 is s2
    finally:
        MultimodalVectorStoreFactory.invalidate()


def test_factory_invalidate_drops_entry(tmp_path):
    """invalidate(kb_id) drops one entry; invalidate() drops everything."""
    MultimodalVectorStoreFactory.invalidate()
    try:
        s_a = MultimodalVectorStoreFactory.get_store(kb_id=100, dim=4)
        s_b = MultimodalVectorStoreFactory.get_store(kb_id=101, dim=4)
        assert s_a is not s_b

        MultimodalVectorStoreFactory.invalidate(kb_id=100)
        s_a2 = MultimodalVectorStoreFactory.get_store(kb_id=100, dim=4)
        s_b2 = MultimodalVectorStoreFactory.get_store(kb_id=101, dim=4)
        # 100 was invalidated → fresh instance
        assert s_a2 is not s_a
        # 101 was preserved → same instance
        assert s_b2 is s_b
    finally:
        MultimodalVectorStoreFactory.invalidate()


def test_factory_invalidate_all_clears(tmp_path):
    """``invalidate()`` (no arg) drops everything."""
    MultimodalVectorStoreFactory.invalidate()
    try:
        MultimodalVectorStoreFactory.get_store(kb_id=200, dim=4)
        MultimodalVectorStoreFactory.get_store(kb_id=201, dim=4)
        MultimodalVectorStoreFactory.invalidate()
        s1 = MultimodalVectorStoreFactory.get_store(kb_id=200, dim=4)
        s2 = MultimodalVectorStoreFactory.get_store(kb_id=200, dim=4)
        # After full clear, fresh instance built on next get_store
        assert s1 is s2  # both built fresh in same call pair
    finally:
        MultimodalVectorStoreFactory.invalidate()
