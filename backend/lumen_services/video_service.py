"""M36: Video composition service — FFmpeg wrapper.

T1 scope (M36.0). Three core ops exposed as plain functions so the
API layer (T3) and the workflow node ``video_compose`` (T4) can call
them without going through any orchestration:

- ``audio_mux(images, audio, out)``: 1+ still image(s) + an audio track → mp4.
- ``subtitle_burn(video, srt, out)``: hardcode SRT/VTT into a video.
- ``concat_segments(videos, out)``: concatenate multiple mp4s into one.

Plus:
- ``build_video_from_assets(...)`` — one-shot composer the API can call,
  mirrors the provider pattern used by image_generation_service /
  tts_service.
- ``ffprobe_duration_ms(path)``, ``ffprobe_probe(path)`` — ported from
  ``tts_service._ffprobe_duration_ms`` but split out as top-level
  helpers so the workflow node can reuse them.
- Cross-platform FFmpeg detect: ``FFMPEG_PATH`` env var > ``PATH``
  > a small list of common Windows install locations.

We deliberately write to a caller-supplied ``output_path`` (so the
service can compose to ``settings.STORAGE_DIR / <rel>`` the same way
``lumen_core.storage.save_bytes`` does for images / audio). The
high-level ``build_video_from_assets`` reads the file back and
returns ``(bytes, size, duration_ms)`` so the API layer can hand the
bytes to ``save_bytes(... subdir="generated_videos")``.

Spec: docs-internal/superpowers/specs/m36-multimodal-foundation.md
(WILDCARD — also covered by m35-multimodal-foundation "M36 video"
deferral).
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

from lumen_core.config import settings

log = logging.getLogger(__name__)

# 200 MB hard cap on the rendered mp4. Larger than the audio cap (50
# MB) because 1080p H.264 video at ~30s can already weigh 50MB+; we
# keep headroom for longer edits / burn-in passes.
MAX_FILE_SIZE = 200 * 1024 * 1024

# FFmpeg can take a while (concat + subtitle burn + 1080p encode), so
# 10 minutes per call gives plenty of headroom before we kill it.
FFMPEG_TIMEOUT_SEC = 600


# ──────────────────────────────────────────────────────────────────────
# FFmpeg binary discovery
# ──────────────────────────────────────────────────────────────────────

def _ffmpeg_bin() -> str:
    """Resolve the absolute path of the ffmpeg binary.

    Lookup order:
    1. ``FFMPEG_PATH`` env var (set this if ffmpeg isn't on PATH).
    2. ``shutil.which("ffmpeg")`` — covers any PATH-based install.
    3. A small list of common Windows install locations.

    Raises FileNotFoundError with an installation hint if nothing
    matches.
    """
    env = os.environ.get("FFMPEG_PATH")
    if env and Path(env).exists():
        return env
    which = shutil.which("ffmpeg")
    if which:
        return which
    if os.name == "nt":
        candidates = [
            Path("C:/ffmpeg/bin/ffmpeg.exe"),
            Path("C:/Program Files/ffmpeg/bin/ffmpeg.exe"),
            Path.home() / "ffmpeg/bin/ffmpeg.exe",
            Path("D:/ffmpeg/bin/ffmpeg.exe"),
        ]
        for c in candidates:
            if c.exists():
                return str(c)
    raise FileNotFoundError(
        "ffmpeg binary not found. Install ffmpeg from https://ffmpeg.org "
        "and either add its bin/ directory to PATH, or set "
        "FFMPEG_PATH=/abs/path/to/ffmpeg(.exe)."
    )


def _ffprobe_bin() -> str:
    """Same resolution rules as ``_ffmpeg_bin()`` but for ffprobe.

    If neither ``FFPROBE_PATH`` env var nor ``shutil.which`` finds a
    binary, fall back to whatever lives next to the resolved ffmpeg
    binary (almost every ffmpeg build ships with ffprobe in the same
    directory).
    """
    env = os.environ.get("FFPROBE_PATH")
    if env and Path(env).exists():
        return env
    which = shutil.which("ffprobe")
    if which:
        return which
    ffmpeg_path = _ffmpeg_bin()
    sibling = Path(ffmpeg_path).with_name("ffprobe")
    if os.name == "nt":
        sibling = sibling.with_suffix(".exe")
    if sibling.exists():
        return str(sibling)
    raise FileNotFoundError(
        "ffprobe binary not found (needed for duration probing). "
        "Install ffmpeg and add to PATH, or set FFPROBE_PATH."
    )


def ffmpeg_version() -> str:
    """Return the ffmpeg version banner (first line of ``ffmpeg -version``)."""
    try:
        proc = subprocess.run(
            [_ffmpeg_bin(), "-version"],
            capture_output=True, text=True, timeout=10,
        )
        return (proc.stdout or "").splitlines()[0] if proc.stdout else ""
    except Exception as e:  # noqa: BLE001 — diagnostics, never crash
        return f"<unavailable: {e}>"


# ──────────────────────────────────────────────────────────────────────
# Probing
# ──────────────────────────────────────────────────────────────────────

def ffprobe_duration_ms(path: str) -> Optional[int]:
    """Probe a media file's duration in ms. None on any failure.

    Used by ``build_video_from_assets`` so the caller can populate
    ``duration_ms`` on the resulting ``GeneratedVideo`` row.
    """
    try:
        proc = subprocess.run(
            [_ffprobe_bin(), "-v", "error",
             "-show_entries", "format=duration",
             "-of", "json", path],
            capture_output=True, text=True, timeout=30,
        )
        if proc.returncode != 0:
            return None
        data = json.loads(proc.stdout or "{}")
        dur = float((data.get("format") or {}).get("duration") or 0)
        if dur <= 0:
            return None
        return int(dur * 1000)
    except (FileNotFoundError, subprocess.TimeoutExpired, ValueError, json.JSONDecodeError):
        return None


def ffprobe_streams(path: str) -> dict:
    """Return the full ffprobe JSON for ``path``, or ``{}`` on failure.

    Useful in tests when we need to assert, e.g., that a video has
    both an ``h264`` video stream and an ``aac`` audio stream.
    """
    try:
        proc = subprocess.run(
            [_ffprobe_bin(), "-v", "error",
             "-show_format", "-show_streams",
             "-of", "json", path],
            capture_output=True, text=True, timeout=30,
        )
        if proc.returncode != 0:
            return {}
        return json.loads(proc.stdout or "{}")
    except (FileNotFoundError, subprocess.TimeoutExpired, ValueError, json.JSONDecodeError):
        return {}


# ──────────────────────────────────────────────────────────────────────
# Core composition ops
# ──────────────────────────────────────────────────────────────────────

def audio_mux(
    *,
    image_paths: Sequence[str],
    audio_path: str,
    output_path: str,
    per_image_seconds: Optional[float] = None,
    resolution: str = "1280x720",
    fps: int = 24,
    audio_fade_in: float = 0.0,
    audio_fade_out: float = 0.0,
    bgm_path: Optional[str] = None,
    bgm_volume: float = 0.3,
) -> str:
    """Combine 1+ still images with an audio track (+ optional BGM) into a single mp4.

    Args:
        image_paths: One or more image paths. If exactly 1, the image
            is displayed for the full audio duration. If >1, images
            are evenly split across the audio (or each shown for
            ``per_image_seconds`` when set).
        audio_path: Path to an audio file (mp3/wav/...). Must exist.
        output_path: Where to write the resulting mp4.
        per_image_seconds: When >1 images, the per-image display
            duration. Defaults to ``audio_dur / len(image_paths)``.
        resolution: Output frame size, default ``1280x720``.
        fps: Output frame rate, default 24.
        audio_fade_in: Seconds of linear fade-in at the start (0 disables).
        audio_fade_out: Seconds of linear fade-out at the end (0 disables).
        bgm_path: M36.2.2 — optional background-music track. ``None``
            (default) keeps the legacy single-track behavior with zero
            regression. When set, the BGM is added as a 2nd input with
            ``-stream_loop -1`` (infinite loop) and mixed into the main
            audio at ``bgm_volume`` (0.0–1.0). The BGM does NOT fade —
            only the main track does — to avoid two-track fade
            complexity.
        bgm_volume: Relative volume of BGM in the mix (0.0–1.0). Default
            0.3. Per M36.2.2 spec; UI 暂不暴露 slider,schema 留位。

    Returns:
        ``output_path`` on success.

    Raises:
        ValueError: Missing inputs.
        FileNotFoundError: Any input file does not exist.
        RuntimeError: ffmpeg exited non-zero or timed out.
    """
    image_paths = list(image_paths)
    if not image_paths:
        raise ValueError("audio_mux requires at least one image")
    for p in image_paths:
        if not Path(p).exists():
            raise FileNotFoundError(f"image not found: {p}")
    if not Path(audio_path).exists():
        raise FileNotFoundError(f"audio not found: {audio_path}")
    if bgm_path is not None and not Path(bgm_path).exists():
        raise FileNotFoundError(f"bgm not found: {bgm_path}")
    if Path(output_path).exists():
        Path(output_path).unlink()  # ffmpeg -y is set, but be explicit

    audio_dur_ms = ffprobe_duration_ms(audio_path)
    audio_dur_sec = (audio_dur_ms / 1000.0) if audio_dur_ms else 60.0
    if len(image_paths) == 1:
        per_dur = audio_dur_sec
    else:
        per_dur = float(per_image_seconds) if per_image_seconds else (audio_dur_sec / len(image_paths))

    args: List[str] = [_ffmpeg_bin(), "-y", "-hide_banner", "-loglevel", "warning"]
    for img in image_paths:
        args += ["-loop", "1", "-t", f"{per_dur:.3f}", "-i", img]
    args += ["-i", audio_path]
    audio_idx = len(image_paths)
    # M36.2.2: BGM 作为第 2 个 audio input,无限循环让短 BGM(30s)
    # 自动填满主轨(几分钟)。
    if bgm_path is not None:
        args += ["-stream_loop", "-1", "-i", bgm_path]
        bgm_idx = audio_idx + 1
    else:
        bgm_idx = None  # type: ignore[assignment]

    # Build the filter graph:
    # - for each image input: scale + pad to `resolution`, force SAR=1
    # - if >1 image: concat them
    # - audio: fade-in/out applied (when non-zero) on main track
    # - M36.2.2: if BGM present, amix main + BGM (BGM does NOT fade)
    # NOTE: the `pad` filter only accepts W:H positional args (not the
    # WxH shorthand `scale` accepts), so we split `resolution` ourselves.
    try:
        w_str, h_str = resolution.lower().split("x", 1)
    except ValueError as e:
        raise ValueError(f"resolution must look like 'WIDTHxHEIGHT' (got {resolution!r})") from e
    filters = []
    for i in range(len(image_paths)):
        filters.append(
            f"[{i}:v]scale={w_str}:{h_str}:force_original_aspect_ratio=decrease,"
            f"pad={w_str}:{h_str}:(ow-iw)/2:(oh-ih)/2:color=black,"
            f"setsar=1,fps={fps},format=yuv420p[v{i}]"
        )
    if len(image_paths) > 1:
        concat_inputs = "".join(f"[v{i}]" for i in range(len(image_paths)))
        filters.append(f"{concat_inputs}concat=n={len(image_paths)}:v=1:a=0[vout]")
        video_label = "[vout]"
    else:
        video_label = "[v0]"

    afilters: List[str] = []
    if audio_fade_in > 0:
        afilters.append(f"afade=in:st=0:d={audio_fade_in}")
    if audio_fade_out > 0:
        fade_start = max(0.0, audio_dur_sec - audio_fade_out)
        afilters.append(f"afade=out:st={fade_start:.3f}:d={audio_fade_out}")
    main_filter = ",".join(afilters) if afilters else "anull"
    if bgm_idx is not None:
        # Main + BGM amix。``amix=inputs=2:duration=first`` 表示混合以
        # 主轨长度为准,BGM 自动被裁短;``aloop`` 已经在外层 input 加了,
        # 这里不再重复。
        bgm_vol_str = f"{bgm_volume:.3f}"
        filters.append(
            f"[{audio_idx}:a]{main_filter}[amain];"
            f"[{bgm_idx}:a]volume={bgm_vol_str}[abgm];"
            f"[amain][abgm]amix=inputs=2:duration=first[aout]"
        )
    else:
        filters.append(f"[{audio_idx}:a]{main_filter}[aout]")

    args += [
        "-filter_complex", ";".join(filters),
        "-map", video_label,
        "-map", "[aout]",
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k",
        "-shortest",
        "-movflags", "+faststart",
        output_path,
    ]
    _run_ffmpeg(args)
    return output_path


def subtitle_burn(
    *,
    video_path: str,
    subtitle_path: str,
    output_path: str,
    font: Optional[str] = None,
    font_size: int = 24,
    font_color: str = "white",
    outline_color: str = "black",
    margin_v: int = 24,
) -> str:
    """Hardcode a SRT/VTT subtitle track into a video.

    Uses FFmpeg's ``subtitles=`` video filter (libass). The subtitle
    file's path is translated to a POSIX-style string because FFmpeg's
    filter parser treats ``C:\...`` as bad option syntax.

    Args:
        video_path: Input video file.
        subtitle_path: SRT or VTT file.
        output_path: Output mp4 path.
        font: Optional font family name.
        font_size: Subtitle text size in px (libass FontSize).
        font_color: Color name — one of: white, black, red, green,
            blue, yellow. Default ``white``.
        outline_color: Subtitle outline color. Default ``black``.
        margin_v: Vertical margin from bottom edge in px.

    Returns:
        ``output_path`` on success.
    """
    if not Path(video_path).exists():
        raise FileNotFoundError(f"video not found: {video_path}")
    if not Path(subtitle_path).exists():
        raise FileNotFoundError(f"subtitle not found: {subtitle_path}")
    if Path(output_path).exists():
        Path(output_path).unlink()

    # Escape Windows drive-letter colons for ffmpeg's subtitles= filter.
    posix_sub = Path(subtitle_path).as_posix().replace(":", "\\:")

    style_parts = [
        f"FontSize={font_size}",
        f"PrimaryColour={_ass_color(font_color)}",
        f"OutlineColour={_ass_color(outline_color)}",
        f"MarginV={margin_v}",
    ]
    if font:
        style_parts.insert(0, f"FontName={font}")
    vf = f"subtitles='{posix_sub}':force_style='{','.join(style_parts)}'"

    args = [
        _ffmpeg_bin(), "-y", "-hide_banner", "-loglevel", "warning",
        "-i", video_path,
        "-vf", vf,
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-c:a", "copy",
        "-movflags", "+faststart",
        output_path,
    ]
    _run_ffmpeg(args)
    return output_path


def concat_segments(
    *,
    video_paths: Sequence[str],
    output_path: str,
) -> str:
    """Concatenate multiple mp4 segments into one.

    Uses FFmpeg's filter-based concat (not the demuxer) so inputs may
    vary in codec/resolution — the filter normalizes and re-encodes
    the video. Audio is also re-encoded to AAC for consistent output.

    Args:
        video_paths: 2+ video file paths.
        output_path: Where to write the concatenated mp4.

    Returns:
        ``output_path`` on success.
    """
    video_paths = list(video_paths)
    if len(video_paths) < 2:
        raise ValueError("concat_segments requires at least 2 video paths")
    for p in video_paths:
        if not Path(p).exists():
            raise FileNotFoundError(f"video not found: {p}")
    if Path(output_path).exists():
        Path(output_path).unlink()

    args: List[str] = [_ffmpeg_bin(), "-y", "-hide_banner", "-loglevel", "warning"]
    for vp in video_paths:
        args += ["-i", vp]
    # Concat each [v][a] pair, then output [vout][aout]
    pairs = "".join(f"[{i}:v][{i}:a]" for i in range(len(video_paths)))
    filter_complex = (
        f"{pairs}concat=n={len(video_paths)}:v=1:a=1[vout][aout]"
    )
    args += [
        "-filter_complex", filter_complex,
        "-map", "[vout]",
        "-map", "[aout]",
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        output_path,
    ]
    _run_ffmpeg(args)
    return output_path


# ──────────────────────────────────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────────────────────────────────

# Friendly color names → ASS color hex (AABBGGRR, alpha + BGR).
_ASS_COLOR_NAMES = {
    "white":  "&H00FFFFFF",
    "black":  "&H00000000",
    "red":    "&H000000FF",
    "green":  "&H0000FF00",
    "blue":   "&H00FF0000",
    "yellow": "&H0000FFFF",
}


def _ass_color(name: str) -> str:
    """Translate a friendly color name to an ASS color tag.

    Falls back to white so an unknown name never breaks the encode
    (the user just gets white text).
    """
    return _ASS_COLOR_NAMES.get((name or "").lower(), "&H00FFFFFF")


def _run_ffmpeg(args: List[str]) -> None:
    """Spawn ffmpeg and raise on non-zero / timeout. Logs stderr."""
    start = time.monotonic()
    proc = subprocess.run(
        args, capture_output=True, text=True, timeout=FFMPEG_TIMEOUT_SEC,
    )
    elapsed_ms = int((time.monotonic() - start) * 1000)
    if proc.returncode == 0:
        log.info("ffmpeg OK in %dms: %s", elapsed_ms, args[:6])
        return
    err = (proc.stderr or proc.stdout or "").strip()
    log.error("ffmpeg exit %d after %dms: %s", proc.returncode, elapsed_ms, err[-1000:])
    # Keep just the last few lines of stderr — ffmpeg banners and config
    # dumps make raw stderr multi-megabyte; the tail usually has the
    # real reason.
    short = "\n".join(err.splitlines()[-10:]) if err else ""
    raise RuntimeError(
        f"ffmpeg failed (exit={proc.returncode}, took={elapsed_ms}ms): {short}"
    )


def _synthesize_silence(*, out: str, seconds: float) -> str:
    """Render ``seconds`` of stereo silence via FFmpeg's anullsrc.

    Used when ``build_video_from_assets`` is called WITHOUT an audio
    track (just images-to-mp4 with no narration).
    """
    args = [
        _ffmpeg_bin(), "-y", "-hide_banner", "-loglevel", "warning",
        "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
        "-t", f"{seconds:.3f}", out,
    ]
    _run_ffmpeg(args)
    return out


# ──────────────────────────────────────────────────────────────────────
# High-level one-shot composer (used by API / workflow node)
# ──────────────────────────────────────────────────────────────────────

def build_video_from_assets(
    *,
    image_paths: Sequence[str],
    audio_path: Optional[str] = None,
    subtitle_path: Optional[str] = None,
    bgm_path: Optional[str] = None,
    bgm_volume: float = 0.3,
    resolution: str = "1280x720",
    fps: int = 24,
    audio_fade_in: float = 0.0,
    audio_fade_out: float = 0.0,
    subtitle_font: Optional[str] = None,
    per_image_seconds: Optional[float] = None,
) -> Tuple[bytes, int, int]:
    """One-shot composer: image(s) [+ audio] [+ subtitle] [+ BGM] → mp4 bytes.

    Writes intermediate files to ``settings.STORAGE_DIR/_tmp/<uuid>/``,
    reads back the final mp4, and returns ``(bytes, file_size,
    duration_ms)``. The intermediate directory is auto-cleaned by
    ``tempfile.TemporaryDirectory``.

    Args:
        image_paths: 1+ image file paths.
        audio_path: Optional audio file path. When ``None``, we
            synthesize silence so the resulting mp4 still has an
            audio stream (otherwise browsers complain).
        subtitle_path: Optional SRT file path. When given, hardcoded
            into the video via ``subtitle_burn``.
        bgm_path: M36.2.2 — optional background-music track; see
            ``audio_mux``. ``None`` keeps the single-track legacy
            behavior.
        bgm_volume: BGM relative volume in the amix; default 0.3.
        resolution / fps / audio fades / subtitle_font: propagated to
            underlying ops. See ``audio_mux`` and ``subtitle_burn``.
        per_image_seconds: see ``audio_mux``.

    Returns:
        Tuple of (mp4_bytes, file_size, duration_ms).

    Raises:
        Same conditions as ``audio_mux`` / ``subtitle_burn``.
    """
    image_paths = list(image_paths)
    if not image_paths:
        raise ValueError("build_video_from_assets requires at least one image")

    tmp_root = settings.STORAGE_DIR / "_tmp"
    tmp_root.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(dir=str(tmp_root)) as raw:
        td = Path(raw)
        silence: Optional[str] = None
        eff_audio = audio_path
        if eff_audio is None:
            silence = str(td / "silent.wav")
            _synthesize_silence(
                out=silence,
                seconds=4.0 * max(1, len(image_paths)),
            )
            eff_audio = silence

        muxed = td / "muxed.mp4"
        audio_mux(
            image_paths=image_paths,
            audio_path=eff_audio,
            output_path=str(muxed),
            per_image_seconds=per_image_seconds,
            resolution=resolution,
            fps=fps,
            audio_fade_in=audio_fade_in,
            audio_fade_out=audio_fade_out,
            bgm_path=bgm_path,
            bgm_volume=bgm_volume,
        )

        if subtitle_path:
            final = td / "final.mp4"
            subtitle_burn(
                video_path=str(muxed),
                subtitle_path=subtitle_path,
                output_path=str(final),
                font=subtitle_font,
            )
        else:
            final = muxed

        data = final.read_bytes()
        if len(data) > MAX_FILE_SIZE:
            raise RuntimeError(
                f"video payload too large: {len(data)} bytes "
                f"(cap={MAX_FILE_SIZE})"
            )
        duration_ms = ffprobe_duration_ms(str(final)) or 0

    return data, len(data), duration_ms


__all__ = [
    "MAX_FILE_SIZE",
    "FFMPEG_TIMEOUT_SEC",
    # FFmpeg discovery + diagnostics
    "ffmpeg_version",
    # Probing
    "ffprobe_duration_ms",
    "ffprobe_streams",
    # Core ops
    "audio_mux",
    "subtitle_burn",
    "concat_segments",
    # High-level
    "build_video_from_assets",
]
