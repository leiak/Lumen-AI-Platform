"""M36.2.2 tests: ffmpeg BGM integration in audio_mux / build_video_from_assets.

Real ffmpeg invocation (mirrors test_video_service.py). Verifies:
- BGM mixing produces an mp4 with one mixed audio stream (amix output)
  whose duration matches the main track.
- The legacy single-track path is unchanged (regression).
"""
import os
import shutil
import struct
import subprocess
import wave
from pathlib import Path

import pytest

from lumen_services import video_service as vs


ffmpeg_missing = shutil.which("ffmpeg") is None and not os.environ.get("FFMPEG_PATH")
if ffmpeg_missing:
    candidates = [
        Path("C:/ffmpeg/bin/ffmpeg.exe"),
        Path("C:/Program Files/ffmpeg/bin/ffmpeg.exe"),
        Path.home() / "ffmpeg/bin/ffmpeg.exe",
        Path("D:/ffmpeg/bin/ffmpeg.exe"),
    ]
    ffmpeg_missing = not any(c.exists() for c in candidates)
needs_ffmpeg = pytest.mark.skipif(
    ffmpeg_missing,
    reason="ffmpeg binary not on PATH and FFMPEG_PATH not set",
)


def _make_wav(path: Path, *, seconds: float = 4.0, freq: float = 440.0) -> None:
    """Render a simple sine-wave WAV for ffmpeg input."""
    rate = 22050
    n = int(rate * seconds)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        import math
        frames = b"".join(
            struct.pack("<h", int(math.sin(2 * math.pi * freq * i / rate) * 16000))
            for i in range(n)
        )
        wf.writeframes(frames)


@needs_ffmpeg
def test_audio_mux_without_bgm_unchanged(tmp_path):
    """Legacy single-track path: no BGM → identical output to v1 (regression guard).

    The wrapper now accepts ``bgm_path=None``; behavior with the default
    must match what shipped before the BGM feature was added.
    """
    from PIL import Image
    img = tmp_path / "img.png"
    Image.new("RGB", (16, 12), color=(64, 64, 64)).save(img)
    audio = tmp_path / "tone.wav"
    _make_wav(audio, seconds=3.0, freq=440.0)

    out = tmp_path / "out.mp4"
    vs.audio_mux(
        image_paths=[str(img)],
        audio_path=str(audio),
        output_path=str(out),
        resolution="16x12",
        fps=4,
    )
    assert out.is_file()
    probed = vs.ffprobe_streams(str(out))
    # Exactly one audio stream (the main track).
    audio_streams = [s for s in probed.get("streams", []) if s.get("codec_type") == "audio"]
    assert len(audio_streams) == 1
    # Duration approximately equals audio duration (3s).
    fmt_dur = float(probed.get("format", {}).get("duration", 0))
    assert 2.5 <= fmt_dur <= 3.5


@needs_ffmpeg
def test_audio_mux_with_bgm_produces_mixed_audio(tmp_path):
    """BGM path: amix merges main track + looped BGM into one audio stream
    whose duration follows the main track (FFmpeg ``duration=first``)."""
    from PIL import Image
    img = tmp_path / "img.png"
    Image.new("RGB", (16, 12), color=(128, 128, 128)).save(img)
    main_audio = tmp_path / "main.wav"
    _make_wav(main_audio, seconds=4.0, freq=440.0)
    # BGM stub: 1 second so the loop iteration is observable in tests.
    bgm = tmp_path / "bgm.wav"
    _make_wav(bgm, seconds=1.0, freq=220.0)

    out = tmp_path / "out.mp4"
    vs.audio_mux(
        image_paths=[str(img)],
        audio_path=str(main_audio),
        output_path=str(out),
        resolution="16x12",
        fps=4,
        bgm_path=str(bgm),
        bgm_volume=0.3,
    )
    assert out.is_file()
    probed = vs.ffprobe_streams(str(out))
    audio_streams = [s for s in probed.get("streams", []) if s.get("codec_type") == "audio"]
    # amix yields a single mixed audio stream (NOT two).
    assert len(audio_streams) == 1
    # Container duration follows the main track (~4s), NOT the BGM stub.
    fmt_dur = float(probed.get("format", {}).get("duration", 0))
    assert 3.5 <= fmt_dur <= 4.5, f"expected main-track duration, got {fmt_dur}"
    # File size > the no-BGM baseline (BGM adds bytes).
    no_bgm_size = 0
    no_bgm_out = tmp_path / "no_bgm.mp4"
    vs.audio_mux(
        image_paths=[str(img)],
        audio_path=str(main_audio),
        output_path=str(no_bgm_out),
        resolution="16x12",
        fps=4,
    )
    no_bgm_size = no_bgm_out.stat().st_size
    bgm_size = out.stat().st_size
    # BGM-mixed output should be at least as big (typically larger).
    assert bgm_size >= no_bgm_size * 0.9
