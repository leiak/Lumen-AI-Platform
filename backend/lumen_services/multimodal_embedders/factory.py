"""M38.4: Multimodal Embedder factory — keyed by ``config_id``.

Mirrors :mod:`lumen_services.embedding_factory` line-for-line so the
two "embedding" subsystems feel the same to callers:

- Process-wide cache ``{config_id: (embedder, dim)}``
- Lazy construction on first call (heavy HF model loads happen here,
  not at startup — KB chunking doesn't always trigger a multimodal
  embed, and a fresh uvicorn boot shouldn't pay 30 s for an unused
  3 GB model)
- ``invalidate_multimodal_cache(id_or_None)`` — drop one or all
  entries; called from the multimodal configs API whenever a config
  is updated or disabled
- Probe ``dimension`` once at first use, then trust the cache

Why a separate factory (not extending the text one):

- Different providers (jina-clip-v2 has no LangChain equivalent)
- Different return shape (must hand back a single PIL image, not a
  text list)
- Different storage policy (image chunk vectors are stored separately
  from text chunk vectors, so a KB can have one text model + one
  multimodal model side-by-side — M38.4 spec §3.5)

The ``dim_probe`` step is the one sharp edge: local HF models can take
~20 s on a cold cache. The factory runs it once, then trusts the
declared ``dimension`` for the lifetime of the process.
"""
from __future__ import annotations

import threading
from typing import Dict, Optional, Tuple

from sqlalchemy.orm import Session

from lumen_models.multimodal_embedding_config import MultimodalEmbeddingConfig
from .base import (
    MultimodalEmbedder,
    MultimodalEmbeddingError,
    UnsupportedProviderError,
)


# Lazy imports — each provider pulls in transformers (or openai /
# aliyun SDKs in the future). Keeping the import out of the factory
# top-level means a KB / chunking service that never touches the
# multimodal factory doesn't pay the import cost.


def _build_jina(config: MultimodalEmbeddingConfig) -> MultimodalEmbedder:
    from .jina_clip_v2 import JinaClipV2Embedder

    return JinaClipV2Embedder(
        model_id=str(config.model_name),
        config=dict(config.config) if config.config else {},
    )


def _build_clip(config: MultimodalEmbeddingConfig) -> MultimodalEmbedder:
    from .clip_base_32 import CLIPBase32Embedder

    return CLIPBase32Embedder(
        model_id=str(config.model_name),
        config=dict(config.config) if config.config else {},
    )


def _build_openai(config: MultimodalEmbeddingConfig) -> MultimodalEmbedder:
    from .openai_vision import OpenAIVisionEmbedder

    return OpenAIVisionEmbedder(
        api_key=str(config.api_key) if config.api_key else None,
        base_url=str(config.base_url) if config.base_url else None,
        model_name=str(config.model_name) if config.model_name else None,
        config=dict(config.config) if config.config else {},
    )


def _build_qwen(config: MultimodalEmbeddingConfig) -> MultimodalEmbedder:
    from .qwen_vl import QwenVLEmbedder

    return QwenVLEmbedder(
        api_key=str(config.api_key) if config.api_key else None,
        base_url=str(config.base_url) if config.base_url else None,
        model_name=str(config.model_name) if config.model_name else None,
        config=dict(config.config) if config.config else {},
    )


def _build_azure(config: MultimodalEmbeddingConfig) -> MultimodalEmbedder:
    from .azure_vision import AzureVisionEmbedder

    return AzureVisionEmbedder(
        api_key=str(config.api_key) if config.api_key else None,
        base_url=str(config.base_url) if config.base_url else None,
        model_name=str(config.model_name) if config.model_name else None,
        config=dict(config.config) if config.config else {},
    )


# Provider-name → builder. New providers register here; the enum on
# ``MultimodalEmbeddingConfig.provider`` must be updated in lockstep
# (see ``lumen_models/multimodal_embedding_config.py``).
_BUILDERS = {
    "jina_clip_v2": _build_jina,
    "clip_base_32": _build_clip,
    "openai_vision": _build_openai,
    "qwen_vl": _build_qwen,
    "azure_vision": _build_azure,
}


# config_id -> (MultimodalEmbedder, dim). ``dim`` is duplicated for
# callers that want just the dimension (vector table rebuild, capacity
# planning) without holding the embedder object open.
_cache: Dict[int, Tuple[MultimodalEmbedder, int]] = {}

