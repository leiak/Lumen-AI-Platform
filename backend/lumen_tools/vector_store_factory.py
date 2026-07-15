import logging
from typing import Optional

from sqlalchemy.orm import Session

from lumen_tools.vector_store_base import VectorStoreBase
from lumen_tools.vector_store import FAISSVectorStore

logger = logging.getLogger(__name__)


class VectorStoreFactory:
    """Factory for creating vector store instances.

    Priority:
    1. Elasticsearch (if ES_ENABLED=True and ES is available)
    2. FAISS (fallback)

    The factory now takes a (kb_id, model_config_id) pair instead of a
    free-form ``collection_name``: the persisted collection is namespaced
    as ``kb_{kb_id}_mc_{model_config_id}`` so changing the embedding
    model on a KB never collides with the prior index, and the embedder
    is pulled from the per-config cache (no more hardcoded
    ``nomic-embed-text``).
    """

    _es_store_class: Optional[type] = None
    _es_config: Optional[dict] = None

    @classmethod
    def _get_es_store(cls):
        """Lazily load ES store class and check availability."""
        if cls._es_store_class is None:
            try:
                from lumen_tools.es_vector_store import ElasticsearchVectorStore
                cls._es_store_class = ElasticsearchVectorStore
            except ImportError:
                logger.warning("ElasticsearchVectorStore not available")
                cls._es_store_class = None
        return cls._es_store_class

    @classmethod
    def _check_es_available(cls, host: str, port: int) -> bool:
        """Check if ES is actually reachable."""
        try:
            from elasticsearch import Elasticsearch
            client = Elasticsearch(
                hosts=[{"host": host, "port": port, "scheme": "http"}],
                request_timeout=5,
            )
            return client.ping()
        except Exception:
            return False

    @classmethod
    def get_store(
        cls,
        kb_id: int,
        model_config_id: int,
        db: Session,
    ) -> VectorStoreBase:
        """Get a vector store instance for the (KB, model_config) pair.

        Args:
            kb_id: Knowledge base id.
            model_config_id: Embedding ModelConfig id. The factory
                pulls the matching embedder + dim via
                ``embedding_factory.get_embeddings_for_config``.
            db: SQLAlchemy session.

        Returns:
            VectorStoreBase implementation (ES or FAISS) configured with
            the right embedder and persisted under
            ``{collection_name=kb_{kb_id}_mc_{model_config_id}}``.
        """
        from lumen_core.config import settings
        from lumen_services.embedding_factory import get_embeddings_for_config

        collection_name = f"kb_{kb_id}_mc_{model_config_id}"
        embeddings, dim = get_embeddings_for_config(model_config_id, db)

        es_enabled = getattr(settings, "ES_ENABLED", False)
        es_host = getattr(settings, "ES_HOST", "localhost")
        es_port = getattr(settings, "ES_PORT", 9200)
        es_index_prefix = getattr(settings, "ES_INDEX_PREFIX", "knowledge")

        if es_enabled:
            es_class = cls._get_es_store()
            if es_class and cls._check_es_available(es_host, es_port):
                logger.info(
                    f"Using Elasticsearch vector store for '{collection_name}'"
                )
                return es_class(
                    collection_name=collection_name,
                    host=es_host,
                    port=es_port,
                    index_prefix=es_index_prefix,
                    embeddings=embeddings,
                    embedding_dim=dim,
                )
            elif es_enabled:
                logger.warning(
                    f"ES_ENABLED=True but Elasticsearch not available at "
                    f"{es_host}:{es_port}. Falling back to FAISS."
                )

        # Fallback to FAISS
        logger.info(f"Using FAISS vector store for '{collection_name}'")
        return FAISSVectorStore(
            collection_name=collection_name,
            embeddings=embeddings,
            embedding_dim=dim,
        )
