"""M38.4: jina-clip-v2 embedder (default multimodal provider).

Local HuggingFace transformers impl for ``jinaai/jina-clip-v2``. 1024
dim, ~3 GB, top retrieval quality (prototype selector report §4.1 —
jina-clip-v2 had 2-3x larger diagonal margin than CLIP-B/32 on
chart / photo test sets).

Notable details vs plain CLIP:

- Uses ``AutoModel`` / ``AutoProcessor`` with ``trust_remote_code=True``;
  jina publishes its own modelling code on the hub and HF's stock CLIP
  classes can't load it.
- Exposes a custom ``encode_text`` / ``encode_image`` API on top of
  the standard HF forward, so we call those directly rather than
  ``get_text_features`` / ``get_image_features`` (which don't exist on
  the custom code).
- Returns ``numpy.ndarray`` directly (no torch output object). Our
  ``to_python_floats`` helper copes with both.

The model revision is pinned via the ``MultimodalEmbeddingConfig.config``
JSON (default: latest revision). Pinning matters because
``trust_remote_code=True`` ships a custom Python file from the hub —
an unpinned reference could silently swap the model behaviour. See
MEMORY 2026-08-31 §3 for the trust_remote_code supply-chain note.
"""
from __future__ import annotations

from typing import Sequence

from .base import MultimodalEmbedder
from ._hf_local import HFLocalMultimodalEmbedder


class JinaClipV2Embedder(HFLocalMultimodalEmbedder):
    """Default multimodal embedder — jina-clip-v2 via HF transformers.

    Construction-time ``model_id`` defaults to the canonical HF id; the
    factory passes the config-stored ``model_name`` which can override
    it for cached / pinned local copies.
    """

    provider_name: str = "jina_clip_v2"
    dimension: int = 1024  # canonical jina-clip-v2 dim; overridden by probe if needed

    def __init__(
        self,
        model_id: str = "jinaai/jina-clip-v2",
        config: dict | None = None,
    ) -> None:
        super().__init__(model_id=model_id, config=config)

    def _load_model(self):
        """Lazy-load jina-clip-v2 with ``trust_remote_code=True``.

        jina's hub repo carries custom modelling code (``AutoModel``
        dispatches to ``JinaCLIPModel``); without ``trust_remote_code``
        HF refuses to run the custom Python file.
        """
        from transformers import AutoModel, AutoProcessor

        # ``revision`` defaults to None (latest). Production SHOULD pin
        # a specific commit hash via ``config['revision']`` for supply-
        # chain stability — this comment is the only place we surface
        # that requirement in code.
        load_kwargs = {"trust_remote_code": True}
        if self._revision:
            load_kwargs["revision"] = self._revision

        model = AutoModel.from_pretrained(self.model_id, **load_kwargs)
        processor = AutoProcessor.from_pretrained(self.model_id, **load_kwargs)
        # ``encode_text`` returns the actual dim — set the canonical
        # attribute so callers don't need to probe. The factory also
        # re-probes via ``assert_dimension`` to catch impl drift.
        self.dimension = 1024
        return model, processor

    def _encode_text(self, model, processor, texts: Sequence[str]):
        """Call jina-clip's ``encode_text`` which returns a torch tensor."""
        # ``encode_text`` accepts a list[str] and returns
        # ``torch.Tensor`` of shape ``(N, 1024)`` on CPU. We wrap in
        # ``torch.no_grad`` at the caller (embed_text / batch).
        return model.encode_text(list(texts))

    def _encode_image(self, model, processor, images):
        """Call jina-clip's ``encode_image`` which accepts PIL images."""
        return model.encode_image(list(images))