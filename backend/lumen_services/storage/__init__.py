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


def apply_storage_config_overrides(
    overrides: "dict[str, str | None] | None",
) -> dict[str, str]:
    """2.1 C.4: 应用 config override 到 ``os.environ``。

    - 跳过 ``None`` 值(保持现有 env 不变)。
    - 设新值覆盖现有 env。
    - 返 dict ``{key: previous_or_current_value}`` 给 caller log / 回滚用。
    """
    if not overrides:
        return {}
    applied: dict[str, str] = {}
    for key, value in overrides.items():
        if value is None:
            continue
        previous = os.environ.get(key)
        applied[key] = previous if previous is not None else "<unset>"
        os.environ[key] = str(value)
    return applied


def toggle_storage_backend(backend_name: str) -> StorageBackend:
    """2.1 C.4: 运行时切换 storage backend。

    流程:
    1. 设 ``STORAGE_BACKEND`` env (大写小写容错)
    2. 调 ``reset_storage_backend()`` 清单例
    3. 调 ``get_storage_backend()`` 触发 lazy init;失败抛 actionable 异常
       让上层 endpoint 返 400

    Returns the active backend instance (admin endpoint 立刻拿来 health_check
    给前端确认新 backend 真活着)。

    Raises:
        ValueError: 未知 backend name。
        S3BackendError: S3 必填 env 缺失。
    """
    normalized = (backend_name or "").strip().lower()
    if normalized not in {"local", "s3"}:
        raise ValueError(
            f"unknown backend {backend_name!r}; must be one of 'local', 's3'"
        )
    os.environ["STORAGE_BACKEND"] = normalized
    reset_storage_backend()
    return get_storage_backend()