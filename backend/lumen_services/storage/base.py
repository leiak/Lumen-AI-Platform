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
from typing import BinaryIO, Dict, Iterator, Optional


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

        For ``S3Backend`` this auto-routes to multipart upload
        when the payload is ``>= 5 MiB`` (the multipart threshold
        documented in M38.1 §4.4). Callers that need to upload a
        pre-buffered stream should use ``put_object_multipart``
        directly.
        """

    def put_object_multipart(
        self,
        key: str,
        data_stream: BinaryIO,
        part_size: int = 5 * 1024 * 1024,
        content_type: Optional[str] = None,
    ) -> str:
        """Stream-upload a large object via S3 multipart.

        Not abstract — ``LocalBackend`` inherits the default that
        drains ``data_stream`` into a single ``put_object`` call.
        ``S3Backend`` overrides to use the real
        ``create_multipart_upload`` + ``complete_multipart_upload``
        chain.

        The caller owns ``data_stream`` (it's a binary file-like
        object); we read but do not close it. Returns the storage
        key on success; raises on any underlying error.
        """

    @abstractmethod
    def get_object(self, key: str) -> bytes:
        """Download an object as bytes. Raises ``FileNotFoundError``
        if the object does not exist."""

    @abstractmethod
    def get_object_stream(self, key: str) -> BinaryIO:
        """Return a file-like object suitable for streaming reads.

        !!! MUST CLOSE !!! — The caller is responsible for closing
        the returned object (use ``with storage.get_object_stream(key) as f:``
        or call ``.close()`` explicitly). Forgetting to close leaks
        file descriptors on the local backend and keeps the
        StreamingBody connection open against S3 / MinIO, eventually
        exhausting the pool.

        Use this path for large files (videos, audio, generated
        images, model artefacts) where holding the whole blob in
        memory is wasteful. The ``LocalBackend`` returns a real
        ``open()`` handle; the ``S3Backend`` returns boto3's
        ``StreamingBody`` wrapped for ``.read()/.close()`` parity.
        """

    @abstractmethod
    def delete_object(self, key: str) -> None:
        """Remove an object. Idempotent — calling on a missing key
        is a silent no-op."""

    @abstractmethod
    def list_objects(self, prefix: str = "", max_keys: int = 1000) -> Iterator[str]:
        """Yield storage keys under ``prefix``.

        Pagination is handled internally — the implementation
        transparently follows the underlying object's continuation
        token (S3 ``list_objects_v2``) until either ``max_keys``
        results have been yielded or the backend reports end of
        data. ``prefix=""`` matches everything in the bucket /
        root.

        For S3-style backends the per-page batch size is independent
        of ``max_keys``; we paginate until we hit ``max_keys`` or
        ``IsTruncated=False``.
        """

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

    def resolve_to_local_path(self, key: str) -> str:
        """Materialise the object to a local filesystem path.

        ``LocalBackend`` returns the existing on-disk path unchanged
        (no copy). ``S3Backend`` downloads the bytes into a temp
        file and returns its path — the caller is responsible for
        deleting it (``finally: Path(p).unlink(missing_ok=True)``)
        or passing it to :func:`cleanup_temp_path`.

        Used by the parser layer (pdfplumber / python-docx /
        docling) which need a path, not a stream. Parsers that can
        work with a stream should prefer :get_object_stream instead.
        """
        raise NotImplementedError

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