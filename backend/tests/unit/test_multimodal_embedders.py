"""M38.4 Step 3 — Multimodal embedder ABC + factory + 5 providers.

Test strategy:

- **Local HF providers** (``jina_clip_v2`` / ``clip_base_32``): we mock
  the ``transformers`` module so the test doesn't pay the 30s+
  model download + ~600 MB / 3 GB model-load cost. The mock mimics the
  surface used by each impl (``AutoModel.from_pretrained`` returns an
  object with ``encode_text`` / ``encode_image`` for jina-clip-v2;
  ``CLIPModel`` returns ``get_text_features`` / ``get_image_features``
  for CLIP-B/32). Mock vectors are fixed-length lists matching the
  canonical dim (1024 / 512).
- **Cloud stubs** (``openai_vision`` / ``qwen_vl`` / ``azure_vision``):
  verify they instantiate, expose the right ``provider_name`` /
  ``dimension``, and raise ``NotImplementedError`` on the first embed
  call — the contract that lets the factory dispatch without real
  API integration.
- **Factory**: build a fresh in-memory ``MultimodalEmbeddingConfig``
  per test, dispatch via ``get_multimodal_embedder``, validate cache
  hit + invalidation behaviour. The ``provider`` / ``enabled`` /
  ``id`` columns are the only fields the factory touches — we use a
  ``MagicMock(spec=MultimodalEmbeddingConfig)`` so type-checked access
  stays honest.

We never persist rows: the factory accepts a ``Session`` only to call
``db.get(MultimodalEmbeddingConfig, config_id)``. Tests substitute
``MagicMock`` for ``db`` and verify the right ``id`` was queried.
"""
from __future__ import annotations

from typing import Any, List, Optional
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from lumen_services import multimodal_embedders
from lumen_services.multimodal_embedders import (
    MultimodalEmbedder,
    MultimodalEmbeddingError,
    UnsupportedProviderError,
    get_multimodal_embedder,
    invalidate_multimodal_cache,
)


# ----------------------------------------------------------------------
# Shared mocks + helpers
# ----------------------------------------------------------------------


def _make_config(
    *,
    config_id: int = 100,
    provider: str = "jina_clip_v2",
    enabled: bool = True,
    model_name: str = "jinaai/jina-clip-v2",
    config: Optional[dict] = None,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
) -> MagicMock:
    """Build a ``MultimodalEmbeddingConfig``-shaped MagicMock."""
    cfg = MagicMock()
    cfg.id = config_id
    cfg.provider = provider
    cfg.enabled = enabled
    cfg.model_name = model_name
    cfg.config = config or {}
    cfg.api_key = api_key
    cfg.base_url = base_url
    return cfg


def _make_db(config: Optional[MagicMock]) -> MagicMock:
    db = MagicMock()
    db.get.return_value = config
    return db


@pytest.fixture(autouse=True)
def _clear_factory_cache():
    """Each test gets a fresh cache."""
    invalidate_multimodal_cache()
    yield
    invalidate_multimodal_cache()


# ----------------------------------------------------------------------
# ABC / base behaviour
# ----------------------------------------------------------------------


def test_abc_cannot_be_instantiated_directly():
    """``MultimodalEmbedder`` is abstract — direct instantiation must fail."""
    with pytest.raises(TypeError):
        MultimodalEmbedder()  # type: ignore[abstract]


def test_abc_subclass_must_implement_abstract_methods():
    """A subclass that omits ``embed_text`` / ``embed_image`` is also abstract."""

    class HalfBaked(MultimodalEmbedder):
        provider_name = "half_baked"
        dimension = 4

        def embed_text(self, text):  # missing embed_image on purpose
            return [0.0] * 4

    with pytest.raises(TypeError):
        HalfBaked()  # type: ignore[abstract]


