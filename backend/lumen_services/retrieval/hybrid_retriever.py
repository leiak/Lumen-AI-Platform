"""
Hybrid retriever combining dense (vector) and sparse (BM25) retrieval.

The combiner uses Reciprocal Rank Fusion (RRF) by default, which is simple,
robust, and avoids the need to normalise BM25 and vector scores. Weights are
exposed so callers can dial the balance between lexical and semantic match.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)


# Default RRF constant (k) - see Cormack et al. 2009
DEFAULT_RRF_K = 60


def _normalise_filter(filter_expr: Optional[str]) -> Tuple[Optional[int], Optional[int]]:
    """Parse the ``tenant_id == X and kb_id == Y`` filter expression."""
    if not filter_expr:
        return None, None
    tenant_id: Optional[int] = None
    kb_id: Optional[int] = None
    tenant_match = re.search(r"tenant_id\s*==\s*(\d+)", filter_expr)
    kb_match = re.search(r"kb_id\s*==\s*(\d+)", filter_expr)
    if tenant_match:
        tenant_id = int(tenant_match.group(1))
    if kb_match:
        kb_id = int(kb_match.group(1))
    return tenant_id, kb_id


def _passes_filter(meta: Dict[str, Any], tenant_id: Optional[int], kb_id: Optional[int]) -> bool:
    if tenant_id is not None and meta.get("tenant_id") != tenant_id:
        return False
    if kb_id is not None and meta.get("kb_id") != kb_id:
        return False
    return True


class HybridRetriever:
    """Combine a vector store and a :class:`BM25Index` using RRF.

    Both inputs are pluggable. The vector store is expected to expose a
    ``similarity_search(query, k, filter_expr)`` method returning
    ``[{"id": ..., "text": ..., "distance": ..., "metadata": ...}, ...]``;
    this is the contract used by the project's existing FAISS/ES vector stores.
    """

    def __init__(
        self,
        vector_store: Any,
        bm25_index: Any,
        vector_weight: float = 0.5,
        bm25_weight: float = 0.5,
        rrf_k: int = DEFAULT_RRF_K,
    ) -> None:
        self.vector_store = vector_store
        self.bm25_index = bm25_index
        self.vector_weight = float(vector_weight)
        self.bm25_weight = float(bm25_weight)
        self.rrf_k = int(rrf_k)

    # ----------------------------------------------------------------- search

    def _vector_search(self, query: str, k: int, filter_expr: Optional[str]) -> List[Dict[str, Any]]:
        if self.vector_store is None:
            return []
        try:
            results = self.vector_store.similarity_search(query, k=k, filter_expr=filter_expr)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Vector search failed: %s", exc)
            return []
        if not results:
            return []
        # Normalise the result shape to a dict.
        normalised: List[Dict[str, Any]] = []
        for r in results:
            if isinstance(r, dict):
                normalised.append({
                    "id": str(r.get("id", "")),
                    "text": r.get("text", ""),
                    "metadata": r.get("metadata", {}) or {},
                    "distance": r.get("distance"),
                })
            else:  # pragma: no cover - defensive
                normalised.append({
                    "id": str(getattr(r, "id", "")),
                    "text": getattr(r, "text", ""),
                    "metadata": getattr(r, "metadata", {}) or {},
                    "distance": getattr(r, "distance", None),
                })
        return normalised

    def _bm25_search(
        self,
        query: str,
        k: int,
        tenant_id: Optional[int],
        kb_id: Optional[int],
    ) -> List[Dict[str, Any]]:
        if self.bm25_index is None or not getattr(self.bm25_index, "is_available", False):
            return []
        try:
            raw = self.bm25_index.search(query, k=k)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("BM25 search failed: %s", exc)
            return []
        results: List[Dict[str, Any]] = []
        for doc_id, score, meta in raw:
            if not _passes_filter(meta, tenant_id, kb_id):
                continue
            results.append({
                "id": str(doc_id),
                "text": self.bm25_index.get_text(doc_id) or "",
                "metadata": meta,
                "bm25_score": float(score),
            })
        return results

    def search(
        self,
        query: str,
        k: int = 5,
        filter_expr: Optional[str] = None,
        candidate_multiplier: int = 3,
    ) -> List[Dict[str, Any]]:
        """Run hybrid search and return up to ``k`` results.

        ``candidate_multiplier`` controls how many candidates are requested
        from each retriever before RRF fusion (we ask for ``k * multiplier``
        from each side).
        """
        if not query or not query.strip():
            return []

        fetch_k = max(k * candidate_multiplier, k)
        tenant_id, kb_id = _normalise_filter(filter_expr)

        vector_results = self._vector_search(query, fetch_k, filter_expr)
        bm25_results = self._bm25_search(query, fetch_k, tenant_id, kb_id)

        # If only one side returned, just return that side (truncated to k).
        if not vector_results and not bm25_results:
            return []
        if not vector_results:
            return bm25_results[:k]
        if not bm25_results:
            return vector_results[:k]

        # RRF fusion
        vector_doc_ids = {r["id"] for r in vector_results}
        bm25_doc_ids = {r["id"] for r in bm25_results}
        all_ids = vector_doc_ids | bm25_doc_ids

        vector_by_id = {r["id"]: r for r in vector_results}
        bm25_by_id = {r["id"]: r for r in bm25_results}

        # Build rank maps (1-based)
        vector_rank = {
            r["id"]: rank for rank, r in enumerate(vector_results, start=1)
        }
        bm25_rank = {
            r["id"]: rank for rank, r in enumerate(bm25_results, start=1)
        }

        fused_scores: Dict[str, float] = {}
        for doc_id in all_ids:
            score = 0.0
            if doc_id in vector_rank:
                score += self.vector_weight * (
                    1.0 / (self.rrf_k + vector_rank[doc_id])
                )
            if doc_id in bm25_rank:
                score += self.bm25_weight * (
                    1.0 / (self.rrf_k + bm25_rank[doc_id])
                )
            fused_scores[doc_id] = score

        ranked = sorted(
            fused_scores.items(),
            key=lambda x: (-x[1], x[0]),
        )[:k]

        # Build the final result objects; prefer vector-store content when
        # available (it includes the embedding distance) and enrich with
        # the BM25 text/metadata if the vector store didn't have it.
        results: List[Dict[str, Any]] = []
        for doc_id, score in ranked:
            v = vector_by_id.get(doc_id)
            b = bm25_by_id.get(doc_id)
            if v is not None:
                result = dict(v)
            elif b is not None:
                result = {
                    "id": doc_id,
                    "text": b.get("text", ""),
                    "metadata": b.get("metadata", {}) or {},
                    "distance": None,
                }
            else:  # pragma: no cover - defensive
                continue
            result["rrf_score"] = float(score)
            if b is not None:
                result["bm25_score"] = b.get("bm25_score")
            results.append(result)
        return results
