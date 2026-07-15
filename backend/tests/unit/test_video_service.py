"""Tests for the M36 video_service FFmpeg wrapper.

These exercise the cross-platform ffmpeg detect + ffprobe round-trip +
build_video_from_assets orchestrator. Tests skip themselves when ffmpeg
isn't installed (Windows dev environments occasionally don't have it).
"""
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from lumen_services import video_service as vs


# Skip the whole module if no ffmpeg binary is reachable. The cross-
# platform detector raises FileNotFoundError; treat that as a "test
# environment missing the dep" and xfail rather than a hard failure
# (the wrapper still gets coverage from the env-var branch).
ffmpeg_missing = shutil.which("ffmpeg") is None and not os.environ.get("FFMPEG_PATH")
if ffmpeg_missing:
    # Probe the Windows candidate list before giving up.
    candidates = [
        Path("C:/ffmpeg/bin/ffmpeg.exe"),
        Path("C:/Program Files/ffmpeg/bin/ffmpeg.exe"),
        Path.home() / "ffmpeg/bin/ffmpeg.exe",
        Path("D:/ffmpeg/bin/ffmpeg.exe"),
    ]
    ffmpeg_missing = not any(c.exists() for c in candidates)
needs_ffmpeg = pytest.mark.skipif(
    ffmpeg_missing,
    reason="ffmpeg binary not on PATH and FFMPEG_PATH not set (T1/Win ffmpeg-N-121839)",
)


def test_ffmpeg_bin_resolve_via_env_var(monkeypatch, tmp_path):
    """Honors FFMPEG_PATH over PATH lookup."""
    fake = tmp_path / "ffmpeg"
    fake.write_text("#!/bin/sh\necho fake\n")
    if os.name != "nt":
        fake.chmod(0o755)
    monkeypatch.setenv("FFMPEG_PATH", str(fake))
    monkeypatch.setattr(shutil, "which", lambda _: None)
    assert vs._ffmpeg_bin() == str(fake)


@needs_ffmpeg
def test_ffprobe_duration_ms_round_trip(tmp_path):
    """Compose a tiny mp4 then ffprobe the duration — round-trip OK."""
    from PIL import Image
    img_path = tmp_path / "in.png"
    Image.new("RGB", (32, 24), color=(64, 64, 64)).save(img_path)
    out = tmp_path / "out.mp4"
    data, size, dur = vs.build_video_from_assets(
        image_paths=[str(img_path)],
        audio_path=None,
        subtitle_path=None,
        resolution="32x24",
        fps=2,
    )
    out.write_bytes(data)
    assert size == len(data) >= 100
    probed = vs.ffprobe_duration_ms(str(out))
    assert probed is not None
    # Single image padded to audio-less default duration (FFmpeg pads the
    # stream to silence if audio absent — minimum commonly 4s for 1-frame
    # input). Accept any positive duration up to 10 minutes; the load-
    # bearing assertion is "duration is discoverable, not zero".
    assert 1 <= probed <= 600_000


@needs_ffmpeg
def test_build_video_from_assets_image_only_synthesizes_silence(tmp_path):
    """No audio_path → FFmpeg wrapper synthesizes a silence mp4."""
    from PIL import Image
    img = tmp_path / "img.png"
    Image.new("RGB", (16, 12), color=(128, 128, 128)).save(img)
    data, size, dur = vs.build_video_from_assets(
        image_paths=[str(img)],
        audio_path=None,
        subtitle_path=None,
        resolution="16x12",
        fps=4,
        per_image_seconds=2.0,
    )
    # mp4 file magic: size + "ftyp" or "moov".
    assert data[:4] == b"\x00\x00\x00\x20" or data[4:8] == b"ftyp"  # mp4 magic
    assert size == len(data) >= 200  # 1 image × ~4s @ small res ≈ 5-50 KB
    assert dur is not None and dur > 0
    # Write to a real file so ffprobe can read headers (Windows doesn't
    # accept binary stdin for ffprobe cleanly).
    out_file = tmp_path / "out.mp4"
    out_file.write_bytes(data)
    probed = vs.ffprobe_duration_ms(str(out_file))
    assert probed is not None and probed > 0


@needs_ffmpeg
def test_ffmpeg_version_reports_a_string():
    """ffmpeg_version() returns a non-empty banner string."""
    v = vs.ffmpeg_version()
    assert isinstance(v, str) and len(v) > 0
    assert "ffmpeg" in v.lower() or "configuration" in v.lower()
