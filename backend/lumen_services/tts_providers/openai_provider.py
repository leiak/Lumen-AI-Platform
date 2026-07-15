"""M35: OpenAI TTS provider (tts-1 / tts-1-hd, paid, opt-in).

Uses the official openai SDK. The ModelConfig stores ``api_key`` and
``base_url``; the provider reads them per-request (the SDK supports
custom base_url for Azure / proxies).

Voice options are the 6 OpenAI TTS voices (alloy/echo/fable/onyx/
nova/shimmer). Speed is passed through directly — OpenAI accepts
0.25 – 4.0.

Cost: $15 / 1M characters for tts-1, $30 / 1M for tts-1-hd
(verified 2026-07; update here if pricing changes).

Spec: docs-internal/superpowers/specs/M35-overview.md §3.4
"""
import logging
from typing import List, Optional, Dict, Any

log = logging.getLogger(__name__)

# OpenAI TTS pricing (per 1M characters). Verified 2026-07-14.
_PRICE_PER_1M = {
    "tts-1": 15.0,
    "tts-1-hd": 30.0,
}

_VOICES = [
    {"id": "alloy", "name": "Alloy", "language": "en-US", "gender": "neutral"},
    {"id": "echo", "name": "Echo", "language": "en-US", "gender": "male"},
    {"id": "fable", "name": "Fable", "language": "en-US", "gender": "neutral"},
    {"id": "onyx", "name": "Onyx", "language": "en-US", "gender": "male"},
    {"id": "nova", "name": "Nova", "language": "en-US", "gender": "female"},
    {"id": "shimmer", "name": "Shimmer", "language": "en-US", "gender": "female"},
]


class OpenAITTSProvider:
    """OpenAI TTS via the openai SDK (≥1.0)."""

    def __init__(self, model_config=None):
        self.model_config = model_config

    def _client(self):
        try:
            from openai import OpenAI
        except ImportError as e:
            raise RuntimeError(
                "openai SDK not installed. `pip install openai`"
            ) from e
        kwargs: Dict[str, Any] = {}
        if self.model_config and self.model_config.api_key:
            kwargs["api_key"] = self.model_config.api_key
        if self.model_config and self.model_config.base_url:
            kwargs["base_url"] = self.model_config.base_url
        return OpenAI(**kwargs)

    async def synthesize(
        self,
        *,
        text: str,
        voice: str = "alloy",
        speed: float = 1.0,
        format: str = "mp3",
    ) -> bytes:
        # OpenAI accepts: mp3, opus, aac, flac, wav, pcm
        valid_formats = {"mp3", "opus", "aac", "flac", "wav", "pcm"}
        if format not in valid_formats:
            log.warning("OpenAITTSProvider: format=%s unsupported, defaulting to mp3", format)
            format = "mp3"

        model_name = "tts-1"
        if self.model_config and self.model_config.model_name:
            model_name = self.model_config.model_name

        def _do_call() -> bytes:
            client = self._client()
            # OpenAI's SDK call is sync; we run it in a thread to keep
            # the event loop unblocked.
            response = client.audio.speech.create(
                model=model_name,
                voice=voice,
                input=text,
                speed=speed,
                response_format=format,
            )
            return response.read()

        import asyncio
        return await asyncio.to_thread(_do_call)

    def list_voices(self, language: Optional[str] = None) -> List[Dict[str, Any]]:
        if language is None or language == "en-US":
            return list(_VOICES)
        return []

    def estimate_cost(self, char_count: int) -> float:
        model_name = "tts-1"
        if self.model_config and self.model_config.model_name:
            model_name = self.model_config.model_name
        per_million = _PRICE_PER_1M.get(model_name, _PRICE_PER_1M["tts-1"])
        return round(char_count / 1_000_000 * per_million, 6)
