"""M33 客户管理(CRM) - 跟进记录 service.

Spec: docs/superpowers/specs/2026-06-20-customer-management-design.md §3.2 / §7.2
Plan: docs/superpowers/plans/2026-06-20-customer-management.md T8

Responsibilities:
- 跟进记录 CRUD(timeline 单向追加)
- 事务内同步更新 customer.last_follow_up_at / next_follow_up_at (SQL 聚合)
- upcoming-follow-ups 查询(我的待跟进,按 next_follow_up_at 升序)
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import List, Optional, Tuple

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from lumen_models.customer import Customer, CustomerFollowUp
from lumen_models.user import User
from lumen_schemas.customer import (
    FollowUpCreate,
    FollowUpUpdate,
    UpcomingFollowUpItem,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 跟进创建/更新/删除时同步 customer 字段(SQL 聚合,避免 N+1)
# ---------------------------------------------------------------------------

def _refresh_customer_aggregates(db: Session, customer_id: int) -> None:
    """在事务内同步 ``customer.last_follow_up_at`` 和 ``next_follow_up_at``。

    用单条 UPDATE + 子查询聚合,避免 Python 端 N+1。

    ``MAX(created_at)`` — 最近一次跟进时间(空表 fallback 用 now)
    ``MAX(next_follow_up_at) WHERE next_follow_up_at IS NOT NULL`` — 最近的下次跟进时间
    """
    row = db.query(Customer).filter(Customer.id == customer_id).first()
    if not row:
        return

    # MAX(created_at)
    last_subq = (
        db.query(func.max(CustomerFollowUp.created_at))
        .filter(CustomerFollowUp.customer_id == customer_id)
        .scalar_subquery()
    )
    # MAX(next_follow_up_at) WHERE not null
    next_subq = (
        db.query(func.max(CustomerFollowUp.next_follow_up_at))
        .filter(
            CustomerFollowUp.customer_id == customer_id,
            CustomerFollowUp.next_follow_up_at.isnot(None),
        )
        .scalar_subquery()
    )

    # 直接 UPDATE 两个字段(SQL 聚合)
    db.query(Customer).filter(Customer.id == customer_id).update(
        {
            Customer.last_follow_up_at: last_subq,
            Customer.next_follow_up_at: next_subq,
        },
        synchronize_session=False,
    )
    # 同步 session state(刚才的 update 已经写到 row)
    db.refresh(row)


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class FollowUpService:
    """跟进记录业务逻辑。多租户隔离。"""

    # ---- timeline list -------------------------------------------------

    def list(
        self,
        db: Session,
        current_user: User,
        customer_id: int,
        page: int = 1,
        page_size: int = 20,
    ) -> Tuple[List[CustomerFollowUp], int]:
        """某客户的 timeline 列表(按 created_at 倒序)。"""
        # 先验客户存在 + tenant 一致
        customer = (
            db.query(Customer)
            .filter(
                Customer.id == customer_id,
                Customer.tenant_id == current_user.tenant_id,
            )
            .first()
        )
        if not customer:
            raise HTTPException(404, f"Customer {customer_id} not found")

        q = (
            db.query(CustomerFollowUp)
            .filter(
                CustomerFollowUp.customer_id == customer_id,
                CustomerFollowUp.tenant_id == current_user.tenant_id,
            )
            .order_by(CustomerFollowUp.created_at.desc())
        )
        total = q.count()
        rows = q.offset((page - 1) * page_size).limit(page_size).all()
        return rows, total

    # ---- create --------------------------------------------------------

    def create(
        self,
        db: Session,
        current_user: User,
        customer_id: int,
        payload: FollowUpCreate,
    ) -> CustomerFollowUp:
        """新增跟进。事务内同步更新 customer 聚合字段。"""
        # 验客户
        customer = (
            db.query(Customer)
            .filter(
                Customer.id == customer_id,
                Customer.tenant_id == current_user.tenant_id,
            )
            .first()
        )
        if not customer:
            raise HTTPException(404, f"Customer {customer_id} not found")

        row = CustomerFollowUp(
            tenant_id=current_user.tenant_id,
            customer_id=customer_id,
            user_id=current_user.id,
            follow_up_type=payload.follow_up_type,
            content=payload.content,
            next_step=payload.next_step,
            next_follow_up_at=payload.next_follow_up_at,
            ai_suggested=False,
        )
        db.add(row)
        db.flush()  # 拿 created_at(由 server_default)
        _refresh_customer_aggregates(db, customer_id)
        db.commit()
        db.refresh(row)
        return row

    # ---- update --------------------------------------------------------

    def update(
        self,
        db: Session,
        current_user: User,
        customer_id: int,
        follow_up_id: int,
        payload: FollowUpUpdate,
    ) -> CustomerFollowUp:
        """更新跟进。同步更新 customer 聚合字段。"""
        row = self._get(db, current_user, customer_id, follow_up_id)

        update_data = payload.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(row, key, value)
        db.flush()
        _refresh_customer_aggregates(db, customer_id)
        db.commit()
        db.refresh(row)
        return row

    # ---- delete --------------------------------------------------------

    def delete(
        self,
        db: Session,
        current_user: User,
        customer_id: int,
        follow_up_id: int,
    ) -> None:
        """删除跟进(物理删除 — 跟进记录可追溯价值低于客户档案)。同步更新 customer 聚合。"""
        row = self._get(db, current_user, customer_id, follow_up_id)
        db.delete(row)
        db.flush()
        _refresh_customer_aggregates(db, customer_id)
        db.commit()

    # ---- upcoming follow-ups -------------------------------------------

    def upcoming(
        self,
        db: Session,
        current_user: User,
        owner_user_id: Optional[int] = None,
        days: int = 7,
        now: Optional[datetime] = None,
    ) -> List[UpcomingFollowUpItem]:
        """我的待跟进客户列表。

        Parameters
        ----------
        owner_user_id : int, optional
            限定负责人;None = 当前用户
        days : int
            时间窗口(默认 7 天内),过期的也显示(days_until_due 负数)
        now : datetime, optional
            "今天" 的参考时间;None = datetime.utcnow()

        Notes
        -----
        ``days_until_due`` 可以负数(逾期);``due_within`` 过滤用 ``next_follow_up_at <= now + days``。
        """
        from datetime import timedelta

        owner = owner_user_id if owner_user_id is not None else current_user.id
        now = now or datetime.utcnow()
        due_within = now + timedelta(days=days)

        rows = (
            db.query(Customer)
            .filter(
                Customer.tenant_id == current_user.tenant_id,
                Customer.is_active == True,  # noqa: E712
                Customer.owner_user_id == owner,
                Customer.next_follow_up_at.isnot(None),
                Customer.next_follow_up_at <= due_within,
            )
            .order_by(Customer.next_follow_up_at.asc())
            .all()
        )

        items: List[UpcomingFollowUpItem] = []
        for c in rows:
            # 上次跟进内容(取最近一条)
            last_fu = (
                db.query(CustomerFollowUp)
                .filter(CustomerFollowUp.customer_id == c.id)
                .order_by(CustomerFollowUp.created_at.desc())
                .first()
            )
            last_content = last_fu.content if last_fu else None
            if last_content and len(last_content) > 50:
                last_content = last_content[:50] + "..."

            days_until = (c.next_follow_up_at - now).days  # 可能负数
            items.append(
                UpcomingFollowUpItem(
                    customer_id=c.id,
                    customer_name=c.name,
                    level=c.level,
                    owner_user_id=c.owner_user_id,
                    next_follow_up_at=c.next_follow_up_at,
                    last_follow_up_content=last_content,
                    days_until_due=days_until,
                )
            )
        return items

    # ---- helpers --------------------------------------------------------

    def _get(
        self,
        db: Session,
        current_user: User,
        customer_id: int,
        follow_up_id: int,
    ) -> CustomerFollowUp:
        """取单条跟进(同时校验 customer 归属 + tenant)。跨租户返 404。"""
        row = (
            db.query(CustomerFollowUp)
            .filter(
                CustomerFollowUp.id == follow_up_id,
                CustomerFollowUp.customer_id == customer_id,
                CustomerFollowUp.tenant_id == current_user.tenant_id,
            )
            .first()
        )
        if not row:
            raise HTTPException(
                404, f"FollowUp {follow_up_id} not found for customer {customer_id}"
            )
        return row