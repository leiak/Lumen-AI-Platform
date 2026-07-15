"""HTTP endpoints for image generation.

Spec: §4
"""
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from lumen_api.v1.auth import get_current_user
from lumen_core.config import settings
from lumen_core.database import get_db
from lumen_models.image_generation import GeneratedImage
from lumen_models.model_config import ModelConfig
from lumen_models.user import User
from lumen_schemas.common import PaginatedResponse, SingleResponse
from lumen_schemas.image_generation import (
    ImageGenerationCreate,
    ImageGenerationDetail,
    ImageGenerationListItem,
)
from lumen_services.image_generation_service import ImageGenerationService

router = APIRouter(prefix="/image-generation", tags=["image-generation"])

service = ImageGenerationService()


def _load_with_model(db: Session, tenant_id: int, image_id: int):
    """Load a GeneratedImage by id+tenant, plus its ModelConfig (left-joined
    lookup). Returns (row, mc) where mc may be None if the config was deleted."""
    row = service.get(db, tenant_id=tenant_id, image_id=image_id)
    if not row:
        return None, None
    mc = (
        db.query(ModelConfig)
        .filter(ModelConfig.id == row.model_config_id)
        .first()
    )
    return row, mc


def _build_list_item(r: GeneratedImage, mc: Optional[ModelConfig]) -> ImageGenerationListItem:
    return ImageGenerationListItem(
        id=r.id,  # type: ignore[arg-type]
        prompt_preview=(r.prompt or "")[:100],  # type: ignore[arg-type]
        model_config_id=r.model_config_id,  # type: ignore[arg-type]
        model_name=mc.name if mc else "",  # type: ignore[arg-type]
        model_type=mc.model_type if mc else "",  # type: ignore[arg-type]
        size=r.size,  # type: ignore[arg-type]
        status=r.status,  # type: ignore[arg-type]
        has_thumbnail=r.thumbnail is not None,
        file_size=r.file_size or None,  # type: ignore[arg-type]
        width=r.width,  # type: ignore[arg-type]
        height=r.height,  # type: ignore[arg-type]
        duration_ms=r.duration_ms,  # type: ignore[arg-type]
        created_at=r.created_at,  # type: ignore[arg-type]
    )


@router.post("/", response_model=SingleResponse[dict])
def create(
    data: ImageGenerationCreate,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a new image generation request. Returns the first row's id
    and batch_id (None when n=1) immediately; the actual image bytes are
    produced by a background task and surface via the GET endpoints."""
    rows, err = service.create(
        db,
        tenant_id=current_user.tenant_id,  # type: ignore[arg-type]
        user_id=current_user.id,  # type: ignore[arg-type]
        model_config_id=data.model_config_id,
        prompt=data.prompt,
        size=data.size,
        n=data.n,
        negative_prompt=data.negative_prompt,
        quality=data.quality,
        style=data.style,
        extra_params=data.extra_params,
        background_tasks=background_tasks,
        playbook_id=data.playbook_id,
    )
    if err == "not_image_capable":
        raise HTTPException(400, "Model is not flagged as image_generation capable")
    if err == "playbook_not_found":
        raise HTTPException(404, "Playbook not found or not visible to this tenant")
    if not rows:
        raise HTTPException(404, "Model config not found in this tenant")
    first = rows[0]
    return SingleResponse(data={
        "id": first.id,
        "status": first.status,
        "batch_id": first.batch_id,
        "model_config_id": first.model_config_id,
        "created_at": first.created_at.isoformat(),
    })


@router.get("/", response_model=PaginatedResponse[ImageGenerationListItem])
def list_images(
    page: int = 1,
    page_size: int = 12,
    model_config_id: Optional[int] = None,
    status: Optional[str] = None,
    prompt: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List images for the current tenant, with optional filters."""
    rows, total = service.list_for_tenant(
        db,
        tenant_id=current_user.tenant_id,  # type: ignore[arg-type]
        page=page,
        page_size=page_size,
        model_config_id=model_config_id,
        status=status,
        prompt=prompt,
    )
    items = []
    for r in rows:
        mc = (
            db.query(ModelConfig)
            .filter(ModelConfig.id == r.model_config_id)
            .first()
        )
        items.append(_build_list_item(r, mc))
    return PaginatedResponse(
        data=items, total=total, page=page, page_size=page_size,
    )


@router.get("/{image_id}", response_model=SingleResponse[ImageGenerationDetail])
def get_image(
    image_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row, mc = _load_with_model(db, current_user.tenant_id, image_id)  # type: ignore[arg-type]
    if not row:
        raise HTTPException(404, "Image not found")
    return SingleResponse(data=ImageGenerationDetail(
        id=row.id,
        prompt_preview=(row.prompt or "")[:100],
        model_config_id=row.model_config_id,
        model_name=mc.name if mc else "",
        model_type=mc.model_type if mc else "",
        size=row.size,
        status=row.status,
        has_thumbnail=row.thumbnail is not None,
        file_size=row.file_size or None,
        width=row.width,
        height=row.height,
        duration_ms=row.duration_ms,
        created_at=row.created_at,
        prompt=row.prompt,
        negative_prompt=row.negative_prompt,
        quality=row.quality,
        style=row.style,
        n=row.n,
        params=row.params,
        error_message=row.error_message,
        updated_at=row.updated_at,
    ))


@router.get("/{image_id}/image")
def get_image_file(
    image_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Stream the full image bytes from disk. Returns 404 if the row is
    still pending/generating (no file on disk yet) or the file vanished."""
    row, _ = _load_with_model(db, current_user.tenant_id, image_id)  # type: ignore[arg-type]
    if not row:
        raise HTTPException(404, "Image not found")
    if row.status != "completed":
        raise HTTPException(404, "Image not yet generated")
    abs_path = settings.STORAGE_DIR / row.file_path
    if not abs_path.exists():
        raise HTTPException(404, "Image file missing on disk")
    return FileResponse(
        abs_path, media_type=row.mime_type, filename=abs_path.name,
    )


@router.get("/{image_id}/thumbnail")
def get_thumbnail(
    image_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Stream the 256x256 JPEG thumbnail (raw bytes stored in DB)."""
    row, _ = _load_with_model(db, current_user.tenant_id, image_id)  # type: ignore[arg-type]
    if not row or not row.thumbnail:
        raise HTTPException(404, "Thumbnail not available")
    return Response(content=row.thumbnail, media_type="image/jpeg")


@router.post("/{image_id}/regenerate", response_model=SingleResponse[dict])
def regenerate(
    image_id: int,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a new image using the same params as ``image_id``. The old row
    is preserved; the new row starts at status=pending."""
    rows = service.regenerate(
        db,
        tenant_id=current_user.tenant_id,  # type: ignore[arg-type]
        user_id=current_user.id,  # type: ignore[arg-type]
        image_id=image_id,
        background_tasks=background_tasks,
    )
    if not rows:
        raise HTTPException(404, "Image not found")
    first = rows[0]
    return SingleResponse(data={
        "id": first.id,
        "status": first.status,
        "model_config_id": first.model_config_id,
        "created_at": first.created_at.isoformat(),
    })


@router.delete("/{image_id}", status_code=204)
def delete(
    image_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete the image row AND the on-disk file. Idempotent w.r.t. tenant
    isolation: returns 404 if the row is from a different tenant."""
    ok = service.delete(
        db, tenant_id=current_user.tenant_id, image_id=image_id,  # type: ignore[arg-type]
    )
    if not ok:
        raise HTTPException(404, "Image not found")
    return Response(status_code=204)
