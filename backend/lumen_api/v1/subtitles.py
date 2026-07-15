"""M35: /api/v1/subtitles/* endpoints."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from lumen_api.v1.auth import get_current_user
from lumen_core.database import get_db
from lumen_models.user import User
from lumen_schemas.common import PaginatedResponse, SingleResponse
from lumen_schemas.subtitle import (
    SubtitleCreate, SubtitleListItem, SubtitleRead,
)
from lumen_services.subtitle_service import SubtitleService

router = APIRouter(prefix="/subtitles", tags=["subtitles"])
service = SubtitleService()


@router.post("/", response_model=SingleResponse[SubtitleRead])
def create_subtitle(
    data: SubtitleCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Generate a SRT subtitle from a script + target duration."""
    try:
        row = service.generate_from_script(
            db,
            tenant_id=current_user.tenant_id,  # type: ignore[arg-type]
            user_id=current_user.id,  # type: ignore[arg-type]
            script=data.script,
            total_duration_ms=data.total_duration_ms,
            language=data.language,
            tts_job_id=data.tts_job_id,
        )
    except ValueError as e:
        raise HTTPException(422, str(e))
    return SingleResponse(data=SubtitleRead.model_validate(row))


@router.get("/", response_model=PaginatedResponse[SubtitleListItem])
def list_subtitles(
    page: int = 1,
    page_size: int = 12,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows, total = service.list_for_tenant(
        db,
        tenant_id=current_user.tenant_id,  # type: ignore[arg-type]
        page=page,
        page_size=page_size,
    )
    items = [SubtitleListItem.model_validate(r) for r in rows]
    return PaginatedResponse(
        data=items, total=total, page=page, page_size=page_size,
    )


@router.get("/{subtitle_id}", response_model=SingleResponse[SubtitleRead])
def get_subtitle(
    subtitle_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = service.get(
        db, tenant_id=current_user.tenant_id, subtitle_id=subtitle_id,  # type: ignore[arg-type]
    )
    if not row:
        raise HTTPException(404, "Subtitle not found")
    return SingleResponse(data=SubtitleRead.model_validate(row))


@router.get("/{subtitle_id}/content")
def get_subtitle_content(
    subtitle_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return the raw SRT text. Content-Type: text/plain; charset=utf-8."""
    row = service.get(
        db, tenant_id=current_user.tenant_id, subtitle_id=subtitle_id,  # type: ignore[arg-type]
    )
    if not row:
        raise HTTPException(404, "Subtitle not found")
    return Response(
        content=row.content,
        media_type="text/plain; charset=utf-8",
    )


@router.get("/{subtitle_id}/download")
def download_subtitle(
    subtitle_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Download the SRT file as an attachment."""
    from fastapi.responses import Response as FastAPIResponse
    row = service.get(
        db, tenant_id=current_user.tenant_id, subtitle_id=subtitle_id,  # type: ignore[arg-type]
    )
    if not row:
        raise HTTPException(404, "Subtitle not found")
    return FastAPIResponse(
        content=row.content,
        media_type="application/x-subrip; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="subtitle_{subtitle_id}.srt"',
        },
    )


@router.delete("/{subtitle_id}", status_code=204)
def delete_subtitle(
    subtitle_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ok = service.delete(
        db, tenant_id=current_user.tenant_id, subtitle_id=subtitle_id,  # type: ignore[arg-type]
    )
    if not ok:
        raise HTTPException(404, "Subtitle not found")
    return Response(status_code=204)
