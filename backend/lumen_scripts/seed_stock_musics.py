"""M36.2.2 seed: 5 built-in background-music tracks.

ComposeModal 需要"开箱即用"的 BGM,避免冷启动时用户没音乐可选。脚本用
Python 内置 ``wave`` + ``math`` 合成 5 段 30 秒 WAV(mellow / upbeat /
dramatic / corporate / ambient,各风格 chord progression + tempo 不
同),再 ``ffmpeg`` 编码成 64k mono MP3(单段约 30-50KB,无版权风险)。

写入 ``stock_musics`` 表,``tenant_id=NULL`` 表示全局 builtin,所有租户
可见。

Idempotent: 已存在的 BGM 按 ``(name, tenant_id)`` 跳过;文件会被重新
生成覆盖。

Usage:
    cd backend && python -m lumen_scripts.seed_stock_musics
"""
from __future__ import annotations

import math
import os
import struct
import subprocess
import sys
import tempfile
import wave
from dataclasses import dataclass
from typing import List, Tuple

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lumen_core.config import settings  # noqa: E402
from lumen_core.database import SessionLocal, ensure_stock_musics_table  # noqa: E402
from lumen_models.stock_music import StockMusic  # noqa: E402


# 采样参数:22050Hz mono 16-bit,WAV 30s ≈ 1.3MB → ffmpeg 64k MP3 → ~30-50KB
SAMPLE_RATE = 22050
DURATION_SECONDS = 30.0


# ────────────────────────────────────────────────────────────────────
# Music theory helpers
# ────────────────────────────────────────────────────────────────────

# Equal-tempered scale: A4 = 440Hz. semitones offsets from A4.
_NOTE_A4_HZ = 440.0
# 音名 → semitone offset from A4。``C0 = -9``(C 是 A 下方 3 个半音,但跨
# 越八度要细分)。``octave`` 参数决定所在的八度。
_NOTE_SEMITONE_FROM_A4 = {
    "C": -9, "C#": -8, "D": -7, "D#": -6, "E": -5, "F": -4,
    "F#": -3, "G": -2, "G#": -1, "A": 0, "A#": 1, "B": 2,
}


def note_hz(name: str, octave: int = 4) -> float:
    """Convert ``(note, octave)`` → Hz. 默认中央 C(C4)=261.6Hz。"""
    semi = _NOTE_SEMITONE_FROM_A4[name]
    # A4 = octave 4 → A4; octave 5 is 12 semitones up.
    distance = semi + (octave - 4) * 12
    return _NOTE_A4_HZ * (2 ** (distance / 12.0))


# ────────────────────────────────────────────────────────────────────
# Synthesis primitives
# ────────────────────────────────────────────────────────────────────

def _sine_sample(t: float, freq: float, harmonics: int = 1) -> float:
    """Return a sine value at time ``t`` for ``freq`` Hz, optionally
    with up to ``harmonics`` upper harmonics to add brightness.

    ``harmonics=1`` = pure sine(mellow); ``harmonics=3`` adds 2x and
    3x components at reduced amplitude for a more bell-like timbre.
    Output is in [-1, 1] but typically much smaller for normalized
    multi-harmonic mixes.
    """
    s = math.sin(2 * math.pi * freq * t)
    if harmonics >= 2:
        s += 0.5 * math.sin(2 * math.pi * freq * 2 * t)
    if harmonics >= 3:
        s += 0.33 * math.sin(2 * math.pi * freq * 3 * t)
    # Normalize amplitude (so louder harmonics don't clip).
    return s / (1.0 + 0.5 + 0.33) if harmonics >= 3 else (
        s / (1.0 + 0.5) if harmonics >= 2 else s
    )


def _adsr(
    t: float,
    note_duration: float,
    *,
    attack: float = 0.02,
    decay: float = 0.10,
    sustain_level: float = 0.7,
    release: float = 0.15,
) -> float:
    """Linear ADSR envelope in [0, 1].

    Attack: ramp 0 → 1 over ``attack`` sec.
    Decay: ramp 1 → sustain_level over ``decay`` sec.
    Sustain: hold sustain_level until note ends - release.
    Release: ramp sustain → 0 over ``release`` sec.
    """
    if t < 0:
        return 0.0
    if t < attack:
        return t / attack if attack > 0 else 1.0
    if t < attack + decay:
        if decay <= 0:
            return sustain_level
        ratio = (t - attack) / decay
        return 1.0 + (sustain_level - 1.0) * ratio
    release_start = note_duration - release
    if t < release_start:
        return sustain_level
    if t < note_duration:
        if release <= 0:
            return 0.0
        return sustain_level * (1.0 - (t - release_start) / release)
    return 0.0


