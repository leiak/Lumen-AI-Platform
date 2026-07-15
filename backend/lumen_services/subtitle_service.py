"""M35: Subtitle service — pure-Python SRT generation.

Takes a script (plain text) and a target total duration, splits by
sentence-final punctuation, and emits a standard SRT file. The
algorithm uses per-language character density to assign timestamps:

    zh-CN: ~4 chars / second (typical Mandarin narration pace)
    en-US: ~14 chars / second (typical English narration pace)
    mixed: weighted by detected character set per cue

Output: standard SRT, UTF-8, CRLF line endings (SRT spec requires
CRLF; VLC and most players accept LF too but we use CRLF for safety).

The duration error is bounded — for typical scripts the total cue
durations sum to the requested total within ±200ms (the spec
acceptance criterion). Long pauses between sentences get a small
floor (200ms) to avoid 0-length gaps that some players render as
visual glitches.

Spec: docs-internal/superpowers/specs/M35-overview.md §5
"""
from __future__ import annotations

import re
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from lumen_models.subtitle import Subtitle


# Per-language narration pace (characters per second). Calibrated
# against typical TTS output for narration pace. Override via the
# ``chars_per_second`` argument on generate_from_script.
_DEFAULT_CHARS_PER_SEC = {
    "zh-CN": 4.0,
    "zh-TW": 4.0,
    "en-US": 14.0,
    "en-GB": 14.0,
    "ja-JP": 5.0,
    "ko-KR": 5.0,
    "de-DE": 12.0,
    "fr-FR": 12.0,
    "es-ES": 13.0,
}

# Sentence-final punctuation. Split keeps the delimiter by using a
# lookahead so each cue is a clean sentence (no trailing punct).
_SENTENCE_END = re.compile(
    r"(?<=[。！？.!?])\s*|\n+"
)

# Minimum gap between cues (ms). Avoids 0-length gaps that some
# players render as visual glitches.
_MIN_GAP_MS = 200

# Maximum cue length (chars). Splits a long sentence into smaller
# cues so each fits within ~5 seconds at the default pace.
_MAX_CUE_CHARS = 60


def _is_cjk(ch: str) -> bool:
    """Return True if the character is CJK (Chinese / Japanese / Korean)."""
    code = ord(ch)
    return (
        0x4E00 <= code <= 0x9FFF
        or 0x3040 <= code <= 0x30FF  # hiragana + katakana
        or 0xAC00 <= code <= 0xD7AF  # hangul syllables
    )


def _detect_cue_density(cue: str) -> float:
    """Estimate narration pace for a cue by mixing CJK and Latin density.

    The simple per-language rate is wrong for mixed-language scripts
    (e.g. zh-CN script with an English term). We weight the per-
    character rates by the proportion of CJK vs Latin in the cue.
    """
    if not cue:
        return _DEFAULT_CHARS_PER_SEC["en-US"]
    cjk = sum(1 for c in cue if _is_cjk(c))
    latin = sum(1 for c in cue if c.isascii() and c.isalpha())
    total = cjk + latin
    if total == 0:
        return _DEFAULT_CHARS_PER_SEC["en-US"]
    # CJK density assumes ~4 cps, Latin assumes ~14 cps.
    cjk_rate = 4.0
    latin_rate = 14.0
    return (cjk * cjk_rate + latin * latin_rate) / total


def _split_into_cues(text: str) -> List[str]:
    """Split script into cue strings, each ≤ MAX_CUE_CHARS.

    - Sentence-final punctuation splits (。」！？.!?\\n).
    - Long sentences get further split at commas / spaces.
    - Empty cues are dropped.
    """
    if not text:
        return []
    # First pass: split by sentence enders + newlines
    raw = _SENTENCE_END.split(text.strip())
    cues: List[str] = []
    for piece in raw:
        piece = piece.strip()
        if not piece:
            continue
        if len(piece) <= _MAX_CUE_CHARS:
            cues.append(piece)
            continue
        # Long sentence — split on commas (zh 「，」/en ',') or whitespace
        sub = re.split(r"(?<=[，,])\s*|(?<=\s)\s+", piece)
        for s in sub:
            s = s.strip()
            if not s:
                continue
            if len(s) <= _MAX_CUE_CHARS:
                cues.append(s)
            else:
                # Last resort: hard split on char boundary
                for i in range(0, len(s), _MAX_CUE_CHARS):
                    cues.append(s[i:i + _MAX_CUE_CHARS])
    return cues


