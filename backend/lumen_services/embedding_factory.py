"""Embedding factory keyed by ModelConfig.id.

The factory caches one ``Embeddings`` instance per model config id so
the embedder (typically an HTTP client to a remote provider) isn't
re-initialized on every chunk. Cache is per-process; multi-worker
deployments each maintain their own cache, which is fine because the
embedder construction itself is cheap and the actual network call
happens lazily on first use.

Cache invalidation:
- ``PUT /models/{id}`` that touches ``model_name`` / ``base_url`` /
  ``api_key`` / ``is_active`` / ``is_embedding`` calls
  ``invalidate_cache(id)``.
- ``DELETE /models/{id}`` calls ``invalidate_cache(id)``.
- On startup the cache is empty, so any config-changes-since-last-run
  are picked up on first use.
"""
from __future__ import annotations

from typing import Dict, Optional, Tuple

import httpx
from langchain_core.embeddings import Embeddings
from pydantic import SecretStr
from sqlalchemy.orm import Session

from lumen_core.config import settings
from lumen_core.httpx_bypass import bypass_proxy_client_kwargs
from lumen_models.model_config import ModelConfig
from lumen_services.embedding_logging import LoggingEmbeddings

# Imported at module level so test code can ``patch`` them
# (e.g. ``patch("lumen_services.embedding_factory.OllamaEmbeddings")``).
# Both are cheap to import; the actual network calls happen lazily
# inside ``embed_query``.
from langchain_ollama import OllamaEmbeddings
from langchain_openai import OpenAIEmbeddings


# model_config_id -> (Embeddings, embedding_dim)
# After M27 the cached object is a ``LoggingEmbeddings`` proxy — the
# proxy delegates to the inner Embeddings instance and only adds
# observability when an ``EmbeddingCallContext`` is set on the
# ContextVar (transparent fall-through otherwise).
_cache: Dict[int, Tuple[Embeddings, int]] = {}


# Providers that can produce embeddings. The factory raises
# ValueError for anything else so an admin who sets
# ``is_embedding=True`` on a non-supported provider gets a clear
# failure at the call site rather than a confusing 502 from the
# remote service.
SUPPORTED_EMBEDDING_PROVIDERS = {"ollama", "openai"}


def get_embeddings_for_config(
    model_config_id: int, db: Session
) -> Tuple[Embeddings, int]:
    """Return ``(embeddings, dim)`` for the given ModelConfig.

    The result is cached per ``model_config_id`` for the lifetime of
    this process.
    """
    cached = _cache.get(model_config_id)
    if cached is not None:
        return cached

    cfg = db.get(ModelConfig, model_config_id)
    if cfg is None:
        raise ValueError(f"ModelConfig {model_config_id} not found")
    if not cfg.is_active:
        raise ValueError(f"ModelConfig {model_config_id} is disabled")
    if not cfg.is_embedding:
        raise ValueError(
            f"ModelConfig {model_config_id} is not marked is_embedding=True"
        )
    if cfg.model_type not in SUPPORTED_EMBEDDING_PROVIDERS:
        raise ValueError(
            f"Embedding not supported for provider '{cfg.model_type}'. "
            f"Supported: {sorted(SUPPORTED_EMBEDDING_PROVIDERS)}"
        )

    if cfg.model_type == "ollama":
        # 跟 model_loader.create_chat_model 同款 httpx proxy bypass:
        # 本机 Windows registry proxy(127.0.0.1:10793 之类)对 localhost:11434
        # 返回 502,httpx 默认 trust_env=True 读 registry 后会走代理。
        # 注入 {"proxy": None, "trust_env": False} 直连。详见
        # lumen_core/httpx_bypass.py 顶部 incident timeline。
        emb: Embeddings = OllamaEmbeddings(
            model=str(cfg.model_name),
            base_url=str(cfg.base_url) if cfg.base_url else settings.OLLAMA_API_BASE,
            client_kwargs=bypass_proxy_client_kwargs(),
        )
    elif cfg.model_type == "openai":
        # 跟 model_loader create_chat_model 走同一个 bypass:openai SDK
        # 用 sync httpx Client 走 embed_query / aembed_query,async httpx
        # AsyncClient 走 aembed_query / aembed_documents。两个都得设,
        # 漏一个留半个 bug。httpx 走顶部 import,test code 可以 patch。
        _bypass = bypass_proxy_client_kwargs()
        emb = OpenAIEmbeddings(
            model=str(cfg.model_name),
            # OpenAIEmbeddings wants SecretStr | None; wrap the plain
            # string from the DB column so mypy is happy and the
            # secret is never accidentally logged.
            api_key=SecretStr(str(cfg.api_key)) if cfg.api_key else None,
            base_url=str(cfg.base_url) if cfg.base_url else None,
            http_client=httpx.Client(**_bypass),
            http_async_client=httpx.AsyncClient(**_bypass),
        )
    else:  # pragma: no cover — guarded by SUPPORTED check above
        raise ValueError(f"Unhandled provider '{cfg.model_type}'")

    # M27: wrap with LoggingEmbeddings proxy BEFORE the dim-probe so the
    # probe itself gets logged (with ``extra.is_dim_probe=True``). The
    # proxy is transparent when no EmbeddingCallContext is set, so the
    # cold-start probe in a request context goes through observability
    # while the same probe at uvicorn startup (no context) does not.
    emb = LoggingEmbeddings(  # type: ignore[assignment]
        emb,
        model_type=str(cfg.model_type),
        model_name=str(cfg.model_name),
        model_config_id=int(cfg.id),  # type: ignore[arg-type]
    )

    # Probe the dim with a throwaway string. The Ollama endpoint
    # sometimes silently returns fewer dims than expected for
    # custom-tuned models, so we trust the probe over the model's
    # documented dim.
    probe = emb.embed_query("dim-probe")
    dim = len(probe)

    _cache[model_config_id] = (emb, dim)
    return emb, dim


def invalidate_cache(model_config_id: Optional[int] = None) -> None:
    """Drop the cache entry for one id, or clear the whole cache.

    Called from the models API whenever a config is updated or
    soft-deleted, so the next ``get_embeddings_for_config`` rebuilds
    the instance with the latest fields.
    """
    if model_config_id is None:
        _cache.clear()
    else:
        _cache.pop(model_config_id, None)
