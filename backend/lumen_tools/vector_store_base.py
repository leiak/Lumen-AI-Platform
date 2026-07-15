from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)


class VectorStoreBase(ABC):
    """Abstract base class for vector stores."""

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """Check if the vector store is connected/available."""
        pass

    @abstractmethod
    def create_index(self) -> bool:
        """Create the index if it doesn't exist. Returns True on success."""
        pass

    @abstractmethod
    def add_texts(
        self,
        texts: List[str],
        metadatas: List[Dict[str, Any]],
        ids: Optional[List[str]] = None
    ) -> List[str]:
        """Add texts to the vector store. Returns list of document IDs."""
        pass

    @abstractmethod
    def similarity_search(
        self,
        query: str,
        k: int = 5,
        filter_expr: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Perform similarity search. Returns list of result dicts with text, metadata, distance."""
        pass

    @abstractmethod
    def hybrid_search(
        self,
        query: str,
        k: int = 5,
        alpha: float = 0.5,
        filter_expr: Optional[str] = None,
        field_weights: Optional[Dict[str, float]] = None
    ) -> List[Dict[str, Any]]:
        """Perform hybrid search combining vector and full-text search.

        Args:
            query: Search query
            k: Number of results to return
            alpha: Weight for vector search (0-1), full-text gets (1-alpha)
            filter_expr: Optional filter expression
            field_weights: Optional field boosts for full-text
                e.g. {"title": 10.0, "important_kw": 30.0, "text": 2.0}

        Returns:
            List of result dicts with text, metadata, distance.
        """
        pass

    @abstractmethod
    def delete_by_ids(self, ids: List[str]) -> bool:
        """Delete documents by IDs. Returns True on success."""
        pass

    def rerank_search(
        self,
        query: str,
        k: int = 10,
        alpha: float = 0.5,
        filter_expr: Optional[str] = None,
        rerank: bool = True,
        rerank_top_n: int = 10,
        field_weights: Optional[Dict[str, float]] = None
    ) -> List[Dict[str, Any]]:
        """Search with optional reranking.

        Default implementation: call hybrid_search then rerank if enabled.
        Subclasses can override to implement more efficient approaches.
        """
        # Get search results (use more k for reranking)
        results = self.hybrid_search(
            query, k=rerank_top_n * 3, alpha=alpha,
            filter_expr=filter_expr, field_weights=field_weights
        )

        if not rerank or not results:
            return results[:k]

        # Rerank
        try:
            from lumen_tools.rerank import RerankerService
            reranker = RerankerService()
            if reranker.is_available:
                return reranker.rerank(query, results, top_k=rerank_top_n)
        except Exception as e:
            logger.warning(f"Reranking failed: {e}")

        return results[:k]
