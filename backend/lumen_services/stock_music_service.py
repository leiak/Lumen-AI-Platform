"""Stock background-music service layer.

M36.2.2 — read-only access to the global builtin + per-tenant BGM
library, mirroring ``lumen_services.stock_service`` (M36.2.1). Upload
+ per-tenant management is intentionally out of scope for the initial
ship; BGM seeding happens via ``lumen_scripts.seed_stock_musics``.
"""
from pathlib import Path, PurePosixPath
from typing import List, Optional, Tuple

from sqlalchemy import or_
from sqlalchemy.orm import Session

from lumen_core.config import settings
from lumen_models.stock_music import StockMusic


class StockMusicService:
    """Read-only access to the global + per-tenant background-music library."""

    def list_musics(
        self,
        db: Session,
        *,
        tenant_id: Optional[int],
        category: Optional[str] = None,
        search: Optional[str] = None,
        page: int = 1,
        page_size: int = 24,
    ) -> Tuple[List[StockMusic], int]:
        """List global builtin BGM + the current tenant's BGM.

        Same visibility rule as ``StockService.list_assets``:
        ``tenant_id IS NULL`` rows are visible to every tenant; otherwise
        only the owning tenant. Filter by category / name substring when
        given. Newest-first ordering matches the rest of the gallery.
        """
        query = db.query(StockMusic).filter(
            or_(StockMusic.tenant_id.is_(None), StockMusic.tenant_id == tenant_id)
        )
        if category:
            query = query.filter(StockMusic.category == category)
        if search:
            like = f"%{search}%"
            query = query.filter(StockMusic.name.like(like))
        total = query.count()
        rows = (
            query.order_by(StockMusic.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        return rows, total

    def get(
        self, db: Session, *, music_id: int, tenant_id: Optional[int]
    ) -> Optional[StockMusic]:
        """Look up one BGM visible to the current tenant (global or own)."""
        return (
            db.query(StockMusic)
            .filter(
                StockMusic.id == music_id,
                or_(StockMusic.tenant_id.is_(None), StockMusic.tenant_id == tenant_id),
            )
            .first()
        )

    def get_file_abs_path(self, row: StockMusic) -> Optional[Path]:
        """Resolve a stock-music file safely under ``STORAGE_DIR``.

        Mirrors ``StockService.get_file_abs_path``: only relative POSIX
        paths are accepted, ``..`` and absolute paths return ``None``,
        and the resolved path must live under ``STORAGE_DIR``. Returns
        ``None`` if the row has no ``file_path`` or the on-disk file is
        missing.
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
