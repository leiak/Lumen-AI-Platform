"""Internal helpers for the two local HuggingFace embedders.

Shared because ``jina_clip_v2`` and ``clip_base_32`` are both local HF
transformers and both need the same:

- PIL image loading from path strings (so callers can pass either PIL
  or a path)
- ``torch.no_grad`` wrapping around inference
- A safe dim-probe (one text + one image, returns the actual dim)
- Lazy model loading (the 600MB / 3GB models are heavy; we only pay
  that cost on first use, not at import time)

The two impls differ in the *processor* / *model* class
(``AutoModel`` for jina-clip-v2, ``CLIPModel`` for CLIP) and the
``encode_*`` API surface. We don't try to unify those — a thin base
class adds more complexity than it saves given only two impls.
"""
from __future__ import annotations

import os
from typing import Any, List, Sequence

import numpy as np
from PIL import Image

from .base import (
    ImageInput,
    MultimodalEmbedder,
    MultimodalEmbeddingError,
    TextInput,
)


def load_pil(image: ImageInput) -> Image.Image:
    """Coerce an :data:`ImageInput` to a PIL Image.

    Path strings are opened in RGB mode (matches what HF processors
    expect — CMYK / RGBA / P-mode JPEGs come up occasionally and need
    to be flattened). Already-PIL inputs are returned unchanged.
    """
    if isinstance(image, Image.Image):
        return image
    if isinstance(image, str):
        if not os.path.exists(image):
            raise FileNotFoundError(f"image path does not exist: {image}")
        return Image.open(image).convert("RGB")
    raise MultimodalEmbeddingError(
        f"ImageInput must be PIL.Image or path string, got {type(image).__name__}"
    )


def to_python_floats(vec) -> List[float]:
    """Coerce a numpy / torch / nested-list vector to ``List[float]``.

    Models in this module return ``torch.Tensor`` (CPU); HF processors
    for some variants return numpy arrays. Downstream code stores the
    vector in MySQL via SQLAlchemy JSON, which prefers plain Python
    types. Strip the wrapper, ensure float dtype, return a list.
    """
    if hasattr(vec, "detach"):  # torch.Tensor
        vec = vec.detach().cpu().numpy()
    if isinstance(vec, np.ndarray):
        # Flatten 2-D single-row outputs (shape (1, D)) to 1-D — the
        # single-input methods always return a flat vector; if a model
        # hands back (1, D) instead of (D,) we treat that as the same.
        if vec.ndim == 2 and vec.shape[0] == 1:
            vec = vec[0]
        if vec.ndim != 1:
            raise MultimodalEmbeddingError(
                f"to_python_floats expected 1-D output, got shape {vec.shape}"
            )
        return [float(x) for x in vec.astype(np.float32).tolist()]
    if isinstance(vec, list):
        if not vec:
            return []
        # Already a Python list — check first element to detect 2-D
        # (single-row batch) and flatten.
        if isinstance(vec[0], (list, tuple)):
            if len(vec) == 1 and isinstance(vec[0], list):
                return [float(x) for x in vec[0]]
            raise MultimodalEmbeddingError(
                "to_python_floats called on 2-D output; use the batch variant"
            )
        return [float(x) for x in vec]
    raise MultimodalEmbeddingError(
        f"to_python_floats got unsupported type {type(vec).__name__}"
    )


def batch_to_python_floats(vecs) -> List[List[float]]:
    """Coerce a batch of vectors (numpy 2-D, torch 2-D, list-of-list) to
    ``List[List[float]]``."""
    if hasattr(vecs, "detach"):
        vecs = vecs.detach().cpu().numpy()
    if isinstance(vecs, np.ndarray):
        if vecs.ndim == 1:
            # Single-vector output from a model that flattens — turn
            # it back into a 1-row batch.
            vecs = vecs[np.newaxis, :]
        vecs = vecs.astype(np.float32).tolist()
    return [[float(x) for x in row] for row in vecs]


