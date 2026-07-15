"""
Hybrid retrieval pipeline: vector + BM25 (lexical) + Reranker.

Public API:
    - BM25Index: lexical retrieval index with optional Chinese tokenization
    - HybridRetriever: combines vector + BM25 with RRF
    - Reranker / JinaReranker / LLMReranker / NoopReranker: reranking stage
    - RetrievalPipeline: high-level facade (vector + BM25 -> RRF -> rerank)
"""
from lumen_services.retrieval.bm25_index import BM25Index, BM25_AVAILABLE, JIEBA_AVAILABLE
from lumen_services.retrieval.hybrid_retriever import HybridRetriever
from lumen_services.retrieval.reranker import (
    Reranker,
    NoopReranker,
    JinaReranker,
    LLMReranker,
    get_reranker,
)
from lumen_services.retrieval.pipeline import RetrievalPipeline, get_retrieval_pipeline

__all__ = [
    "BM25Index",
    "BM25_AVAILABLE",
    "JIEBA_AVAILABLE",
    "HybridRetriever",
    "Reranker",
    "NoopReranker",
    "JinaReranker",
    "LLMReranker",
    "get_reranker",
    "RetrievalPipeline",
    "get_retrieval_pipeline",
]
