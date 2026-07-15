from pydantic import BaseModel
from datetime import datetime


class TenantBase(BaseModel):
    name: str
    code: str
    max_users: int = 10


class TenantCreate(TenantBase):
    pass


class TenantUpdate(BaseModel):
    name: Optional[str] = None
    status: Optional[bool] = None
    max_users: Optional[int] = None


class TenantResponse(TenantBase):
    id: int
    status: bool
    created_at: datetime

    class Config:
        from_attributes = True
