"""M38.4 Step 7 / 2.0 spec A4 (2026-09-07): real qwen_vl DashScope + mock fallback tests.

Covers ``QwenVLMultimodalEmbedder``'s contract:

- **Mock path (default)**: deterministic SHA-256, 1024-dim unit vector,
  works without ``DASHSCOPE_API_KEY``.
- **Real path**: DashScope HTTP call shape — URL, headers, body,
  response parsing, error surfacing.
- **Factory wiring**: dim-probe runs (no longer skipped as a stub) and
  caches via the shared ``get_multimodal_embedder`` entry point.
- **Lifecycle**: ``close()`` is idempotent.

The DashScope HTTP call is mocked with ``unittest.mock.patch`` on
``httpx.Client.post`` so tests stay hermetic — no key required, no
network. The real API is documented in the class docstring.
"""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest


# Force-mock for the mock-path tests so we never accidentally hit the
# real network even if a developer has DASHSCOPE_API_KEY in env.
@pytest.fixture(autouse=True)
def _force_mock(monkeypatch):
    monkeypatch.setenv("QWEN_VL_USE_MOCK", "true")
    # Clear any pre-set key so the fixture explicitly opts out.
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)


def _import_embedder():
    from lumen_services.multimodal_embedders.qwen_vl import QwenVLMultimodalEmbedder

    return QwenVLMultimodalEmbedder


# ---------------------------------------------------------------------
# Mock path
# ---------------------------------------------------------------------


def test_embed_text_mock_returns_1024_dim():
    cls = _import_embedder()
    inst = cls()
    vec = inst.embed_text("hello world")
    assert isinstance(vec, list)
    assert len(vec) == 1024


def test_embed_text_mock_deterministic_same_input_same_vec():
    """Hash-based mock: SHA-256 is stable, so the same bytes → same vec."""
    cls = _import_embedder()
    inst = cls()
    a = inst.embed_text("identical input")
    b = inst.embed_text("identical input")
    assert a == b


def test_embed_text_mock_different_input_different_vec():
    cls = _import_embedder()
    inst = cls()
    a = inst.embed_text("alpha")
    b = inst.embed_text("beta")
    assert a != b


def test_embed_text_mock_normalized_unit_length():
    """Cosine similarity math needs unit-length vectors — assert ||v||≈1."""
    cls = _import_embedder()
    inst = cls()
    vec = inst.embed_text("normalised?")
    norm = sum(x * x for x in vec) ** 0.5
    assert abs(norm - 1.0) < 1e-9


def test_embed_image_mock_from_bytes_returns_1024_dim():
    cls = _import_embedder()
    inst = cls()
    vec = inst.embed_image(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
    assert len(vec) == 1024


def test_embed_image_mock_from_path(tmp_path):
    cls = _import_embedder()
    inst = cls()
    p = tmp_path / "fake.png"
    p.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 50)
    vec = inst.embed_image(str(p))
    assert len(vec) == 1024


def test_embed_image_mock_from_pil_image():
    """PIL.Image.Image path goes through _coerce_image_bytes → PNG."""
    from PIL import Image

    cls = _import_embedder()
    inst = cls()
    img = Image.new("RGB", (16, 16), color=(128, 128, 128))
    vec = inst.embed_image(img)
    assert len(vec) == 1024


def test_embed_image_unsupported_type_raises():
    cls = _import_embedder()
    inst = cls()
    with pytest.raises(Exception) as exc_info:
        inst.embed_image(42)  # int has no .save / no str path
    # MultimodalEmbeddingError is the ABC's contract; permissive check
    # covers both the explicit raise and any attribute-lookup path.
    assert "Unsupported" in str(exc_info.value) or "save" in str(exc_info.value)


# ---------------------------------------------------------------------
# Real path — HTTP mocked, no actual network call
# ---------------------------------------------------------------------


def _build_with_real_api_key(monkeypatch, api_key="sk-test-key"):
    """Helper: build an embedder that will exercise the real-API branch."""
    monkeypatch.setenv("QWEN_VL_USE_MOCK", "false")
    monkeypatch.setenv("DASHSCOPE_API_KEY", api_key)
    cls = _import_embedder()
    return cls(api_key=api_key)


def test_embed_text_real_calls_dashscope_with_correct_shape(monkeypatch):
    embedder = _build_with_real_api_key(monkeypatch)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "output": {"embeddings": [{"embedding": [0.1] * 1024}]}
    }

    with patch("httpx.Client.post", return_value=mock_resp) as mock_post:
        vec = embedder.embed_text("hello dashscope")

    assert len(vec) == 1024
    assert mock_post.call_count == 1
    # URL + headers + body assertions
    call_kwargs = mock_post.call_args.kwargs
    assert call_kwargs["headers"]["Authorization"] == "Bearer sk-test-key"
    assert call_kwargs["headers"]["Content-Type"] == "application/json"
    body = call_kwargs["json"]
    assert body["model"] == "multimodal-embedding-v1"
    assert body["input"]["contents"] == [{"text": "hello dashscope"}]
    # URL ends with the canonical DashScope path
    called_url = mock_post.call_args.args[0]
    assert called_url.endswith(
        "/api/v1/services/embeddings/multimodal-embedding/multimodal-embedding"
    )


def test_embed_image_real_sends_base64_data_url(monkeypatch):
    """embed_image must wrap bytes as data:image/png;base64,...."""
    embedder = _build_with_real_api_key(monkeypatch)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "output": {"embeddings": [{"embedding": [0.0] * 1024}]}
    }

    raw_bytes = b"\x89PNG\r\n\x1a\n" + b"\xff" * 32
    with patch("httpx.Client.post", return_value=mock_resp) as mock_post:
        vec = embedder.embed_image(raw_bytes)

    assert len(vec) == 1024
    body = mock_post.call_args.kwargs["json"]
    contents = body["input"]["contents"]
    assert len(contents) == 1
    image_field = contents[0]["image"]
    assert image_field.startswith("data:image/png;base64,")
    # The base64 payload should be the round-trip of our raw bytes.
    import base64

    decoded = base64.b64decode(image_field.split(",", 1)[1])
    assert decoded == raw_bytes


