"""M33 客户管理(CRM) - Pydantic schemas for /api/v1/customers/*

Spec: docs/superpowers/specs/2026-06-20-customer-management-design.md §4.3
Plan: docs/superpowers/plans/2026-06-20-customer-management.md

All schemas follow project conventions:
- ``Optional[X] = None`` for nullable fields
- ``Field(min_length, max_length, pattern, ge, le)`` for constraints
- ``Literal[...]`` for enum values
- All datetime fields are timezone-naive UTC by convention (project-wide)
"""
from datetime import date, datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# CustomFieldResolved - 详情里 custom_fields 解析后的结构(带 schema 元信息)
# ---------------------------------------------------------------------------

class CustomFieldResolved(BaseModel):
    """``CustomerResponse.custom_fields_schema_resolved`` 单条记录。

    把 ``customers.custom_fields`` 的 dict 按 ``CustomerFieldDefinition``
    解析,前端可直接渲染 label / type / options / required。
    """
    key: str
    label: str
    type: str  # text / number / date / select / multiselect / textarea
    value: Optional[Any] = None
    required: bool = False
    options: Optional[List[str]] = None  # select / multiselect 的选项


# ---------------------------------------------------------------------------
# Customer 主表 schemas
# ---------------------------------------------------------------------------

# Spec §3.1 enum 约束
Level = Literal["vip", "normal", "potential", "lost"]
Source = Literal["referral", "website", "exhibition", "ad", "other"]
Gender = Literal["M", "F", "U"]
CompanySize = Literal["1-10", "11-50", "51-200", "201-1000", "1000+"]


class CustomerCreate(BaseModel):
    """Body for ``POST /api/v1/customers``.

    Spec §4.3 — ``owner_user_id`` 必填(销售负责人);
    ``custom_fields`` 在 service 层按 field_definitions 校验。
    """
    name: str = Field(min_length=1, max_length=100)
    owner_user_id: int

    # 基础信息
    phone: Optional[str] = Field(default=None, max_length=50)
    email: Optional[str] = Field(default=None, max_length=200)
    wechat: Optional[str] = Field(default=None, max_length=100)
    gender: Optional[Gender] = None
    birthday: Optional[date] = None
    address: Optional[str] = Field(default=None, max_length=500)
    avatar_url: Optional[str] = Field(default=None, max_length=500)

    # 公司信息
    company_name: Optional[str] = Field(default=None, max_length=200)
    company_position: Optional[str] = Field(default=None, max_length=100)
    industry: Optional[str] = Field(default=None, max_length=100)
    company_size: Optional[CompanySize] = None
    company_website: Optional[str] = Field(default=None, max_length=500)

    # 客户属性
    level: Level = "potential"
    source: Optional[Source] = None
    tags: Optional[List[str]] = None
    custom_fields: Optional[Dict[str, Any]] = None
    remark: Optional[str] = None


class CustomerUpdate(BaseModel):
    """Body for ``PUT /api/v1/customers/{id}`` — 所有字段 Optional。"""
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    owner_user_id: Optional[int] = None  # 转单

    phone: Optional[str] = Field(default=None, max_length=50)
    email: Optional[str] = Field(default=None, max_length=200)
    wechat: Optional[str] = Field(default=None, max_length=100)
    gender: Optional[Gender] = None
    birthday: Optional[date] = None
    address: Optional[str] = Field(default=None, max_length=500)
    avatar_url: Optional[str] = Field(default=None, max_length=500)

    company_name: Optional[str] = Field(default=None, max_length=200)
    company_position: Optional[str] = Field(default=None, max_length=100)
    industry: Optional[str] = Field(default=None, max_length=100)
    company_size: Optional[CompanySize] = None
    company_website: Optional[str] = Field(default=None, max_length=500)

    level: Optional[Level] = None
    source: Optional[Source] = None
    tags: Optional[List[str]] = None
    custom_fields: Optional[Dict[str, Any]] = None
    remark: Optional[str] = None


class CustomerListItem(BaseModel):
    """列表页 row shape — 手机号脱敏。

    Spec §4.2 — 列表里 phone 返 ``phone_masked``(中间 4 位 ``*``),完整 phone
    只在详情 API 返。owner_user_name 由 service 层 join users 表填充。
    """
    id: int
    name: str
    phone_masked: Optional[str] = None  # 138****1234
    email: Optional[str] = None
    company_name: Optional[str] = None
    company_position: Optional[str] = None
    level: str
    source: Optional[str] = None
    tags: Optional[List[str]] = None
    owner_user_id: int
    owner_user_name: Optional[str] = None
    last_follow_up_at: Optional[datetime] = None
    next_follow_up_at: Optional[datetime] = None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class CustomerDetail(BaseModel):
    """详情页 shape — 手机号完整 + 自定义字段 schema 解析。"""
    id: int
    name: str
    phone: Optional[str] = None
    email: Optional[str] = None
    wechat: Optional[str] = None
    avatar_url: Optional[str] = None
    gender: Optional[str] = None
    birthday: Optional[date] = None
    address: Optional[str] = None

    company_name: Optional[str] = None
    company_position: Optional[str] = None
    industry: Optional[str] = None
    company_size: Optional[str] = None
    company_website: Optional[str] = None

    level: str
    source: Optional[str] = None
    tags: Optional[List[str]] = None
    custom_fields: Optional[Dict[str, Any]] = None
    custom_fields_schema_resolved: List[CustomFieldResolved] = Field(default_factory=list)
    remark: Optional[str] = None

    owner_user_id: int
    owner_user_name: Optional[str] = None
    created_by: int
    last_follow_up_at: Optional[datetime] = None
    next_follow_up_at: Optional[datetime] = None
    follow_ups_count: int = 0

    is_active: bool
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# FollowUp schemas
# ---------------------------------------------------------------------------

