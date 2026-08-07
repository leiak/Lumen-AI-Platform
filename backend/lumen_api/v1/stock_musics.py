"""Stock background-music HTTP endpoints (read-only gallery + Bearer proxy).

M36.2.2: list + detail + audio proxy, mirroring
``lumen_api.v1.stock_assets``. The audio file is streamed with Bearer
auth so frontend ``<audio>`` elements must use ``fetch + blob +
createObjectURL`` (see MEMORY 2026-06-20) — ``<audio src=...>`` cannot
set an ``Authorization`` header, so the proxy URL alone would 401.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from lumen_api.v1.auth import get_current_user
from lumen_core.database import get_db
from lumen_models.user import User
from lumen_schemas.common import PaginatedResponse, SingleResponse
from lumen_schemas.stock_music import StockMusicDetail, StockMusicListItem
from lumen_services.stock_music_service import StockMusicService


router = APIRouter(prefix="/stock-musics", tags=["stock-musics"])
service = StockMusicService()


@router.get("/", response_model=PaginatedResponse[StockMusicListItem])
def list_stock_musics(
    category: Optional[str] = None,
    search: Optional[str] = None,
    page: int = 1,
    page_size: int = 24,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List BGM tracks (global builtin + current tenant). Newest first."""
    rows, total = service.list_musics(
        db,
        tenant_id=current_user.tenant_id,
        category=category,
        search=search,
        page=page,
        page_size=page_size,
    )
    return PaginatedResponse(
        data=[StockMusicListItem.model_validate(r) for r in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{music_id}", response_model=SingleResponse[StockMusicDetail])
def get_stock_music(
    music_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return the metadata for one BGM track (incl. file_path for the proxy URL)."""
    row = service.get(db, music_id=music_id, tenant_id=current_user.tenant_id)
    if not row:
        raise HTTPException(404, "Stock music not found")
    return SingleResponse(data=StockMusicDetail.model_validate(row))


@router.get("/{music_id}/file")
def get_stock_music_file(
    music_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Stream the BGM bytes with Bearer auth.

    Frontend ``<audio src=...>`` cannot set an Authorization header, so
    the UI must wrap this URL in ``fetch + Bearer + blob +
    createObjectURL`` (see MEMORY 2026-06-20). The video composition
    service reads bytes directly from disk via
    ``stock_music_service.get_file_abs_path`` — it never calls this
    endpoint.
    """
    row = service.get(db, music_id=music_id, tenant_id=current_user.tenant_id)
    if not row:
        raise HTTPException(404, "Stock music not found")
    abs_path = service.get_file_abs_path(row)
    if abs_path is None:
        raise HTTPException(404, "Stock music file missing on disk")
    return FileResponse(
        abs_path,
        media_type=row.mime_type or "audio/mpeg",
        filename=abs_path.name,
    )
