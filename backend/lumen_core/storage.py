"""File storage helpers for generated images.

Spec: §6
"""
import uuid
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Tuple

from lumen_core.config import settings

# Mime-type → file extension map. Covers images (M22) and audio (M35).
_EXT_MAP = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/wave": ".wav",
    "audio/opus": ".opus",
    "audio/flac": ".flac",
    "audio/aac": ".aac",
}


def save_bytes(
    tenant_id: int,
    data: bytes,
    mime_type: str,
    subdir: str = "generated_images",
) -> Tuple[Path, int, str]:
    """Save raw bytes to disk. Returns (absolute_path, file_size, relative_path).

    relative_path is what we store in DB (relative to settings.STORAGE_DIR).
    Always uses forward slashes (POSIX style) for cross-platform portability.

    The ``subdir`` argument (M35) lets callers route audio files to
    ``generated_audios/<tenant>/<date>/`` instead of the default
    ``generated_images/<tenant>/<date>/``. Default keeps the M22
    call sites working unchanged.
    """
    ext = _EXT_MAP.get(mime_type, ".bin")
    date_dir = datetime.utcnow().strftime("%Y-%m-%d")
    rel_dir = Path(f"{subdir}/{tenant_id}/{date_dir}")
    abs_dir = settings.STORAGE_DIR / rel_dir
    abs_dir.mkdir(parents=True, exist_ok=True)
    name = f"{uuid.uuid4().hex}{ext}"
    abs_path = abs_dir / name
    abs_path.write_bytes(data)
    # Always use forward slashes in the DB-stored path for portability
    # (Path.__truediv__ on Windows would otherwise yield backslashes via
    # str()).
    rel_path = f"{rel_dir.as_posix()}/{name}"
    return abs_path, len(data), rel_path


def delete_relative(rel_path: str) -> None:
    """Delete a file by its DB-stored relative path. Missing files are ignored."""
    if not rel_path:
        return
    # DB-stored paths use forward slashes. pathlib.PurePosixPath keeps
    # them as-is; on Windows the joined Path will use the OS-native
    # separator while still resolving the correct file.
    abs_path = settings.STORAGE_DIR / PurePosixPath(rel_path)
    abs_path.unlink(missing_ok=True)
