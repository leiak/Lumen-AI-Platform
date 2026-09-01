"""M38.4: Aliyun Qwen-VL embedder (cloud stub).

Documented in spec §3.4 and listed in the ``provider`` enum, but no
real call yet — see ``_cloud_stub.py`` docstring for why.

When a real impl lands it will hit the DashScope multimodal embedding
endpoint (``https://dashscope.aliyuncs.com/api/v1/services/embeddings/
multimodal-embedding/multimodal-embedding``) with a base64 image + a
text prompt. The exact model name (``qwen-vl-plus``, ``qwen-vl-max``,
or a dedicated embedding-only model when Aliyun ships one) is left
for the implementer to pin at that time.
"""
from __future__ import annotations

from ._cloud_stub import _CloudStubEmbedder


class QwenVLEmbedder(_CloudStubEmbedder):
    """Aliyun Tongyi Qwen-VL embedding — stub, raises NotImplementedError.

    Real impl will use DashScope's ``multimodal-embedding`` endpoint
    with the configured ``api_key`` / ``base_url`` (defaults to the
    Aliyun ``.aliyuncs.com`` endpoint when unset).
    """

    provider_name: str = "qwen_vl"
    # Placeholder; real DashScope multimodal-embedding returns 1024 dim.
    dimension: int = 1024