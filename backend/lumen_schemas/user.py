from pydantic import BaseModel
from datetime import datetime
from typing import Optional


class UserBase(BaseModel):
    username: str
    # P0-2 (2026-06-20): 改 EmailStr → str.
    # dev DB seed admin user 邮箱是 "admin@local" (无 TLD),
    # Pydantic v2 EmailStr 严格校验需要 xxx.yyy 格式, list_users 在序列化时
    # 触发 ValidationError → 500, 而 dynamic_cors middleware 在 5xx 路径上
    # 因外层 uvicorn ServerErrorMiddleware 拦截而不 inject ACAO header,
    # 浏览器误判为 CORS blocked (实际是 500).
    # 放宽为 str 兼容 dev seed, production 可后续加 Pydantic validator.
    email: str
    full_name: Optional[str] = None


class UserCreate(UserBase):
    password: str


class UserUpdate(BaseModel):
    email: Optional[str] = None
    full_name: Optional[str] = None
    password: Optional[str] = None
    is_active: Optional[bool] = None


class UserResponse(UserBase):
    id: int
    tenant_id: int
    is_active: bool
    is_superuser: bool
    created_at: datetime

    class Config:
        from_attributes = True


class UserSimpleResponse(UserBase):
    """极简版用户信息(只含 id + 姓名 + 邮箱),给 owner_select 之类的下拉用。

    不含 tenant_id / is_active / is_superuser / created_at,
    也就不暴露用户的内部字段 — 用于「指派给某个用户」之类只需显示
    名字的 UI 场景,任何已认证用户都能查同租户的 active 用户。
    """

    id: int

    class Config:
        from_attributes = True


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
