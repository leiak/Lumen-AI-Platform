"""M35: Piper TTS provider (local on-device, no network).

Piper is a fast local neural TTS that runs on CPU. Models are
distributed as ``.onnx`` + ``.onnx.json`` files. We expect them to
live under ``storage/tts_models/piper/<voice>.onnx`` per the spec.

The actual call shells out to the ``piper`` CLI (assumed to be
installed in the container via ``apt install piper`` or a
pre-baked image layer). If the binary is missing, we raise a clear
``RuntimeError`` so the service can mark the row failed and the
admin sees "Piper not installed" instead of a generic 500.

Spec: docs-internal/superpowers/specs/M35-overview.md §3.3
"""
import asyncio
import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import List, Optional, Dict, Any

log = logging.getLogger(__name__)

# Storage root is shared with lumen_core.storage; Piper models live
# outside the ``generated_*`` tree because they're reference assets,
# not per-request outputs.
_DEFAULT_MODEL_DIR = Path("storage/tts_models/piper")


class PiperTTSProvider:
    """Local Piper TTS. Subprocess to the ``piper`` CLI."""

    def __init__(self, model_config=None):
        self.model_config = model_config
        # Resolve the model dir relative to backend cwd (which is where
        # uvicorn runs in dev). Tests can override via env var.
        self.model_dir = Path(
            os.environ.get("PIPER_MODEL_DIR", str(_DEFAULT_MODEL_DIR))
        )

    async def synthesize(
        self,
        *,
        text: str,
        voice: str = "en_US-amy-medium",
        speed: float = 1.0,
        format: str = "wav",
    ) -> bytes:
        piper_bin = shutil.which("piper")
        if piper_bin is None:
            raise RuntimeError(
                "piper binary not found on PATH. Install via `apt install piper` "
                "or add it to the lumen-platform-backend image."
            )
        onnx = self.model_dir / f"{voice}.onnx"
        if not onnx.exists():
            raise FileNotFoundError(
                f"Piper model file not found: {onnx}. "
                f"Download from https://github.com/rhasspy/piper/releases and "
                f"place under {self.model_dir}/."
            )
        # Piper writes WAV to --output_file. Speed is set via length_scale
        # on the model config (no CLI flag) — accepted as known limitation.
        # Format: always WAV (Piper doesn't emit MP3).
        out_path = self.model_dir / f"_tmp_{os.getpid()}.wav"
        try:
            proc = await asyncio.to_thread(
                subprocess.run,
                [
                    piper_bin,
                    "--model", str(onnx),
                    "--output_file", str(out_path),
                ],
                input=text.encode("utf-8"),
                capture_output=True,
                timeout=120,
                check=False,
            )
            if proc.returncode != 0:
                err = proc.stderr.decode("utf-8", errors="replace")[:500]
                raise RuntimeError(f"piper failed (rc={proc.returncode}): {err}")
            data = out_path.read_bytes()
        finally:
            if out_path.exists():
                out_path.unlink()
        if not data:
            raise RuntimeError(f"piper returned empty WAV for voice={voice!r}")
        return data

    def list_voices(self, language: Optional[str] = None) -> List[Dict[str, Any]]:
        if not self.model_dir.exists():
            return []
        out = []
        for f in sorted(self.model_dir.glob("*.onnx")):
            voice = f.stem
            # Crude language detection from the prefix (e.g. en_US-amy-medium
            # → en-US, zh_CN-... → zh-CN).
            lang = "en-US"
            if voice.startswith("zh_"):
                lang = "zh-CN"
            elif voice.startswith("en_"):
                lang = "en-US"
            elif voice.startswith("de_"):
                lang = "de-DE"
            elif voice.startswith("ja_"):
                lang = "ja-JP"
            if language is not None and lang != language:
                continue
            out.append({"id": voice, "name": voice, "language": lang, "gender": "neutral"})
        return out

    def estimate_cost(self, char_count: int) -> float:
        return 0.0