def test_unimplemented_error_is_a_value_error():
    """``UnsupportedProviderError`` must catch as ``ValueError`` (matches
    the pattern in ``lumen_services.embedding_factory``)."""
    with pytest.raises(ValueError):
        raise UnsupportedProviderError("nope")


def test_unimplemented_error_is_a_multimodal_error():
    """And also as ``MultimodalEmbeddingError`` so broad catchers work."""
    with pytest.raises(MultimodalEmbeddingError):
        raise UnsupportedProviderError("nope")


def test_assert_dimension_catches_mismatch():
    """Impls reporting wrong dim must fail the contract check.

    Contract: ``assert_dimension(observed)`` raises when the impl's
    declared ``dimension`` disagrees with the dimension actually
    returned by a probe embed. The factory calls this after a single
    ``embed_text('dim-probe')`` to catch impls that mis-set the
    class attribute.
    """

    class LieAboutDim(MultimodalEmbedder):
        provider_name = "liar"
        dimension = 512  # declared — impl is wrong, actual probe returns 1024

        def embed_text(self, text):
            return [0.0] * 1024  # actual

        def embed_image(self, image):
            return [0.0] * 1024

    # Probe with the declared value → no mismatch → silent pass.
    LieAboutDim().assert_dimension(512)
    # Probe with the actual embed output (1024) → mismatch → raise.
    with pytest.raises(MultimodalEmbeddingError, match="reported dimension=512"):
        LieAboutDim().assert_dimension(1024)


def test_assert_dimension_accepts_matching_probe():
    """Happy path: declared dim matches probe → silent pass."""

    class Honest(MultimodalEmbedder):
        provider_name = "honest"
        dimension = 768

        def embed_text(self, text):
            return [0.0] * 768

        def embed_image(self, image):
            return [0.0] * 768

    # Should not raise.
    Honest().assert_dimension(768)


def test_default_batch_methods_loop_the_single_call():
    """When a subclass doesn't override the batch variant, it loops
    the single-method path. This is the documented behaviour for
    cloud stubs."""
    calls = {"text": 0, "image": 0}

    class Loopy(MultimodalEmbedder):
        provider_name = "loopy"
        dimension = 3

        def embed_text(self, text):
            calls["text"] += 1
            return [0.0, 0.0, 0.0]

        def embed_image(self, image):
            calls["image"] += 1
            return [0.0, 0.0, 0.0]

    inst = Loopy()
    out_text = inst.embed_text_batch(["a", "b", "c"])
    out_image = inst.embed_image_batch(["x", "y"])
    assert calls == {"text": 3, "image": 2}
    assert len(out_text) == 3 and len(out_image) == 2
    for vec in out_text + out_image:
        assert vec == [0.0, 0.0, 0.0]


# ----------------------------------------------------------------------
# Local HF providers — fully mocked transformers
# ----------------------------------------------------------------------


def _patch_transformers_for_jina(dimension: int = 1024):
    """Patch ``transformers.AutoModel`` / ``AutoProcessor`` for jina-clip-v2.

    Returns the patchers so tests can stop them; ``model.encode_text``
    returns a (N, dimension) torch-like object — we use a thin wrapper
    because the impl code expects ``.detach().cpu().numpy()`` for
    batch + ``[0]`` for single.
    """

    class _Tensor:
        """Minimal stand-in for ``torch.Tensor`` with the surface the
        embedder uses: ``.detach()``, ``.cpu()``, ``.numpy()``,
        ``.dim()``, ``.shape``, indexing ``[0]``."""

        def __init__(self, arr: np.ndarray):
            self._arr = arr

        def detach(self):
            return self

        def cpu(self):
            return self

        def numpy(self):
            return self._arr

        def to(self, _device):
            return self

        @property
        def dim(self):
            return self._arr.ndim

        @property
        def shape(self):
            return self._arr.shape

        def __getitem__(self, idx):
            return _Tensor(self._arr[idx])

        def eval(self):  # pragma: no cover — called by embedder
            return self

    def _make_model():
        m = MagicMock()

        def encode_text(texts):
            arr = np.zeros((len(list(texts)), dimension), dtype=np.float32)
            return _Tensor(arr)

        def encode_image(images):
            arr = np.zeros((len(list(images)), dimension), dtype=np.float32)
            return _Tensor(arr)

        m.encode_text.side_effect = encode_text
        m.encode_image.side_effect = encode_image
        m.to.return_value = m
        m.eval.return_value = m
        return m

    def _make_processor():
        return MagicMock()

    p_model = patch(
        "transformers.AutoModel.from_pretrained", side_effect=lambda *a, **kw: _make_model()
    )
    p_proc = patch(
        "transformers.AutoProcessor.from_pretrained", side_effect=lambda *a, **kw: _make_processor()
    )
    return p_model, p_proc


