"""HTTP endpoints for video composition (M36).

Mirrors the shape of ``lumen_api/v1/image_generation.py`` (M22) and
``lumen_api/v1/tts.py`` (M35):

- ``POST /videos/`` — fire-and-forget composition
- ``GET /videos/`` — paginated history for the current tenant
- ``GET /videos/{id}`` — full detail
- ``GET /videos/{id}/download`` — Bearer-authed stream of the mp4
  (see MEMORY 2026-06-20: ``<video src=...>`` cannot set
  ``Authorization`` headers — see frontend note in template; the
  frontend's fetch helper attaches the Bearer header).

Spec: docs-internal/superpowers/specs/m36-multimodal-foundation.md §4
"""
from pathlib import PurePosixPath
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from lumen_api.v1.auth import get_current_user
from lumen_core.config import settings
from lumen_core.database import get_db
from lumen_models.user import User
from lumen_models.video import GeneratedVideo
from lumen_schemas.common import PaginatedResponse, SingleResponse
from lumen_schemas.video import (
    VideoComposeCreate,
    VideoComposeListItem,
    VideoComposeRead,
)
from lumen_services.video_compose_service import VideoComposeService

router = APIRouter(prefix="/videos", tags=["videos"])

service = VideoComposeService()


def _build_list_item(r: GeneratedVideo) -> VideoComposeListItem:
    return VideoComposeListItem(
        id=r.id,  # type: ignore[arg-type]
        resolution=r.resolution,
        fps=r.fps,
        file_size=r.file_size or 0,
        duration_ms=r.duration_ms,
        status=r.status,  # type: ignore[arg-type]
        image_count=len(r.source_images or []),
        created_at=r.created_at,
    )


@router.post("/", response_model=SingleResponse[VideoComposeRead])
def create(
    data: VideoComposeCreate,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Submit a composition request. Returns the row in ``status=pending``.

    The actual FFmpeg encode runs as a BackgroundTask (see
    ``lumen_services.video_compose_service._run_composition``). Clients
    poll ``GET /videos/{id}`` until ``status`` flips to ``completed`` or
    ``failed``.

    Error tags mapped to HTTP status codes:
    - ``"empty_sources"`` → 422
    - ``"audio_not_found"`` → 404
    - ``"subtitle_not_found"`` → 404
    """
    row, err = service.create(
        db,
        tenant_id=current_user.tenant_id,  # type: ignore[arg-type]
        user_id=current_user.id,  # type: ignore[arg-type]
        payload=data,
        background_tasks=background_tasks,
    )
    if err == "empty_sources":
        raise HTTPException(422, "source_images must contain at least one path")
    if err == "audio_not_found":
        raise HTTPException(404, "audio id did not resolve to a row in this tenant")
    if err == "subtitle_not_found":
        raise HTTPException(404, "subtitle id did not resolve to a row in this tenant")
    if row is None:
        raise HTTPException(500, "unexpected: no row written")
    return SingleResponse(data=VideoComposeRead.model_validate(row))


@router.get("/", response_model=PaginatedResponse[VideoComposeListItem])
def list_videos(
    page: int = 1,
    page_size: int = 12,
    status: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List composed videos for the current tenant, newest first."""
    rows, total = service.list_for_tenant(
        db,
        tenant_id=current_user.tenant_id,  # type: ignore[arg-type]
        page=page,
        page_size=page_size,
        status=status,
    )
    items = [_build_list_item(r) for r in rows]
    return PaginatedResponse(
        data=items, total=total, page=page, page_size=page_size,
    )


@router.get("/{video_id}", response_model=SingleResponse[VideoComposeRead])
def get_video(
    video_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = service.get(
        db,
        tenant_id=current_user.tenant_id,  # type: ignore[arg-type]
        video_id=video_id,
    )
    if not row:
        raise HTTPException(404, "Video not found")
    return SingleResponse(data=VideoComposeRead.model_validate(row))


@router.get("/{video_id}/download")
def download_video(
    video_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Stream the composed mp4 from disk.

    Returns 404 if the row is still pending / composing / failed. The
    frontend uses ``fetch + Bearer + createObjectURL`` to feed
    ``<video src=...>`` (see MEMORY 2026-06-20 — ``<video>`` doesn't
    pass Authorization headers natively).
    """
    row = service.get(
        db,
        tenant_id=current_user.tenant_id,  # type: ignore[arg-type]
        video_id=video_id,
    )
    if not row:
        raise HTTPException(404, "Video not found")
    if row.status != "completed":
        raise HTTPException(404, f"Video not yet ready (status={row.status})")
    abs_path = settings.STORAGE_DIR / PurePosixPath(row.file_path)
    if not abs_path.exists():
        raise HTTPException(404, "Video file missing on disk")
    # FileResponse handles Content-Length / Range / streaming for us.
    return FileResponse(
        abs_path,
        media_type=row.mime_type or "video/mp4",
        filename=abs_path.name,
    )


@router.post("/{video_id}/cancel", response_model=SingleResponse[dict])
def cancel_video(
    video_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Mark a pending / composing video as cancelled.

    Best-effort only: we don't kill the underlying FFmpeg subprocess
    (no PID is tracked). If the encode completes between the request
    arriving and our DB flip, the row stays ``completed`` and
    ``GET .../download`` will return 200.
    """
    ok = service.cancel(
        db,
        tenant_id=current_user.tenant_id,  # type: ignore[arg-type]
        user_id=current_user.id,  # type: ignore[arg-type]
        video_id=video_id,
    )
    if not ok:
        # Distinguish "doesn't exist" from "already terminal".
        row = service.get(
            db,
            tenant_id=current_user.tenant_id,  # type: ignore[arg-type]
            video_id=video_id,
        )
        if not row:
            raise HTTPException(404, "Video not found")
        raise HTTPException(
            409,
            f"Cannot cancel video in terminal status {row.status!r}",
        )
    return SingleResponse(message="Video cancelled")


@router.delete("/{video_id}", status_code=204)
def delete_video(
    video_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete the row AND the on-disk mp4. Idempotent w.r.t. tenant."""
    from lumen_core.storage import delete_relative

    row = service.get(
        db,
        tenant_id=current_user.tenant_id,  # type: ignore[arg-type]
        video_id=video_id,
    )
    if not row:
        raise HTTPException(404, "Video not found")
    delete_relative(row.file_path)  # type: ignore[arg-type]
    db.delete(row)
    db.commit()
    return Response(status_code=204)