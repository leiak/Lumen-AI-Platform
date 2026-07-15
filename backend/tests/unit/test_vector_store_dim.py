"""Tests for FAISSVectorStore accepting external embeddings + dim."""
import os
import tempfile
from unittest.mock import MagicMock

import pytest


def test_faiss_uses_injected_dim_not_hardcoded_768():
    """Constructor must honor the dim passed in, not default to 768."""
    from lumen_tools.vector_store import FAISSVectorStore

    with tempfile.TemporaryDirectory() as tmp:
        emb = MagicMock()
        emb.embed_query.return_value = [0.0] * 384  # e.g. all-MiniLM
        store = FAISSVectorStore(
            collection_name="test_kb_1",
            embeddings=emb,
            embedding_dim=384,
            persist_dir=tmp,
        )
        assert store.index.d == 384


def test_faiss_persist_path_uses_persist_dir_and_collection_name():
    """Persist path: {persist_dir}/{collection_name}."""
    from lumen_tools.vector_store import FAISSVectorStore

    with tempfile.TemporaryDirectory() as tmp:
        emb = MagicMock()
        emb.embed_query.return_value = [0.0] * 768
        store = FAISSVectorStore(
            collection_name="kb5_mc12",
            embeddings=emb,
            embedding_dim=768,
            persist_dir=tmp,
        )
        assert store._persist_path == os.path.join(tmp, "kb5_mc12")