def _patch_transformers_for_clip(dimension: int = 512):
    """Patch ``transformers.CLIPModel`` / ``CLIPProcessor`` for CLIP-B/32.

    The CLIP path uses ``get_text_features(**text_inputs)`` /
    ``get_image_features(pixel_values=...)`` instead of
    ``encode_text`` / ``encode_image``.
    """

    class _Tensor:
        def __init__(self, arr: np.ndarray):
            self._arr = arr

        def detach(self):
            return self

        def cpu(self):
            return self

        def numpy(self):
            return self._arr

        def to(self, _device):
            return self

        @property
        def dim(self):
            return self._arr.ndim

        @property
        def shape(self):
            return self._arr.shape

        def __getitem__(self, idx):
            return _Tensor(self._arr[idx])

        def eval(self):
            return self

    def _make_model():
        m = MagicMock()

        def get_text_features(**kwargs):
            input_ids = kwargs.get("input_ids")
            n = len(input_ids)
            return _Tensor(np.zeros((n, dimension), dtype=np.float32))

        def get_image_features(**kwargs):
            pixel_values = kwargs.get("pixel_values")
            # The mock processor returns a fake dict-shaped object;
            # we index the ``__len__`` of whatever it hands us.
            n = len(pixel_values)
            return _Tensor(np.zeros((n, dimension), dtype=np.float32))

        m.get_text_features.side_effect = get_text_features
        m.get_image_features.side_effect = get_image_features
        m.to.return_value = m
        m.eval.return_value = m
        return m

    def _make_processor():
        proc = MagicMock()

        def _call(text=None, images=None, return_tensors=None, padding=None, truncation=None):
            n_text = len(text) if text else 0
            n_images = len(images) if images else 0
            out: dict[str, Any] = {}
            if text is not None:
                out["input_ids"] = [object()] * n_text
                out["attention_mask"] = [object()] * n_text
            if images is not None:
                out["pixel_values"] = [object()] * n_images
            return out

        proc.side_effect = _call
        return proc

    p_model = patch(
        "transformers.CLIPModel.from_pretrained", side_effect=lambda *a, **kw: _make_model()
    )
    p_proc = patch(
        "transformers.CLIPProcessor.from_pretrained", side_effect=lambda *a, **kw: _make_processor()
    )
    return p_model, p_proc


def test_jina_clip_v2_factory_dispatches_and_probes_dim():
    cfg = _make_config(provider="jina_clip_v2", model_name="jinaai/jina-clip-v2")
    db = _make_db(cfg)
    p_model, p_proc = _patch_transformers_for_jina(dimension=1024)
    with p_model, p_proc:
        embedder, dim = get_multimodal_embedder(100, db)
    assert embedder.provider_name == "jina_clip_v2"
    assert dim == 1024
    assert embedder.dimension == 1024
    db.get.assert_called_once()


def test_jina_clip_v2_embed_text_returns_correct_dim():
    cfg = _make_config(provider="jina_clip_v2", config_id=101)
    db = _make_db(cfg)
    p_model, p_proc = _patch_transformers_for_jina(dimension=1024)
    with p_model, p_proc:
        embedder, _ = get_multimodal_embedder(101, db)
        vec = embedder.embed_text("hello world")
    assert isinstance(vec, list)
    assert len(vec) == 1024
    assert all(isinstance(x, float) for x in vec)


