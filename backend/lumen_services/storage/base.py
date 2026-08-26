"""M38.1: Abstract storage backend interface.

All storage operations across the KB / image / stock / video / music
services should go through one of these methods. ``LocalBackend`` and
``S3Backend`` are the only concrete implementations shipped in core;
plugins / vendor SDKs are out of scope for the MVP.

Storage keys (the ``key`` parameter) follow the convention
``<tenant_id>/<kb_id>/<doc_uuid>/<filename>`` — see the spec §5.3 for
why caller-controlled path segments are forbidden.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import BinaryIO, Dict, Optional


class StorageBackend(ABC):
    """Storage backend abstraction.

    All methods are synchronous; async wrapping (FastAPI / Celery)
    is the caller's responsibility. Methods raise ``FileNotFoundError``
    for missing objects on read paths and ``PermissionError`` for
    access denials.
    """

    backend_name: str = "abstract"

    @abstractmethod
    def put_object(
        self,
        key: str,
        data: bytes,
        content_type: Optional[str] = None,
    ) -> str:
        """Upload an object. Returns the storage key.

        Implementations should be idempotent on overwrite (later
        ``put_object`` with the same key replaces the existing
        object) — this matches local-filesystem ``open('wb')``
        semantics that the existing code relies on.
        """

    @abstractmethod
    def get_object(self, key: str) -> bytes:
        """Download an object as bytes. Raises ``FileNotFoundError``
        if the object does not exist."""

    @abstractmethod
    def get_object_stream(self, key: str) -> BinaryIO:
        """Return a file-like object suitable for streaming reads.

        The caller is responsible for closing the returned object.
        Use this path for large files (videos, audio) where holding
        the whole blob in memory is wasteful.
        """

    @abstractmethod
    def delete_object(self, key: str) -> None:
        """Remove an object. Idempotent — calling on a missing key
        is a silent no-op."""

    @abstractmethod
    def object_exists(self, key: str) -> bool:
        """Check existence without downloading the bytes."""

    @abstractmethod
    def get_presigned_url(self, key: str, expiry: Optional[int] = None) -> str:
        """Return a URL the browser can use to fetch the object
        directly, bypassing the FastAPI auth layer.

        - ``LocalBackend`` returns ``/api/v1/storage/local/<key>`` —
          the route enforces Bearer auth + tenant isolation before
          reading the file (CLAUDE.md §3 image Bearer pattern).
        - ``S3Backend`` returns an AWS-style presigned URL with the
          configured expiry; expiry defaults to
          ``S3_PRESIGNED_URL_EXPIRY`` seconds.
        """

    @abstractmethod
    def health_check(self) -> Dict[str, object]:
        """Lightweight connectivity probe. Returns
        ``{"backend", "ok", "detail", "latency_ms"}``; never raises
        (errors are reported in ``detail``)."""

    # -- Helpers shared by all backends ---------------------------------

    @staticmethod
    def _validate_key(key: str) -> str:
        """Reject keys that try to escape the storage root.

        - No absolute paths (``/etc/passwd``).
        - No parent-segment traversal (``../foo``).
        - No empty / whitespace-only strings.
        """
        if not key or not key.strip():
            raise ValueError("storage key must be non-empty")
        if key.startswith("/"):
            raise ValueError(f"storage key must be relative: {key!r}")
        normalized = key.replace("\\", "/")
        if ".." in normalized.split("/"):
            raise ValueError(f"storage key may not contain '..': {key!r}")
        return normalized