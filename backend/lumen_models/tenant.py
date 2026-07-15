from sqlalchemy import Column, String, Boolean, Integer
from lumen_models.base import BaseModel


class Tenant(BaseModel):
    __tablename__ = "tenants"

    name = Column(String(100), nullable=False, index=True)
    code = Column(String(50), unique=True, nullable=False, index=True)
    status = Column(Boolean, default=True)
    max_users = Column(Integer, default=10)
