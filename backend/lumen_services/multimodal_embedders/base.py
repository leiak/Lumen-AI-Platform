"""M38.4: Multimodal Embedder ABC.

Cross-modal embedding interface — text and image share the same vector
space (same dimension) so retrieval is symmetric. The KB layer can
take a query of one modality and search across chunks of any modality.

Design choices:

- **Both ``embed_text()`` and ``embed_image()`` are required.** A pure
  text-only or pure image-only embedder does not satisfy the spec's
  cross-modal retrieval goal (spec §1.3 acceptance 1: "用户文字问 'logo'
  → 命中上传的图片").
- **Output is a flat ``List[float]``** for the single-input methods,
  and ``List[List[float]]`` for the batch methods — keeps the API
  symmetric with ``langchain_core.embeddings.Embeddings`` so the chunking
  / vector store layer can swap providers without rewriting loops.
- **Input types are permissive.** ``TextInput`` is ``str``; ``ImageInput``
  is either a ``PIL.Image.Image`` (already in memory) or a local path
  string (``PIL`` opens it lazily). This matches the two ways callers
  hit the embedder:
    - KB image parser hands over a PIL Image it just extracted
    - ``/image-search`` endpoint hands over a temp path (the uploaded
      query image)
- **Dimension is fixed at construction time** and surfaces via the
  ``dimension`` attribute — never re-probed. The factory caches it in
  the ``MultimodalEmbeddingConfig.dimension`` column after the first
  successful test embed, so admins can pick a config with confidence
  before any KB is bound to it.
- **``close()`` is defined but optional.** Local HF models keep a torch
  process / cached tensors; cloud providers may close HTTP sessions.
  Default is a no-op; implementations override only when they hold
  resources.

``MultimodalEmbeddingError`` and ``UnsupportedProviderError`` are the only
exceptions the abstract interface guarantees callers can catch; impls
may raise their own (e.g. network errors), but the factory wraps any
``ValueError`` from the embedder construction into
``UnsupportedProviderError`` so the API layer sees one consistent
failure mode.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Sequence, Union

from PIL import Image


# PIL Image (preferred, no extra I/O) or a filesystem path string
# (loaded on demand inside the embedder). Both are equivalent — the
# concrete provider may prefer one (e.g. CLIP's ``AutoProcessor``
# accepts PIL directly).
ImageInput = Union[Image.Image, str]
TextInput = str


class MultimodalEmbeddingError(Exception):
    """Raised when a multimodal embedding call fails.

    Covers both impl-side errors (e.g. HF model not loaded) and
    upstream data errors (e.g. undecodable image bytes). The factory
    surfaces this verbatim; ``UnsupportedProviderError`` is a
    specialised subclass (see below) reserved for config-level
    problems.
    """


class UnsupportedProviderError(ValueError, MultimodalEmbeddingError):
    """The ``MultimodalEmbeddingConfig.provider`` value is not recognised.

    Inherits from both ``ValueError`` (matches the behaviour of
    ``lumen_services.embedding_factory`` for ``SUPPORTED_EMBEDDING_PROVIDERS``
    violations) and :class:`MultimodalEmbeddingError` (so callers that
    catch the broad class still match).
    """


class MultimodalEmbedder(ABC):
    """Abstract cross-modal embedding interface.

    Concrete impls are expected to be **stateless across calls** —
    model weights / HTTP sessions are loaded once at construction and
    reused. Inputs are read-only; callers must not mutate the PIL
    images after handing them over.
    """

    #: Vector dimensionality of this embedder. MUST equal
    #: ``embed_text(...)`` and ``embed_image(...)`` output length.
    #: Set by subclasses as a class attribute or in ``__init__``.
    dimension: int

    #: Provider tag from ``MultimodalEmbeddingConfig.provider``.
    #: Subclasses set this to their canonical name (matches the DB enum).
    provider_name: str

    @abstractmethod
    def embed_text(self, text: TextInput) -> List[float]:
        """Embed a single text string. Returns ``dimension``-dim vector.

        Empty string is permitted; the embedder returns a zero vector
        or its "no-signal" default. Callers MUST validate non-empty
        before calling when they care about retrieval quality.
        """

    @abstractmethod
    def embed_image(self, image: ImageInput) -> List[float]:
        """Embed a single image (PIL Image or local path).

        If a path is passed and the file does not exist, raise
        :class:`FileNotFoundError`. Other errors (decode failure,
        unsupported format) raise :class:`MultimodalEmbeddingError`.
        """

    def embed_text_batch(self, texts: Sequence[TextInput]) -> List[List[float]]:
        """Batch variant of :meth:`embed_text`. Default loops the single
        version for impls that don't expose a true batch path.

        Local HF transformers will typically override this to do a
        single ``processor(text=...)`` + ``get_text_features`` round
        trip, which is 2-5× faster than per-call loops for big batches.
        """
        return [self.embed_text(t) for t in texts]

    def embed_image_batch(self, images: Sequence[ImageInput]) -> List[List[float]]:
        """Batch variant of :meth:`embed_image`. Default loops the single
        version for impls that don't expose a true batch path.

        Local HF transformers will typically override this. PIL Image
        inputs are forwarded as-is; path strings are loaded inside the
        impl so the batched ``processor(images=...)`` call sees PIL.
        """
        return [self.embed_image(img) for img in images]

    def close(self) -> None:
        """Release any held resources (HTTP sessions, model handles).

        Default is a no-op. Local HF impls typically don't need this
        (Python GC + ``torch``'s reference counting handle it), but
        cloud providers with explicit HTTP clients SHOULD override.
        Idempotent — calling ``close()`` twice is a no-op.
        """

    # ------------------------------------------------------------------
    # Context manager sugar (optional; impls need not redefine)
    # ------------------------------------------------------------------

    def __enter__(self) -> "MultimodalEmbedder":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Sanity check used by the factory at construction time.
    # ------------------------------------------------------------------

    def assert_dimension(self, observed_dim: int) -> None:
        """Raise if ``observed_dim`` doesn't match ``self.dimension``.

        The factory calls this after a probe embed (single text +
        single image) to catch impl bugs that mis-report
        ``dimension`` (e.g. local override forgot to set it).
        """
        if observed_dim != self.dimension:
            raise MultimodalEmbeddingError(
                f"{self.provider_name} reported dimension={self.dimension} "
                f"but actual embed returned dim={observed_dim}"
            )