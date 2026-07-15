from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

class PermissionResponse(BaseModel):
    id: int
    name: str
    resource: Optional[str]
    action: Optional[str]

    class Config:
        from_attributes = True

class RoleCreate(BaseModel):
    name: str
    description: Optional[str] = None
    permission_ids: List[int] = []

class RoleResponse(BaseModel):
    id: int
    name: str
    description: Optional[str]
    is_active: bool
    permissions: List[PermissionResponse] = []

    class Config:
        from_attributes = True
