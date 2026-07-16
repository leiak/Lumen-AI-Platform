"""Stock asset HTTP endpoints (read-only gallery + Bearer proxy).

M36.2.1: 公开当前租户可见的全局内置 + 租户自传素材；图片流走
``/api/v1/stock-assets/{id}/image``，前端用 ``fetch + blob`` 模式取
受保护资源。
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from lumen_api.v1.auth import get_current_user
from lumen_core.database import get_db
from lumen_models.user import User
from lumen_schemas.common import PaginatedResponse, SingleResponse
from lumen_schemas.stock_asset import StockAssetDetail, StockAssetListItem
from lumen_services.stock_service import StockService


router = APIRouter(prefix="/stock-assets", tags=["stock-assets"])
service = StockService()


def _build_list_item(r) -> StockAssetListItem:
    return StockAssetListItem.model_validate(r)


@router.get("/", response_model=PaginatedResponse[StockAssetListItem])
def list_stock_assets(
    category: Optional[str] = None,
    search: Optional[str] = None,
    page: int = 1,
    page_size: int = 24,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List stock assets (global + current tenant). Newest first."""
    rows, total = service.list_assets(
        db,
        tenant_id=current_user.tenant_id,
        category=category,
        search=search,
        page=page,
        page_size=page_size,
    )
    return PaginatedResponse(
        data=[_build_list_item(r) for r in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{asset_id}", response_model=SingleResponse[StockAssetDetail])
def get_stock_asset(
    asset_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = service.get(
        db, asset_id=asset_id, tenant_id=current_user.tenant_id,
    )
    if not row:
        raise HTTPException(404, "Stock asset not found")
    return SingleResponse(data=StockAssetDetail.model_validate(row))


@router.get("/{asset_id}/image")
def get_stock_asset_image(
    asset_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Stream the stock asset bytes. Frontend uses fetch + Bearer + blob
    to feed ``<img src=blob:...>`` (see MEMORY 2026-06-20).
    """
    row = service.get(
        db, asset_id=asset_id, tenant_id=current_user.tenant_id,
    )
    if not row:
        raise HTTPException(404, "Stock asset not found")
    abs_path = service.get_file_abs_path(row)
    if abs_path is None:
        raise HTTPException(404, "Stock asset file missing on disk")
    return FileResponse(
        abs_path,
        media_type=row.mime_type or "image/png",
        filename=abs_path.name,
    )
