import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

try:
    from jina import JinaReranker
    JINA_AVAILABLE = True
except ImportError:
    JINA_AVAILABLE = False


class RerankerService:
    """Reranking service using Jina Reranker."""

    def __init__(self, model: str = "jina-reranker-v2-base-multilingual"):
        self.model = model
        self._client: Optional[JinaReranker] = None

        if JINA_AVAILABLE:
            try:
                self._client = JinaReranker(model=model)
            except Exception as e:
                logger.warning(f"Failed to initialize JinaReranker: {e}")

    @property
    def is_available(self) -> bool:
        return self._client is not None

    def rerank(
        self,
        query: str,
        documents: List[Dict[str, Any]],
        top_k: int = 10
    ) -> List[Dict[str, Any]]:
        """Rerank documents based on query.

        Args:
            query: Search query
            documents: List of dicts with 'text' key
            top_k: Number of results to return after reranking

        Returns:
            Reranked list of documents with 'text', 'metadata', 'relevance_score'
        """
        if not self.is_available:
            logger.warning("Reranker not available, returning original order")
            return documents[:top_k]

        if not documents:
            return []

        try:
            # Extract texts for reranking
            texts = [doc.get("text", "") for doc in documents]

            # Perform reranking
            results = self._client.rank(
                query=query,
                documents=texts,
                top_n=top_k
            )

            # Map back to original documents with scores
            reranked = []
            for result in results:
                idx = result.index
                reranked.append({
                    **documents[idx],
                    "relevance_score": result.relevance_score
                })

            return reranked
        except Exception as e:
            logger.error(f"Reranking failed: {e}")
            return documents[:top_k]
