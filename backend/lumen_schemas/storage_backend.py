"""2.1 C.4: runtime toggle storage backend schema。

``POST /api/v1/storage/backend`` 请求体 — admin 在 dev / staging 想切换
STORAGE_BACKEND 时不用重启 uvicorn:

    {
      "backend": "s3",
      "config": {            // 可选,覆盖 env var
        "S3_BUCKET": "lumen-prod",
        "S3_ENDPOINT": "https://s3.amazonaws.com",
        "S3_REGION": "us-east-1",
        "S3_ACCESS_KEY": "...",
        "S3_SECRET_KEY": "...",
        "S3_USE_SSL": "true",
        "S3_PATH_STYLE": "false"
      }
    }

如果 backend == "s3",``config`` 至少要含 S3_BUCKET + S3_ACCESS_KEY +
S3_SECRET_KEY(否则 backend 启动失败)。如果只切 backend 不传 config,
helper 只 reset singleton + 重读现有 env —— 适合"dev 在 .env 改完直接
toggle"场景。

local backend 切换不要 config,直接 reset singleton 走默认 root。

Spec: docs-internal/superpowers/specs/2026-09-07-lumen-2.1-spec.md §Phase 0 C.4
"""
from __future__ import annotations

from typing import Dict, Literal, Optional

from pydantic import BaseModel, Field


# Allowed backend names — keep in sync with ``lumen_services.storage.__init__``
# factory dispatch. Adding a new backend requires adding to this Literal.
BackendName = Literal["local", "s3"]


class StorageBackendConfig(BaseModel):
    """Optional env var overrides applied via ``os.environ`` before the
    backend is re-instantiated.

    All keys are optional. Missing keys fall back to whatever the process
    already had set (typically the .env file loaded by uvicorn /
    pytest). This is purely additive — pre-existing env wins on the
    next ``get_storage_backend()`` call if you don't include the key
    here.

    For ``backend=s3`` you need at least ``S3_BUCKET``,
    ``S3_ACCESS_KEY`` and ``S3_SECRET_KEY`` — either via this config or
    via pre-set env vars, otherwise the toggle fails with a 400 and a
    clear reason.
    """

    # ---- local backend ----
    STORAGE_LOCAL_ROOT: Optional[str] = None

    # ---- S3 backend ----
    S3_BUCKET: Optional[str] = None
    S3_ENDPOINT: Optional[str] = None
    S3_REGION: Optional[str] = None
    S3_ACCESS_KEY: Optional[str] = None
    S3_SECRET_KEY: Optional[str] = None
    S3_USE_SSL: Optional[str] = None  # string "true"/"false", not bool
    S3_PATH_STYLE: Optional[str] = None
    S3_PRESIGNED_URL_EXPIRY: Optional[str] = None


class StorageBackendToggleRequest(BaseModel):
    """``POST /api/v1/storage/backend`` request body."""

    backend: BackendName = Field(
        ...,
        description="Target backend name: 'local' or 's3'.",
    )
    config: Optional[StorageBackendConfig] = Field(
        default=None,
        description=(
            "Optional env var overrides applied before re-instantiating "
            "the singleton. Keys are the same as the env vars the "
            "backend factory reads."
        ),
    )


class StorageBackendInfo(BaseModel):
    """Active backend snapshot returned by ``GET /api/v1/storage/health``
    and the toggle endpoint."""

    backend: str
    ok: bool
    detail: str
    latency_ms: int