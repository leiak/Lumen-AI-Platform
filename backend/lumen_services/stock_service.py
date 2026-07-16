"""Stock asset service layer.

M36.2.1 提供全局内置素材和当前租户素材的只读查询；上传与 Pexels 接入留给后续里程碑。
"""
from pathlib import Path, PurePosixPath
from typing import List, Optional, Tuple

from sqlalchemy import or_
from sqlalchemy.orm import Session

from lumen_core.config import settings
from lumen_models.stock_asset import StockAsset


class StockService:
    """Read-only access to the global + per-tenant stock asset library."""

    def list_assets(
        self,
        db: Session,
        *,
        tenant_id: Optional[int],
        category: Optional[str] = None,
        search: Optional[str] = None,
        page: int = 1,
        page_size: int = 24,
    ) -> Tuple[List[StockAsset], int]:
        """List global assets and assets belonging to the current tenant.

        全局内置素材的 ``tenant_id`` 为 NULL；租户素材只能由所属租户看到，避免
        列表与详情接口泄露其他租户的文件元数据。
        """
        query = db.query(StockAsset).filter(
            or_(StockAsset.tenant_id.is_(None), StockAsset.tenant_id == tenant_id)
        )
        if category:
            query = query.filter(StockAsset.category == category)
        if search:
            like = f"%{search}%"
            # 搜 name + tags(name 用 LIKE,tags 是 JSON 用 json search 较复杂,
            # 这里只 LIKE name 已经够用)
            query = query.filter(StockAsset.name.like(like))
        total = query.count()
        rows = (
            query.order_by(StockAsset.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        return rows, total

    def get(
        self, db: Session, *, asset_id: int, tenant_id: Optional[int]
    ) -> Optional[StockAsset]:
        """Get one global or current-tenant asset."""
        return (
            db.query(StockAsset)
            .filter(
                StockAsset.id == asset_id,
                or_(StockAsset.tenant_id.is_(None), StockAsset.tenant_id == tenant_id),
            )
            .first()
        )

    def get_file_abs_path(self, row: StockAsset) -> Optional[Path]:
        """Resolve a stock file safely under ``STORAGE_DIR``.

        只接受相对 POSIX 路径并用 ``resolve`` + ``relative_to`` 阻止 ``..`` 和
        符号链接逃逸到 storage 根目录之外；文件不存在或不是普通文件时返回 None。
        """
        if not row.file_path:
            return None
        relative_path = PurePosixPath(row.file_path)
        if relative_path.is_absolute():
            return None
        storage_root = settings.STORAGE_DIR.resolve()
        abs_path = (storage_root / relative_path).resolve()
        try:
            abs_path.relative_to(storage_root)
        except ValueError:
            return None
        return abs_path if abs_path.is_file() else None