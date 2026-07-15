"""M33 客户管理(CRM) - 客户档案 service.

Spec: docs/superpowers/specs/2026-06-20-customer-management-design.md §3.1 / §4.2
Plan: docs/superpowers/plans/2026-06-20-customer-management.md T4

Responsibilities:
- 客户 CRUD with multi-tenant 隔离
- 多维过滤(8 query param)+ 排序
- 列表 API 手机号脱敏,详情 API 完整
- custom_fields 写入前调 ``field_service.validate_custom_fields_dict``
- 详情返 ``custom_fields_schema_resolved``(按 field_definitions 解析)
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException
from sqlalchemy import or_, and_, func
from sqlalchemy.orm import Session

from lumen_models.customer import Customer, CustomerFieldDefinition, CustomerFollowUp
from lumen_models.user import User
from lumen_schemas.customer import (
    CustomerCreate,
    CustomerDetail,
    CustomerListItem,
    CustomerUpdate,
    CustomFieldResolved,
    Level,
    Source,
)
from lumen_services.customer.field_service import (
    validate_custom_fields_dict,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 手机号脱敏
# ---------------------------------------------------------------------------

def mask_phone(phone: Optional[str]) -> Optional[str]:
    """中间 4 位 ``*``。短号 (<7) 原样返回,空返 None。

    13800138000 → "138****8000"
    +86 138 0013 8000 → "+86 138****8000"(保留前缀)
    """
    if not phone:
        return None
    digits = phone.strip()
    if len(digits) < 7:
        return digits
    # 中国大陆手机号 11 位:前 3 + 中间 4 **** + 后 4
    if len(digits) == 11 and digits.isdigit():
        return f"{digits[:3]}****{digits[7:]}"
    # 国际号:找最后 11 位数字处理
    last11 = digits[-11:] if len(digits) >= 11 else digits
    if last11.isdigit() and len(last11) == 11:
        prefix = digits[: -11].rstrip()
        masked = f"{last11[:3]}****{last11[7:]}"
        return f"{prefix} {masked}" if prefix else masked
    return digits  # fallback


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class CustomerService:
    """客户档案业务逻辑。多租户隔离。"""

    # ---- 列表(多维过滤) ------------------------------------------------

    def list(
        self,
        db: Session,
        current_user: User,
        page: int = 1,
        page_size: int = 20,
        keyword: Optional[str] = None,
        levels: Optional[List[str]] = None,
        sources: Optional[List[str]] = None,
        owner_user_id: Optional[int] = None,
        industry: Optional[str] = None,
        tags: Optional[List[str]] = None,
        next_follow_up_before: Optional[datetime] = None,
        is_active: Optional[bool] = True,
        sort: Optional[str] = None,
    ) -> Tuple[List[Customer], int]:
        """多维过滤分页列表。

        Parameters
        ----------
        keyword : str, optional
            模糊匹配 name / phone / email / company_name(OR)
        levels : list[str], optional
            多选(逗号分隔),spec §4.2 GET /customers
        sources : list[str], optional
            多选
        tags : list[str], optional
            多 tag AND 过滤(JSON_CONTAINS)
        next_follow_up_before : datetime, optional
            next_follow_up_at < 此日期
        sort : str, optional
            created_at_desc / last_follow_up_at_desc /
            next_follow_up_at_asc / level_asc
        """
        q = db.query(Customer).filter(Customer.tenant_id == current_user.tenant_id)

        # 默认过滤掉软删的
        if is_active is not None:
            q = q.filter(Customer.is_active == is_active)

        # 关键字模糊(name / phone / email / company_name)
        if keyword:
            kw = f"%{keyword.strip()}%"
            q = q.filter(
                or_(
                    Customer.name.like(kw),
                    Customer.phone.like(kw),
                    Customer.email.like(kw),
                    Customer.company_name.like(kw),
                )
            )

        # 多选 level
        if levels:
            q = q.filter(Customer.level.in_(levels))

        # 多选 source
        if sources:
            q = q.filter(Customer.source.in_(sources))

        # 负责人
        if owner_user_id is not None:
            q = q.filter(Customer.owner_user_id == owner_user_id)

        # 行业
        if industry:
            q = q.filter(Customer.industry == industry)

        # 多 tag AND(JSON_CONTAINS)
        if tags:
            for tag in tags:
                q = q.filter(
                    func.json_contains(Customer.tags, func.json_quote(tag)) == 1
                )

        # 下次跟进时间上限
        if next_follow_up_before is not None:
            q = q.filter(Customer.next_follow_up_at < next_follow_up_before)

        # 排序
        if sort == "last_follow_up_at_desc":
            q = q.order_by(Customer.last_follow_up_at.desc().nullslast())
        elif sort == "next_follow_up_at_asc":
            q = q.order_by(Customer.next_follow_up_at.asc().nullslast())
        elif sort == "level_asc":
            q = q.order_by(Customer.level.asc())
        else:
            # 默认:创建时间倒序
            q = q.order_by(Customer.created_at.desc())

        total = q.count()
        rows = q.offset((page - 1) * page_size).limit(page_size).all()
        return rows, total

    # ---- 创建 ----------------------------------------------------------

    def create(
        self,
        db: Session,
        current_user: User,
        payload: CustomerCreate,
    ) -> Customer:
        """创建客户。

        校验:
        - owner_user_id 必须存在(SELECT 1 from users)
        - custom_fields 按 field_definitions 校验
        """
        # 校验 owner_user_id
        owner = db.query(User).filter(User.id == payload.owner_user_id).first()
        if not owner:
            raise HTTPException(400, f"owner_user_id {payload.owner_user_id} not found")

        # 校验 custom_fields
        validate_custom_fields_dict(
            db, current_user.tenant_id, payload.custom_fields
        )

        row = Customer(
            tenant_id=current_user.tenant_id,
            owner_user_id=payload.owner_user_id,
            created_by=current_user.id,
            name=payload.name,
            phone=payload.phone,
            email=payload.email,
            wechat=payload.wechat,
            avatar_url=payload.avatar_url,
            gender=payload.gender,
            birthday=payload.birthday,
            address=payload.address,
            company_name=payload.company_name,
            company_position=payload.company_position,
            industry=payload.industry,
            company_size=payload.company_size,
            company_website=payload.company_website,
            level=payload.level,
            source=payload.source,
            tags=payload.tags,
            custom_fields=payload.custom_fields,
            remark=payload.remark,
            is_active=True,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row

    # ---- 详情 ----------------------------------------------------------

    def get(
        self,
        db: Session,
        current_user: User,
        customer_id: int,
    ) -> Customer:
        """按 ID 取客户;跨租户返 404。"""
        row = (
            db.query(Customer)
            .filter(
                Customer.id == customer_id,
                Customer.tenant_id == current_user.tenant_id,
            )
            .first()
        )
        if not row:
            raise HTTPException(404, f"Customer {customer_id} not found")
        return row

    # ---- 更新 ----------------------------------------------------------

    def update(
        self,
        db: Session,
        current_user: User,
        customer_id: int,
        payload: CustomerUpdate,
    ) -> Customer:
        """更新客户。"""
        row = self.get(db, current_user, customer_id)

        # owner_user_id 转单校验
        if payload.owner_user_id is not None and payload.owner_user_id != row.owner_user_id:
            owner = db.query(User).filter(User.id == payload.owner_user_id).first()
            if not owner:
                raise HTTPException(
                    400, f"owner_user_id {payload.owner_user_id} not found"
                )

        # custom_fields 校验
        if payload.custom_fields is not None:
            validate_custom_fields_dict(
                db, current_user.tenant_id, payload.custom_fields
            )

        update_data = payload.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(row, key, value)
        db.commit()
        db.refresh(row)
        return row

    # ---- 软删 / 恢复 ---------------------------------------------------

    def soft_delete(
        self,
        db: Session,
        current_user: User,
        customer_id: int,
    ) -> Customer:
        """软删(is_active=False)。保留跟进记录(CASCADE 不删)。"""
        row = self.get(db, current_user, customer_id)
        row.is_active = False
        db.commit()
        db.refresh(row)
        return row

    def restore(
        self,
        db: Session,
        current_user: User,
        customer_id: int,
    ) -> Customer:
        """恢复软删客户。"""
        row = (
            db.query(Customer)
            .filter(
                Customer.id == customer_id,
                Customer.tenant_id == current_user.tenant_id,
            )
            .first()
        )
        if not row:
            raise HTTPException(404, f"Customer {customer_id} not found")
        row.is_active = True
        db.commit()
        db.refresh(row)
        return row

    # ---- 辅助:列表项 / 详情序列化 ---------------------------------------

    def to_list_item(
        self,
        db: Session,
        row: Customer,
        owner_name: Optional[str] = None,
    ) -> CustomerListItem:
        """Build list-item shape(手机号脱敏)。"""
        return CustomerListItem(
            id=row.id,
            name=row.name,
            phone_masked=mask_phone(row.phone),
            email=row.email,
            company_name=row.company_name,
            company_position=row.company_position,
            level=row.level,
            source=row.source,
            tags=row.tags,
            owner_user_id=row.owner_user_id,
            owner_user_name=owner_name,
            last_follow_up_at=row.last_follow_up_at,
            next_follow_up_at=row.next_follow_up_at,
            is_active=row.is_active,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    def to_detail(
        self,
        db: Session,
        row: Customer,
        owner_name: Optional[str] = None,
    ) -> CustomerDetail:
        """Build detail shape(手机号完整 + custom_fields 解析)。"""
        resolved = self._resolve_custom_fields(db, current_user_tenant_id=row.tenant_id, custom_fields=row.custom_fields)
        follow_ups_count = (
            db.query(func.count(CustomerFollowUp.id))
            .filter(CustomerFollowUp.customer_id == row.id)
            .scalar()
            or 0
        )
        return CustomerDetail(
            id=row.id,
            name=row.name,
            phone=row.phone,
            email=row.email,
            wechat=row.wechat,
            avatar_url=row.avatar_url,
            gender=row.gender,
            birthday=row.birthday,
            address=row.address,
            company_name=row.company_name,
            company_position=row.company_position,
            industry=row.industry,
            company_size=row.company_size,
            company_website=row.company_website,
            level=row.level,
            source=row.source,
            tags=row.tags,
            custom_fields=row.custom_fields,
            custom_fields_schema_resolved=resolved,
            remark=row.remark,
            owner_user_id=row.owner_user_id,
            owner_user_name=owner_name,
            created_by=row.created_by,
            last_follow_up_at=row.last_follow_up_at,
            next_follow_up_at=row.next_follow_up_at,
            follow_ups_count=follow_ups_count,
            is_active=row.is_active,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    def _resolve_custom_fields(
        self,
        db: Session,
        current_user_tenant_id: int,
        custom_fields: Optional[Dict[str, Any]],
    ) -> List[CustomFieldResolved]:
        """按 field_definitions 解析 custom_fields,返带 schema 元信息的 list。"""
        if not custom_fields:
            return []
        defs = (
            db.query(CustomerFieldDefinition)
            .filter(
                CustomerFieldDefinition.tenant_id == current_user_tenant_id,
                CustomerFieldDefinition.is_active == True,  # noqa: E712
            )
            .order_by(CustomerFieldDefinition.order_index.asc())
            .all()
        )
        def_by_key = {d.field_key: d for d in defs}
        out: List[CustomFieldResolved] = []
        # 按 defs 顺序遍历,缺失字段也展示(value=None)
        for d in defs:
            out.append(
                CustomFieldResolved(
                    key=d.field_key,
                    label=d.field_label,
                    type=d.field_type,
                    value=custom_fields.get(d.field_key),
                    required=d.required,
                    options=d.options,
                )
            )
        # 兜底:custom_fields 里有但 defs 缺失的 key(理论上 validate 已拦)
        for k in custom_fields:
            if k not in def_by_key:
                out.append(
                    CustomFieldResolved(
                        key=k, label=k, type="text", value=custom_fields[k]
                    )
                )
        return out

    # ---- 辅助:批量拉 owner_user_name ------------------------------------

    def get_owner_names_map(
        self,
        db: Session,
        owner_user_ids: List[int],
    ) -> Dict[int, str]:
        """批量 SELECT users WHERE id IN (...) 返 {id: name}。"""
        if not owner_user_ids:
            return {}
        rows = db.query(User).filter(User.id.in_(owner_user_ids)).all()
        return {u.id: (u.full_name or u.username) for u in rows}