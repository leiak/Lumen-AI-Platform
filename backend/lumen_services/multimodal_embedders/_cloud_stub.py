"""Cloud-provider scaffold shared by ``openai_vision`` / ``qwen_vl`` /
``azure_vision``.

The cloud providers all need:

- A bearer / subscription key loaded from the config row (already
  encrypted in :class:`MultimodalEmbeddingConfig.api_key`)
- An HTTP client wrapper with the right base URL (Azure needs a
  region + deployment suffix; Qwen uses an Aliyun endpoint)
- A request body that names the model, embeds a base64 / URL image,
  and asks for ``embedding`` task output

We keep that wiring in one shared scaffold so each provider file only
states what's unique (the API URL path + request shape), instead of
copy-pasting the same config-loader / error-handler boilerplate three
times.

All three providers are **MVP stubs**: ``embed_text`` / ``embed_image``
raise :class:`NotImplementedError` with a message pointing at the
provider file and spec §"开放问题 1". Wiring them into the factory
keeps the schema consistent (every enum value resolves a class), and
swapping a stub for a real impl is a single-file change.

Why stubs instead of full impls:

- No dev API keys — the project has been on ollama + HuggingFace since
  day one, and adding a paid cloud call without testing it would be
  reckless (spec §10 risk 1 — "GPT-4V / Qwen-VL API 成本高,默认走
  本地 ollama").
- The KB / parser / frontend layers don't yet need cross-cloud
  diversity — they need *one* working impl (jina-clip-v2). Adding three
  cloud impls at the same time would multiply test + ops surface without
  unlocking any feature.
- The factory ships with the dispatch wired, so future work can drop
  in a real OpenAI / Qwen / Azure call by replacing one method body
  without touching any caller.
"""
from __future__ import annotations

from .base import MultimodalEmbedder


class _CloudStubEmbedder(MultimodalEmbedder):
    """Common base for the three cloud-provider stubs.

    Subclasses set ``dimension`` and ``provider_name`` and override the
    HTTP-call method (or implement ``embed_text`` / ``embed_image``
    directly when their API differs enough from the template).

    Construction accepts the standard ``MultimodalEmbeddingConfig``
    fields (``api_key``, ``base_url``, ``model_name``, ``config`` JSON)
    so a real impl can subclass + use them without rewiring the factory.

    The ``is_stub = True`` marker is read by the factory's dim-probe —
    a real model can be probed to verify its dim; a stub can't, so
    the factory trusts the declared ``dimension`` instead.
    """

    provider_name: str = "cloud_stub"
    dimension: int = 0  # subclasses MUST override
    is_stub: bool = True

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model_name: str | None = None,
        config: dict | None = None,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url
        self.model_name = model_name
        self.config = config or {}

    def embed_text(self, text: str):  # type: ignore[override]
        raise NotImplementedError(
            f"{self.provider_name} cloud provider not yet implemented; "
            f"see lumen_services/multimodal_embedders/_cloud_stub.py"
        )

    def embed_image(self, image):  # type: ignore[override]
        raise NotImplementedError(
            f"{self.provider_name} cloud provider not yet implemented; "
            f"see lumen_services/multimodal_embedders/_cloud_stub.py"
        )

    def close(self) -> None:  # type: ignore[override]
        # Future-proof: cloud impls will close their HTTP client here.
        # Stubs have nothing to close.
        return