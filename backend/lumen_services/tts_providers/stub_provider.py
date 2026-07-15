"""M35: stub TTS provider — returns a 1-second silence WAV.

Used when:
- model_type is unknown (factory fallback)
- a unit test wants to exercise the service layer without hitting Edge
  TTS / OpenAI / Piper

Generates the smallest valid 16-bit PCM mono WAV (8000 samples × 2
bytes = 16 KB silence) using the stdlib ``wave`` module so there are
no extra dependencies.

The bytes are wrapped in a CStringIO since ``wave.open`` needs a
file-like object supporting ``seek``.
"""
import io
import logging
import struct
import wave
from typing import List, Optional, Dict, Any

log = logging.getLogger(__name__)

_SILENCE_SAMPLE_RATE = 8000
_SILENCE_DURATION_SEC = 1


class StubTTSProvider:
    """Returns a 1-second mono 8 kHz 16-bit silence WAV.

    The 1-second duration is a useful sentinel for the duration_ms
    probe (ffprobe) and the audio player — anything > 0 ms is enough
    to distinguish "completed" from "pending" in the UI.
    """

    def __init__(self, model_config=None):
        self.model_config = model_config

    async def synthesize(
        self,
        *,
        text: str,
        voice: str = "default",
        speed: float = 1.0,
        format: str = "wav",
    ) -> bytes:
        log.warning(
            "StubTTSProvider used — model_config_id=%s, model_type=%s. "
            "Configure a real provider (edge/piper/openai) for actual TTS.",
            getattr(self.model_config, "id", None),
            getattr(self.model_config, "model_type", None),
        )
        n_samples = int(_SILENCE_SAMPLE_RATE * _SILENCE_DURATION_SEC)
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(_SILENCE_SAMPLE_RATE)
            wf.writeframes(b"\x00\x00" * n_samples)
        return buf.getvalue()

    def list_voices(self, language: Optional[str] = None) -> List[Dict[str, Any]]:
        return [
            {"id": "default", "name": "Default Silence", "language": "en-US", "gender": "neutral"},
        ]

    def estimate_cost(self, char_count: int) -> float:
        return 0.0
