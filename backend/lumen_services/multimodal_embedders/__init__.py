"""M38.4: Multimodal Embedder abstraction.

Cross-modal embedding needs a different interface than the text-only
``lumen_services.embedding_factory`` — both text and image map to the
**same** vector space so a text query "logo" can hit an uploaded product
image (spec §1.3 验收用例 1). Every implementation MUST therefore
expose ``embed_text()`` AND ``embed_image()`` returning vectors of the
**same dimension** (the ``dimension`` attribute is fixed at construction
time).

Factory pattern:
- :func:`get_multimodal_embedder` — keyed by ``config_id`` with a
  per-process cache, mirroring ``lumen_services.embedding_factory``.
- :func:`invalidate_multimodal_cache` — drop one or all entries when
  admin updates / disables a config.

Concrete implementations live in sibling modules:
- :mod:`.jina_clip_v2`   — default, local HF transformers
- :mod:`.clip_base_32`   — fallback, local HF transformers
- :mod:`.openai_vision`  — OpenAI (placeholder; not enabled in dev)
- :mod:`.qwen_vl`        — Aliyun Tongyi (placeholder; not enabled in dev)
- :mod:`.azure_vision`   — Azure Computer Vision (placeholder)

Spec: ``docs-internal/superpowers/specs/2026-08-26-kb-multimodal-parsing.md``
"""
from .base import (
    MultimodalEmbedder,
    MultimodalEmbeddingError,
    UnsupportedProviderError,
    ImageInput,
    TextInput,
)
from .factory import (
    get_multimodal_embedder,
    invalidate_multimodal_cache,
)

__all__ = [
    "MultimodalEmbedder",
    "MultimodalEmbeddingError",
    "UnsupportedProviderError",
    "ImageInput",
    "TextInput",
    "get_multimodal_embedder",
    "invalidate_multimodal_cache",
]