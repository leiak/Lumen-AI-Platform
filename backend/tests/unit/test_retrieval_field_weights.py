"""Tests for M28 — wire ``KnowledgeBase.search_weights`` (4 滑块) into
``RetrievalPipeline.search()``.

The 4 ``multi_match`` field boosts (``title`` / ``important_kw`` /
``question_kw`` / ``text``) are editable in the KB UI and stored on
``KnowledgeBase.search_weights`` (JSON column). The values previously
had no effect because the retrieval pipeline only went through
``similarity_search`` (KNN, no field weighting).

This module verifies the dispatch logic added in M28:
- ES-backed pipelines call ``ElasticsearchVectorStore.hybrid_search``
  with the resolved ``field_weights`` argument.
- FAISS-backed pipelines (or any non-ES store) silently ignore
  ``search_weights`` and keep the old ``HybridRetriever.search`` path.
- ES disconnect degrades to the BM25+vector hybrid path.
- The per-request override wins over the KB row's stored value.
- Non-dict values are sanitised away (no ``TypeError`` poisoning).
- ``describe()`` reports ``search_weights_supported`` correctly.
"""
import os
import sys

import pytest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))


# ---------------------------------------------------------------------------
# Fixtures: stub out heavy collaborators so we can build a real
# ``RetrievalPipeline`` without needing a live ES / FAISS / Ollama.
# ---------------------------------------------------------------------------


@pytest.fixture
def es_vector_store():
    """Mock store that passes ``isinstance(_ES_STORE_TYPE)`` checks."""
    from lumen_tools.es_vector_store import ElasticsearchVectorStore

    store = MagicMock(spec=ElasticsearchVectorStore)
    store.is_connected = True
    store.hybrid_search.return_value = [
        {"id": "es-1", "text": "chunk A", "metadata": {"kb_id": 7}},
    ]
    return store


@pytest.fixture
def faiss_vector_store():
    """Mock store that is NOT an ``ElasticsearchVectorStore`` instance."""
    from lumen_tools.vector_store import FAISSVectorStore

    store = MagicMock(spec=FAISSVectorStore)
    store.similarity_search.return_value = [
        {"id": "faiss-1", "text": "chunk A", "metadata": {"kb_id": 7}},
    ]
    # Force the similarity_search contract that HybridRetriever expects.
    return store


@pytest.fixture
def bm25_index():
    """Stand-in for ``app.services.retrieval.bm25_index.BM25Index``."""
    idx = MagicMock()
    idx.is_available = True
    idx.size = 0
    idx.search.return_value = []
    return idx


@pytest.fixture
def reranker():
    """NoopReranker stub: passthrough, no extra calls."""
    r = MagicMock()
    r.is_available = True
    r.name = "NoopReranker"
    r.rerank.side_effect = lambda q, docs, top_k: docs[:top_k]
    return r


@pytest.fixture
def hybrid_retriever():
    """Stand-in for ``HybridRetriever``; configurable ``vector_weight``."""
    h = MagicMock()
    h.vector_weight = 0.5
    h.bm25_weight = 0.5
    h.search.return_value = [
        {"id": "h-1", "text": "hybrid chunk", "metadata": {"kb_id": 7}},
    ]
    return h


@pytest.fixture
def pipeline_factory(monkeypatch, bm25_index, reranker, hybrid_retriever):
    """Build a real ``RetrievalPipeline`` with the given vector store + mocked
    collaborators. Returns a callable: ``make(es_or_faiss_store)`` -> pipeline.
    """
    from lumen_services.retrieval import pipeline as pipeline_mod

    def _build(vector_store):
        # Skip the real ctor's BM25 / HybridRetriever / Reranker wiring —
        # we only need ``search()`` to run, and that path consults
        # ``self.vector_store`` and ``self.hybrid_retriever`` directly.
        p = pipeline_mod.RetrievalPipeline.__new__(pipeline_mod.RetrievalPipeline)
        p.collection_name = "kb_7_mc_4"
        p.vector_store = vector_store
        p.vector_weight = 0.5
        p.bm25_weight = 0.5
        p.rerank_enabled = True
        p.rerank_type = "auto"
        p.rerank_model = None
        p.rerank_top_n = 20
        p.bm25_index = bm25_index
        p.hybrid_retriever = hybrid_retriever
        p.reranker = reranker
        return p

    return _build


# ---------------------------------------------------------------------------
# ES path: hybrid_search is called with the resolved weights.
# ---------------------------------------------------------------------------


def test_es_path_threads_search_weights_to_hybrid_search(
    pipeline_factory, es_vector_store, hybrid_retriever, reranker
):
    """ES path: ``hybrid_search`` receives the per-request weights; reranker
    still runs on the post-fusion results."""
    pipeline = pipeline_factory(es_vector_store)

    weights = {"title": 10.0, "important_kw": 30.0, "question_kw": 20.0, "text": 2.0}
    out = pipeline.search(query="hello world", k=3, search_weights=weights)

    # 1) hybrid_search received the weights as field_weights kwarg
    es_vector_store.hybrid_search.assert_called_once()
    call_kwargs = es_vector_store.hybrid_search.call_args.kwargs
    assert call_kwargs["field_weights"] == weights
    assert call_kwargs["query"] == "hello world"
    assert call_kwargs["k"] >= 3

    # 2) hybrid_retriever.search was NOT used (ES path bypasses it)
    hybrid_retriever.search.assert_not_called()

    # 3) Reranker still applied to the ES results
    reranker.rerank.assert_called_once()
    assert out == [{"id": "es-1", "text": "chunk A", "metadata": {"kb_id": 7}}]