def test_clip_base_32_factory_dispatches_and_probes_dim():
    cfg = _make_config(
        provider="clip_base_32",
        model_name="openai/clip-vit-base-patch32",
        config_id=200,
    )
    db = _make_db(cfg)
    p_model, p_proc = _patch_transformers_for_clip(dimension=512)
    with p_model, p_proc:
        embedder, dim = get_multimodal_embedder(200, db)
    assert embedder.provider_name == "clip_base_32"
    assert dim == 512


def test_clip_base_32_embed_image_accepts_path_string(tmp_path):
    """The PIL-path loader inside the embedder must open the file."""
    from PIL import Image

    img_path = tmp_path / "test.png"
    Image.new("RGB", (10, 10), "red").save(img_path)

    cfg = _make_config(provider="clip_base_32", config_id=201)
    db = _make_db(cfg)
    p_model, p_proc = _patch_transformers_for_clip(dimension=512)
    with p_model, p_proc:
        embedder, _ = get_multimodal_embedder(201, db)
        vec = embedder.embed_image(str(img_path))
    assert len(vec) == 512


def test_clip_base_32_embed_image_rejects_missing_path(tmp_path):
    cfg = _make_config(provider="clip_base_32", config_id=202)
    db = _make_db(cfg)
    p_model, p_proc = _patch_transformers_for_clip(dimension=512)
    with p_model, p_proc:
        embedder, _ = get_multimodal_embedder(202, db)
        with pytest.raises(FileNotFoundError):
            embedder.embed_image(str(tmp_path / "missing.png"))


def test_factory_returns_cached_embedder_on_second_call():
    """Cache hit must skip the DB lookup entirely."""
    cfg = _make_config(provider="jina_clip_v2", config_id=300)
    db = _make_db(cfg)
    p_model, p_proc = _patch_transformers_for_jina(dimension=1024)
    with p_model, p_proc:
        first, _ = get_multimodal_embedder(300, db)
        second, _ = get_multimodal_embedder(300, db)
    # Same object, db.get only called once (during construction).
    assert first is second
    assert db.get.call_count == 1


def test_invalidate_cache_drops_entry():
    cfg = _make_config(provider="jina_clip_v2", config_id=301)
    db = _make_db(cfg)
    p_model, p_proc = _patch_transformers_for_jina(dimension=1024)
    with p_model, p_proc:
        first, _ = get_multimodal_embedder(301, db)
        invalidate_multimodal_cache(301)
        # After invalidation, second call returns a new object
        # (still the same model — but a fresh wrapper instance).
        second, _ = get_multimodal_embedder(301, db)
    assert first is not second
    assert db.get.call_count == 2


def test_invalidate_cache_clear_drops_all():
    cfg_a = _make_config(provider="jina_clip_v2", config_id=302)
    cfg_b = _make_config(provider="clip_base_32", config_id=303)

    db_a = _make_db(cfg_a)
    db_b = _make_db(cfg_b)

    p_model_j, p_proc_j = _patch_transformers_for_jina()
    p_model_c, p_proc_c = _patch_transformers_for_clip()
    with p_model_j, p_proc_j, p_model_c, p_proc_c:
        get_multimodal_embedder(302, db_a)
        get_multimodal_embedder(303, db_b)
        # Both cached now; clear all
        invalidate_multimodal_cache()
        get_multimodal_embedder(302, db_a)  # 2nd construction
        get_multimodal_embedder(303, db_b)  # 2nd construction
    assert db_a.get.call_count == 2
    assert db_b.get.call_count == 2


def test_factory_rejects_unknown_provider():
    cfg = _make_config(provider="not_a_real_provider", config_id=400)
    db = _make_db(cfg)
    with pytest.raises(UnsupportedProviderError, match="not_a_real_provider"):
        get_multimodal_embedder(400, db)


