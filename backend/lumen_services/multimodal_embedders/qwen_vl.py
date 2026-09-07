"""M38.4 Step 7 / 2.0 spec A4 (2026-09-07): real qwen_vl DashScope multimodal-embedding.

Upgrades the M38.4 Step 3 stub (``_CloudStubEmbedder`` with ``is_stub=True``)
to a real impl that talks to DashScope's ``multimodal-embedding`` endpoint.
For dev environments without an ``DASHSCOPE_API_KEY``, the same class
falls back to a deterministic SHA-256-based mock so the factory can still
probe the dim and the API layer can still hand back meaningful vectors.

Env vars
--------
``DASHSCOPE_API_KEY``
    Required for real calls. Falls back to mock when unset.
``QWEN_VL_USE_MOCK``
    Defaults to ``"true"`` — explicit force-mock override; test fixtures
    flip this to ``"true"`` to keep CI hermetic.
``QWEN_VL_BASE_URL``
    Override the default Aliyun endpoint (mainly for testing or a private
    DashScope deployment). Default ``https://dashscope.aliyuncs.com``.

Real API contract
-----------------
``POST https://dashscope.aliyuncs.com/api/v1/services/embeddings/
multimodal-embedding/multimodal-embedding``

Body::

    {
      "model": "multimodal-embedding-v1",
      "input": {
        "contents": [
          {"text": "..."}            # for embed_text
          # OR
          {"image": "data:image/png;base64,..."}  # for embed_image
        ]
      }
    }

Response::

    {
      "output": {
        "embeddings": [{"embedding": [float, ...]}]
      }
    }

Dim: **1024** (matches the declared ``dimension`` so the factory's
``assert_dimension`` check stays honest).

Why mock instead of always-real
-------------------------------
The dev container has no Aliyun key, and we don't want a paid API call
on the critical path of every PDF upload (spec §10 risk 1 — "GPT-4V /
Qwen-VL API 成本高,默认走本地 ollama"). Default-on-mock keeps the
contract testable; admins who want the real call set the env vars and
restart the worker (no code change).
"""
from __future__ import annotations

import base64
import hashlib
import io
import os
from typing import Any, Dict, List, Union

import httpx

from .base import MultimodalEmbeddingError
from ._cloud_stub import _CloudStubEmbedder


# Default DashScope multimodal-embedding endpoint. Pinned by spec A4
# ("选 qwen_vl: API 文档最全").
_DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com"
_DEFAULT_MODEL = "multimodal-embedding-v1"
_QWEN_VL_DIM = 1024


def _truthy(raw: str | None) -> bool:
    """Parse a "force mock" env var tolerantly. Accepts true/1/yes/on (case-insensitive)."""
    if not raw:
        return False
    return raw.strip().lower() in {"1", "true", "yes", "on"}


