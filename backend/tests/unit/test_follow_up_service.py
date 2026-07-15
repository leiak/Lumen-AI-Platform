"""Tests for FollowUpService.

Spec: docs/superpowers/specs/2026-06-20-customer-management-design.md §3.2 / §7.2
Plan: docs/superpowers/plans/2026-06-20-customer-management.md T11

Covers:
  - timeline 倒序聚合
  - 创建/更新/删除时 customer.last/next_follow_up_at 同步更新
  - upcoming-follow-ups 按 next_follow_up_at 升序,过期显示(days_until_due 负数)
"""
from __future__ import annotations

import itertools
from datetime import datetime, timedelta

import pytest

from lumen_core.database import SessionLocal, create_tables
from lumen_core.security import get_password_hash
from lumen_models.customer import Customer, CustomerFollowUp
from lumen_models.tenant import Tenant
from lumen_models.user import User
from lumen_schemas.customer import FollowUpCreate, FollowUpUpdate
from lumen_services.customer.follow_up_service import FollowUpService

create_tables()

_TEST_TENANT_CODE = "t-follow-up-test"
_TEST_USER_NAME = "u-follow-up-test"
_counter = itertools.count(1)


def _next_id() -> int:
    return next(_counter)


@pytest.fixture
def db():
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    s = SessionLocal()
    try:
        tenant_ids_q = s.query(Tenant.id).filter(Tenant.code.like(f"{_TEST_TENANT_CODE}%"))
        s.query(CustomerFollowUp).filter(CustomerFollowUp.tenant_id.in_(tenant_ids_q.subquery())).delete(synchronize_session=False)
        s.query(Customer).filter(Customer.tenant_id.in_(tenant_ids_q.subquery())).delete(synchronize_session=False)
        s.query(User).filter(User.username.like(f"{_TEST_USER_NAME}%")).delete(synchronize_session=False)
        s.query(Tenant).filter(Tenant.code.like(f"{_TEST_TENANT_CODE}%")).delete(synchronize_session=False)
        s.commit()
    except Exception:
        s.rollback()
    finally:
        s.close()


def _make_tenant(db) -> Tenant:
    t = Tenant(
        name="follow up test",
        code=f"{_TEST_TENANT_CODE}-{_next_id()}",
        status=True,
        max_users=10,
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


def _make_user(db, tenant_id: int) -> User:
    n = _next_id()
    u = User(
        username=f"{_TEST_USER_NAME}-{n}",
        email=f"follow-up-{n}@test.local",
        hashed_password=get_password_hash("x"),
        full_name="Follow Up User",
        is_active=True,
        tenant_id=tenant_id,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _make_customer(db, tenant_id: int, owner_id: int, created_by: int, name: str = "Test") -> Customer:
    c = Customer(
        tenant_id=tenant_id,
        owner_user_id=owner_id,
        created_by=created_by,
        name=name,
        level="normal",
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_create_follow_up_updates_customer_aggregates(db):
    """Spec §7.2 — 创建跟进后, customer.last_follow_up_at 和 next_follow_up_at 被同步更新。"""
    t = _make_tenant(db)
    u = _make_user(db, t.id)
    c = _make_customer(db, t.id, u.id, u.id, "aggregates test")
    assert c.last_follow_up_at is None
    assert c.next_follow_up_at is None

    next_at = datetime.utcnow() + timedelta(days=3)
    svc = FollowUpService()
    fu = svc.create(
        db, current_user=u, customer_id=c.id,
        payload=FollowUpCreate(follow_up_type="phone", content="call", next_follow_up_at=next_at),
    )
    db.refresh(c)

    assert c.last_follow_up_at is not None
    assert c.next_follow_up_at is not None
    # next_follow_up_at 应该在几秒误差内等于 next_at
    diff = abs((c.next_follow_up_at - next_at).total_seconds())
    assert diff < 5


def test_list_follow_ups_returns_descending_order(db):
    """Spec §3.2 — timeline 按 created_at 倒序。"""
    t = _make_tenant(db)
    u = _make_user(db, t.id)
    c = _make_customer(db, t.id, u.id, u.id, "timeline test")
    svc = FollowUpService()

    for i in range(3):
        svc.create(
            db, current_user=u, customer_id=c.id,
            payload=FollowUpCreate(follow_up_type="phone", content=f"call {i}"),
        )

    rows, total = svc.list(db, current_user=u, customer_id=c.id)
    assert total == 3
    # 倒序:最后创建的应该在最前
    assert rows[0].content == "call 2"
    assert rows[2].content == "call 0"


def test_delete_follow_up_syncs_customer_aggregates(db):
    """Spec §7.2 — 删除跟进后,customer 聚合字段同步更新。"""
    t = _make_tenant(db)
    u = _make_user(db, t.id)
    c = _make_customer(db, t.id, u.id, u.id, "delete sync test")
    svc = FollowUpService()
    fu = svc.create(
        db, current_user=u, customer_id=c.id,
        payload=FollowUpCreate(follow_up_type="phone", content="only one"),
    )
    db.refresh(c)
    assert c.last_follow_up_at is not None

    svc.delete(db, current_user=u, customer_id=c.id, follow_up_id=fu.id)
    db.refresh(c)
    # 删除后没有 follow_ups,last/next 都应该回到 None
    assert c.last_follow_up_at is None
    assert c.next_follow_up_at is None


def test_upcoming_follow_ups_orders_by_next_at_asc(db):
    """Spec §4.2 — upcoming-follow-ups 按 next_follow_up_at 升序,过期也显示。"""
    t = _make_tenant(db)
    u = _make_user(db, t.id)
    svc = FollowUpService()

    now = datetime.utcnow()
    # 3 个客户:分别 +1d / -2d(过期)/ +5d
    customers = []
    for label, delta in [("soon", 1), ("overdue", -2), ("later", 5)]:
        c = _make_customer(db, t.id, u.id, u.id, f"upcoming {label}")
        svc.create(
            db, current_user=u, customer_id=c.id,
            payload=FollowUpCreate(
                follow_up_type="phone",
                content=f"for {label}",
                next_follow_up_at=now + timedelta(days=delta),
            ),
        )
        customers.append((c, delta))

    items = svc.upcoming(db, current_user=u, owner_user_id=u.id, days=7, now=now)
    assert len(items) == 3
    # 升序:overdue(-2d) → soon(+1d) → later(+5d)
    # ``(dt - dt).days`` 对 23-48h 之间值可能是 -2 或 -3(因 truncation),
    # 用 ±1 容差规避 timing race。
    assert items[0].customer_name == "upcoming overdue"
    assert items[0].days_until_due in (-3, -2)
    assert items[1].customer_name == "upcoming soon"
    assert items[1].days_until_due in (0, 1)
    assert items[2].customer_name == "upcoming later"
    assert items[2].days_until_due in (4, 5)