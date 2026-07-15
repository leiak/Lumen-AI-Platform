from sqlalchemy import Column, Integer, String, Text, ForeignKey, JSON
from sqlalchemy.orm import relationship
from lumen_models.base import BaseModel


class NLPTrainingClassification(BaseModel):
    __tablename__ = "nlp_classification"

    name = Column(String(100), nullable=False)
    description = Column(Text)
    keywords = Column(JSON, default=list)  # 关键词列表
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)

    annotations = relationship("NLPAnnotation", back_populates="classification", cascade="all, delete-orphan")


class NLPAnnotation(BaseModel):
    __tablename__ = "nlp_annotation"

    content = Column(Text, nullable=False)
    classification_id = Column(Integer, ForeignKey("nlp_classification.id"), nullable=False)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)

    classification = relationship("NLPTrainingClassification", back_populates="annotations")


class NLPQA(BaseModel):
    __tablename__ = "nlp_qa"

    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=False)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