def test_embed_image_real_from_path_reads_then_base64s(monkeypatch, tmp_path):
    embedder = _build_with_real_api_key(monkeypatch)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "output": {"embeddings": [{"embedding": [0.5] * 1024}]}
    }

    p = tmp_path / "x.png"
    p.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\xab" * 8)

    with patch("httpx.Client.post", return_value=mock_resp) as mock_post:
        embedder.embed_image(str(p))

    body = mock_post.call_args.kwargs["json"]
    image_field = body["input"]["contents"][0]["image"]
    assert image_field.startswith("data:image/png;base64,")


def test_api_non_200_raises_multimodal_embedding_error(monkeypatch):
    from lumen_services.multimodal_embedders.base import MultimodalEmbeddingError

    embedder = _build_with_real_api_key(monkeypatch)
    mock_resp = MagicMock()
    mock_resp.status_code = 401
    mock_resp.text = "Unauthorized: invalid api key"

    with patch("httpx.Client.post", return_value=mock_resp):
        with pytest.raises(MultimodalEmbeddingError) as exc_info:
            embedder.embed_text("hi")
    assert "401" in str(exc_info.value)
    assert "Unauthorized" in str(exc_info.value)


def test_api_malformed_body_raises_multimodal_embedding_error(monkeypatch):
    """Missing output.embeddings[0].embedding → surfaced as config error."""
    from lumen_services.multimodal_embedders.base import MultimodalEmbeddingError

    embedder = _build_with_real_api_key(monkeypatch)
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = '{"foo": "bar"}'
    mock_resp.json.return_value = {"foo": "bar"}  # missing output key

    with patch("httpx.Client.post", return_value=mock_resp):
        with pytest.raises(MultimodalEmbeddingError) as exc_info:
            embedder.embed_text("hi")
    assert "missing output" in str(exc_info.value).lower()


def test_close_is_idempotent(monkeypatch):
    """close() called twice should be a no-op (no AttributeError)."""
    embedder = _build_with_real_api_key(monkeypatch)
    # First close — client was never opened, but the impl is robust to that.
    embedder.close()
    embedder.close()
    assert embedder._client is None


# ---------------------------------------------------------------------
# Constructor behaviour
# ---------------------------------------------------------------------


def test_use_mock_falls_back_when_api_key_absent(monkeypatch):
    """No DASHSCOPE_API_KEY + QWEN_VL_USE_MOCK unset → mock path."""
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    monkeypatch.delenv("QWEN_VL_USE_MOCK", raising=False)
    cls = _import_embedder()
    inst = cls()
    assert inst._use_mock is True


def test_use_mock_explicit_env_overrides_api_key(monkeypatch):
    """QWEN_VL_USE_MOCK=true wins even when DASHSCOPE_API_KEY is set."""
    monkeypatch.setenv("QWEN_VL_USE_MOCK", "true")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-should-be-ignored")
    cls = _import_embedder()
    inst = cls()
    assert inst._use_mock is True


def test_env_api_key_picked_up_when_constructor_arg_absent(monkeypatch):
    """Constructor may omit api_key; impl reads env DASHSCOPE_API_KEY."""
    monkeypatch.setenv("QWEN_VL_USE_MOCK", "false")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-env-key")
    cls = _import_embedder()
    inst = cls()
    assert inst.api_key == "sk-env-key"


def test_constructor_passes_config_kwargs():
    """``_CloudStubEmbedder.__init__`` accepts api_key / base_url / model_name / config."""
    cls = _import_embedder()
    inst = cls(
        api_key="sk-test",
        base_url="https://example.com",
        model_name="custom-model",
        config={"region": "cn-hangzhou"},
    )
    assert inst.api_key == "sk-test"
    assert inst.base_url == "https://example.com"
    assert inst.model_name == "custom-model"
    assert inst.config == {"region": "cn-hangzhou"}


# ---------------------------------------------------------------------
# Factory integration
# ---------------------------------------------------------------------


def test_factory_dispatches_qwen_vl_with_mock_fallback(monkeypatch):
    """Real factory: qwen_vl provider → QwenVLMultimodalEmbedder, 1024 dim, cache hits."""
    from sqlalchemy.orm import Session

    from lumen_models.multimodal_embedding_config import MultimodalEmbeddingConfig
    from lumen_services.multimodal_embedders import factory
    from lumen_services.multimodal_embedders.qwen_vl import QwenVLMultimodalEmbedder

    monkeypatch.setenv("QWEN_VL_USE_MOCK", "true")
    factory.invalidate_multimodal_cache()  # clear any cross-test cache

    cfg = MultimodalEmbeddingConfig(
        id=99001,
        provider="qwen_vl",
        model_name="multimodal-embedding-v1",
        api_key="",
        base_url=None,
        config={},
        enabled=True,
    )

    mock_db = MagicMock(spec=Session)
    mock_db.get.return_value = cfg

    embedder, dim = factory.get_multimodal_embedder(99001, mock_db)
    assert isinstance(embedder, QwenVLMultimodalEmbedder)
    assert dim == 1024
    assert embedder.dimension == 1024

    # Second call hits cache (same config_id)
    embedder2, dim2 = factory.get_multimodal_embedder(99001, mock_db)
    assert embedder2 is embedder  # identity-equal: cached
    assert dim2 == 1024

    factory.invalidate_multimodal_cache()
