"""M36.2.2: Stock background-music Pydantic schemas.

Mirrors ``lumen_schemas.stock_asset`` — separate Create/Read/ListItem
shapes so the gallery list stays light while the detail page surfaces
every column. The audio proxy at ``/api/v1/stock-musics/{id}/file`` is
Bearer-protected; consumers must use ``fetch + Bearer + blob +
createObjectURL`` (see MEMORY 2026-06-20).
"""
from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict


StockMusicSource = Literal["builtin", "uploaded"]


class StockMusicListItem(BaseModel):
    """Lightweight row for the gallery list — name + duration + category."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    category: str
    description: Optional[str] = None
    mime_type: str
    file_size: int
    duration_seconds: float
    source: StockMusicSource
    created_at: datetime


class StockMusicDetail(StockMusicListItem):
    """Full row returned by ``GET /stock-musics/{id}``.

    Includes ``file_path`` so the frontend can build the proxy URL
    (``/api/v1/stock-musics/{id}/file``). The proxy enforces Bearer
    auth — we do NOT leak an absolute file path.
    """

    file_path: str
    tenant_id: Optional[int] = None
