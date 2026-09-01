"""M38.4: CLIP ViT-B/32 embedder (fallback multimodal provider).

Local HuggingFace transformers impl for ``openai/clip-vit-base-patch32``.
512 dim, ~600 MB, fast — a reasonable fallback when jina-clip-v2 isn't
available (e.g. transient HF download failure, dev box with tight disk
budget) or when the KB corpus is simple enough that the smaller model's
worse margin doesn't matter.

Unlike jina-clip-v2, vanilla CLIP uses stock HF classes — no
``trust_remote_code``, no custom encode helpers. We drive the standard
``get_text_features`` / ``get_image_features`` entry points after
building inputs with ``CLIPProcessor``.

This module deliberately mirrors :mod:`.jina_clip_v2` line-for-line
where the surface is identical — both inherit from
:class:`HFLocalMultimodalEmbedder` and differ only in the HF class
they import and the encode path they take. If a third local provider
arrives (CLIP-L/14, SigLIP, etc.) it should follow the same pattern.
"""
from __future__ import annotations

from typing import Sequence

from ._hf_local import HFLocalMultimodalEmbedder


class CLIPBase32Embedder(HFLocalMultimodalEmbedder):
    """CLIP ViT-B/32 fallback embedder (512 dim, faster than jina-clip-v2).

    Use when the dev environment can't host jina-clip-v2's 3 GB model
    or when retrieval quality on a simple corpus doesn't justify the
    bigger model. The factory exposes this as ``provider='clip_base_32'``.
    """

    provider_name: str = "clip_base_32"
    dimension: int = 512  # canonical CLIP-B/32 dim; overridden by probe if needed

    def __init__(
        self,
        model_id: str = "openai/clip-vit-base-patch32",
        config: dict | None = None,
    ) -> None:
        super().__init__(model_id=model_id, config=config)

    def _load_model(self):
        """Lazy-load CLIP ViT-B/32 with stock HF classes (no trust_remote_code)."""
        from transformers import CLIPModel, CLIPProcessor

        load_kwargs = {}
        if self._revision:
            load_kwargs["revision"] = self._revision

        model = CLIPModel.from_pretrained(self.model_id, **load_kwargs)
        processor = CLIPProcessor.from_pretrained(self.model_id, **load_kwargs)
        self.dimension = 512
        return model, processor

    def _encode_text(self, model, processor, texts: Sequence[str]):
        """Stock CLIP path: build inputs via ``CLIPProcessor`` and call
        ``model.get_text_features``."""
        # ``processor(text=...)`` returns a dict with ``input_ids`` /
        # ``attention_mask``. We feed those straight to
        # ``get_text_features`` which accepts the kwargs and returns a
        # ``torch.Tensor`` of shape ``(N, 512)``.
        text_inputs = processor(
            text=list(texts),
            return_tensors="pt",
            padding=True,
            truncation=True,
        )
        return model.get_text_features(**text_inputs)

    def _encode_image(self, model, processor, images):
        """Stock CLIP path: ``CLIPProcessor`` for image preprocessing +
        ``model.get_image_features`` for the actual encoding.

        ``CLIPProcessor`` returns ``pixel_values`` already normalised to
        the CLIP stats — we don't need to do PIL → tensor conversion
        ourselves.
        """
        image_inputs = processor(
            images=list(images),
            return_tensors="pt",
        )
        return model.get_image_features(pixel_values=image_inputs["pixel_values"])