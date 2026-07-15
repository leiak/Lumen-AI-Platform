"""PPT generation task persistence model.

Spec: docs-internal/superpowers/specs/m35-ppt-generation.md §11
"""
from sqlalchemy import Column, Integer, String, Text, ForeignKey, Index, Enum as SQLEnum
from lumen_models.base import BaseModel


class PptTask(BaseModel):
    __tablename__ = "ppt_tasks"

    task_id = Column(String(64), unique=True, nullable=False, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id"), nullable=True, index=True)
    title = Column(String(255), nullable=False)
    status = Column(
        SQLEnum("pending", "processing", "completed", "failed", name="ppt_task_status"),
        nullable=False,
        default="pending",
    )
    mode = Column(SQLEnum("frontend", "backend", name="ppt_task_mode"), nullable=False, default="backend")
    style = Column(String(32), nullable=False, default="simple")
    include_charts = Column(Integer, nullable=False, default=0)  # TINYINT(1)
    file_url = Column(String(512), nullable=True)
    error = Column(Text, nullable=True)
    schema_json = Column(Text, nullable=True)  # 存储生成的 PPT JSON Schema

    __table_args__ = (
        Index("ix_ppt_tasks_tenant_status", "tenant_id", "status"),
        Index("ix_ppt_tasks_user_created", "user_id", "created_at"),
    )
