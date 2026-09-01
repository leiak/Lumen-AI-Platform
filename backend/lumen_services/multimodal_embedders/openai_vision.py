"""M38.4: OpenAI Vision embedder (cloud stub).

Documented in spec §3.4 and listed in the ``provider`` enum, but no
real ``openai`` call yet — see ``_cloud_stub.py`` docstring for why.
The dispatch in :mod:`lumen_services.multimodal_embedders.factory` IS
wired so swapping this stub for a real impl is a single-method-body
change.

When a real impl lands it will likely call the OpenAI ``embeddings``
endpoint with the multimodal ``CLIP`` model variant (OpenAI ships
``text-embedding-3-small`` / ``-large`` for text and a separate CLIP
endpoint for image-text alignment); the exact API surface is
intentionally left for the implementer to look up at that time.
"""
from __future__ import annotations

from ._cloud_stub import _CloudStubEmbedder


class OpenAIVisionEmbedder(_CloudStubEmbedder):
    """OpenAI cloud vision embedding — stub, raises NotImplementedError.

    Replace ``embed_text`` / ``embed_image`` with real OpenAI SDK calls
    when API keys + budget are available (spec §10 risk 1 — cloud cost
    is the gating concern for dev). Keep ``dimension`` aligned with
    the OpenAI multimodal model output.
    """

    provider_name: str = "openai_vision"
    # Default placeholder dim. Real OpenAI CLIP variant will be 1536
    # (matches text-embedding-3-* family). The factory calls
    # ``assert_dimension`` after the first probe, so wrong dims surface
    # immediately.
    dimension: int = 1536