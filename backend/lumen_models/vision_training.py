from sqlalchemy import Column, Integer, String, ForeignKey, JSON
from sqlalchemy.orm import relationship
from lumen_models.base import BaseModel


class VisionClassification(BaseModel):
    __tablename__ = "vision_classification"

    name = Column(String(100), nullable=False)
    description = Column(String(500))
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)

    images = relationship("VisionImage", back_populates="classification", cascade="all, delete-orphan")


class VisionImage(BaseModel):
    __tablename__ = "vision_image"

    filename = Column(String(255), nullable=False)
    file_path = Column(String(500), nullable=False)
    classification_id = Column(Integer, ForeignKey("vision_classification.id"), nullable=False, index=True)
    features = Column(JSON)  # 特征向量
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)

    classification = relationship("VisionClassification", back_populates="images")