class QwenVLMultimodalEmbedder(_CloudStubEmbedder):
    """Aliyun DashScope multimodal-embedding — real impl + mock fallback.

    ``is_stub = False`` so the factory's dim-probe actually invokes
    ``embed_text`` (cheap mock path; no network). The probe still
    exercises the contract — if a future refactor changes the dim, the
    factory's ``assert_dimension`` fires immediately.

    The HTTP client is lazy-initialised on first real call (mock path
    doesn't touch it). ``close()`` is idempotent so callers can pair it
    with the ABC's context-manager sugar.
    """

    provider_name: str = "qwen_vl"
    dimension: int = _QWEN_VL_DIM
    # M38.4 Step 7 / 2.0 spec A4 (2026-09-07): real impl — factory will
    # probe dim via a (cheap) mock embed; no more is_stub=True skip.
    is_stub: bool = False

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model_name: str | None = None,
        config: dict | None = None,
    ) -> None:
        super().__init__(
            api_key=api_key,
            base_url=base_url,
            model_name=model_name,
            config=config,
        )
        # Resolved at construction time so the embed-text fast path
        # doesn't re-read env on every call (vector chunking fires
        # embed_text_batch per doc — could be 100s of calls/minute).
        env_use_mock = _truthy(os.getenv("QWEN_VL_USE_MOCK"))
        env_key = os.getenv("DASHSCOPE_API_KEY", "").strip()
        # If the config didn't pass an api_key but the env has one,
        # pick it up so admins don't have to re-key every DB row.
        if not self.api_key and env_key:
            self.api_key = env_key
        # Mock when: env says so, OR no api_key configured anywhere.
        # (Env var wins — admins can force-mock even after wiring a key.)
        self._use_mock = env_use_mock or not (self.api_key or "")
        self._base_url = (
            self.base_url
            or os.getenv("QWEN_VL_BASE_URL")
            or _DEFAULT_BASE_URL
        ).rstrip("/")
        self._client: httpx.Client | None = None

    # ------------------------------------------------------------------
    # HTTP client lifecycle
    # ------------------------------------------------------------------

    def _get_client(self) -> httpx.Client:
        """Lazy-construct the HTTP client on first real call.

        M38.1.x follow-up #2 (`2179c8d`) mirrored this pattern: keep the
        network resource out of ``__init__`` so test fixtures that never
        touch the network don't accidentally open a socket.
        """
        if self._client is None:
            # 30 s timeout covers a slow Aliyun API call (spec A4 said
            # P99 ≈ 8 s for the embedding endpoint). Increase if your
            # target KB has very large PPT slides — base64 of a 4096×4096
            # PNG ≈ 8 MB at the request body.
            self._client = httpx.Client(timeout=30)
        return self._client

    def close(self) -> None:
        """Idempotent resource release. Safe to call multiple times."""
        if self._client is not None:
            self._client.close()
            self._client = None

    # ------------------------------------------------------------------
    # Public API: embed_text / embed_image
    # ------------------------------------------------------------------

    def embed_text(self, text: str) -> List[float]:
        """Embed a single text via DashScope (or mock if configured).

        The mock path always succeeds and returns a 1024-dim unit vector
        derived from SHA-256(text). Two calls with the same input give
        the same vector — handy for test assertions.
        """
        if self._use_mock:
            return self._mock_embed(text.encode("utf-8"))
        return self._call_api({"text": text})

    def embed_image(
        self, image: Union["PIL.Image.Image", str, bytes]
    ) -> List[float]:
        """Embed a single image via DashScope (or mock).

        Accepts:
        - ``str`` filesystem path (loaded eagerly — smaller, single read)
        - ``bytes`` raw image bytes (PNG / JPEG; we re-encode for the API)
        - ``PIL.Image.Image`` (PNG-encoded into bytes before upload)

        Real-API path re-encodes as PNG so the size + content-type sent
        to DashScope is deterministic; this matches what the jina-clip-v2
        local impl does in ``_encode_image`` so retrieval semantics stay
        consistent regardless of input format.
        """
        img_bytes = self._coerce_image_bytes(image)
        if self._use_mock:
            return self._mock_embed(img_bytes)
        b64 = base64.b64encode(img_bytes).decode("ascii")
        return self._call_api({"image": f"data:image/png;base64,{b64}"})

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _mock_embed(payload: bytes) -> List[float]:
        """Deterministic mock: SHA-256(payload) × 32 → 1024-dim unit vec.

        The same bytes always produce the same vector, so tests can
        assert specific output values (subject to a hash-function
        version pin — SHA-256 is in the FIPS-180 standard and isn't
        changing under us). L2-normalised to keep cosine similarity
        values in the same range as the real API.
        """
        h = hashlib.sha256(payload).digest()  # 32 bytes
        raw = (h * 32)[:_QWEN_VL_DIM]  # 32 × 32 = 1024 bytes
        # Map unsigned bytes [0, 255] → signed [-1, 1].
        vec = [(b - 128) / 128.0 for b in raw]
        norm = sum(x * x for x in vec) ** 0.5 or 1.0
        return [x / norm for x in vec]

    @staticmethod
    def _coerce_image_bytes(image: Union["PIL.Image.Image", str, bytes]) -> bytes:
        """Normalise the three accepted image input types to PNG bytes."""
        if isinstance(image, bytes):
            return image
        if isinstance(image, str):
            with open(image, "rb") as f:
                return f.read()
        # PIL.Image path — encode to PNG. Importing PIL locally keeps
        # the cloud embedder module importable on machines that never
        # process images (M38.1.x memory: keep heavy imports out of
        # __init__ when the class can be constructed without them).
        try:
            from PIL import Image as _PILImage  # type: ignore
        except ImportError as exc:  # pragma: no cover - tested via test_qwen_vl_embedder
            raise MultimodalEmbeddingError(
                "PIL not installed; cannot coerce PIL image to PNG bytes"
            ) from exc
        if not hasattr(image, "save"):
            raise MultimodalEmbeddingError(
                f"Unsupported image type for qwen_vl embed: {type(image).__name__}"
            )
        buf = io.BytesIO()
        image.save(buf, format="PNG")
        return buf.getvalue()

    def _call_api(self, content: Dict[str, str]) -> List[float]:
        """One HTTP round-trip to DashScope's multimodal-embedding.

        Raises:
            MultimodalEmbeddingError on transport failure, non-200 status,
            or a body shape that doesn't carry ``output.embeddings[0].embedding``.
        """
        client = self._get_client()
        url = (
            f"{self._base_url}/api/v1/services/embeddings/"
            f"multimodal-embedding/multimodal-embedding"
        )
        body = {
            "model": self.model_name or _DEFAULT_MODEL,
            "input": {"contents": [content]},
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        try:
            resp = client.post(url, headers=headers, json=body)
        except httpx.HTTPError as exc:
            raise MultimodalEmbeddingError(
                f"qwen_vl DashScope request failed: {exc}"
            ) from exc
        if resp.status_code != 200:
            # Truncate body so logs don't blow up on a 5xx HTML page.
            raise MultimodalEmbeddingError(
                f"qwen_vl DashScope returned status={resp.status_code} "
                f"body={resp.text[:200]!r}"
            )
        try:
            data: Dict[str, Any] = resp.json()
            embedding = data["output"]["embeddings"][0]["embedding"]
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise MultimodalEmbeddingError(
                f"qwen_vl DashScope response missing output.embeddings[0].embedding: "
                f"{exc}; body={resp.text[:200]!r}"
            ) from exc
        if not isinstance(embedding, list) or not all(
            isinstance(x, (int, float)) for x in embedding
        ):
            raise MultimodalEmbeddingError(
                f"qwen_vl DashScope returned non-numeric embedding: "
                f"{type(embedding).__name__}"
            )
        return [float(x) for x in embedding]