_cache_lock = threading.Lock()


# ----------------------------------------------------------------------
# Public API
# ----------------------------------------------------------------------


def get_multimodal_embedder(
    config_id: int,
    db: Session,
) -> Tuple[MultimodalEmbedder, int]:
    """Return ``(embedder, dim)`` for the given ``MultimodalEmbeddingConfig.id``.

    The result is cached per ``config_id`` for the lifetime of this
    process. First call resolves the config, picks a provider, lazily
    loads any heavyweight model, and probes the dimension; subsequent
    calls hit the cache.

    Raises :class:`UnsupportedProviderError` if the config's
    ``provider`` is not in ``_BUILDERS`` — this is the API-layer's
    signal to surface a 400 to the admin.

    Raises :class:`MultimodalEmbeddingError` if the config is missing,
    disabled, or the lazy probe fails.
    """
    cached = _cache.get(config_id)
    if cached is not None:
        return cached

    with _cache_lock:
        cached = _cache.get(config_id)
        if cached is not None:
            return cached

        cfg = db.get(MultimodalEmbeddingConfig, config_id)
        if cfg is None:
            raise MultimodalEmbeddingError(
                f"MultimodalEmbeddingConfig {config_id} not found"
            )
        if not cfg.enabled:
            raise MultimodalEmbeddingError(
                f"MultimodalEmbeddingConfig {config_id} is disabled"
            )

        builder = _BUILDERS.get(str(cfg.provider))
        if builder is None:
            raise UnsupportedProviderError(
                f"Multimodal provider '{cfg.provider}' not supported. "
                f"Supported: {sorted(_BUILDERS)}"
            )

        embedder = builder(cfg)
        # Probe dim with a throwaway call. This is the one spot that
        # may be slow (HF model load on first call). For cloud stubs
        # this will raise NotImplementedError — that's fine, we surface
        # it unchanged so the API layer can return a clean 501.
        dim = _probe_dimension(embedder)
        embedder.assert_dimension(dim)
        _cache[config_id] = (embedder, dim)
        return embedder, dim


def invalidate_multimodal_cache(config_id: Optional[int] = None) -> None:
    """Drop the cache entry for one id, or clear the whole cache.

    Call from the multimodal-configs admin API whenever a config is
    updated, disabled, or deleted. Without this, edits to
    ``model_name`` / ``provider`` would only take effect on the next
    uvicorn restart.
    """
    with _cache_lock:
        if config_id is None:
            _cache.clear()
        else:
            _cache.pop(config_id, None)


# ----------------------------------------------------------------------
# Internals
# ----------------------------------------------------------------------


def _probe_dimension(embedder: MultimodalEmbedder) -> int:
    """Probe the embedder's actual dim with one cheap call.

    Strategy: try ``embed_text`` first (text input is cheaper than
    loading a PIL image for cloud stubs that have no real impl).

    For cloud stubs (``_CloudStubEmbedder`` subclass with the
    ``is_stub = True`` marker), we skip the probe — there's no real
    model to query, and the declared ``dimension`` attribute is the
    best signal we have until the stub is replaced by a real impl.
    This keeps the factory contract honest: stubs *can* be dispatched
    and cached, but their first ``embed_text`` call raises
    ``NotImplementedError`` as expected.

    The single-text probe ("dim-probe") mirrors the pattern in
    ``lumen_services.embedding_factory._probe_dimension``.
    """
    # Cloud stubs have no model — probing raises ``NotImplementedError``
    # by design. We skip the probe and trust the declared dim so the
    # factory can still cache the stub and the API layer can hand back
    # a clean 501 to the admin when they try to use it.
    if getattr(embedder, "is_stub", False):
        return embedder.dimension

    try:
        vec = embedder.embed_text("dim-probe")
    except NotImplementedError:
        # Non-stub embedder unexpectedly raised NotImplementedError.
        # Surface as a config error so the admin sees the real issue.
        raise MultimodalEmbeddingError(
            f"{embedder.provider_name} embed_text raised NotImplementedError "
            f"but embedder is not marked as a stub"
        )
    except Exception as exc:
        raise MultimodalEmbeddingError(
            f"{embedder.provider_name} dim probe failed: {exc}"
        ) from exc
    if not isinstance(vec, list):
        raise MultimodalEmbeddingError(
            f"{embedder.provider_name} embed_text returned {type(vec).__name__}; "
            f"expected List[float]"
        )
    return len(vec)