from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, JSON, Index, text
from sqlalchemy.sql import func
from lumen_models.base import BaseModel


class SkillMarketplace(BaseModel):
    """Skill marketplace catalog - available skills that can be installed"""
    __tablename__ = "skill_marketplace"

    name = Column(String(100), nullable=False)
    category = Column(String(50), nullable=False, index=True)  # code, writing, data, testing, design
    type = Column(String(20), nullable=False, default="prompt", server_default=text("'prompt'"), index=True)  # M16: prompt | script | http
    description = Column(Text, nullable=True)
    content = Column(Text, nullable=True)  # The actual skill prompt or code
    type_config = Column(JSON, nullable=True)  # M16: type-specific config (script code, http endpoint, etc.)
    version = Column(String(20), default="1.0.0")
    provider = Column(String(100), nullable=True)  # Who published this skill
    downloads = Column(Integer, default=0)  # Download/install count
    rating = Column(String(10), nullable=True)  # e.g., "4.8"
    meta_data = Column(JSON, nullable=True)  # Additional metadata like tags
    is_verified = Column(Integer, default=0)  # 1=verified, 0=unverified
    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("idx_marketplace_category", "category"),
    )

    def __repr__(self):
        return f"<SkillMarketplace(id={self.id}, name={self.name}, category={self.category})>"


class InstalledSkill(BaseModel):
    """Skills installed by tenants from marketplace"""
    __tablename__ = "installed_skills"

    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    marketplace_skill_id = Column(Integer, ForeignKey("skill_marketplace.id"), nullable=False)
    skill_id = Column(Integer, ForeignKey("skills.id"), nullable=True)  # Link to actual skill if created
    status = Column(String(20), default="active")  # active, inactive, error
    installed_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("idx_installed_tenant_marketplace", "tenant_id", "marketplace_skill_id", unique=True),
    )

    def __repr__(self):
        return f"<InstalledSkill(tenant_id={self.tenant_id}, marketplace_skill_id={self.marketplace_skill_id})>"