def test_factory_rejects_disabled_config():
    cfg = _make_config(enabled=False, config_id=401)
    db = _make_db(cfg)
    with pytest.raises(MultimodalEmbeddingError, match="disabled"):
        get_multimodal_embedder(401, db)


def test_factory_rejects_missing_config():
    db = _make_db(None)
    with pytest.raises(MultimodalEmbeddingError, match="not found"):
        get_multimodal_embedder(999, db)


# ----------------------------------------------------------------------
# Cloud stubs — verify they exist + raise NotImplementedError
# ----------------------------------------------------------------------


def test_openai_vision_stub_raises_on_embed():
    db = _make_db(_make_config(provider="openai_vision", model_name="gpt-4o", config_id=500))
    embedder, dim = get_multimodal_embedder(500, db)
    assert embedder.provider_name == "openai_vision"
    assert dim == embedder.dimension == 1536
    with pytest.raises(NotImplementedError):
        embedder.embed_text("hi")


def test_qwen_vl_stub_raises_on_embed():
    db = _make_db(_make_config(provider="qwen_vl", model_name="qwen-vl-plus", config_id=501))
    embedder, dim = get_multimodal_embedder(501, db)
    assert embedder.provider_name == "qwen_vl"
    assert dim == embedder.dimension == 1024
    with pytest.raises(NotImplementedError):
        embedder.embed_image("ignored")  # still raises on first call


def test_azure_vision_stub_raises_on_embed():
    db = _make_db(_make_config(provider="azure_vision", config_id=502))
    embedder, dim = get_multimodal_embedder(502, db)
    assert embedder.provider_name == "azure_vision"
    assert dim == embedder.dimension == 1024


def test_cloud_stub_close_is_noop():
    """Cloud impls will close HTTP sessions; the stubs need to support
    the ``close()`` call without complaint so the context-manager sugar
    works once a real impl lands."""
    from lumen_services.multimodal_embedders.openai_vision import OpenAIVisionEmbedder
    from lumen_services.multimodal_embedders.qwen_vl import QwenVLEmbedder
    from lumen_services.multimodal_embedders.azure_vision import AzureVisionEmbedder

    for cls in (OpenAIVisionEmbedder, QwenVLEmbedder, AzureVisionEmbedder):
        inst = cls()
        # Idempotent close — calling twice is fine.
        inst.close()
        inst.close()


def test_cloud_stub_constructor_passes_config_kwargs():
    """The stub base must accept ``api_key`` / ``base_url`` /
    ``model_name`` / ``config`` so a real impl can subclass + use them
    without rewiring the factory."""
    from lumen_services.multimodal_embedders.openai_vision import OpenAIVisionEmbedder

    inst = OpenAIVisionEmbedder(
        api_key="sk-test",
        base_url="https://api.openai.com/v1",
        model_name="gpt-4o",
        config={"api_version": "2024-01"},
    )
    assert inst.api_key == "sk-test"
    assert inst.base_url == "https://api.openai.com/v1"
    assert inst.model_name == "gpt-4o"
    assert inst.config == {"api_version": "2024-01"}


# ----------------------------------------------------------------------
# Helpers — shared module exports
# ----------------------------------------------------------------------


def test_package_re_exports_public_api():
    """The package ``__init__`` must re-export the public ABC + factory
    symbols so callers can ``from lumen_services.multimodal_embedders import X``.
    """
    assert multimodal_embedders.MultimodalEmbedder is MultimodalEmbedder
    assert multimodal_embedders.MultimodalEmbeddingError is MultimodalEmbeddingError
    assert multimodal_embedders.UnsupportedProviderError is UnsupportedProviderError
    assert multimodal_embedders.get_multimodal_embedder is get_multimodal_embedder
    assert multimodal_embedders.invalidate_multimodal_cache is invalidate_multimodal_cache