# ────────────────────────────────────────────────────────────────────
# Style-specific generators
# ────────────────────────────────────────────────────────────────────

@dataclass
class ChordEvent:
    """A chord starting at ``start`` sec, lasting ``duration`` sec.

    ``notes`` is a list of (note_name, octave) tuples.
    """
    start: float
    duration: float
    notes: List[Tuple[str, int]]
    harmonics: int = 1
    velocity: float = 0.6  # peak amplitude multiplier


def _render(events: List[ChordEvent], sample_rate: int, total_seconds: float) -> List[int]:
    """Render a list of chord events into a 16-bit mono PCM list."""
    total_samples = int(total_seconds * sample_rate)
    out = [0] * total_samples
    for ev in events:
        start_sample = int(ev.start * sample_rate)
        end_sample = min(total_samples, int((ev.start + ev.duration) * sample_rate))
        n_samples = end_sample - start_sample
        if n_samples <= 0:
            continue
        for i in range(n_samples):
            t = i / sample_rate
            envelope = _adsr(t, ev.duration) * ev.velocity
            sample = 0.0
            for name, octave in ev.notes:
                f = note_hz(name, octave)
                sample += _sine_sample(t, f, harmonics=ev.harmonics)
            # Average over the chord voices + envelope.
            sample = (sample / max(1, len(ev.notes))) * envelope
            out[start_sample + i] += int(sample * 32767)
    # Soft-clip (saturate peaks beyond 32000 to avoid harsh clipping artifacts).
    for i in range(len(out)):
        v = out[i]
        if v > 32000:
            out[i] = 32000 + int((v - 32000) * 0.3)
        elif v < -32000:
            out[i] = -32000 + int((v + 32000) * 0.3)
    return out


def _write_wav(path: str, samples: List[int], sample_rate: int) -> None:
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(struct.pack(f"<{len(samples)}h", *samples))


def _encode_mp3(wav_path: str, mp3_path: str) -> int:
    """Convert WAV → MP3 (64k mono). Returns MP3 file size in bytes."""
    # 失败 throw → 让 seed 报错出去,而不是静默落下 mp3
    args = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "warning",
        "-i", wav_path,
        "-codec:a", "libmp3lame", "-b:a", "64k",
        "-ac", "1",  # mono
        mp3_path,
    ]
    subprocess.run(args, check=True)
    return os.path.getsize(mp3_path)


def _resolve_ffmpeg() -> str:
    """Same lookup rules as ``video_service._ffmpeg_bin`` but inline
    so the seed script doesn't have to import the wrapper."""
    env = os.environ.get("FFMPEG_PATH")
    if env and os.path.exists(env):
        return env
    which = _shutil_which("ffmpeg")
    if which:
        return which
    if os.name == "nt":
        for c in (
            "C:/ffmpeg/bin/ffmpeg.exe",
            "C:/Program Files/ffmpeg/bin/ffmpeg.exe",
            os.path.join(os.path.expanduser("~"), "ffmpeg/bin/ffmpeg.exe"),
            "D:/ffmpeg/bin/ffmpeg.exe",
        ):
            if os.path.exists(c):
                return c
    raise FileNotFoundError("ffmpeg not found — see video_service._ffmpeg_bin for lookup")


def _shutil_which(name: str) -> str | None:
    import shutil
    return shutil.which(name)


# ────────────────────────────────────────────────────────────────────
# Music compositions (each ~30 seconds)
# ────────────────────────────────────────────────────────────────────

