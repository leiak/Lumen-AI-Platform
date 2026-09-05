"""
High-level retrieval pipeline used by the knowledge base service.

This module ties together a vector store, a :class:`BM25Index`, a
:class:`HybridRetriever`, and a :class:`Reranker` into a single facade that
the API layer can call.

The pipeline is intentionally tolerant: if the BM25 index or reranker is
unavailable, the corresponding stage is skipped, so the existing vector-only
behaviour is preserved.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Use the existing settings module for default paths / config.
try:
    from lumen_core.config import settings  # type: ignore
except Exception:  # pragma: no cover - defensive
    settings = None  # type: ignore

# Guarded import — Elasticsearch is optional; some deployments are FAISS-only
# and must not hard-fail at module import time.
try:
    from lumen_tools.es_vector_store import ElasticsearchVectorStore
    _ES_STORE_TYPE = ElasticsearchVectorStore  # type: ignore[misc]
except ImportError:  # pragma: no cover - defensive
    ElasticsearchVectorStore = None  # type: ignore[assignment]
    _ES_STORE_TYPE = None  # type: ignore[assignment]


_DEFAULT_PERSIST_DIR = "./data/faiss"
_FALLBACK_VS = None
_FALLBACK_BM25: Dict[str, Any] = {}
_FALLBACK_PIPELINE: Dict[str, Any] = {}


def _persist_path_for(collection: str) -> str:
    base = getattr(settings, "FAISS_INDEX_PATH", _DEFAULT_PERSIST_DIR) if settings else _DEFAULT_PERSIST_DIR
    # Use the directory that contains the FAISS index files. The BM25 file
    # is named ``<collection>.bm25.pkl``.
    return os.path.join(os.path.dirname(base) or ".", f"{collection}.bm25.pkl")


def _bm25_path_for(collection: str) -> str:
    """Where the BM25 index for ``collection`` should be persisted."""
    return _persist_path_for(collection)


class RetrievalPipeline:
    """Facade combining vector store, BM25, RRF fusion, and a reranker.

    The pipeline is created per-collection-name; lightweight in-memory
    instances are cached to avoid rebuilding BM25 on every call.
    """

    def __init__(
        self,
        collection_name: str = "knowledge_base",
        vector_store: Any = None,
        vector_weight: Optional[float] = None,
        bm25_weight: Optional[float] = None,
        rerank_enabled: Optional[bool] = None,
        rerank_type: Optional[str] = None,
        rerank_model: Optional[str] = None,
        rerank_top_n: Optional[int] = None,
        use_jieba: bool = True,
    ) -> None:
        self.collection_name = collection_name

        # Resolve configuration from settings when not provided.
        if settings is not None:
            self.vector_weight = float(
                vector_weight
                if vector_weight is not None
                else getattr(settings, "RETRIEVAL_VECTOR_WEIGHT", 0.5)
            )
            self.bm25_weight = float(
                bm25_weight
                if bm25_weight is not None
                else getattr(settings, "RETRIEVAL_BM25_WEIGHT", 0.5)
            )
            self.rerank_enabled = bool(
                rerank_enabled
                if rerank_enabled is not None
                else getattr(settings, "RERANK_ENABLED", True)
            )
            self.rerank_type = (
                rerank_type
                if rerank_type is not None
                else getattr(settings, "RERANK_TYPE", "auto")
            )
            self.rerank_model = (
                rerank_model
                if rerank_model is not None
                else getattr(settings, "RERANK_MODEL", None)
            )
            self.rerank_top_n = int(
                rerank_top_n
                if rerank_top_n is not None
                else getattr(settings, "RERANK_TOP_N", 20)
            )
        else:
            self.vector_weight = float(vector_weight if vector_weight is not None else 0.5)
            self.bm25_weight = float(bm25_weight if bm25_weight is not None else 0.5)
            self.rerank_enabled = bool(rerank_enabled if rerank_enabled is not None else True)
            self.rerank_type = rerank_type or "auto"
            self.rerank_model = rerank_model
            self.rerank_top_n = int(rerank_top_n if rerank_top_n is not None else 20)

        # Vector store
        if vector_store is None:
            # Caller didn't inject one; build a default namespaced
            # FAISS for the given collection_name. This path is only
            # used by tests / legacy callers — production code should
            # pass ``vector_store`` explicitly via ``get_retrieval_pipeline``.
            from lumen_tools.vector_store import FAISSVectorStore
            vector_store = FAISSVectorStore(collection_name=collection_name)
        self.vector_store = vector_store

        # BM25 index
        from lumen_services.retrieval.bm25_index import BM25Index
        self.bm25_index = BM25Index(
            persist_path=_bm25_path_for(collection_name),
            use_jieba=use_jieba,
        )

        # Hybrid retriever
        from lumen_services.retrieval.hybrid_retriever import HybridRetriever
        self.hybrid_retriever = HybridRetriever(
            vector_store=vector_store,
            bm25_index=self.bm25_index,
            vector_weight=self.vector_weight,
            bm25_weight=self.bm25_weight,
        )

        # Reranker
        from lumen_services.retrieval.reranker import get_reranker
        self.reranker = get_reranker(
            enabled=self.rerank_enabled,
            preferred=self.rerank_type,
            model=self.rerank_model,
        )

    # ---------------------------------------------------------- write paths

    def add_documents(
        self,
        texts: List[str],
        metadatas: List[Dict[str, Any]],
        ids: Optional[List[str]] = None,
    ) -> List[str]:
        """Add documents to both the vector store and the BM25 index.

        The returned ids are the ones used in the BM25 index, which mirrors
        whatever ids the vector store assigns to the documents.
        """
        # 1) Add to vector store; capture the ids it returns
        vector_ids: List[str] = []
        if self.vector_store is not None:
            try:
                vector_ids = self.vector_store.add_texts(
                    texts=texts, metadatas=metadatas, ids=ids
                )
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("Vector store add_texts failed: %s", exc)
                vector_ids = []

        # 2) Add to BM25 index. If the vector store didn't return ids, use
        # the caller's ids or generate sequential ones.
        if not vector_ids:
            if ids is not None:
                bm25_ids = list(ids)
            else:
                start = self.bm25_index.size
                bm25_ids = [str(start + i) for i in range(len(texts))]
        else:
            bm25_ids = [str(v) for v in vector_ids]

        from lumen_services.retrieval.bm25_index import BM25Index  # local alias
        # Reuse the add_texts implementation
        self.bm25_index.add_texts(
            texts=texts, metadatas=metadatas, ids=bm25_ids
        )

        # Persist BM25
        try:
            self.bm25_index.save()
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("Failed to persist BM25 index: %s", exc)

        return bm25_ids

    def remove_documents(self, ids: List[str]) -> int:
        """Remove documents from BM25 (the vector store may not support delete)."""
        return self.bm25_index.remove_by_ids(ids)

    def rebuild_bm25(self) -> None:
        """Force a rebuild of the BM25 index from the current corpus."""
        self.bm25_index._rebuild_index()

    # ----------------------------------------------------------- search path

    def search(
        self,
        query: str,
        k: int = 5,
        filter_expr: Optional[str] = None,
        rerank: Optional[bool] = None,
        *,
        search_weights: Optional[Dict[str, float]] = None,
    ) -> List[Dict[str, Any]]:
        """Run the full pipeline: vector + BM25 -> RRF -> rerank -> top-k.

        Args:
            query: the user query
            k: number of final results to return
            filter_expr: optional filter expression (``tenant_id == X and kb_id == Y``)
            rerank: override the configured ``RERANK_ENABLED`` flag
            search_weights: optional per-request override of the KB's
                ``search_weights`` (multi_match field boosts). Only honoured
                when the underlying ``vector_store`` is an
                :class:`ElasticsearchVectorStore` — the only store that
                implements ``hybrid_search`` with field boosting. For
                FAISS-backed pipelines this kwarg is silently ignored
                (FAISS has no multi_match / field^N concept).
        """
        # Phase 1 Group B 4.4 Day 3 (2026-09-05): retrieval.search OTel span。
        # 关键 attribute:doc_count / top_score / kb_id(从 collection_name 派生)
        # / backend(FAISS / ES)。filter_expr 不解析(避免误把 tenant_id 暴露)、
        # 只记长度作为 search-complexity 信号。
        from opentelemetry import trace as _otel_trace

        _kb_id: Optional[int] = None
        # collection_name 形如 "kb_55_mc_3" — 抽 KB id
        if self.collection_name.startswith("kb_"):
            try:
                _kb_id = int(self.collection_name.split("_")[1])
            except (ValueError, IndexError):
                _kb_id = None

        _backend = "elasticsearch" if (
            _ES_STORE_TYPE is not None
            and isinstance(self.vector_store, _ES_STORE_TYPE)
        ) else "faiss"

        _search_span = _otel_trace.get_tracer("lumen.manual").start_span(
            "retrieval.search",
            attributes={
                "retrieval.kb_id": _kb_id if _kb_id is not None else -1,
                "retrieval.collection_name": self.collection_name,
                "retrieval.backend": _backend,
                "retrieval.k": k,
                "retrieval.query_chars": len(query or ""),
                "retrieval.has_filter": bool(filter_expr),
                "retrieval.filter_chars": len(filter_expr or ""),
                "retrieval.rerank_enabled": bool(
                    self.rerank_enabled if rerank is None else rerank
                ),
            },
        )
        _search_t0 = time.monotonic()
        try:
            if not query or not query.strip():
                try:
                    _search_span.set_attribute("retrieval.doc_count", 0)
                    _search_span.set_attribute("retrieval.top_score", 0.0)
                    _search_span.set_attribute("retrieval.duration_ms", 0)
                except Exception:  # noqa: BLE001
                    pass
                return []
            return self._search_impl(
                query=query,
                k=k,
                filter_expr=filter_expr,
                rerank=rerank,
                search_weights=search_weights,
                _search_span=_search_span,
                _search_t0=_search_t0,
            )
        except Exception as e:
            try:
                from opentelemetry.trace import Status, StatusCode
                _search_span.record_exception(e)
                _search_span.set_status(Status(StatusCode.ERROR, str(e)[:200]))
                _search_span.set_attribute(
                    "retrieval.duration_ms",
                    int((time.monotonic() - _search_t0) * 1000),
                )
            except Exception:  # noqa: BLE001
                pass
            raise
        finally:
            try:
                _search_span.end()
            except Exception:  # noqa: BLE001
                pass

    def _search_impl(
        self,
        query: str,
        k: int,
        filter_expr: Optional[str],
        rerank: Optional[bool],
        search_weights: Optional[Dict[str, float]],
        *,
        _search_span: Any,
        _search_t0: float,
    ) -> List[Dict[str, Any]]:
        """内部 search 实现,被外层 retrieval.search span 包。"""

        use_rerank = self.rerank_enabled if rerank is None else bool(rerank)

        # Decide how many candidates to fetch from hybrid before rerank
        if use_rerank and getattr(self.reranker, "is_available", True):
            fetch_k = max(self.rerank_top_n, k)
        else:
            fetch_k = k

        # Sanitise per-request override: drop non-dict types so a malformed
        # caller value (e.g. accidental string from a Form param) cannot
        # poison the dispatch.
        resolved_weights: Optional[Dict[str, float]]
        if search_weights is None or isinstance(search_weights, dict):
            resolved_weights = search_weights
        else:
            logger.warning(
                "search_weights must be a dict, got %s — ignoring",
                type(search_weights).__name__,
            )
            resolved_weights = None

        # ES vs FAISS dispatch: only ES supports field-boosted hybrid search.
        # FAISS keeps the original path (HybridRetriever is the only fusion).
        if _ES_STORE_TYPE is not None and isinstance(self.vector_store, _ES_STORE_TYPE):
            if not getattr(self.vector_store, "is_connected", False):
                # ES is unreachable; degrade gracefully to the BM25 + KNN
                # hybrid path rather than returning [].
                logger.warning(
                    "Elasticsearch disconnected at search; "
                    "falling back to HybridRetriever for collection %r",
                    self.collection_name,
                )
                results = self.hybrid_retriever.search(
                    query=query, k=fetch_k, filter_expr=filter_expr,
                )
            else:
                # Honour the legacy ``alpha`` parameter (vector vs BM25
                # relative weight) by passing it as ``alpha`` to
                # ``hybrid_search``; field^N boosts are layered on top.
                results = self.vector_store.hybrid_search(
                    query=query,
                    k=fetch_k,
                    alpha=self.hybrid_retriever.vector_weight,
                    filter_expr=filter_expr,
                    field_weights=resolved_weights,
                )
        else:
            # FAISS path (or any non-ES backend): unchanged.
            # `search_weights` is intentionally a no-op here.
            results = self.hybrid_retriever.search(
                query=query,
                k=fetch_k,
                filter_expr=filter_expr,
            )

        # If reranking is requested and the reranker is available, apply it.
        # This stage is shared by both ES and FAISS backends — the reranker
        # only sees post-fusion results, not the raw ES scores.
        if use_rerank and getattr(self.reranker, "is_available", True) and results:
            try:
                results = self.reranker.rerank(query, results, top_k=k)
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("Reranking failed, returning hybrid results: %s", exc)
                results = results[:k]
        else:
            results = results[:k]

        # Phase 1 Group B 4.4 Day 3 (2026-09-05): 写 retrieval.search span
        # 的关键 attribute:doc_count / top_score / duration_ms。
        try:
            _search_span.set_attribute("retrieval.doc_count", len(results))
            # top_score:results 里 dict 可能含 "score" / "_score" / "rerank_score"
            # 等多种 key;取 max 数值,没结果就 0。
            top_score = 0.0
            for r in results:
                for k_score in ("score", "_score", "rerank_score", "rrf_score"):
                    v = r.get(k_score) if isinstance(r, dict) else None
                    if isinstance(v, (int, float)):
                        top_score = max(top_score, float(v))
                        break
            _search_span.set_attribute("retrieval.top_score", top_score)
            _search_span.set_attribute(
                "retrieval.duration_ms",
                int((time.monotonic() - _search_t0) * 1000),
            )
        except Exception:  # noqa: BLE001
            logger.debug("retrieval.search span attr write failed; ignored", exc_info=True)

        return results

    # ----------------------------------------------------------------- meta

    def describe(self) -> Dict[str, Any]:
        """Return a small dict describing the pipeline configuration."""
        is_es = bool(
            _ES_STORE_TYPE is not None and isinstance(self.vector_store, _ES_STORE_TYPE)
        )
        return {
            "collection_name": self.collection_name,
            "vector_store": type(self.vector_store).__name__ if self.vector_store else None,
            "bm25_available": getattr(self.bm25_index, "is_available", False),
            "bm25_size": getattr(self.bm25_index, "size", 0),
            "vector_weight": self.vector_weight,
            "bm25_weight": self.bm25_weight,
            "rerank_enabled": self.rerank_enabled,
            "rerank_type": self.rerank_type,
            "rerank_model": self.rerank_model,
            "rerank_top_n": self.rerank_top_n,
            "reranker": getattr(self.reranker, "name", None),
            # M28: only ES-backed stores can honour KB ``search_weights``
            # (the 4 multi_match field boosts from the KB UI). FAISS
            # silently ignores the slider values.
            "search_weights_supported": is_es,
        }


_pipeline_lock = threading.Lock()
_pipelines: Dict[int, RetrievalPipeline] = {}


def get_retrieval_pipeline(
    kb_id: int,
    model_config_id: int,
    db,
) -> RetrievalPipeline:
    """Return a cached :class:`RetrievalPipeline` for the given KB.

    The pipeline is keyed by ``kb_id`` (NOT ``model_config_id``): the
    spec locks the embedding model on a KB, so there's exactly one
    pipeline per KB. The embedder is supplied by the factory and
    pulled from its per-config cache.
    """
    from lumen_tools.vector_store_factory import VectorStoreFactory  # type: ignore

    if kb_id in _pipelines:
        return _pipelines[kb_id]
    with _pipeline_lock:
        if kb_id not in _pipelines:
            vector_store = VectorStoreFactory.get_store(
                kb_id=kb_id,
                model_config_id=model_config_id,
                db=db,
            )
            _pipelines[kb_id] = RetrievalPipeline(
                collection_name=f"kb_{kb_id}_mc_{model_config_id}",
                vector_store=vector_store,
            )
        return _pipelines[kb_id]
