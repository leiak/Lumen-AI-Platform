"""M35: /api/v1/tts/* endpoints.

- POST /tts/jobs           — create a TTS job (background synthesis)
- GET  /tts/jobs           — list jobs
- GET  /tts/jobs/{id}      — job detail
- POST /tts/jobs/{id}/cancel — cancel a still-running job
- GET  /tts/voices         — voice list for a model_config_id
- GET  /tts/jobs/{id}/audio — stream audio bytes (Bearer auth — M32 pattern)

The audio endpoint serves the file with Content-Disposition: inline so
the browser can play it via <audio src=...>. The auth path requires
the user's Bearer token (set by the frontend via blob+createObjectURL,
NOT via <img>/<audio> direct src — see MEMORY 2026-06-20).

Spec: docs-internal/superpowers/specs/M35-overview.md §4
"""
from pathlib import PurePosixPath
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session

from lumen_api.v1.auth import get_current_user
from lumen_core.config import settings
from lumen_core.database import get_db
from lumen_models.model_config import ModelConfig
from lumen_models.user import User
from lumen_schemas.common import PaginatedResponse, SingleResponse
from lumen_schemas.tts import (
    TTSJobCreate, TTSJobListItem, TTSJobRead, TTSVoiceItem,
)
from lumen_services.tts_providers.factory import get_tts_provider
from lumen_services.tts_service import TTSService

router = APIRouter(prefix="/tts", tags=["tts"])
service = TTSService()


@router.post("/jobs", response_model=SingleResponse[dict])
def create_job(
    data: TTSJobCreate,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a TTS job. Returns the job id immediately; audio bytes
    arrive via GET /tts/jobs/{id}/audio once status=completed."""
    row, err = service.create(
        db,
        tenant_id=current_user.tenant_id,  # type: ignore[arg-type]
        user_id=current_user.id,  # type: ignore[arg-type]
        model_config_id=data.model_config_id,
        text=data.text,
        voice=data.voice,
        speed=data.speed,
        format=data.format,
        playbook_id=data.playbook_id,
        conversation_id=data.conversation_id,
        background_tasks=background_tasks,
    )
    if err == "not_found":
        raise HTTPException(404, "Model config not found")
    if err == "not_tts_capable":
        raise HTTPException(400, "Model is not flagged as TTS-capable")
    if err == "playbook_not_found":
        raise HTTPException(404, "Playbook not found or not visible to this tenant")
    if err == "text_too_long":
        raise HTTPException(400, "Text exceeds 10000 characters")
    if err == "empty_text":
        raise HTTPException(400, "Text is empty")
    if not row:
        raise HTTPException(500, "Failed to create TTS job")
    return SingleResponse(data={
        "id": row.id,
        "status": row.status,
        "model_config_id": row.model_config_id,
        "format": row.format,
        "voice": row.voice,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    })


@router.get("/jobs", response_model=PaginatedResponse[TTSJobListItem])
def list_jobs(
    page: int = 1,
    page_size: int = 12,
    status: Optional[str] = None,
    model_config_id: Optional[int] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows, total = service.list_for_tenant(
        db,
        tenant_id=current_user.tenant_id,  # type: ignore[arg-type]
        page=page,
        page_size=page_size,
        status=status,
        model_config_id=model_config_id,
    )
    items = [
        TTSJobListItem(
            id=r.id,  # type: ignore[arg-type]
            model_config_id=r.model_config_id,  # type: ignore[arg-type]
            voice=r.voice,  # type: ignore[arg-type]
            format=r.format,  # type: ignore[arg-type]
            status=r.status,  # type: ignore[arg-type]
            text_preview=(r.text or "")[:100],  # type: ignore[arg-type]
            duration_ms=r.duration_ms,
            char_count=r.char_count,  # type: ignore[arg-type]
            created_at=r.created_at,  # type: ignore[arg-type]
        ) for r in rows
    ]
    return PaginatedResponse(
        data=items, total=total, page=page, page_size=page_size,
    )


@router.get("/jobs/{job_id}", response_model=SingleResponse[TTSJobRead])
def get_job(
    job_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = service.get(
        db, tenant_id=current_user.tenant_id, audio_id=job_id,  # type: ignore[arg-type]
    )
    if not row:
        raise HTTPException(404, "TTS job not found")
    return SingleResponse(data=TTSJobRead.model_validate(row))


@router.post("/jobs/{job_id}/cancel", response_model=SingleResponse[dict])
def cancel_job(
    job_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = service.cancel(
        db, tenant_id=current_user.tenant_id, audio_id=job_id,  # type: ignore[arg-type]
    )
    if not row:
        raise HTTPException(404, "TTS job not found")
    return SingleResponse(data={"id": row.id, "status": row.status})


@router.get("/voices", response_model=SingleResponse[list[TTSVoiceItem]])
def list_voices(
    model_config_id: int,
    language: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return the voice list for the given TTS model config.

    Global configs (tenant_id=NULL) are visible to all tenants. Tenant-
    scoped configs only to their own tenant.
    """
    mc = db.query(ModelConfig).filter(ModelConfig.id == model_config_id).first()
    if not mc:
        raise HTTPException(404, "Model config not found")
    if mc.tenant_id is not None and mc.tenant_id != current_user.tenant_id:
        raise HTTPException(404, "Model config not found")
    if not mc.is_tts:
        raise HTTPException(400, "Model is not TTS-capable")
    provider = get_tts_provider(mc)
    voices = provider.list_voices(language=language)
    return SingleResponse(data=[TTSVoiceItem(**v) for v in voices])


@router.get("/jobs/{job_id}/audio")
def get_audio(
    job_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Stream the synthesized audio bytes. Auth is via the standard
    Bearer token (NOT query string — query tokens are not checked by
    the auth layer; see MEMORY 2026-06-20).

    Returns 404 if the job is still pending / running, or if the
    on-disk file is missing.
    """
    row = service.get(
        db, tenant_id=current_user.tenant_id, audio_id=job_id,  # type: ignore[arg-type]
    )
    if not row:
        raise HTTPException(404, "TTS job not found")
    if row.status != "completed":
        raise HTTPException(404, f"Audio not yet ready (status={row.status})")
    if not row.file_path:
        raise HTTPException(404, "Audio file path is empty")
    abs_path = settings.STORAGE_DIR / PurePosixPath(row.file_path)  # type: ignore[arg-type]
    if not abs_path.exists():
        raise HTTPException(404, "Audio file missing on disk")
    return FileResponse(
        abs_path,
        media_type=row.mime_type,
        filename=abs_path.name,
        headers={"Content-Disposition": "inline"},
    )


@router.delete("/jobs/{job_id}", status_code=204)
def delete_job(
    job_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ok = service.delete(
        db, tenant_id=current_user.tenant_id, audio_id=job_id,  # type: ignore[arg-type]
    )
    if not ok:
        raise HTTPException(404, "TTS job not found")
    return Response(status_code=204)
