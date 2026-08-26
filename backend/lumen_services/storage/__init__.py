"""M38.1: Storage backend abstraction.

Single entry point :func:`get_storage_backend` returns a process-wide
singleton configured from environment variables. All file I/O across
the KB / image / stock / video / music services should route through
this module instead of calling ``open()`` directly.

See ``docs-internal/superpowers/specs/2026-08-26-kb-storage-abstraction.md``
for the full design.
"""
from __future__ import annotations

import os
import threading
from typing import Optional

from .base import StorageBackend
from .local_backend import LocalBackend

__all__ = ["StorageBackend", "LocalBackend", "get_storage_backend"]


_storage_lock = threading.Lock()
_storage_singleton: Optional[StorageBackend] = None


def get_storage_backend() -> StorageBackend:
    """Return the process-wide storage backend singleton.

    The backend is selected by the ``STORAGE_BACKEND`` env var:

    - ``local`` (default): on-disk ``LocalBackend``
    - ``s3``: any S3-compatible service via ``S3Backend``
      (MinIO / AWS S3 / Aliyun OSS / Tencent COS all speak the v4
      protocol)

    The singleton is cached after first instantiation; tests that
    need to swap the backend should call :func:`reset_storage_backend`
    or set ``STORAGE_BACKEND`` before the first call.
    """
    global _storage_singleton
    if _storage_singleton is not None:
        return _storage_singleton
    with _storage_lock:
        if _storage_singleton is not None:
            return _storage_singleton
        name = (os.getenv("STORAGE_BACKEND") or "local").strip().lower()
        if name == "s3":
            # Import lazily so the boto3 dependency is optional at
            # test-import time. Local-only dev / unit tests can run
            # without boto3 installed.
            from .s3_backend import S3Backend
            _storage_singleton = S3Backend.from_env()
        else:
            _storage_singleton = LocalBackend.from_env()
    return _storage_singleton


def reset_storage_backend() -> None:
    """Clear the singleton so the next :func:`get_storage_backend`
    call re-reads env vars.

    Tests that mutate ``STORAGE_BACKEND`` between cases should call
    this in their ``setUp`` / ``tearDown``.
    """
    global _storage_singleton
    with _storage_lock:
        _storage_singleton = None