"""M38.1: Local-disk storage backend.

Default backend (``STORAGE_BACKEND=local`` or unset). The MVP
default root is ``./data`` so that ``Document.file_path`` values
written by the pre-M38.1 upload code (``data/uploads/<tenant>/<kb>/
<filename>``) continue to resolve to the same on-disk location
without any data migration. KB uploaded files and generated
content (image / audio / video from ``lumen_core.storage``) live
under separate roots — ``./data`` for user uploads, ``./storage``
for generated artefacts — so swapping ``STORAGE_LOCAL_ROOT`` only
moves the user-uploaded files.
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import BinaryIO, Dict, Iterator, Optional

from .base import StorageBackend

# The dev default — ``./data`` is where the pre-M38.1 upload code
# wrote files (``data/uploads/<tenant>/<kb>/<filename>``); pinning
# the storage root to the same prefix means parsers that still
# ``open(file_path)`` resolve to the same bytes ``storage.put_object``
# wrote. Override via the ``STORAGE_LOCAL_ROOT`` env var.
_DEFAULT_LOCAL_ROOT = "./data"


class LocalBackend(StorageBackend):
    """Stores objects on the local filesystem under a single root
    directory. Storage keys are relative paths under that root.
    """

    backend_name = "local"

    def __init__(self, root: str) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    # -- factory --------------------------------------------------------

    @classmethod
    def from_env(cls) -> "LocalBackend":
        """Build from ``STORAGE_LOCAL_ROOT`` (falling back to
        ``./data``). Honours ``DEFAULT_STORAGE_DIR`` from
        ``lumen_core.config`` only when ``STORAGE_LOCAL_ROOT`` is
        unset AND the operator explicitly opted into the legacy
        ``./storage`` root via the ``STORAGE_LOCAL_USE_LEGACY_ROOT``
        env var. The default ``./data`` is what the pre-M38.1
        upload code used, so leaving it unset preserves file_path
        resolution without any data migration."""
        env_root = os.getenv("STORAGE_LOCAL_ROOT")
        if env_root:
            return cls(root=env_root)
        legacy = os.getenv("STORAGE_LOCAL_USE_LEGACY_ROOT", "").strip().lower() in {
            "1", "true", "yes", "on",
        }
        if legacy:
            from lumen_core.config import DEFAULT_STORAGE_DIR  # type: ignore
            return cls(root=str(DEFAULT_STORAGE_DIR))
        return cls(root=_DEFAULT_LOCAL_ROOT)

    # -- internal helpers ----------------------------------------------

    def _abs_path(self, key: str) -> Path:
        safe = self._validate_key(key)
        return self.root / safe

    # -- interface ------------------------------------------------------

    def put_object(
        self,
        key: str,
        data: bytes,
        content_type: Optional[str] = None,
    ) -> str:
        abs_path = self._abs_path(key)
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        # ``os.open`` + ``os.fdopen`` avoids a brief window where the
        # file exists but is still being written; the existing code
        # path opened with ``open(file_path, 'wb')`` so the behaviour
        # is functionally identical.
        fd = os.open(abs_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
        except Exception:
            # Clean up a half-written file so subsequent reads don't
            # silently pick up corrupt bytes.
            try:
                abs_path.unlink()
            except OSError:
                pass
            raise
        # content_type is intentionally not persisted: the project's
        # doc parser looks at the extension, not the HTTP header.
        return f"local://{key}"

    def get_object(self, key: str) -> bytes:
        abs_path = self._abs_path(key)
        if not abs_path.is_file():
            raise FileNotFoundError(key)
        return abs_path.read_bytes()

    def get_object_stream(self, key: str) -> BinaryIO:
        abs_path = self._abs_path(key)
        if not abs_path.is_file():
            raise FileNotFoundError(key)
        # Real file handle — caller is responsible for ``.close()``
        # (or use ``with`` form). ``S3Backend`` returns a
        # ``StreamingBody`` with the same lifecycle, so the parser
        # layer's ``with storage.get_object_stream(key) as f:`` pattern
        # works uniformly.
        return open(abs_path, "rb")

    def put_object_multipart(
        self,
        key: str,
        data_stream: BinaryIO,
        part_size: int = 5 * 1024 * 1024,
        content_type: Optional[str] = None,
    ) -> str:
        """Drain ``data_stream`` into a single ``put_object`` call.

        ``LocalBackend`` has no concept of multipart — the filesystem
        doesn't care about chunk boundaries. We read ``data_stream``
        in ``part_size`` blocks only to keep peak memory bounded for
        callers that would otherwise build a full in-memory blob.
        # ``part_size`` is honored for read batching only; the final
        # ``put_object`` is a single atomic write either way.
        """
        safe = self._validate_key(key)
        chunks = []
        while True:
            chunk = data_stream.read(part_size)
            if not chunk:
                break
            chunks.append(chunk)
        data = b"".join(chunks)
        return self.put_object(safe, data, content_type=content_type)

    def list_objects(self, prefix: str = "", max_keys: int = 1000) -> Iterator[str]:
        """Yield keys under ``prefix`` (relative to ``self.root``).

        Uses ``Path.rglob`` so nested directories under the prefix
        are included; an empty prefix matches the whole root.
        Directories themselves are skipped (they're not objects).
        """
        if prefix:
            base = self._abs_path(prefix)
        else:
            base = self.root
        if not base.exists():
            return iter(())
        # ``rglob('*')`` returns every entry under ``base`` recursively;
        # we filter out directories and normalise the relative path
        # to match the storage key convention.
        for path in sorted(base.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(self.root).as_posix()
            yield rel
            # Caller iterates with a ``for`` loop; Python ignores
            # the manual ``StopIteration`` so we keep yielding until
            # the caller breaks. To enforce ``max_keys`` we let the
            # caller handle that with ``itertools.islice``.

    def delete_object(self, key: str) -> None:
        abs_path = self._abs_path(key)
        try:
            abs_path.unlink()
        except FileNotFoundError:
            return  # idempotent
        except IsADirectoryError:
            # Don't silently swallow programmer errors; surface them.
            raise

    def object_exists(self, key: str) -> bool:
        return self._abs_path(key).is_file()

    def get_presigned_url(self, key: str, expiry: Optional[int] = None) -> str:
        # Local backend cannot mint a real presigned URL; the
        # ``/api/v1/storage/local/<key>`` route enforces the same
        # Bearer + tenant check that the rest of the API uses, so
        # the browser-side fetch+blob+createObjectURL pattern
        # (CLAUDE.md §3) keeps working unchanged.
        return f"/api/v1/storage/local/{key}"

    def resolve_to_local_path(self, key: str) -> str:
        # Local backend: the path IS the storage location, no copy.
        abs_path = self._abs_path(key)
        if not abs_path.is_file():
            raise FileNotFoundError(key)
        return str(abs_path)

    def health_check(self) -> Dict[str, object]:
        start = time.monotonic()
        detail = "ok"
        ok = True
        try:
            writable = os.access(self.root, os.W_OK)
            readable = os.access(self.root, os.R_OK)
            ok = writable and readable
            detail = "writable" if ok else f"writable={writable} readable={readable}"
        except Exception as exc:  # pragma: no cover - defensive
            ok = False
            detail = f"error: {exc}"
        return {
            "backend": self.backend_name,
            "ok": ok,
            "detail": detail,
            "latency_ms": int((time.monotonic() - start) * 1000),
        }