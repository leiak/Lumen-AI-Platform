"""Generated image persistence model.

Spec: docs/superpowers/specs/2026-06-11-image-generation-design.md §3.2
"""
from sqlalchemy import Column, Integer, String, Text, JSON, LargeBinary, ForeignKey, Index
from lumen_models.base import BaseModel


class GeneratedImage(BaseModel):
    __tablename__ = "generated_images"

    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    model_config_id = Column(
        Integer,
        ForeignKey("model_configs.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    batch_id = Column(String(36), nullable=True, index=True)
    prompt = Column(Text, nullable=False)
    negative_prompt = Column(Text, nullable=True)
    size = Column(String(20), nullable=False)
    n = Column(Integer, nullable=False, default=1)
    quality = Column(String(20), nullable=True)
    style = Column(String(20), nullable=True)
    params = Column(JSON, nullable=True)
    file_path = Column(String(500), nullable=False)
    file_size = Column(Integer, nullable=False)
    mime_type = Column(String(50), nullable=False)
    width = Column(Integer, nullable=True)
    height = Column(Integer, nullable=True)
    # MEDIUMBLOB 上限 16MB, 256x256 JPEG ~10-30KB 远低于
    thumbnail = Column(LargeBinary(length=16777215), nullable=True)
    status = Column(String(20), nullable=False, default="pending")  # pending/generating/completed/failed
    error_message = Column(Text, nullable=True)
    duration_ms = Column(Integer, nullable=True)

    __table_args__ = (
        Index("ix_gen_images_tenant_status_created", "tenant_id", "status", "created_at"),
    )
