import logging
import re
from typing import List, Dict, Any, Optional

from lumen_core.config import settings
from lumen_tools.vector_store_base import VectorStoreBase

logger = logging.getLogger(__name__)

try:
    from elasticsearch import Elasticsearch, helpers
    ES_AVAILABLE = True
except ImportError:
    ES_AVAILABLE = False


class ElasticsearchVectorStore(VectorStoreBase):
    """Elasticsearch implementation of vector store with hybrid search."""

    def __init__(
        self,
        collection_name: str = "knowledge_base",
        host: str = "localhost",
        port: int = 9200,
        index_prefix: str = "knowledge",
        field_weights: Optional[Dict[str, float]] = None,
        embeddings=None,
        embedding_dim: int = 768,
    ):
        self.collection_name = collection_name
        self.host = host
        self.port = port
        self.index_prefix = index_prefix
        self.index_name = f"{index_prefix}_{collection_name}"
        self._client: Optional[Elasticsearch] = None
        self._connected = False
        # Injected embedder from the factory; if None, the per-method
        # _get_embedding falls back to the legacy hardcoded Ollama path
        # (kept so unit tests / non-factory call sites still work).
        self.embeddings = embeddings

        # Field weights for hybrid search (field name -> boost factor)
        # Default: title=10, important_kw=30, question_kw=20, text=2
        self.field_weights = field_weights or {
            "title": 10.0,
            "important_kw": 30.0,
            "question_kw": 20.0,
            "text": 2.0
        }

        # Embedding dimension — supplied by the factory, NOT hardcoded.
        self.embedding_dim = embedding_dim

        if ES_AVAILABLE:
            self._connect()

    def _connect(self):
        """Connect to Elasticsearch."""
        try:
            self._client = Elasticsearch(
                hosts=[{"host": self.host, "port": self.port, "scheme": "http"}],
                request_timeout=30,
            )
            # Check connection
            if self._client.ping():
                self._connected = True
                logger.info(f"Connected to Elasticsearch at {self.host}:{self.port}")
            else:
                logger.warning("Elasticsearch ping failed")
                self._connected = False
        except Exception as e:
            logger.warning(f"Failed to connect to Elasticsearch: {e}")
            self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected and self._client is not None

    def create_index(self) -> bool:
        """Create the index with KNN mapping if it doesn't exist."""
        if not self.is_connected:
            return False

        try:
            if self._client.indices.exists(index=self.index_name):
                return True

            mapping = {
                "settings": {
                    "number_of_shards": 1,
                    "number_of_replicas": 0,
                    "analysis": {
                        "analyzer": {
                            "default": {
                                "type": "standard"
                            }
                        }
                    }
                },
                "mappings": {
                    "properties": {
                        "text": {"type": "text"},
                        "title": {"type": "text"},
                        "important_kw": {"type": "text"},
                        "question_kw": {"type": "text"},
                        "text_vec": {
                            "type": "dense_vector",
                            "dims": self.embedding_dim,
                            "index": True,
                            "similarity": "cosine"
                        },
                        "tenant_id": {"type": "integer", "index": True},
                        "kb_id": {"type": "integer", "index": True},
                        "document_id": {"type": "integer", "index": True},
                        "chunk_id": {"type": "integer", "index": True},
                        # M38.4: modality 字段 — keyword type 让 ES
                        # ``term`` query 直接命中("image" / "text")。
                        # 旧索引没这个字段时 ES term query 会返 0 hits
                        # —— 这是正确的语义:modality filter 不应该
                        # 把 pre-M38.4 chunks 拉进来。
                        "modality": {"type": "keyword", "index": True},
                        "metadata": {"type": "object", "enabled": True}
                    }
                }
            }

            self._client.indices.create(index=self.index_name, body=mapping)
            logger.info(f"Created Elasticsearch index: {self.index_name}")
            return True
        except Exception as e:
            logger.error(f"Failed to create index: {e}")
            return False

    def _get_embedding(self, text: str) -> List[float]:
        """Get embedding for text using the injected embedder (or legacy fallback)."""
        try:
            if self.embeddings is not None:
                return self.embeddings.embed_query(text)
            # Legacy fallback for callers that pre-date the factory.
            from langchain_ollama import OllamaEmbeddings
            embeddings = OllamaEmbeddings(
                model="nomic-embed-text",
                base_url=settings.OLLAMA_API_BASE,
            )
            return embeddings.embed_query(text)
        except Exception as e:
            logger.error(f"Failed to get embedding: {e}")
            raise

    def _parse_filter_expr(self, filter_expr: Optional[str]) -> Dict[str, Any]:
        """Parse filter expression to ES query DSL.

        Supports:
        - tenant_id == X
        - kb_id == Y
        - document_id == Z
        - tenant_id == X and kb_id == Y
        - modality == 'image'  (M38.4 — single or double quoted string)
        """
        if not filter_expr:
            return {}

        must_clauses = []

        # Match tenant_id
        tenant_match = re.search(r'tenant_id\s*==\s*(\d+)', filter_expr)
        if tenant_match:
            must_clauses.append({"term": {"tenant_id": int(tenant_match.group(1))}})

        # Match kb_id
        kb_match = re.search(r'kb_id\s*==\s*(\d+)', filter_expr)
        if kb_match:
            must_clauses.append({"term": {"kb_id": int(kb_match.group(1))}})

        # Match document_id (from subquery like "document_id in (select id from documents where ...)")
        doc_match = re.search(r'document_id\s+in\s*\(([^)]+)\)', filter_expr)
        if doc_match:
            # Extract IDs from the subquery content - simplified approach
            subquery = doc_match.group(1)
            id_matches = re.findall(r'\d+', subquery)
            if id_matches:
                must_clauses.append({"terms": {"document_id": [int(i) for i in id_matches]}})

        # M38.4: modality is a quoted string. 'image' / "text" 等,
        # term query 直接命中 keyword field。character class 不允许
        # 嵌套引号,防注入 "image'); DROP"。
        modality_match = re.search(r"""modality\s*==\s*['"]([^'"]+)['"]""", filter_expr)
        if modality_match:
            must_clauses.append({"term": {"modality": modality_match.group(1)}})

        if must_clauses:
            return {"bool": {"must": must_clauses}}
        return {}

    def add_texts(
        self,
        texts: List[str],
        metadatas: List[Dict[str, Any]],
        ids: Optional[List[str]] = None,
        titles: Optional[List[str]] = None,
        important_kws: Optional[List[str]] = None,
        question_kws: Optional[List[str]] = None
    ) -> List[str]:
        """Add texts to Elasticsearch using bulk indexing.

        Args:
            texts: List of text contents
            metadatas: List of metadata dicts
            ids: Optional list of document IDs
            titles: Optional list of title strings
            important_kws: Optional list of important keywords
            question_kws: Optional list of question keywords
        """
        if not self.is_connected:
            logger.warning("Elasticsearch not connected, returning mock IDs")
            return [f"mock_{i}" for i in range(len(texts))]

        self.create_index()

        result_ids = []
        actions = []

        for i, text in enumerate(texts):
            doc_id = ids[i] if ids else f"es_{i}"

            try:
                vector = self._get_embedding(text)

                doc_source = {
                    "text": text,
                    "text_vec": vector,
                    "tenant_id": metadatas[i].get("tenant_id"),
                    "kb_id": metadatas[i].get("kb_id"),
                    "document_id": metadatas[i].get("document_id"),
                    "chunk_id": metadatas[i].get("chunk_id"),
                    # M38.4: 顶层 modality 字段让 ES term query 直接命中
                    # ``?modality=image`` filter。legacy chunk 没这个
                    # 字段时 ES 返 0 hits(modality filter 本就不该
                    # 把 pre-M38.4 chunks 拉进来)。
                    "modality": metadatas[i].get("modality", "text"),
                    "metadata": metadatas[i]
                }

                # Add optional fields
                if titles and i < len(titles):
                    doc_source["title"] = titles[i]
                if important_kws and i < len(important_kws):
                    doc_source["important_kw"] = important_kws[i]
                if question_kws and i < len(question_kws):
                    doc_source["question_kw"] = question_kws[i]

                action = {
                    "_index": self.index_name,
                    "_id": doc_id,
                    "_source": doc_source
                }
                actions.append(action)
                result_ids.append(doc_id)
            except Exception as e:
                logger.error(f"Failed to prepare document {i}: {e}")
                result_ids.append(f"error_{i}")

        # Bulk insert
        if actions:
            try:
                success, failed = helpers.bulk(self._client, actions, raise_on_error=False)
                logger.info(f"Bulk indexed {success} documents, {len(failed) if failed else 0} failed")
            except Exception as e:
                logger.error(f"Bulk indexing failed: {e}")

        return result_ids

    def similarity_search(
        self,
        query: str,
        k: int = 5,
        filter_expr: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Perform KNN similarity search."""
        if not self.is_connected:
            return []

        try:
            query_vector = self._get_embedding(query)
            filter_query = self._parse_filter_expr(filter_expr)

            search_body = {
                "knn": {
                    "field": "text_vec",
                    "query_vector": query_vector,
                    "k": k,
                    "num_candidates": k * 3
                },
                "_source": ["text", "metadata", "tenant_id", "kb_id", "document_id", "chunk_id"]
            }

            if filter_query:
                search_body["query"] = filter_query

            response = self._client.search(index=self.index_name, body=search_body)

            results = []
            for hit in response["hits"]["hits"]:
                results.append({
                    "id": hit["_id"],
                    "text": hit["_source"].get("text", ""),
                    "distance": 1.0 - hit["_score"] / 100,  # Approximate distance
                    "metadata": hit["_source"].get("metadata", {})
                })

            return results
        except Exception as e:
            logger.error(f"Search failed: {e}")
            return []

    def hybrid_search(
        self,
        query: str,
        k: int = 5,
        alpha: float = 0.5,
        filter_expr: Optional[str] = None,
        field_weights: Optional[Dict[str, float]] = None
    ) -> List[Dict[str, Any]]:
        """Perform hybrid search using KNN + full-text with RRF fusion.

        Args:
            query: Search query
            k: Number of results
            alpha: Weight for vector search (0-1), full-text gets (1-alpha)
            filter_expr: Optional filter expression
            field_weights: Optional dict of field boosts
                e.g. {"title": 10.0, "important_kw": 30.0, "text": 2.0}
        """
        if not self.is_connected:
            return []

        weights = field_weights or self.field_weights

        try:
            query_vector = self._get_embedding(query)
            filter_query = self._parse_filter_expr(filter_expr)

            # Build weighted multi-match query
            # Fields with higher weights get boosted
            fields_list = []
            if weights.get("title"):
                fields_list.append(f"title^{weights['title']}")
            if weights.get("important_kw"):
                fields_list.append(f"important_kw^{weights['important_kw']}")
            if weights.get("question_kw"):
                fields_list.append(f"question_kw^{weights['question_kw']}")
            if weights.get("text"):
                fields_list.append(f"text^{weights['text']}")

            # KNN search
            knn_body = {
                "knn": {
                    "field": "text_vec",
                    "query_vector": query_vector,
                    "k": k,
                    "num_candidates": k * 3
                },
                "_source": ["text", "title", "metadata", "tenant_id", "kb_id", "document_id", "chunk_id"]
            }
            if filter_query:
                knn_body["query"] = filter_query

            # Full-text search with field boosting
            match_body = {
                "query": {
                    "multi_match": {
                        "query": query,
                        "fields": fields_list,
                        "type": "best_fields",
                        "fuzziness": "AUTO"
                    }
                },
                "size": k,
                "_source": ["text", "title", "metadata", "tenant_id", "kb_id", "document_id", "chunk_id"]
            }
            if filter_query:
                match_body["query"] = {
                    "bool": {
                        "must": [match_body["query"]],
                        "filter": filter_query
                    }
                }

            # Execute both searches
            knn_response = self._client.search(index=self.index_name, body=knn_body)
            match_response = self._client.search(index=self.index_name, body=match_body)

            # RRF (Reciprocal Rank Fusion)
            rrf_scores: Dict[str, float] = {}
            rrf_k = 60  # RRF constant

            # KNN scores
            for rank, hit in enumerate(knn_response["hits"]["hits"]):
                doc_id = hit["_id"]
                rrf_scores[doc_id] = rrf_scores.get(doc_id, 0) + alpha * (1.0 / (rrf_k + rank + 1))

            # Full-text scores
            for rank, hit in enumerate(match_response["hits"]["hits"]):
                doc_id = hit["_id"]
                rrf_scores[doc_id] = rrf_scores.get(doc_id, 0) + (1 - alpha) * (1.0 / (rrf_k + rank + 1))

            # Sort by RRF score
            sorted_doc_ids = sorted(rrf_scores.keys(), key=lambda x: rrf_scores[x], reverse=True)[:k]

            # Build results with distance info
            doc_map = {}
            for hit in knn_response["hits"]["hits"]:
                doc_map[hit["_id"]] = hit
            for hit in match_response["hits"]["hits"]:
                doc_map[hit["_id"]] = hit

            results = []
            for doc_id in sorted_doc_ids:
                if doc_id in doc_map:
                    hit = doc_map[doc_id]
                    results.append({
                        "id": doc_id,
                        "text": hit["_source"].get("text", ""),
                        "title": hit["_source"].get("title"),
                        "distance": 1.0 - rrf_scores[doc_id],
                        "metadata": hit["_source"].get("metadata", {})
                    })

            return results
        except Exception as e:
            logger.error(f"Hybrid search failed: {e}")
            return []

    def delete_by_ids(self, ids: List[str]) -> bool:
        """Delete documents by IDs."""
        if not self.is_connected:
            return False

        try:
            for doc_id in ids:
                self._client.delete(index=self.index_name, id=doc_id, ignore=[404])
            logger.info(f"Deleted {len(ids)} documents from {self.index_name}")
            return True
        except Exception as e:
            logger.error(f"Delete failed: {e}")
            return False
