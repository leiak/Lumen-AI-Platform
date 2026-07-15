"""Tests for the per-config embedding factory + cache."""
import pytest
from unittest.mock import MagicMock, patch

from lumen_services import embedding_factory


@pytest.fixture(autouse=True)
def _clear_cache():
    """Each test gets a fresh cache."""
    embedding_factory.invalidate_cache()
    yield
    embedding_factory.invalidate_cache()


def _make_db(config_id, *, is_active=True, is_embedding=True,
             model_type="ollama", model_name="nomic-embed-text"):
    cfg = MagicMock()
    cfg.id = config_id
    cfg.is_active = is_active
    cfg.is_embedding = is_embedding
    cfg.model_type = model_type
    cfg.model_name = model_name
    cfg.base_url = "http://localhost:11434"
    cfg.api_key = None
    db = MagicMock()
    db.get.return_value = cfg
    return db, cfg


def test_returns_ollama_embeddings_for_ollama_config():
    """Ollama configs use OllamaEmbeddings with the configured model + base_url.

    M27: ``get_embeddings_for_config`` now wraps the inner Embeddings in
    a ``LoggingEmbeddings`` proxy. Verify the proxy delegates to the
    expected inner via ``_inner``.
    """
    from lumen_services.embedding_logging import LoggingEmbeddings

    db, cfg = _make_db(5)
    with patch("lumen_services.embedding_factory.OllamaEmbeddings") as MockOll:
        MockOll.return_value.embed_query.return_value = [0.1] * 768
        emb, dim = embedding_factory.get_embeddings_for_config(5, db)
    MockOll.assert_called_once_with(
        model="nomic-embed-text", base_url="http://localhost:11434"
    )
    assert dim == 768
    assert isinstance(emb, LoggingEmbeddings)
    assert emb._inner is MockOll.return_value


def test_returns_openai_embeddings_for_openai_config():
    """OpenAI configs use OpenAIEmbeddings with api_key/base_url."""
    db, cfg = _make_db(6, model_type="openai", model_name="text-embedding-3-small")
    cfg.api_key = "sk-test"
    with patch("lumen_services.embedding_factory.OpenAIEmbeddings") as MockOpenAI:
        MockOpenAI.return_value.embed_query.return_value = [0.0] * 1536
        emb, dim = embedding_factory.get_embeddings_for_config(6, db)
    assert MockOpenAI.called
    assert dim == 1536


def test_rejects_unsupported_provider():
    """zhipu / anthropic / MiniMax can't do embeddings — raise ValueError."""
    db, cfg = _make_db(7, model_type="zhipu", model_name="glm-4")
    with pytest.raises(ValueError, match="not supported for provider"):
        embedding_factory.get_embeddings_for_config(7, db)


def test_rejects_is_embedding_false():
    """A config that isn't marked is_embedding=True is refused."""
    db, cfg = _make_db(8, is_embedding=False)
    with pytest.raises(ValueError, match="not marked is_embedding=True"):
        embedding_factory.get_embeddings_for_config(8, db)


def test_rejects_inactive_config():
    """Soft-deleted (is_active=False) configs are refused."""
    db, cfg = _make_db(9, is_active=False)
    with pytest.raises(ValueError, match="is disabled"):
        embedding_factory.get_embeddings_for_config(9, db)


def test_rejects_missing_config():
    """Unknown config id → ValueError, not a KeyError."""
    db = MagicMock()
    db.get.return_value = None
    with pytest.raises(ValueError, match="not found"):
        embedding_factory.get_embeddings_for_config(999, db)


def test_cache_hits_skip_constructor():
    """Second call for the same id must not call OllamaEmbeddings() again."""
    db, cfg = _make_db(10)
    with patch("lumen_services.embedding_factory.OllamaEmbeddings") as MockOll:
        MockOll.return_value.embed_query.return_value = [0.1] * 768
        embedding_factory.get_embeddings_for_config(10, db)
        embedding_factory.get_embeddings_for_config(10, db)
        embedding_factory.get_embeddings_for_config(10, db)
    assert MockOll.call_count == 1


def test_invalidate_cache_forces_reload():
    """invalidate_cache(id) drops that id; invalidate_cache() drops all."""
    db, cfg = _make_db(11)
    with patch("lumen_services.embedding_factory.OllamaEmbeddings") as MockOll:
        MockOll.return_value.embed_query.return_value = [0.1] * 768
        embedding_factory.get_embeddings_for_config(11, db)
        embedding_factory.invalidate_cache(11)
        embedding_factory.get_embeddings_for_config(11, db)
    assert MockOll.call_count == 2