def test_es_path_skips_hybrid_retriever(
    pipeline_factory, es_vector_store, hybrid_retriever
):
    """The ES branch must short-circuit before ``hybrid_retriever.search``."""
    pipeline = pipeline_factory(es_vector_store)
    pipeline.search(query="q", k=2, search_weights={"title": 5.0})

    es_vector_store.hybrid_search.assert_called_once()
    hybrid_retriever.search.assert_not_called()


def test_es_disconnect_falls_back_to_hybrid_retriever(
    pipeline_factory, es_vector_store, hybrid_retriever, caplog
):
    """If ``is_connected`` is False, the pipeline degrades to
    ``hybrid_retriever.search`` instead of returning ``[]``."""
    import logging

    es_vector_store.is_connected = False

    pipeline = pipeline_factory(es_vector_store)
    with caplog.at_level(logging.WARNING, logger="lumen_services.retrieval.pipeline"):
        out = pipeline.search(query="q", k=2, search_weights={"title": 1.0})

    es_vector_store.hybrid_search.assert_not_called()
    hybrid_retriever.search.assert_called_once()
    # Warning surfaces the degradation (helps ops diagnose)
    assert any(
        "Elasticsearch disconnected" in rec.message for rec in caplog.records
    )
    # We still get results (from hybrid_retriever), not []
    assert out and out[0]["id"] == "h-1"


# ---------------------------------------------------------------------------
# FAISS path: hybrid_search is NOT called; search_weights is a no-op.
# ---------------------------------------------------------------------------


def test_faiss_path_ignores_search_weights(
    pipeline_factory, faiss_vector_store, hybrid_retriever, es_vector_store
):
    """FAISS has no multi_match / field^N concept — weights are silently
    ignored, the original ``hybrid_retriever.search`` path is preserved."""
    pipeline = pipeline_factory(faiss_vector_store)
    out = pipeline.search(
        query="q", k=2, search_weights={"title": 999.0, "text": 1.0}
    )

    # ES path completely bypassed
    es_vector_store.hybrid_search.assert_not_called()
    # FAISS still goes through HybridRetriever (which in turn calls
    # vector_store.similarity_search under the hood — not our concern here)
    hybrid_retriever.search.assert_called_once()
    assert out and out[0]["id"] == "h-1"


# ---------------------------------------------------------------------------
# Weight resolution: per-request override > KB row > None.
# ---------------------------------------------------------------------------


def test_search_weights_none_falls_through_to_es_defaults(
    pipeline_factory, es_vector_store
):
    """``search_weights=None`` is passed through verbatim; the ES store
    itself falls back to its class defaults inside ``hybrid_search``."""
    pipeline = pipeline_factory(es_vector_store)
    pipeline.search(query="q", k=2, search_weights=None)

    es_vector_store.hybrid_search.assert_called_once()
    assert es_vector_store.hybrid_search.call_args.kwargs["field_weights"] is None


def test_per_request_override_wins_over_kb_row(
    pipeline_factory, es_vector_store
):
    """The API/service layer resolves ``weights if weights else kb.search_weights``
    before calling ``pipeline.search()``; the pipeline itself only sees the
    resolved value, so we verify that any non-None value is forwarded as-is."""
    pipeline = pipeline_factory(es_vector_store)
    # Simulate the API layer passing the per-request override (already merged)
    per_request = {"title": 999.0, "text": 1.0}
    pipeline.search(query="q", k=2, search_weights=per_request)

    es_vector_store.hybrid_search.assert_called_once()
    assert (
        es_vector_store.hybrid_search.call_args.kwargs["field_weights"]
        == per_request
    )


def test_search_weights_invalid_type_dropped(
    pipeline_factory, es_vector_store, caplog
):
    """Non-dict values (e.g. accidental string from a Form param) are
    sanitised to None — they must not raise TypeError inside ``hybrid_search``."""
    import logging

    pipeline = pipeline_factory(es_vector_store)
    with caplog.at_level(logging.WARNING, logger="lumen_services.retrieval.pipeline"):
        pipeline.search(query="q", k=2, search_weights="not a dict")

    es_vector_store.hybrid_search.assert_called_once()
    assert (
        es_vector_store.hybrid_search.call_args.kwargs["field_weights"] is None
    )
    # Operator should see a warning explaining the drop
    assert any(
        "search_weights must be a dict" in rec.message for rec in caplog.records
    )


# ---------------------------------------------------------------------------
# describe(): expose whether the current backend honours field weights.
# ---------------------------------------------------------------------------


def test_describe_reports_search_weights_supported(
    pipeline_factory, es_vector_store, faiss_vector_store
):
    es_pipe = pipeline_factory(es_vector_store)
    faiss_pipe = pipeline_factory(faiss_vector_store)

    es_desc = es_pipe.describe()
    faiss_desc = faiss_pipe.describe()

    assert es_desc["search_weights_supported"] is True
    assert faiss_desc["search_weights_supported"] is False
    # Both pipelines serialise ``describe()`` as a plain dict — the keys
    # ``search_weights_supported`` plus the original ``vector_store`` /
    # ``vector_weight`` fields must be present so the diagnostic endpoint
    # (``GET /api/v1/knowledge/{kb_id}/search/compare``) can read them.
    assert "vector_store" in es_desc
    assert "vector_weight" in es_desc
    assert "search_weights_supported" in es_desc
    assert "search_weights_supported" in faiss_desc
