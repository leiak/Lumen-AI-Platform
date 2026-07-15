"""Tests for VectorStoreFactory.get_store(kb_id, model_config_id, db)."""
import tempfile
from unittest.mock import MagicMock, patch


def _make_db(config_id, *, model_name="nomic-embed-text", model_type="ollama"):
    cfg = MagicMock()
    cfg.id = config_id
    cfg.is_active = True
    cfg.is_embedding = True
    cfg.model_type = model_type
    cfg.model_name = model_name
    cfg.base_url = "http://localhost:11434"
    cfg.api_key = None
    db = MagicMock()
    db.get.return_value = cfg
    return db, cfg


def test_factory_uses_collection_name_pattern():
    """get_store must namespace the persisted collection as kb_{kb_id}_mc_{mc_id}."""
    from lumen_tools.vector_store_factory import VectorStoreFactory

    db, _ = _make_db(7)
    fake_emb = MagicMock()
    fake_emb.embed_query.return_value = [0.0] * 768

    with patch(
        "lumen_services.embedding_factory.get_embeddings_for_config",
        return_value=(fake_emb, 768),
    ) as mock_get:
        with patch("lumen_tools.vector_store_factory.FAISSVectorStore") as MockFAISS:
            MockFAISS.return_value = MagicMock()
            with tempfile.TemporaryDirectory() as tmp:
                # Force FAISS path (no ES available in CI)
                with patch.object(VectorStoreFactory, "_check_es_available", return_value=False):
                    store = VectorStoreFactory.get_store(5, 7, db)

    # Must have called the factory with the namespaced collection
    call_kwargs = MockFAISS.call_args.kwargs
    assert call_kwargs["collection_name"] == "kb_5_mc_7"
    assert call_kwargs["embedding_dim"] == 768
    assert call_kwargs["embeddings"] is fake_emb


def test_factory_falls_back_to_faiss_when_es_unavailable():
    """When ES is disabled, return a FAISS instance (not raise)."""
    from lumen_tools.vector_store_factory import VectorStoreFactory

    db, _ = _make_db(8)
    fake_emb = MagicMock()
    fake_emb.embed_query.return_value = [0.0] * 768

    with patch(
        "lumen_services.embedding_factory.get_embeddings_for_config",
        return_value=(fake_emb, 768),
    ):
        with patch("lumen_tools.vector_store_factory.FAISSVectorStore") as MockFAISS:
            MockFAISS.return_value = MagicMock()
            with patch.object(VectorStoreFactory, "_check_es_available", return_value=False):
                store = VectorStoreFactory.get_store(3, 8, db)
    assert store is not None