def _mellow_events() -> List[ChordEvent]:
    """Slow piano-like chord progression, ~60 BPM, pure sine."""
    # Progression: C - Am - F - G(IV-vi-II-V 倒置)
    progression = [
        [("C", 4), ("E", 4), ("G", 4)],
        [("A", 3), ("C", 4), ("E", 4)],
        [("F", 3), ("A", 3), ("C", 4)],
        [("G", 3), ("B", 3), ("D", 4)],
    ]
    # 30s, 4 bars, ~7.5s/bar, ~2s per chord (sustained)
    events: List[ChordEvent] = []
    bar = 0
    while bar * 7.5 < DURATION_SECONDS:
        for ci, notes in enumerate(progression):
            start = bar * 7.5 + ci * 1.85
            if start >= DURATION_SECONDS:
                break
            events.append(ChordEvent(
                start=start, duration=1.8,
                notes=notes, harmonics=1, velocity=0.45,
            ))
        bar += 1
    return events


def _upbeat_events() -> List[ChordEvent]:
    """Major chord progression, ~120 BPM, brighter timbre (3 harmonics)."""
    progression = [
        [("C", 4), ("E", 4), ("G", 4)],
        [("G", 3), ("B", 3), ("D", 4)],
        [("A", 3), ("C", 4), ("E", 4)],
        [("F", 3), ("A", 3), ("C", 4)],
    ]
    # 30s, 8 bars, ~3.75s/bar, ~0.94s per chord (one per beat at 120 BPM = 0.5s,
    # but with sustain longer).
    events: List[ChordEvent] = []
    bar = 0
    while bar * 3.75 < DURATION_SECONDS:
        for ci, notes in enumerate(progression):
            start = bar * 3.75 + ci * 0.94
            if start >= DURATION_SECONDS:
                break
            events.append(ChordEvent(
                start=start, duration=0.9,
                notes=notes, harmonics=3, velocity=0.5,
            ))
        bar += 1
    return events


def _dramatic_events() -> List[ChordEvent]:
    """Minor chord progression with rising melody on top, ~80 BPM."""
    progression = [
        [("A", 3), ("C", 4), ("E", 4)],
        [("F", 3), ("A", 3), ("C", 4)],
        [("C", 4), ("E", 4), ("G", 4)],
        [("G", 3), ("B", 3), ("D", 4)],
    ]
    events: List[ChordEvent] = []
    bar = 0
    # 30s, 6 bars, ~5s/bar, ~1.25s per chord
    while bar * 5.0 < DURATION_SECONDS:
        for ci, notes in enumerate(progression):
            start = bar * 5.0 + ci * 1.25
            if start >= DURATION_SECONDS:
                break
            events.append(ChordEvent(
                start=start, duration=1.2,
                notes=notes, harmonics=2, velocity=0.55,
            ))
        bar += 1
    # Add rising melody on top (single high notes ascending)
    melody = [("C", 5), ("D", 5), ("E", 5), ("F", 5), ("G", 5), ("A", 5)]
    for i, (n, o) in enumerate(melody):
        start = i * 5.0
        if start >= DURATION_SECONDS:
            break
        events.append(ChordEvent(
            start=start, duration=4.5,
            notes=[(n, o)], harmonics=2, velocity=0.25,
        ))
    return events


def _corporate_events() -> List[ChordEvent]:
    """Neutral major progression, ~100 BPM, clean tone."""
    progression = [
        [("C", 4), ("E", 4), ("G", 4)],
        [("F", 3), ("A", 3), ("C", 4)],
        [("G", 3), ("B", 3), ("D", 4)],
        [("A", 3), ("C", 4), ("E", 4)],
    ]
    events: List[ChordEvent] = []
    bar = 0
    # 30s, ~7.5 bars, ~4s/bar, ~1s per chord
    while bar * 4.0 < DURATION_SECONDS:
        for ci, notes in enumerate(progression):
            start = bar * 4.0 + ci * 1.0
            if start >= DURATION_SECONDS:
                break
            events.append(ChordEvent(
                start=start, duration=0.95,
                notes=notes, harmonics=2, velocity=0.5,
            ))
        bar += 1
    return events


def _ambient_events() -> List[ChordEvent]:
    """Slow pad-like sustained chords, no rhythm, very soft envelope."""
    progression = [
        [("C", 4), ("G", 4)],
        [("A", 3), ("E", 4)],
        [("F", 3), ("C", 4)],
        [("G", 3), ("D", 4)],
    ]
    events: List[ChordEvent] = []
    # 30s, 4 sections, 7.5s/section
    for si, notes in enumerate(progression):
        start = si * 7.5
        if start >= DURATION_SECONDS:
            break
        events.append(ChordEvent(
            start=start, duration=7.0,
            notes=notes, harmonics=2, velocity=0.35,
        ))
    return events


