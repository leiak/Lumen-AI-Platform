"""M35: Edge TTS provider (Microsoft's edge-tts package).

Zero-cost, zero-API-key TTS via Microsoft Edge's online speech
service. Supports 100+ voices across zh-CN, en-US, ja-JP, etc.
The recommended M35 default.

The ``edge_tts.Communicate(text, voice).save()`` call streams MP3
bytes into a BytesIO — wrapped in ``asyncio.run`` so the sync
service entrypoint can ``await`` it.

Spec: docs-internal/superpowers/specs/M35-overview.md §3.2
"""
import asyncio
import io
import logging
from typing import List, Optional, Dict, Any

log = logging.getLogger(__name__)

# Curated voice list — 4 zh + 4 en. Picking from 100+ available voices
# is a UI problem (long list, hard to search); the spec calls for a
# focused 8 to ship with. Admins can extend later via a custom
# voice-set seed.
_CURATED_VOICES = [
    {"id": "zh-CN-XiaoxiaoNeural", "name": "晓晓 (Xiaoxiao)", "language": "zh-CN", "gender": "female"},
    {"id": "zh-CN-YunxiNeural", "name": "云希 (Yunxi)", "language": "zh-CN", "gender": "male"},
    {"id": "zh-CN-YunjianNeural", "name": "云健 (Yunjian)", "language": "zh-CN", "gender": "male"},
    {"id": "zh-CN-XiaoyiNeural", "name": "晓伊 (Xiaoyi)", "language": "zh-CN", "gender": "female"},
    {"id": "en-US-JennyNeural", "name": "Jenny", "language": "en-US", "gender": "female"},
    {"id": "en-US-GuyNeural", "name": "Guy", "language": "en-US", "gender": "male"},
    {"id": "en-US-AriaNeural", "name": "Aria", "language": "en-US", "gender": "female"},
    {"id": "en-US-DavisNeural", "name": "Davis", "language": "en-US", "gender": "male"},
]


class EdgeTTSProvider:
    """Wraps the edge-tts package. Always returns MP3 bytes."""

    def __init__(self, model_config=None):
        self.model_config = model_config

    async def synthesize(
        self,
        *,
        text: str,
        voice: str = "zh-CN-XiaoxiaoNeural",
        speed: float = 1.0,
        format: str = "mp3",
    ) -> bytes:
        try:
            import edge_tts
        except ImportError as e:
            raise RuntimeError(
                "edge-tts package not installed. `pip install edge-tts`"
            ) from e

        # edge-tts Communicate() doesn't accept format directly; it
        # produces MP3 by default. rate= param adjusts speed.
        # 0% = 1.0x, +10% = 1.1x, -20% = 0.8x.
        rate_percent = int(round((speed - 1.0) * 100))
        rate = f"{rate_percent:+d}%"

        comm = edge_tts.Communicate(text=text, voice=voice, rate=rate)
        buf = io.BytesIO()
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                buf.write(chunk["data"])
        data = buf.getvalue()
        if not data:
            raise RuntimeError(
                f"edge-tts returned empty audio for voice={voice!r} text={text[:50]!r}"
            )
        return data

    def list_voices(self, language: Optional[str] = None) -> List[Dict[str, Any]]:
        if language is None:
            return list(_CURATED_VOICES)
        return [v for v in _CURATED_VOICES if v["language"] == language]

    def estimate_cost(self, char_count: int) -> float:
        return 0.0
