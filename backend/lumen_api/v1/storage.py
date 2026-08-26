"""M38.1: storage backend admin endpoints.

Three endpoints covering:

- ``GET  /api/v1/storage/health`` — connectivity probe for the
  configured backend. Cheap; safe to poll from a status page.
- ``GET  /api/v1/storage/local/<key:path>`` — bearer-authenticated
  local-disk proxy. Required because ``LocalBackend.get_presigned_url``
  returns this URL and the browser needs to fetch the bytes
  through the FastAPI auth layer (CLAUDE.md §3 image Bearer
  pattern). The handler also enforces tenant isolation against
  the user-bound Document row.
- ``POST /api/v1/storage/migrate-to-s3`` — **admin-only** cold
  migration: walk all ``documents`` rows whose
  ``asset_storage_key IS NULL`` and copy their ``file_path`` bytes
  into the configured S3 backend. Idempotent — re-running only
  processes rows that haven't been migrated yet. Returns a
  progress summary.

Spec: ``docs-internal/superpowers/specs/2026-08-26-kb-storage-abstraction.md``
§ 6.2.
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session

from lumen_core.database import get_db
from lumen_models.knowledge import Document
from lumen_models.user import User
from lumen_schemas.common import SingleResponse

from .auth import get_current_user, require_admin

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/storage", tags=["storage"])


# -- 1. health ----------------------------------------------------------


@router.get("/health", response_model=SingleResponse[Dict[str, Any]])
def storage_health() -> SingleResponse[Dict[str, Any]]:
    """Probe the configured storage backend.

    Never raises — errors are reported in the payload's ``ok``
    field so dashboards can render degraded states without
    handling 5xx separately.
    """
    # Import inside the handler so test environments that haven't
    # pulled in ``boto3`` can still import this module.
    from lumen_services.storage import get_storage_backend

    backend = get_storage_backend()
    report = backend.health_check()
    return SingleResponse(data=report)


# -- 2. local proxy -----------------------------------------------------


@router.get("/local/{key:path}")
def storage_local_get(
    key: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    """Read an object from the LocalBackend with Bearer auth.

    The :class:`LocalBackend` returns
    ``/api/v1/storage/local/<key>`` from ``get_presigned_url`` so the
    browser can fetch protected bytes via the standard
    ``Authorization: Bearer`` header (CLAUDE.md §3).

    Tenant isolation: every KB document is owned by a tenant; we
    refuse to serve a key unless it points at a row whose
    ``knowledge_base.tenant_id`` matches the caller (or the caller
    is admin).
    """
    from lumen_services.storage import get_storage_backend

    storage = get_storage_backend()
    if storage.backend_name != "local":
        # Defence-in-depth: if someone misconfigures ``STORAGE_BACKEND``
        # but a client still has an old ``/local/...`` URL, return a
        # clear 410 Gone rather than silently proxying through the
        # wrong backend.
        raise HTTPException(
            status_code=410,
            detail="Local storage proxy is disabled in this environment",
        )

    # Resolve the key back to a Document row so we can enforce
    # tenant isolation. Key shape is ``uploads/<tenant>/<kb>/<filename>``
    # which uniquely identifies the row (modulo overwrites).
    doc = (
        db.query(Document)
        .filter(Document.asset_storage_key == key)
        .first()
    )
    if doc is None:
        # Fallback: legacy rows predate ``asset_storage_key``. Try
        # matching by ``file_path`` (POSIX-style relative path that
        # starts with ``data/<key>``).
        candidate_path = f"data/{key}"
        doc = (
            db.query(Document)
            .filter(Document.file_path == candidate_path)
            .first()
        )
    if doc is None:
        raise HTTPException(status_code=404, detail="Object not found")

    # Tenant guard. Admin can read across tenants (matches the
    # existing admin override pattern in ``lumen_api/v1/knowledge``).
    is_admin = bool(getattr(current_user, "is_superuser", False))
    if not is_admin:
        # Lazy-load the KB tenant_id so this handler doesn't
        # require ``Document.tenant_id`` on the ORM.
        from lumen_models.knowledge import KnowledgeBase

        kb = db.get(KnowledgeBase, doc.knowledge_base_id)
        if kb is None or kb.tenant_id != current_user.tenant_id:
            raise HTTPException(status_code=403, detail="Forbidden")

    try:
        data = storage.get_object(key)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Object missing on disk")

    # Crude content-type from the extension; precise mapping lives in
    # ``lumen_core/storage.py`` but pulling that in here would create
    # an import cycle. The browser falls back to ``application/octet-stream``
    # which is fine for the binary asset use case.
    name = key.rsplit("/", 1)[-1]
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    content_type = {
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "webp": "image/webp",
        "mp4": "video/mp4",
        "mp3": "audio/mpeg",
        "wav": "audio/wav",
        "pdf": "application/pdf",
        "txt": "text/plain; charset=utf-8",
        "md": "text/markdown; charset=utf-8",
    }.get(ext, "application/octet-stream")

    return Response(content=data, media_type=content_type)


# -- 3. cold migration --------------------------------------------------


def _read_bytes_for_migration(key: str, legacy_file_path: str) -> bytes:
    """Resolve migration bytes from the active storage backend.

    Prefers ``get_storage_backend().get_object(key)`` — the
    bytes-of-truth in any deployment that has already completed
    the migration for some rows. Falls back to opening
    ``legacy_file_path`` directly so legacy rows whose bytes
    predate the storage abstraction still migrate cleanly.
    """
    from lumen_services.storage import get_storage_backend

    storage = get_storage_backend()
    try:
        return storage.get_object(key)
    except FileNotFoundError:
        try:
            with open(legacy_file_path, "rb") as f:
                return f.read()
        except OSError as exc:
            # Re-raise as FileNotFoundError so the endpoint's
            # error reporter shows a uniform reason string.
            raise FileNotFoundError(legacy_file_path) from exc


@router.post(
    "/migrate-to-s3",
    response_model=SingleResponse[Dict[str, Any]],
)
def storage_migrate_to_s3(
    batch_size: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> SingleResponse[Dict[str, Any]]:
    """Cold-migrate legacy KB documents to the S3 backend.

    Walks ``documents`` rows whose ``asset_storage_key IS NULL``,
    reads the local file at ``file_path``, PUTs it under a key
    shaped ``uploads/<tenant>/<kb>/<filename>``, and updates the
    row.

    Returns ``{"scanned", "migrated", "failed", "errors"}``. The
    route is admin-only; production deployments should set up a
    similar background Celery beat job (this MVP keeps it
    synchronous because the dev workload fits in one batch).
    """
    # Local imports keep import cost down and avoid cycles.
    from lumen_services.storage import get_storage_backend

    backend = get_storage_backend()
    if backend.backend_name != "s3":
        raise HTTPException(
            status_code=400,
            detail=(
                "STORAGE_BACKEND must be 's3' to migrate. "
                f"Currently configured: {backend.backend_name!r}"
            ),
        )

    candidates = (
        db.query(Document)
        .filter(Document.asset_storage_key.is_(None))
        .limit(max(1, batch_size))
        .all()
    )
    scanned = len(candidates)
    migrated = 0
    failed = 0
    errors: list[Dict[str, Any]] = []

    for doc in candidates:
        # Pre-M38.1 ``file_path`` is a POSIX-relative path under
        # ``./data/uploads/...``. Convert to the storage key by
        # stripping the ``data/`` prefix the legacy writer used.
        if not doc.file_path or not doc.file_path.startswith("data/"):
            failed += 1
            errors.append({"document_id": doc.id, "reason": "no_legacy_file_path"})
            continue
        key = doc.file_path[len("data/"):]
        try:
            # Read the bytes through whichever backend is currently
            # configured (LocalBackend during dev / test runs; could
            # be a second S3Backend if you're running this from one
            # S3 deployment to another). The legacy ``file_path`` is
            # kept here only as a locator — the bytes themselves come
            # from the active backend.
            data = _read_bytes_for_migration(key, doc.file_path)
            backend.put_object(key, data)
            doc.asset_storage_key = key
            doc.storage_backend = "s3"
            migrated += 1
        except Exception as exc:
            failed += 1
            errors.append({"document_id": doc.id, "reason": str(exc)[:200]})

    db.commit()

    return SingleResponse(
        data={
            "scanned": scanned,
            "migrated": migrated,
            "failed": failed,
            "errors": errors[:20],  # cap response size
        }
    )