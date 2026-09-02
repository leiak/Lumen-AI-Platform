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

    2026-09-02 (Bug B): also assert that ``client_kwargs`` carries the
    httpx proxy bypass (``{"proxy": None, "trust_env": False}``) — see
    ``lumen_core.httpx_bypass.bypass_proxy_client_kwargs``. Without this
    arg the embed call goes through the user's Windows registry proxy
    and gets 502 for localhost-bound ollama (incident 1148 timeline
    mirrored to embeddings).
    """
    from lumen_services.embedding_logging import LoggingEmbeddings
    from lumen_core.httpx_bypass import bypass_proxy_client_kwargs

    db, cfg = _make_db(5)
    with patch("lumen_services.embedding_factory.OllamaEmbeddings") as MockOll:
        MockOll.return_value.embed_query.return_value = [0.1] * 768
        emb, dim = embedding_factory.get_embeddings_for_config(5, db)
    MockOll.assert_called_once_with(
        model="nomic-embed-text",
        base_url="http://localhost:11434",
        client_kwargs=bypass_proxy_client_kwargs(),
    )
    assert dim == 768
    assert isinstance(emb, LoggingEmbeddings)
    assert emb._inner is MockOll.return_value


def test_returns_openai_embeddings_for_openai_config():
    """OpenAI configs use OpenAIEmbeddings with api_key/base_url.

    2026-09-02 (Bug B): also assert that ``http_client`` and
    ``http_async_client`` carry the httpx proxy bypass kwargs. Without
    both, the openai SDK's sync path bypasses but async path leaks
    through the proxy.
    """
    from lumen_core.httpx_bypass import bypass_proxy_client_kwargs

    db, cfg = _make_db(6, model_type="openai", model_name="text-embedding-3-small")
    cfg.api_key = "sk-test"
    with patch("lumen_services.embedding_factory.OpenAIEmbeddings") as MockOpenAI, \
         patch("lumen_services.embedding_factory.httpx") as MockHttpx:
        MockHttpx.Client.return_value = MagicMock()
        MockHttpx.AsyncClient.return_value = MagicMock()
        MockOpenAI.return_value.embed_query.return_value = [0.0] * 1536
        emb, dim = embedding_factory.get_embeddings_for_config(6, db)
    assert MockOpenAI.called
    assert dim == 1536
    bypass = bypass_proxy_client_kwargs()
    # Both sync + async clients must get the bypass kwargs (openai SDK
    # uses sync for embed_query, async for aembed_query).
    MockHttpx.Client.assert_called_once_with(**bypass)
    MockHttpx.AsyncClient.assert_called_once_with(**bypass)


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


# ---------------------------------------------------------------------------
# Bug B (2026-09-02) — OllamaEmbeddings + OpenAIEmbeddings need
# httpx proxy bypass on dev boxes that route through the Windows
# registry proxy. Same root cause as workflow 1148 (2026-08-31) but
# in the embed path; fixed by ``lumen_core.httpx_bypass`` and applied
# here in 2026-09-02.
# ---------------------------------------------------------------------------


def test_bypass_proxy_client_kwargs_returns_bypass_dict():
    """lumen_core.httpx_bypass returns ``{"proxy": None, "trust_env": False}``.

    Both keys are required: ``proxy=None`` disables the proxy map and
    ``trust_env=False`` stops httpx from re-reading the env vars on
    every request. Without either, httpx would re-read the Windows
    registry proxy on localhost:11434 → 502.
    """
    from lumen_core.httpx_bypass import bypass_proxy_client_kwargs

    kwargs = bypass_proxy_client_kwargs()
    assert kwargs == {"proxy": None, "trust_env": False}


def test_ollama_embeddings_passes_proxy_bypass_client_kwargs():
    """Regression: OllamaEmbeddings must receive ``client_kwargs`` with
    the proxy bypass so the underlying httpx Client bypasses the
    Windows registry proxy. Without this the embed call silently 502s.
    """
    db, _ = _make_db(20)
    with patch("lumen_services.embedding_factory.OllamaEmbeddings") as MockOll:
        MockOll.return_value.embed_query.return_value = [0.1] * 768
        embedding_factory.get_embeddings_for_config(20, db)
    _, kwargs = MockOll.call_args
    assert kwargs.get("client_kwargs") == {"proxy": None, "trust_env": False}


def test_openai_embeddings_passes_proxy_bypass_to_both_clients():
    """Regression: openai SDK uses sync httpx.Client for ``embed_query``
    and async httpx.AsyncClient for ``aembed_query``. Missing either
    leaves one half of the embed path exposed to the proxy.
    """
    db, cfg = _make_db(21, model_type="openai", model_name="text-embedding-3-small")
    cfg.api_key = "sk-test"
    with patch("lumen_services.embedding_factory.OpenAIEmbeddings") as MockOpenAI, \
         patch("lumen_services.embedding_factory.httpx") as MockHttpx:
        MockHttpx.Client.return_value = MagicMock()
        MockHttpx.AsyncClient.return_value = MagicMock()
        MockOpenAI.return_value.embed_query.return_value = [0.0] * 1536
        embedding_factory.get_embeddings_for_config(21, db)
    bypass = {"proxy": None, "trust_env": False}
    MockHttpx.Client.assert_called_once_with(**bypass)
    MockHttpx.AsyncClient.assert_called_once_with(**bypass)
    _, kwargs = MockOpenAI.call_args
    # both clients must be present in the constructor call so the SDK
    # routes sync + async through the bypassed httpx clients
    assert kwargs["http_client"] is MockHttpx.Client.return_value
    assert kwargs["http_async_client"] is MockHttpx.AsyncClient.return_value
