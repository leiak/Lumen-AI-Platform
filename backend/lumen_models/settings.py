from sqlalchemy import Column, Integer, String, Boolean, Text
from lumen_core.database import Base

class SystemSettings(Base):
    __tablename__ = "system_settings"

    id = Column(Integer, primary_key=True, index=True)
    system_name = Column(String(100), default="Lumen AI Platform")
    system_description = Column(Text, nullable=True)
    default_model = Column(Integer, nullable=True)
    embedding_model = Column(Integer, nullable=True)
    chat_history_days = Column(Integer, default=30)
    tenant_id = Column(Integer, nullable=True, index=True)

class SecuritySettings(Base):
    __tablename__ = "security_settings"

    id = Column(Integer, primary_key=True, index=True)
    enforce_password_complexity = Column(Boolean, default=True)
    min_password_length = Column(Integer, default=8)
    login_fail_lock_count = Column(Integer, default=5)
    token_expire_minutes = Column(Integer, default=30)
    tenant_id = Column(Integer, nullable=True, index=True)