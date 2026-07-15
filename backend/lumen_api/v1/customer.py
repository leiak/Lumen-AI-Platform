"""M33 客户管理(CRM) - HTTP endpoints.

Spec: docs/superpowers/specs/2026-06-20-customer-management-design.md §4.1
Plan: docs/superpowers/plans/2026-06-20-customer-management.md

CP1 范围 — 10 个 endpoint:
- GET    /api/v1/customers                     列表(多维过滤)
- POST   /api/v1/customers                     创建
- GET    /api/v1/customers/{id}                详情(含 custom_fields 解析)
- PUT    /api/v1/customers/{id}                更新
- DELETE /api/v1/customers/{id}                软删
- POST   /api/v1/customers/{id}/restore        恢复
- GET    /api/v1/customer-fields               字段定义列表
- POST   /api/v1/customer-fields               创建字段定义
- PUT    /api/v1/customer-fields/{id}          更新
- DELETE /api/v1/customer-fields/{id}          删除

CP2 加跟进 5 endpoint + upcoming-follow-ups 1 endpoint。
CP3 加 AI suggest 1 endpoint。

Cross-tenant 隔离由 service 层 ``get()`` / ``get_field()`` 内部完成:
跨租户访问返 404(防 IDOR 信息泄露)。

注册位置: ``backend/app/api/v1/__init__.py`` 顶层 — 主 router + fields router。
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from lumen_api.v1.auth import get_current_user
from lumen_core.database import get_db
from lumen_models.user import User
from lumen_schemas.common import PaginatedResponse, SingleResponse
from lumen_schemas.customer import (
    AIAdvisorRequest,
    AIAdvisorResponse,
    CustomerCreate,
    CustomerDetail,
    CustomerFieldDefinitionCreate,
    CustomerFieldDefinitionResponse,
    CustomerFieldDefinitionUpdate,
    CustomerListItem,
    CustomerUpdate,
    FollowUpCreate,
    FollowUpResponse,
    FollowUpUpdate,
    UpcomingFollowUpItem,
)
from lumen_services.customer.ai_advisor import AIAdvisor
from lumen_services.customer.customer_service import CustomerService
from lumen_services.customer.field_service import CustomerFieldService
from lumen_services.customer.follow_up_service import FollowUpService

log = logging.getLogger(__name__)

# 主 router:客户档案 CRUD。prefix 拼出 /api/v1/customers
router = APIRouter(prefix="/customers", tags=["customer"])
# 子 router:字段定义 CRUD。prefix 拼出 /api/v1/customer-fields
fields_router = APIRouter(prefix="/customer-fields", tags=["customer-fields"])

# Module-level service singletons(项目惯例:无状态 service 类,singleton 安全)
customer_service = CustomerService()
field_service = CustomerFieldService()
follow_up_service = FollowUpService()


# ---------------------------------------------------------------------------
# 客户列表 + 创建
# ---------------------------------------------------------------------------

@router.get("", response_model=PaginatedResponse[CustomerListItem])
def list_customers(
    page: int = 1,
    page_size: int = 20,
    keyword: Optional[str] = None,
    levels: Optional[str] = Query(None, description="逗号分隔,例: vip,normal"),
    sources: Optional[str] = Query(None, description="逗号分隔,例: referral,website"),
    owner_user_id: Optional[int] = None,
    industry: Optional[str] = None,
    tags: Optional[str] = Query(None, description="逗号分隔,AND 过滤,例: 决策人,紧急"),
    next_follow_up_before: Optional[datetime] = None,
    is_active: Optional[bool] = True,
    sort: Optional[str] = Query(
        None,
        description="created_at_desc / last_follow_up_at_desc / next_follow_up_at_asc / level_asc",
    ),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """分页列表 + 多维过滤。手机号返 ``phone_masked``(中间 4 位 ``*``)。"""
    levels_list = [s.strip() for s in levels.split(",") if s.strip()] if levels else None
    sources_list = [s.strip() for s in sources.split(",") if s.strip()] if sources else None
    tags_list = [s.strip() for s in tags.split(",") if s.strip()] if tags else None

    rows, total = customer_service.list(
        db,
        current_user=current_user,
        page=page,
        page_size=page_size,
        keyword=keyword,
        levels=levels_list,
        sources=sources_list,
        owner_user_id=owner_user_id,
        industry=industry,
        tags=tags_list,
        next_follow_up_before=next_follow_up_before,
        is_active=is_active,
        sort=sort,
    )

    # 批量拉 owner_user_name,避免 N+1
    owner_ids = list({r.owner_user_id for r in rows})
    owner_map = customer_service.get_owner_names_map(db, owner_ids)

    items = [
        customer_service.to_list_item(db, r, owner_map.get(r.owner_user_id))
        for r in rows
    ]
    return PaginatedResponse(
        data=items, total=total, page=page, page_size=page_size,
    )


@router.post("", response_model=SingleResponse[CustomerDetail], status_code=201)
def create_customer(
    payload: CustomerCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """创建客户。手机号等基础信息写入,custom_fields 按字段定义校验。"""
    row = customer_service.create(db, current_user=current_user, payload=payload)
    owner_name = customer_service.get_owner_names_map(
        db, [row.owner_user_id]
    ).get(row.owner_user_id)
    return SingleResponse(data=customer_service.to_detail(db, row, owner_name))


# ---------------------------------------------------------------------------
# 我的待跟进列表(必须在 /{customer_id} 之前注册,避免路径冲突)
# ---------------------------------------------------------------------------

@router.get(
    "/upcoming-follow-ups",
    response_model=PaginatedResponse[UpcomingFollowUpItem],
)
def upcoming_follow_ups(
    page: int = 1,
    page_size: int = 20,
    owner_user_id: Optional[int] = None,
    days: int = 7,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """我的待跟进客户(按 next_follow_up_at 升序;过期也显示,days_until_due 负数)。"""
    items = follow_up_service.upcoming(
        db,
        current_user=current_user,
        owner_user_id=owner_user_id,
        days=days,
    )
    start = (page - 1) * page_size
    page_items = items[start : start + page_size]
    return PaginatedResponse(
        data=page_items, total=len(items), page=page, page_size=page_size,
    )


# ---------------------------------------------------------------------------
# 客户详情 / 更新 / 软删 / 恢复
# ---------------------------------------------------------------------------

@router.get("/{customer_id}", response_model=SingleResponse[CustomerDetail])
def get_customer(
    customer_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """客户详情。手机号完整 + custom_fields 按 schema 解析。"""
    row = customer_service.get(db, current_user=current_user, customer_id=customer_id)
    owner_name = customer_service.get_owner_names_map(
        db, [row.owner_user_id]
    ).get(row.owner_user_id)
    return SingleResponse(data=customer_service.to_detail(db, row, owner_name))


@router.put("/{customer_id}", response_model=SingleResponse[CustomerDetail])
def update_customer(
    customer_id: int,
    payload: CustomerUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """更新客户元数据。所有字段 Optional,只改传入的。"""
    row = customer_service.update(
        db, current_user=current_user, customer_id=customer_id, payload=payload
    )
    owner_name = customer_service.get_owner_names_map(
        db, [row.owner_user_id]
    ).get(row.owner_user_id)
    return SingleResponse(data=customer_service.to_detail(db, row, owner_name))


@router.delete("/{customer_id}", status_code=204)
def delete_customer(
    customer_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """软删客户(is_active=False)。保留跟进记录(CASCADE 不删)。"""
    customer_service.soft_delete(
        db, current_user=current_user, customer_id=customer_id
    )
    return None


@router.post(
    "/{customer_id}/restore",
    response_model=SingleResponse[CustomerDetail],
)
def restore_customer(
    customer_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """恢复软删客户。"""
    row = customer_service.restore(
        db, current_user=current_user, customer_id=customer_id
    )
    owner_name = customer_service.get_owner_names_map(
        db, [row.owner_user_id]
    ).get(row.owner_user_id)
    return SingleResponse(data=customer_service.to_detail(db, row, owner_name))


# ---------------------------------------------------------------------------
# 跟进记录(CP2)
# ---------------------------------------------------------------------------

def _to_follow_up_response(
    db: Session, row, user_name: Optional[str] = None
) -> FollowUpResponse:
    return FollowUpResponse(
        id=row.id,
        customer_id=row.customer_id,
        follow_up_type=row.follow_up_type,
        content=row.content,
        next_step=row.next_step,
        next_follow_up_at=row.next_follow_up_at,
        ai_suggested=row.ai_suggested,
        user_id=row.user_id,
        user_name=user_name,
        created_at=row.created_at,
    )


@router.get(
    "/{customer_id}/follow-ups",
    response_model=PaginatedResponse[FollowUpResponse],
)
def list_follow_ups(
    customer_id: int,
    page: int = 1,
    page_size: int = 20,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """客户的跟进 timeline(按 created_at 倒序)。"""
    rows, total = follow_up_service.list(
        db, current_user=current_user, customer_id=customer_id,
        page=page, page_size=page_size,
    )
    user_ids = list({r.user_id for r in rows})
    user_map = customer_service.get_owner_names_map(db, user_ids)
    items = [_to_follow_up_response(db, r, user_map.get(r.user_id)) for r in rows]
    return PaginatedResponse(
        data=items, total=total, page=page, page_size=page_size,
    )


@router.post(
    "/{customer_id}/follow-ups",
    response_model=SingleResponse[FollowUpResponse],
    status_code=201,
)
def create_follow_up(
    customer_id: int,
    payload: FollowUpCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """新增跟进。事务内同步更新 customer.last/next_follow_up_at。"""
    row = follow_up_service.create(
        db, current_user=current_user, customer_id=customer_id, payload=payload,
    )
    user_name = customer_service.get_owner_names_map(
        db, [row.user_id]
    ).get(row.user_id)
    return SingleResponse(data=_to_follow_up_response(db, row, user_name))


@router.put(
    "/{customer_id}/follow-ups/{follow_up_id}",
    response_model=SingleResponse[FollowUpResponse],
)
def update_follow_up(
    customer_id: int,
    follow_up_id: int,
    payload: FollowUpUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """更新跟进。同步更新 customer 聚合字段。"""
    row = follow_up_service.update(
        db, current_user=current_user, customer_id=customer_id,
        follow_up_id=follow_up_id, payload=payload,
    )
    user_name = customer_service.get_owner_names_map(
        db, [row.user_id]
    ).get(row.user_id)
    return SingleResponse(data=_to_follow_up_response(db, row, user_name))


@router.delete(
    "/{customer_id}/follow-ups/{follow_up_id}",
    status_code=204,
)
def delete_follow_up(
    customer_id: int,
    follow_up_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """删除跟进(物理删除)。同步更新 customer 聚合字段。"""
    follow_up_service.delete(
        db, current_user=current_user, customer_id=customer_id,
        follow_up_id=follow_up_id,
    )
    return None


# ---------------------------------------------------------------------------
# AI 智能建议(CP3)
# ---------------------------------------------------------------------------

@router.post(
    "/{customer_id}/ai/suggest",
    response_model=SingleResponse[AIAdvisorResponse],
)
def ai_suggest(
    customer_id: int,
    payload: AIAdvisorRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """AI 智能建议 — 基于最近 5 条跟进 + 客户画像,推荐下次话术和时间。

    同步响应(5-15s),走 ``create_chat_model`` 自动登记 ``llm_call_logs``。
    """
    customer = customer_service.get(
        db, current_user=current_user, customer_id=customer_id
    )
    advisor = AIAdvisor(db, current_user=current_user)
    result = advisor.suggest_next_step(
        customer,
        model_config_id=payload.model_config_id,
        focus=payload.focus,
    )
    return SingleResponse(data=AIAdvisorResponse(**result))


# ---------------------------------------------------------------------------
# 自定义字段定义 CRUD(fields_router)
# ---------------------------------------------------------------------------

@fields_router.get("", response_model=PaginatedResponse[CustomerFieldDefinitionResponse])
def list_customer_fields(
    page: int = 1,
    page_size: int = 100,
    include_inactive: bool = False,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """字段定义列表。``include_inactive=True`` 时返所有(包括已禁用)。"""
    rows = field_service.list(
        db, current_user=current_user, include_inactive=include_inactive
    )
    # PaginatedResponse 信封仍要求 page / total / page_size;字段定义数小,内存分页
    start = (page - 1) * page_size
    page_rows = rows[start : start + page_size]
    items = [
        CustomerFieldDefinitionResponse(
            id=r.id,
            field_key=r.field_key,
            field_label=r.field_label,
            field_type=r.field_type,
            options=r.options,
            required=r.required,
            order_index=r.order_index,
            is_active=r.is_active,
            created_by=r.created_by,
            created_at=r.created_at,
            updated_at=r.updated_at,
        )
        for r in page_rows
    ]
    return PaginatedResponse(
        data=items, total=len(rows), page=page, page_size=page_size,
    )


@fields_router.post(
    "",
    response_model=SingleResponse[CustomerFieldDefinitionResponse],
    status_code=201,
)
def create_customer_field(
    payload: CustomerFieldDefinitionCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """创建字段定义。field_key UNIQUE(tenant_id) + options 必填校验。"""
    row = field_service.create(db, current_user=current_user, payload=payload)
    return SingleResponse(
        data=CustomerFieldDefinitionResponse(
            id=row.id,
            field_key=row.field_key,
            field_label=row.field_label,
            field_type=row.field_type,
            options=row.options,
            required=row.required,
            order_index=row.order_index,
            is_active=row.is_active,
            created_by=row.created_by,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
    )


@fields_router.put(
    "/{field_id}",
    response_model=SingleResponse[CustomerFieldDefinitionResponse],
)
def update_customer_field(
    field_id: int,
    payload: CustomerFieldDefinitionUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """更新字段定义。改 field_type 时若有客户引用 → 422。"""
    row = field_service.update(
        db, current_user=current_user, field_id=field_id, payload=payload
    )
    return SingleResponse(
        data=CustomerFieldDefinitionResponse(
            id=row.id,
            field_key=row.field_key,
            field_label=row.field_label,
            field_type=row.field_type,
            options=row.options,
            required=row.required,
            order_index=row.order_index,
            is_active=row.is_active,
            created_by=row.created_by,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
    )


@fields_router.delete("/{field_id}", status_code=204)
def delete_customer_field(
    field_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """删除字段定义。若有客户引用 → 422。"""
    field_service.delete(db, current_user=current_user, field_id=field_id)
    return None