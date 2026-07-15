"""M35: TTS provider abstraction.

Mirrors lumen_services.image_providers (M22) — a Protocol describing
``synthesize(text, voice, speed, format) -> bytes`` plus voice
enumeration and cost estimation. Implementations live in
``stub_provider`` / ``edge_provider`` / ``piper_provider`` /
``openai_provider``.

Spec: docs-internal/superpowers/specs/M35-overview.md §3
"""
from typing import List, Optional, Dict, Any, Protocol


class TTSProvider(Protocol):
    """Provider that turns text + voice config into raw audio bytes.

    All methods are async because the actual HTTP / network calls
    (Edge TTS, OpenAI TTS) are async-friendly. Piper subprocess is
    wrapped in ``asyncio.to_thread`` so it doesn't block the event loop.
    """

    async def synthesize(
        self,
        *,
        text: str,
        voice: str,
        speed: float = 1.0,
        format: str = "mp3",
    ) -> bytes: ...

    def list_voices(self, language: Optional[str] = None) -> List[Dict[str, Any]]:
        """Return ``[{"id": "...", "name": "...", "language": "...", "gender": "..."}]``.

        Used by the TTS page's voice selector and ``GET /tts/voices``.
        """
        ...

    def estimate_cost(self, char_count: int) -> float:
        """Return a USD cost estimate for synthesizing ``char_count``
        characters. Edge TTS and Piper return ``0.0`` (free);
        OpenAI TTS returns ``char_count / 1000 * price_per_1k``.
        """
        ...
