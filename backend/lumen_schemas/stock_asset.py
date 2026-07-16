"""M36.2.1: Stock asset Pydantic schemas (list + detail)."""
from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict


StockSource = Literal["builtin", "pexels", "uploaded"]


class StockAssetListItem(BaseModel):
    """Lightweight row for the gallery list."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    category: str
    tags: Optional[List[str]] = None
    mime_type: str
    width: Optional[int] = None
    height: Optional[int] = None
    file_size: int
    source: StockSource
    created_at: datetime


class StockAssetDetail(StockAssetListItem):
    """Full row returned by GET /stock-assets/{id}.

    Frontend uses ``file_path`` to build the proxy URL
    (``/api/v1/stock-assets/{id}/image``). We do NOT leak the relative
    path as an absolute URL — the proxy endpoint enforces Bearer auth.
    """

    file_path: str
    description: Optional[str] = None
    pexels_id: Optional[int] = None
    tenant_id: Optional[int] = None