class HFLocalMultimodalEmbedder(MultimodalEmbedder):
    """Common scaffolding for the two local HF providers.

    Subclasses override:
      - ``provider_name``
      - ``dimension``
      - ``_load_model()``  → ``(model, processor)``
      - ``_encode_text(model, processor, texts)`` → tensor
      - ``_encode_image(model, processor, images)`` → tensor

    They inherit the ``embed_text`` / ``embed_image`` / batch wiring +
    dim-probe + lazy loading + ``torch.no_grad`` discipline from this
    base. Subclasses need only encode the model-specific I/O surface.
    """

    #: Override in subclasses. Set BEFORE first ``_load_model`` call
    #: (typically as a class attribute) so the factory's dim-probe
    #: works without a model load.
    dimension: int = 0

    def __init__(self, model_id: str, config: dict | None = None) -> None:
        """``model_id`` is the HF model id (or local path).

        ``config`` is the JSON column from
        ``MultimodalEmbeddingConfig.config``; we read ``device`` (cpu
        / cuda) and ``revision`` (pinned HF commit). Defaults are ``cpu``
        + ``None`` (latest).
        """
        self.model_id = model_id
        self.config = config or {}
        self._device: str = self.config.get("device", "cpu")
        self._revision: str | None = self.config.get("revision")
        # Lazy: filled by ``_ensure_loaded``. We don't preload at
        # __init__ because HF model downloads can take 30+s in dev
        # and the KB layer only resolves the factory on first chunk
        # to embed, not at startup.
        self._model = None
        self._processor = None
        self._load_lock_marker = False  # debug aid; not a real lock

    # ------------------------------------------------------------------
    # Lazy model load
    # ------------------------------------------------------------------

    def _ensure_loaded(self) -> None:
        """Idempotent: load the HF model + processor on first call."""
        if self._model is not None:
            return
        # Delegate to subclass — they know which HF class to use.
        model, processor = self._load_model()
        # Move to device (cpu in dev; cuda in production if available).
        try:
            model = model.to(self._device)
        except Exception:  # pragma: no cover — defensive
            pass
        model.eval()  # disable dropout for deterministic embeddings
        self._model = model
        self._processor = processor
        # Sanity: actual dim should match the declared one. We can't
        # do a real probe here without paying a tokenize round trip;
        # the factory does that after construction.

    def _load_model(self):
        """Subclass hook: ``(model, processor) = self._load_model()``.

        Implementations MUST set ``self.dimension`` to the actual
        output dim if it differs from the class-attribute default.
        """
        raise NotImplementedError

    def _encode_text(self, model, processor, texts: Sequence[TextInput]):
        """Subclass hook: encode ``texts`` → ``(N, dimension)`` tensor / array."""
        raise NotImplementedError

    def _encode_image(self, model, processor, images: Sequence[Image.Image]):
        """Subclass hook: encode PIL images → ``(N, dimension)`` tensor / array."""
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Public API (inherited; subclasses normally don't override)
    # ------------------------------------------------------------------

    def embed_text(self, text: TextInput) -> List[float]:
        self._ensure_loaded()
        import torch  # local import keeps HF optional at import time

        if not isinstance(text, str):  # narrow the type
            raise MultimodalEmbeddingError(
                f"embed_text expects str, got {type(text).__name__}"
            )
        with torch.no_grad():
            vec = self._encode_text(self._model, self._processor, [text])
        return to_python_floats(self._first_row(vec))

    def embed_image(self, image: ImageInput) -> List[float]:
        self._ensure_loaded()
        import torch

        pil = load_pil(image)
        with torch.no_grad():
            vec = self._encode_image(self._model, self._processor, [pil])
        return to_python_floats(self._first_row(vec))

    def embed_text_batch(self, texts: Sequence[TextInput]) -> List[List[float]]:
        self._ensure_loaded()
        import torch

        strs = [t if isinstance(t, str) else str(t) for t in texts]
        with torch.no_grad():
            vecs = self._encode_text(self._model, self._processor, strs)
        return batch_to_python_floats(vecs)

    def embed_image_batch(self, images: Sequence[ImageInput]) -> List[List[float]]:
        self._ensure_loaded()
        import torch

        pils = [load_pil(img) for img in images]
        with torch.no_grad():
            vecs = self._encode_image(self._model, self._processor, pils)
        return batch_to_python_floats(vecs)

    @staticmethod
    def _first_row(vecs):
        """Reduce a (1, D) tensor to a (D,) tensor.

        The HF APIs always return ``(N, D)`` even for N=1; our single
        embed methods want a flat ``(D,)``. ``batch_to_python_floats``
        does the same for the 2-D case.

        We check ``ndim`` first because torch's ``Tensor.dim()`` is a
        *method*, not a property — using it on objects that don't define
        it (e.g. numpy arrays where ``dim`` is also a method that
        doesn't exist) crashes with "'int' not callable". Numpy's
        ``ndim`` attribute is the canonical shape probe and works on
        both numpy arrays and torch tensors (1.x+).
        """
        if hasattr(vecs, "ndim"):
            ndim = vecs.ndim
            if ndim == 2 and vecs.shape[0] == 1:
                return vecs[0]
        if isinstance(vecs, list) and len(vecs) == 1 and isinstance(vecs[0], list):
            return vecs[0]
        return vecs