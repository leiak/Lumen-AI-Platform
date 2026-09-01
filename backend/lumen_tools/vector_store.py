from typing import List, Dict, Any, Optional
import os
import pickle
import re
import logging

from lumen_core.config import settings
from lumen_tools.vector_store_base import VectorStoreBase

logger = logging.getLogger(__name__)

try:
    import faiss
    import numpy as np
    FAISS_AVAILABLE = True
except ImportError:
    FAISS_AVAILABLE = False

try:
    from rank_bm25 import BM25Okapi
    BM25_AVAILABLE = True
except ImportError:
    BM25_AVAILABLE = False


class FAISSVectorStore(VectorStoreBase):
    def __init__(
        self,
        collection_name: str = "knowledge_base",
        embeddings=None,
        embedding_dim: int = 768,
        persist_dir: str = "./data/faiss",
    ):
        """Initialize the FAISS index.

        Args:
            collection_name: Per-(kb_id, model_config_id) identifier that
                namespaces the persisted index file.
            embeddings: A ready-built LangChain ``Embeddings`` instance
                (typically from ``embedding_factory.get_embeddings_for_config``).
                If None, falls back to a default OllamaEmbeddings using
                ``settings.OLLAMA_API_BASE`` — the legacy path, kept so
                existing test fixtures / data still work.
            embedding_dim: Dimension of the embedding vectors. MUST match
                what the embedder actually produces. The factory probes
                the embedder to discover this dynamically.
            persist_dir: Root directory for persisted indexes. Each
                ``collection_name`` gets its own ``.index`` + ``.meta``
                file inside this directory.
        """
        self.collection_name = collection_name
        self.embeddings = embeddings
        self._requested_dim = embedding_dim
        self.index = None
        self._connected = False
        self.metadata_store = {}  # Store text and metadata separately
        self._next_id = 0
        self._persist_path = os.path.join(persist_dir, collection_name)
        self._bm25_index = None
        self._bm25_corpus = []
        self._id_list = []  # Track doc_id at each corpus index to map to FAISS indices

        if FAISS_AVAILABLE:
            try:
                if self.embeddings is None:
                    # Legacy fallback: keep the old hardcoded Ollama
                    # embedder so unit tests and the /data path that
                    # pre-date the factory still work.
                    from langchain_ollama import OllamaEmbeddings
                    self.embeddings = OllamaEmbeddings(
                        model="nomic-embed-text",
                        base_url=settings.OLLAMA_API_BASE,
                    )

                # Create persist directory
                os.makedirs(os.path.dirname(self._persist_path) or ".", exist_ok=True)

                # Load existing index or create new one
                index_path = f"{self._persist_path}.index"
                meta_path = f"{self._persist_path}.meta"

                if os.path.exists(index_path):
                    self.index = faiss.read_index(index_path)
                    with open(meta_path, 'rb') as f:
                        data = pickle.load(f)
                        self.metadata_store = data.get('metadata', {})
                        self._next_id = data.get('next_id', 0)
                        self._id_list = data.get('id_list', [])
                else:
                    # New index — use the requested dim, NOT a hardcoded 768.
                    self.index = faiss.IndexFlatL2(self._requested_dim)

                self._connected = True
                if BM25_AVAILABLE:
                    self._init_bm25()
            except Exception as e:
                logger.warning(f"Could not initialize FAISS: {e}")
                self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    def create_index(self) -> bool:
        """FAISS creates index automatically on first add. This is a no-op."""
        return self._connected

    def _save(self):
        if self._connected and self.index:
            index_path = f"{self._persist_path}.index"
            meta_path = f"{self._persist_path}.meta"
            faiss.write_index(self.index, index_path)
            with open(meta_path, 'wb') as f:
                pickle.dump({
                    'metadata': self.metadata_store,
                    'next_id': self._next_id,
                    'id_list': self._id_list
                }, f)

    def _init_bm25(self):
        """Initialize BM25 index from stored texts using insertion order tracking"""
        if self.metadata_store and self._id_list:
            # Use _id_list to maintain proper mapping between corpus index and doc_id
            self._bm25_corpus = [self.metadata_store[doc_id].get('text', '') for doc_id in self._id_list if doc_id in self.metadata_store]
            if self._bm25_corpus:
                tokenized_corpus = [doc.split() for doc in self._bm25_corpus]
                self._bm25_index = BM25Okapi(tokenized_corpus)

    def add_texts(
        self, texts: List[str], metadatas: List[Dict[str, Any]], ids: Optional[List[str]] = None
    ) -> List[str]:
        if not self._connected:
            return [f"mock_{i}" for i in range(len(texts))]

        result_ids = []
        for i, text in enumerate(texts):
            if ids is None:
                chunk_id = str(self._next_id)
                self._next_id += 1
            else:
                chunk_id = ids[i]

            # Get embedding
            vector = self.embeddings.embed_query(text)
            vector_np = np.array([vector]).astype('float32')

            # Add to index
            self.index.add(vector_np)

            # Store metadata
            self.metadata_store[chunk_id] = {
                'text': text,
                'metadata': metadatas[i]
            }
            result_ids.append(chunk_id)
            self._id_list.append(chunk_id)

            # Also add to BM25 corpus (rebuilt lazily via _init_bm25)
            self._bm25_corpus.append(text)

        # Rebuild BM25 if needed
        if self._bm25_index is not None and len(self._bm25_corpus) > 100:
            self._init_bm25()

        self._save()
        return result_ids

    def similarity_search(
        self, query: str, k: int = 5, filter_expr: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        if not self._connected:
            return []

        # Get query embedding
        query_vector = self.embeddings.embed_query(query)
        query_np = np.array([query_vector]).astype('float32')

        # Search - fetch more than k to account for filtering
        k_search = min(k * 3, self.index.ntotal) if self.index else 0
        if k_search == 0:
            return []

        distances, indices = self.index.search(query_np, k_search)

        results = []
        for dist, idx in zip(distances[0], indices[0]):
            if idx >= 0 and str(idx) in self.metadata_store:
                data = self.metadata_store[str(idx)]
                result = {
                    "id": str(idx),
                    "text": data['text'],
                    "distance": float(dist),
                    "metadata": data['metadata']
                }

                # Apply client-side filtering if filter_expr is provided
                # filter_expr format: "tenant_id == X and kb_id == Y and modality == 'image'"
                if filter_expr:
                    meta = data['metadata']
                    # Parse tenant_id from filter_expr
                    tenant_match = re.search(r'tenant_id\s*==\s*(\d+)', filter_expr)
                    kb_match = re.search(r'kb_id\s*==\s*(\d+)', filter_expr)
                    # M38.4: modality is a quoted string ('image' | "image").
                    # Match either quote style so callers can write naturally.
                    modality_match = re.search(r"""modality\s*==\s*['"]([^'"]+)['"]""", filter_expr)

                    tenant_ok = True
                    kb_ok = True
                    modality_ok = True

                    if tenant_match:
                        tenant_ok = meta.get('tenant_id') == int(tenant_match.group(1))
                    if kb_match:
                        kb_ok = meta.get('kb_id') == int(kb_match.group(1))
                    if modality_match:
                        # Default missing 'modality' to 'text' (legacy chunks).
                        meta_modality = meta.get('modality', 'text')
                        modality_ok = meta_modality == modality_match.group(1)

                    if tenant_ok and kb_ok and modality_ok:
                        results.append(result)
                else:
                    results.append(result)

        return results[:k]

    def hybrid_search(
        self,
        query: str,
        k: int = 5,
        alpha: float = 0.5,
        filter_expr: str = None,
        field_weights: dict = None  # Ignored for FAISS
    ) -> list:
        """
        Hybrid search combining vector and BM25 scores.

        Args:
            query: Search query
            k: Number of results to return
            alpha: Weight for vector search (0-1), BM25 gets (1-alpha)
            filter_expr: Optional filter expression
            field_weights: Ignored for FAISS (for API compatibility)
        """
        if not self._connected:
            return []

        # Get vector search results
        vector_results = self.similarity_search(query, k=k * 3, filter_expr=filter_expr)

        if not vector_results:
            return []

        # BM25 search
        if BM25_AVAILABLE and self._bm25_index and self._bm25_corpus:
            query_tokens = query.split()
            bm25_scores = self._bm25_index.get_scores(query_tokens)

            # Create a map of all docs
            all_docs = {r['id']: r for r in vector_results}

            # RRF (Reciprocal Rank Fusion) combination
            rrf_scores = {}

            # Add vector scores (using rank)
            for rank, r in enumerate(vector_results):
                doc_id = r['id']
                vector_score = 1.0 / (60 + rank)  # RRF formula
                rrf_scores[doc_id] = rrf_scores.get(doc_id, 0) + alpha * vector_score

            # Add BM25 scores (using rank within top results)
            sorted_bm25_indices = sorted(range(len(bm25_scores)), key=lambda i: bm25_scores[i], reverse=True)

            # Only consider docs in our vector results for fair comparison
            vector_doc_ids = set(r['id'] for r in vector_results)
            for rank, idx in enumerate(sorted_bm25_indices):
                if idx < len(self._id_list):
                    # Map corpus index to doc_id via _id_list (handles FAISS index alignment)
                    doc_id = self._id_list[idx]
                    if doc_id in vector_doc_ids:
                        bm25_score = 1.0 / (60 + rank)
                        rrf_scores[doc_id] = rrf_scores.get(doc_id, 0) + (1 - alpha) * bm25_score

            # Re-rank by combined scores
            sorted_results = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)[:k]

            return [all_docs[doc_id] for doc_id, score in sorted_results if doc_id in all_docs]

        # Fallback: just return vector results
        return vector_results[:k]

    def delete_by_ids(self, ids: List[str]) -> bool:
        raise NotImplementedError("FAISS does not support efficient deletion. Use a different vector DB for production.")


# Alias for backward compatibility
MilvusVectorStore = FAISSVectorStore
VectorStore = FAISSVectorStore