FollowUpType = Literal["phone", "wechat", "email", "meeting", "other"]


class FollowUpCreate(BaseModel):
    """Body for ``POST /api/v1/customers/{id}/follow-ups``."""
    follow_up_type: FollowUpType
    content: str = Field(min_length=1, max_length=5000)
    next_step: Optional[str] = Field(default=None, max_length=1000)
    next_follow_up_at: Optional[datetime] = None


class FollowUpUpdate(BaseModel):
    """Body for ``PUT /api/v1/customers/{id}/follow-ups/{fid}``."""
    follow_up_type: Optional[FollowUpType] = None
    content: Optional[str] = Field(default=None, min_length=1, max_length=5000)
    next_step: Optional[str] = Field(default=None, max_length=1000)
    next_follow_up_at: Optional[datetime] = None


class FollowUpResponse(BaseModel):
    """timeline 单条记录。"""
    id: int
    customer_id: int
    follow_up_type: str
    content: str
    next_step: Optional[str] = None
    next_follow_up_at: Optional[datetime] = None
    ai_suggested: bool
    user_id: int
    user_name: Optional[str] = None
    created_at: datetime


# ---------------------------------------------------------------------------
# UpcomingFollowUp - 我的待跟进列表项
# ---------------------------------------------------------------------------

class UpcomingFollowUpItem(BaseModel):
    """``GET /api/v1/customers/upcoming-follow-ups`` 单条记录。

    只返「下次跟进时间 + 客户基础信息 + 上次跟进内容摘要」,不返完整 follow_ups。
    """
    customer_id: int
    customer_name: str
    level: str
    owner_user_id: int
    next_follow_up_at: datetime
    last_follow_up_content: Optional[str] = None  # 截断 50 字
    days_until_due: int


# ---------------------------------------------------------------------------
# AIAdvisor schemas
# ---------------------------------------------------------------------------

class AIAdvisorRequest(BaseModel):
    """Body for ``POST /api/v1/customers/{id}/ai/suggest``."""
    model_config_id: Optional[int] = None  # None = 用 tenant 默认 chat 模型
    focus: Optional[str] = Field(default=None, max_length=100)


class AIAdvisorResponse(BaseModel):
    """Response for ``POST /api/v1/customers/{id}/ai/suggest``."""
    suggested_message: str
    suggested_next_follow_up_at: Optional[datetime] = None
    reasoning: str
    llm_call_id: str
    duration_ms: int


# ---------------------------------------------------------------------------
# CustomerFieldDefinition schemas
# ---------------------------------------------------------------------------

FieldType = Literal["text", "number", "date", "select", "multiselect", "textarea"]


class CustomerFieldDefinitionCreate(BaseModel):
    """Body for ``POST /api/v1/customer-fields``."""
    field_key: str = Field(
        min_length=1,
        max_length=50,
        pattern=r"^[a-z][a-z0-9_]{0,49}$",
        description="英文 + 下划线,小写开头,创建后不可修改",
    )
    field_label: str = Field(min_length=1, max_length=100)
    field_type: FieldType
    options: Optional[List[str]] = None  # select / multiselect 时必填
    required: bool = False
    order_index: int = 0


class CustomerFieldDefinitionUpdate(BaseModel):
    """Body for ``PUT /api/v1/customer-fields/{id}`` — field_key 不可改。

    修改 ``field_type`` 时,service 层检查是否有客户引用,有则 422。
    """
    field_label: Optional[str] = Field(default=None, min_length=1, max_length=100)
    field_type: Optional[FieldType] = None
    options: Optional[List[str]] = None
    required: Optional[bool] = None
    order_index: Optional[int] = None
    is_active: Optional[bool] = None


class CustomerFieldDefinitionResponse(BaseModel):
    """Response for 字段定义 CRUD。"""
    id: int
    field_key: str
    field_label: str
    field_type: str
    options: Optional[List[str]] = None
    required: bool
    order_index: int
    is_active: bool
    created_by: int
    created_at: datetime
    updated_at: datetime