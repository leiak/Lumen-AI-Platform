"""M36.2.1: Stock footage / image library ORM.

Built-in stock assets are global (tenant_id=NULL) and visible to every tenant.
User-uploaded stock (M36.2.1.x) will reuse this model with tenant_id=current
user.tenant_id.

Spec: docs-internal/superpowers/specs/m36-2-video-ecosystem.md §2.1
"""
from sqlalchemy import Column, Integer, String, JSON, Text, Index
from lumen_models.base import BaseModel


class StockAsset(BaseModel):
    __tablename__ = "stock_assets"

    name = Column(String(120), nullable=False, comment="Human-readable label, e.g. '金色日落山景'")
    category = Column(String(40), nullable=False, index=True, comment="风景 / 抽象 / 商务 / 人物 / 产品")
    tags = Column(JSON, nullable=True, comment="Free-form tag list, e.g. ['sunset', 'mountain']")
    file_path = Column(String(500), nullable=False, comment="Relative to settings.STORAGE_DIR, e.g. 'stock/landscape/sunset-01.png'")
    mime_type = Column(String(50), nullable=False, default="image/png")
    file_size = Column(Integer, nullable=False, default=0)
    width = Column(Integer, nullable=True)
    height = Column(Integer, nullable=True)
    source = Column(String(20), nullable=False, default="builtin", comment="builtin | pexels | uploaded")
    # pexels_id = external id when source='pexels' (NULL for builtin / uploaded)
    pexels_id = Column(Integer, nullable=True)
    # tenant_id NULL = global / builtin (visible to all tenants)
    tenant_id = Column(Integer, nullable=True, index=True, comment="NULL = global builtin")
    description = Column(Text, nullable=True)

    __table_args__ = (
        Index("ix_stock_assets_category_created", "category", "created_at"),
    )