# ────────────────────────────────────────────────────────────────────
# Seed entry point
# ────────────────────────────────────────────────────────────────────

TRACKS = [
    ("舒缓钢琴", "mellow", _mellow_events, "Soft piano-like chord progression — calms the viewer, ideal for training / tutorial videos."),
    ("活力节拍", "upbeat", _upbeat_events, "Energetic major chord progression — adds energy, suitable for product launches / promotions."),
    ("戏剧张力", "dramatic", _dramatic_events, "Minor chord progression with rising melody — builds tension, suitable for trailers / storytelling."),
    ("商务大气", "corporate", _corporate_events, "Neutral major progression — professional, suitable for corporate intros / B2B presentations."),
    ("空灵氛围", "ambient", _ambient_events, "Slow sustained pad chords — atmospheric background, suitable for art films / brand mood pieces."),
]


def _category_for(style: str) -> str:
    return {
        "mellow": "舒缓",
        "upbeat": "振奋",
        "dramatic": "戏剧",
        "corporate": "商务",
        "ambient": "氛围",
    }[style]


def upsert_stock_music(db, *, name: str, style: str, events_factory, description: str) -> StockMusic:
    """Render + persist one global built-in BGM track."""
    existing = (
        db.query(StockMusic)
        .filter(StockMusic.tenant_id.is_(None), StockMusic.name == name)
        .first()
    )
    rel_path = f"stock/music/{style}.mp3"
    abs_path = settings.STORAGE_DIR / rel_path
    abs_path.parent.mkdir(parents=True, exist_ok=True)

    # Render to a temp WAV, encode to MP3, drop WAV.
    samples = _render(events_factory(), SAMPLE_RATE, DURATION_SECONDS)
    with tempfile.TemporaryDirectory() as tmp:
        wav_path = os.path.join(tmp, f"{style}.wav")
        _write_wav(wav_path, samples, SAMPLE_RATE)
        ffmpeg_bin = _resolve_ffmpeg()
        # Override PATH-aware ffmpeg call by setting FFMPEG_PATH so our
        # ``subprocess.run(["ffmpeg", ...])`` finds the right binary.
        env = os.environ.copy()
        env["FFMPEG_PATH"] = ffmpeg_bin
        args = [
            ffmpeg_bin, "-y", "-hide_banner", "-loglevel", "warning",
            "-i", wav_path,
            "-codec:a", "libmp3lame", "-b:a", "64k",
            "-ac", "1",
            str(abs_path),
        ]
        subprocess.run(args, check=True, env=env)

    mp3_size = abs_path.stat().st_size
    if existing:
        existing.category = _category_for(style)  # type: ignore[assignment]
        existing.description = description  # type: ignore[assignment]
        existing.file_path = rel_path  # type: ignore[assignment]
        existing.mime_type = "audio/mpeg"  # type: ignore[assignment]
        existing.file_size = mp3_size  # type: ignore[assignment]
        existing.duration_seconds = DURATION_SECONDS  # type: ignore[assignment]
        existing.source = "builtin"  # type: ignore[assignment]
        existing.tenant_id = None  # type: ignore[assignment]
        return existing
    row = StockMusic(
        name=name,
        category=_category_for(style),
        description=description,
        file_path=rel_path,
        mime_type="audio/mpeg",
        file_size=mp3_size,
        duration_seconds=DURATION_SECONDS,
        source="builtin",
        tenant_id=None,
    )
    db.add(row)
    return row


def main() -> None:
    ensure_stock_musics_table()
    print(f"M36.2.2 seed — rendering {len(TRACKS)} built-in BGM tracks...")
    db = SessionLocal()
    try:
        for name, style, factory, desc in TRACKS:
            row = upsert_stock_music(
                db, name=name, style=style, events_factory=factory, description=desc,
            )
            if row.id is None:
                db.flush()
            print(f"  - {name} ({style}): {row.file_size // 1024} KB")
        db.commit()
        total = db.query(StockMusic).filter(StockMusic.tenant_id.is_(None)).count()
        print(f"OK — committed {len(TRACKS)} tracks (total builtin rows: {total}).")
    except Exception as exc:
        db.rollback()
        print(f"FAILED: {type(exc).__name__}: {exc}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
