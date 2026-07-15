from pydantic import BaseModel, Field
from typing import Optional

class SystemSettingsBase(BaseModel):
    system_name: str = "Lumen AI Platform"
    system_description: Optional[str] = None
    default_model: Optional[int] = None
    embedding_model: Optional[int] = None
    chat_history_days: int = Field(default=30, ge=1, le=365)

class SystemSettingsUpdate(BaseModel):
    system_name: Optional[str] = Field(default=None, max_length=100)
    system_description: Optional[str] = None
    default_model: Optional[int] = None
    embedding_model: Optional[int] = None
    chat_history_days: Optional[int] = Field(default=None, ge=1, le=365)

class SystemSettingsResponse(SystemSettingsBase):
    id: Optional[int] = None

    class Config:
        from_attributes = True

class SecuritySettingsBase(BaseModel):
    enforce_password_complexity: bool = True
    min_password_length: int = Field(default=8, ge=6, le=128)
    login_fail_lock_count: int = Field(default=5, ge=1, le=20)
    token_expire_minutes: int = Field(default=30, ge=5, le=1440)

class SecuritySettingsUpdate(BaseModel):
    enforce_password_complexity: Optional[bool] = None
    min_password_length: Optional[int] = Field(default=None, ge=6, le=128)
    login_fail_lock_count: Optional[int] = Field(default=None, ge=1, le=20)
    token_expire_minutes: Optional[int] = Field(default=None, ge=5, le=1440)

class SecuritySettingsResponse(SecuritySettingsBase):
    id: Optional[int] = None

    class Config:
        from_attributes = True