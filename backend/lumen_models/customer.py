"""M33 客户管理(CRM) - 3 张表 model(客户 / 跟进记录 / 自定义字段定义)

Spec: docs/superpowers/specs/2026-06-20-customer-management-design.md §3
Plan: docs/superpowers/plans/2026-06-20-customer-management.md

3 张表的依赖:
- CustomerFieldDefinition 不依赖 Customer(独立表)
- CustomerFollowUp.cutomer_id → Customer.id ON DELETE CASCADE
"""
from sqlalchemy import (
    Column,
    Computed,
    Integer,
    String,
    Text,
    JSON,
    Date,
    DateTime,
    Boolean,
    ForeignKey,
    Index,
    UniqueConstraint,
)
from lumen_models.base import BaseModel


# ---------------------------------------------------------------------------
# CustomerFieldDefinition - 自定义字段定义(独立表)
# ---------------------------------------------------------------------------

class CustomerFieldDefinition(BaseModel):
    """客户档案的自定义字段定义(每 tenant 一份 schema)。

    Spec §3.3 — 字段值存 ``customers.custom_fields`` JSON,key = ``field_key``。
    字段值校验在 service 层 ``FieldService.validate_value``。
    """
    __tablename__ = "customer_field_definitions"

    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    field_key = Column(String(50), nullable=False)
    field_label = Column(String(100), nullable=False)
    # Spec §3.3:6 种字段类型(text / number / date / select / multiselect / textarea)
    field_type = Column(String(20), nullable=False)
    # select / multiselect 的选项 list;其他类型为 NULL
    options = Column(JSON, nullable=True)
    required = Column(Boolean, nullable=False, default=False)
    order_index = Column(Integer, nullable=False, default=0)
    is_active = Column(Boolean, nullable=False, default=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)

    # Phase 1 Group A 3.4 (2026-09-04):VIRTUAL GENERATED 列,active 行 =
    # 原 field_key,弱删行(``is_active=0``)= NULL;让
    # ``uk_customer_fields_tenant_key`` UNIQUE 落在 dedup 列上,实现
    # "弱删后同 tenant 内 field_key 可复用"。
    cfd_dedup_key = Column(
        String(50),
        Computed(
            "CASE WHEN is_active = 1 THEN field_key ELSE NULL END",
            persisted=False,
        ),
        nullable=True,
        comment="Phase 1 3.4 dedup key for soft-delete UNIQUE",
    )

    __table_args__ = (
        # Spec §3.3:UNIQUE(tenant_id, field_key) — 同租户下 field_key 唯一
        # Phase 1 3.4:DB 实际列是 ``(tenant_id, cfd_dedup_key)``
        # (见 ``lumen_core.database.ensure_customer_field_definitions_unique_dedup``)。
        UniqueConstraint("tenant_id", "field_key", name="uk_customer_fields_tenant_key"),
        Index("idx_customer_fields_tenant_active", "tenant_id", "is_active", "order_index"),
    )


# ---------------------------------------------------------------------------
# Customer - 客户主表
# ---------------------------------------------------------------------------

class Customer(BaseModel):
    """客户档案主表。

    Spec §3.1 — 基础信息 + 公司信息 + 客户分级 + 标签 + 自定义字段 JSON + 备注。
    ``last_follow_up_at`` / ``next_follow_up_at`` 由 follow_up_service 在事务内同步。
    """
    __tablename__ = "customers"

    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    # 负责人(销售) — 必填,选 owner 时不能为空
    owner_user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)

    # ---- 基础信息 ----
    name = Column(String(100), nullable=False, index=True)
    phone = Column(String(50), nullable=True, index=True)
    email = Column(String(200), nullable=True)
    wechat = Column(String(100), nullable=True)
    avatar_url = Column(String(500), nullable=True)
    gender = Column(String(10), nullable=True)  # M / F / U
    birthday = Column(Date, nullable=True)
    address = Column(String(500), nullable=True)

    # ---- 公司信息 ----
    company_name = Column(String(200), nullable=True, index=True)
    company_position = Column(String(100), nullable=True)
    industry = Column(String(100), nullable=True, index=True)
    company_size = Column(String(50), nullable=True)  # 1-10/11-50/51-200/201-1000/1000+
    company_website = Column(String(500), nullable=True)

    # ---- 客户属性 ----
    level = Column(String(20), nullable=False, default="potential", index=True)
    # vip / normal / potential / lost
    source = Column(String(50), nullable=True, index=True)
    # referral / website / exhibition / ad / other
    tags = Column(JSON, nullable=True)  # List[str]
    custom_fields = Column(JSON, nullable=True)  # Dict[str, Any] 按 schema 校验
    remark = Column(Text, nullable=True)

    # ---- 跟进时间聚合(follow_up_service 同步) ----
    last_follow_up_at = Column(DateTime, nullable=True, index=True)
    next_follow_up_at = Column(DateTime, nullable=True, index=True)

    is_active = Column(Boolean, nullable=False, default=True)

    __table_args__ = (
        # 列表页常用复合过滤
        Index("idx_customers_tenant_owner", "tenant_id", "owner_user_id"),
        Index("idx_customers_tenant_level", "tenant_id", "level"),
        Index("idx_customers_tenant_next_follow", "tenant_id", "next_follow_up_at"),
        Index("idx_customers_tenant_phone", "tenant_id", "phone"),
        Index("idx_customers_tenant_active_updated", "tenant_id", "is_active", "updated_at"),
    )


# ---------------------------------------------------------------------------
# CustomerFollowUp - 跟进记录
# ---------------------------------------------------------------------------

class CustomerFollowUp(BaseModel):
    """客户跟进记录(timeline 单向追加)。

    Spec §3.2 — 沟通历史;创建/更新/删除都在事务内同步更新
    ``Customer.last_follow_up_at`` 和 ``next_follow_up_at``。
    """
    __tablename__ = "customer_follow_ups"

    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    customer_id = Column(
        Integer,
        ForeignKey("customers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    # 跟进类型:phone / wechat / email / meeting / other
    follow_up_type = Column(String(30), nullable=False, index=True)
    content = Column(Text, nullable=False)
    next_step = Column(Text, nullable=True)
    next_follow_up_at = Column(DateTime, nullable=True)
    # 是否由 AI 智能建议触发的跟进(采纳 AIAdvisor.suggest 时设 True)
    ai_suggested = Column(Boolean, nullable=False, default=False)

    __table_args__ = (
        # timeline 查询常用(customer_id + 时间倒序)
        Index("idx_follow_ups_customer_created", "customer_id", "created_at"),
    )