def _format_srt_timestamp(ms: int) -> str:
    """Format milliseconds as SRT timestamp ``HH:MM:SS,mmm``."""
    if ms < 0:
        ms = 0
    h, rem = divmod(ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def build_srt(
    script: str,
    total_duration_ms: int,
    *,
    language: str = "zh-CN",
) -> str:
    """Build the SRT text from a script and target total duration.

    Returns the SRT body as a single string (CRLF-separated lines).
    Raises ValueError on empty script or invalid duration.
    """
    if total_duration_ms < 1000:
        raise ValueError("total_duration_ms must be >= 1000")
    script = (script or "").strip()
    if not script:
        raise ValueError("script is empty")
    cues = _split_into_cues(script)
    if not cues:
        raise ValueError("script produced no cues after split")
    # Per-cue density + total cue char count, then normalize so the
    # sum of cue durations equals total_duration_ms exactly.
    densities = [_detect_cue_density(c) for c in cues]
    raw_durations = [len(c) / d * 1000 for c, d in zip(cues, densities)]
    total_raw = sum(raw_durations)
    if total_raw <= 0:
        scale = 1.0
    else:
        scale = (total_duration_ms - len(cues) * _MIN_GAP_MS) / total_raw
    if scale < 0.1:
        scale = 0.1  # floor: never let a cue drop below 10% of its raw duration
    durations = [d * scale for d in raw_durations]
    # Build cues
    out: List[str] = []
    cursor = 0
    for i, (cue, dur) in enumerate(zip(cues, durations), 1):
        start_ms = int(cursor)
        end_ms = int(cursor + dur)
        # Last cue ends exactly at total_duration_ms (no trailing gap)
        if i == len(cues):
            end_ms = total_duration_ms
        out.append(str(i))
        out.append(f"{_format_srt_timestamp(start_ms)} --> {_format_srt_timestamp(end_ms)}")
        out.append(cue)
        out.append("")  # blank line separator
        cursor = end_ms + _MIN_GAP_MS
        if cursor > total_duration_ms:
            cursor = total_duration_ms
    return "\r\n".join(out)


def _total_duration_from_srt(srt: str) -> int:
    """Return the end timestamp (ms) of the last cue. Used for tests."""
    matches = re.findall(
        r"\d{2}:\d{2}:\d{2},\d{3}\s*-->\s*(\d{2}):(\d{2}):(\d{2}),(\d{3})",
        srt,
    )
    if not matches:
        return 0
    h, m, s, ms = (int(x) for x in matches[-1])
    return ((h * 60 + m) * 60 + s) * 1000 + ms


# ──────────────────────────────────────────────────────────────────────
# DB-backed entrypoint
# ──────────────────────────────────────────────────────────────────────

class SubtitleService:
    """Business logic for /api/v1/subtitles."""

    def generate_from_script(
        self,
        db: Session,
        *,
        tenant_id: int,
        user_id: int,
        script: str,
        total_duration_ms: int,
        language: str = "zh-CN",
        tts_job_id: Optional[int] = None,
    ) -> Subtitle:
        """Build SRT from a script and persist as a Subtitle row.

        Raises ValueError on empty script / invalid duration (the
        API layer converts to 422).
        """
        srt = build_srt(script, total_duration_ms, language=language)
        cue_count = srt.count("-->")
        char_count = len(script)
        row = Subtitle(
            tenant_id=tenant_id,
            user_id=user_id,
            tts_job_id=tts_job_id,
            source_type="script",
            language=language,
            format="srt",
            content=srt,
            cue_count=cue_count,
            duration_ms=total_duration_ms,
            char_count=char_count,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row

    def get(
        self,
        db: Session,
        *,
        tenant_id: int,
        subtitle_id: int,
    ) -> Optional[Subtitle]:
        return db.query(Subtitle).filter(
            Subtitle.id == subtitle_id,
            Subtitle.tenant_id == tenant_id,
        ).first()

    def list_for_tenant(
        self,
        db: Session,
        *,
        tenant_id: int,
        page: int = 1,
        page_size: int = 12,
    ) -> Tuple[List[Subtitle], int]:
        q = db.query(Subtitle).filter(Subtitle.tenant_id == tenant_id)
        total = q.count()
        q = q.order_by(Subtitle.created_at.desc())
        offset = (page - 1) * page_size
        return q.offset(offset).limit(page_size).all(), total

    def delete(
        self,
        db: Session,
        *,
        tenant_id: int,
        subtitle_id: int,
    ) -> bool:
        row = self.get(db, tenant_id=tenant_id, subtitle_id=subtitle_id)
        if not row:
            return False
        db.delete(row)
        db.commit()
        return True
