from sqlalchemy import Column, String, Text, Integer, ForeignKey, JSON, Index
from sqlalchemy.orm import relationship
from lumen_models.base import BaseModel


class WorkflowTemplate(BaseModel):
    """
    A published, reusable workflow template.

    Workflow templates are public to all tenants — any authenticated user
    can browse them and one-click import to create their own copy as
    a regular Workflow owned by their tenant.
    """
    __tablename__ = "workflow_templates"

    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    category = Column(String(50), nullable=False, index=True, default="general")
    tags = Column(JSON, nullable=True)  # list[str]
    workflow_json = Column(JSON, nullable=False)  # the WorkflowDefinition
    author_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    author_name = Column(String(100), nullable=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=True, index=True)  # optional
    downloads = Column(Integer, default=0, nullable=False)

    author = relationship("User", foreign_keys=[author_id])

    __table_args__ = (
        Index("idx_wftemplate_category", "category"),
    )

    def __repr__(self):
        return f"<WorkflowTemplate(id={self.id}, name={self.name}, category={self.category})>"
