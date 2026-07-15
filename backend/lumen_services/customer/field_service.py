"""M33 客户管理(CRM) - 自定义字段定义 service.

Spec: docs/superpowers/specs/2026-06-20-customer-management-design.md §3.3 / §4.2
Plan: docs/superpowers/plans/2026-06-20-customer-management.md T5

Responsibilities:
- 自定义字段定义 CRUD(每 tenant 一份 schema)
- ``validate_value`` 按 field_type 严格校验,失败 400
- 删除 / 改 field_type 时检查是否有客户 custom_fields 引用,有则 422
- ``UNIQUE(tenant_id, field_key)`` 由 model __table_args__ 守门
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, Union

from fastapi import HTTPException
from sqlalchemy.orm import Session

from lumen_models.customer import Customer, CustomerFieldDefinition
from lumen_models.user import User
from lumen_schemas.customer import (
    CustomerFieldDefinitionCreate,
    CustomerFieldDefinitionUpdate,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 字段值校验(spec §3.3 校验表)
# ---------------------------------------------------------------------------

class FieldValidationError(ValueError):
    """字段值校验失败。HTTPException(400) 在 service 边界处 raise。"""


def validate_value(
    field_type: str,
    value: Any,
    options: Optional[List[str]] = None,
    required: bool = False,
) -> None:
    """按 field_type 校验 value。失败 raise FieldValidationError。

    Parameters
    ----------
    field_type : str
        text / number / date / select / multiselect / textarea
    value : Any
        待校验值;允许 None(若 required=False)
    options : list[str], optional
        select / multiselect 的可选值
    required : bool
        是否必填;True 时 None 报错
    """
    if value is None:
        if required:
            raise FieldValidationError("field is required")
        return

    if field_type == "text":
        if not isinstance(value, str):
            raise FieldValidationError(f"text field must be string, got {type(value).__name__}")
        if len(value) > 200:
            raise FieldValidationError(f"text field exceeds 200 chars (got {len(value)})")
    elif field_type == "textarea":
        if not isinstance(value, str):
            raise FieldValidationError(f"textarea field must be string, got {type(value).__name__}")
        if len(value) > 2000:
            raise FieldValidationError(f"textarea field exceeds 2000 chars (got {len(value)})")
    elif field_type == "number":
        # bool 是 int 的子类,需先排除
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise FieldValidationError(f"number field must be numeric, got {type(value).__name__}")
    elif field_type == "date":
        if not isinstance(value, str):
            raise FieldValidationError(f"date field must be ISO string, got {type(value).__name__}")
        # 简单 ISO 8601 date 校验(YYYY-MM-DD);不强制 parse,让 service 层 caller 处理
        from datetime import datetime as _dt
        try:
            _dt.strptime(value[:10], "%Y-%m-%d")
        except (ValueError, TypeError):
            raise FieldValidationError(f"date field must match YYYY-MM-DD, got {value!r}")
    elif field_type == "select":
        if not isinstance(value, str):
            raise FieldValidationError(f"select field must be string, got {type(value).__name__}")
        if options is None:
            raise FieldValidationError("select field requires options")
        if value not in options:
            raise FieldValidationError(f"select value {value!r} not in options {options}")
    elif field_type == "multiselect":
        if not isinstance(value, list):
            raise FieldValidationError(f"multiselect field must be list, got {type(value).__name__}")
        if options is None:
            raise FieldValidationError("multiselect field requires options")
        bad = [v for v in value if v not in options]
        if bad:
            raise FieldValidationError(f"multiselect values {bad} not in options {options}")
    else:
        raise FieldValidationError(f"unknown field_type: {field_type!r}")


def _is_field_referenced(db: Session, tenant_id: int, field_key: str) -> bool:
    """检查是否有客户的 ``custom_fields`` 引用了此 field_key。

    MySQL JSON 路径查询:JSON_EXTRACT(custom_fields, '$."<key>"') IS NOT NULL。
    用 Python 端短路 OR — 简单可靠;若以后字段数 / 客户数膨胀,改为 SQL JSON_TABLE。
    """
    rows = (
        db.query(Customer)
        .filter(
            Customer.tenant_id == tenant_id,
            Customer.is_active == True,  # noqa: E712
            Customer.custom_fields.isnot(None),
        )
        .limit(500)  # 防御性 LIMIT,实测远小于此
        .all()
    )
    for row in rows:
        cf = row.custom_fields or {}
        if isinstance(cf, dict) and field_key in cf:
            return True
    return False


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class CustomerFieldService:
    """自定义字段定义管理。多租户隔离通过 ``current_user.tenant_id`` 守门。"""

    def list(
        self,
        db: Session,
        current_user: User,
        include_inactive: bool = False,
    ) -> List[CustomerFieldDefinition]:
        """列出当前租户的字段定义。默认只返 ``is_active=True``。"""
        q = db.query(CustomerFieldDefinition).filter(
            CustomerFieldDefinition.tenant_id == current_user.tenant_id
        )
        if not include_inactive:
            q = q.filter(CustomerFieldDefinition.is_active == True)  # noqa: E712
        return q.order_by(
            CustomerFieldDefinition.order_index.asc(),
            CustomerFieldDefinition.id.asc(),
        ).all()

    def get(
        self,
        db: Session,
        current_user: User,
        field_id: int,
    ) -> CustomerFieldDefinition:
        """按 ID 取字段定义;跨租户返 404(防 IDOR 探测)。"""
        row = (
            db.query(CustomerFieldDefinition)
            .filter(
                CustomerFieldDefinition.id == field_id,
                CustomerFieldDefinition.tenant_id == current_user.tenant_id,
            )
            .first()
        )
        if not row:
            raise HTTPException(404, f"CustomerFieldDefinition {field_id} not found")
        return row

    def create(
        self,
        db: Session,
        current_user: User,
        payload: CustomerFieldDefinitionCreate,
    ) -> CustomerFieldDefinition:
        """创建字段定义。

        校验:
        - field_key UNIQUE(tenant_id, field_key) — 由 DB 守门,service 提前 SELECT 友好提示
        - field_type=select/multiselect 必须提供 options
        """
        # options 必填校验
        if payload.field_type in ("select", "multiselect") and not payload.options:
            raise HTTPException(
                400,
                f"{payload.field_type} field requires non-empty 'options'",
            )
        if payload.field_type not in ("select", "multiselect") and payload.options is not None:
            # 非枚举类型忽略 options
            payload_dict = payload.model_dump()
            payload_dict["options"] = None
            payload = CustomerFieldDefinitionCreate(**payload_dict)

        # UNIQUE 预检
        existing = (
            db.query(CustomerFieldDefinition)
            .filter(
                CustomerFieldDefinition.tenant_id == current_user.tenant_id,
                CustomerFieldDefinition.field_key == payload.field_key,
            )
            .first()
        )
        if existing:
            raise HTTPException(
                409,
                f"field_key {payload.field_key!r} already exists for this tenant",
            )

        row = CustomerFieldDefinition(
            tenant_id=current_user.tenant_id,
            field_key=payload.field_key,
            field_label=payload.field_label,
            field_type=payload.field_type,
            options=payload.options,
            required=payload.required,
            order_index=payload.order_index,
            is_active=True,
            created_by=current_user.id,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row

    def update(
        self,
        db: Session,
        current_user: User,
        field_id: int,
        payload: CustomerFieldDefinitionUpdate,
    ) -> CustomerFieldDefinition:
        """更新字段定义。

        限制:
        - 改 ``field_type`` 时若有客户引用 → 422(防止客户已有值变成非法)
        - ``field_key`` 不可改(spec §4.3,创建后冻结)
        """
        row = self.get(db, current_user, field_id)

        # 检测 field_type 是否变化
        type_changed = (
            payload.field_type is not None and payload.field_type != row.field_type
        )

        # field_type 变化时检查引用
        if type_changed and _is_field_referenced(db, current_user.tenant_id, row.field_key):
            raise HTTPException(
                422,
                f"cannot change field_type while customers reference {row.field_key!r}",
            )

        # 应用更新
        update_data = payload.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            if key == "field_key":
                # spec: field_key 不可改
                continue
            setattr(row, key, value)
        db.commit()
        db.refresh(row)
        return row

    def delete(
        self,
        db: Session,
        current_user: User,
        field_id: int,
    ) -> None:
        """删除字段定义。若有客户引用 → 422。"""
        row = self.get(db, current_user, field_id)
        if _is_field_referenced(db, current_user.tenant_id, row.field_key):
            raise HTTPException(
                422,
                f"cannot delete field {row.field_key!r}: referenced by customers",
            )
        db.delete(row)
        db.commit()


# ---------------------------------------------------------------------------
# 字段值校验入口(供 customer_service 调)
# ---------------------------------------------------------------------------

def validate_custom_fields_dict(
    db: Session,
    tenant_id: int,
    custom_fields: Optional[Dict[str, Any]],
) -> None:
    """校验整个 ``customers.custom_fields`` dict。

    读 active 字段定义,逐 key 校验;失败 raise HTTPException(400)。
    """
    if not custom_fields:
        return
    # 拉字段定义 — 直接 query 而不调 service,避免循环引用
    defs = (
        db.query(CustomerFieldDefinition)
        .filter(
            CustomerFieldDefinition.tenant_id == tenant_id,
            CustomerFieldDefinition.is_active == True,  # noqa: E712
        )
        .all()
    )
    def_by_key = {d.field_key: d for d in defs}

    for key, value in custom_fields.items():
        if key not in def_by_key:
            raise HTTPException(400, f"undefined custom_field: {key!r}")
        d = def_by_key[key]
        try:
            validate_value(d.field_type, value, d.options, d.required)
        except FieldValidationError as e:
            raise HTTPException(400, f"invalid custom_field {key!r}: {e}")