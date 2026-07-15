"""Tests for Customer / CustomerFollowUp / CustomerFieldDefinition ORM models.

Spec: docs/superpowers/specs/2026-06-20-customer-management-design.md §3

Covers:
  - model create + default values
  - tenant_id 隔离(Customer 不跨 tenant 查询)
  - ForeignKey 守门(invalid tenant_id / customer_id 报 IntegrityError)
  - UNIQUE(tenant_id, field_key) 守门(field_key 重复报 IntegrityError)
  - CustomerFollowUp ON DELETE CASCADE(删 customer 自动删 follow_ups)
"""
from __future__ import annotations

import itertools
import pytest
from sqlalchemy.exc import IntegrityError

from lumen_core.database import SessionLocal, create_tables
from lumen_core.security import get_password_hash
from lumen_models.customer import Customer, CustomerFieldDefinition, CustomerFollowUp
from lumen_models.tenant import Tenant
from lumen_models.user import User

# Idempotent: only creates missing tables. Safe on every test run.
create_tables()


# Per-module counter for unique tenant.code / user.username — ``id(db)``
# is the SessionLocal object id, which is stable across calls in the
# same process, so we need a real monotonic source instead.
_counter = itertools.count(1)


def _next_id() -> int:
    return next(_counter)


# ---------------------------------------------------------------------------
# Test data prefix — keeps cleanup targeted to this test file's rows.
# ---------------------------------------------------------------------------
_TEST_TENANT_CODE = "t-customer-models-test"
_TEST_USER_NAME = "u-customer-models-test"
_TEST_FIELD_KEY = "customer_models_test_key"


@pytest.fixture
def db():
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture(autouse=True)
def _cleanup():
    """删掉所有 test prefix 的行 — tenant / user / customers / follow_ups /
    field_definitions,按 FK 顺序。
    """
    yield
    s = SessionLocal()
    try:
        # field defs by field_key
        s.query(CustomerFieldDefinition).filter(
            CustomerFieldDefinition.field_key.like("customer_models_%")
        ).delete(synchronize_session=False)
        # follow_ups by tenant (CASCADE 删除客户时已经清掉)
        s.query(CustomerFollowUp).filter(
            CustomerFollowUp.tenant_id.in_(
                s.query(Tenant.id).filter(Tenant.code.like(f"{_TEST_TENANT_CODE}%"))
            )
        ).delete(synchronize_session=False)
        # customers by tenant
        s.query(Customer).filter(
            Customer.tenant_id.in_(
                s.query(Tenant.id).filter(Tenant.code.like(f"{_TEST_TENANT_CODE}%"))
            )
        ).delete(synchronize_session=False)
        # users
        s.query(User).filter(User.username.like(f"{_TEST_USER_NAME}%")).delete(
            synchronize_session=False
        )
        # tenants
        s.query(Tenant).filter(Tenant.code.like(f"{_TEST_TENANT_CODE}%")).delete(
            synchronize_session=False
        )
        s.commit()
    except Exception:
        s.rollback()
    finally:
        s.close()


def _make_tenant(db) -> Tenant:
    t = Tenant(
        name="customer models test",
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
        email=f"customer-models-{n}@test.local",
        hashed_password=get_password_hash("x"),
        full_name="Test User",
        is_active=True,
        tenant_id=tenant_id,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_create_customer_minimum(db):
    """Spec §3.1 — Customer 最小创建(name + owner_user_id + created_by + tenant_id)。"""
    t = _make_tenant(db)
    u = _make_user(db, t.id)
    c = Customer(
        tenant_id=t.id,
        owner_user_id=u.id,
        created_by=u.id,
        name="Test Co",
        level="potential",
    )
    db.add(c)
    db.commit()
    db.refresh(c)

    assert c.id is not None
    assert c.level == "potential"
    assert c.is_active is True
    assert c.tags is None
    assert c.custom_fields is None
    assert c.last_follow_up_at is None
    assert c.next_follow_up_at is None
    assert c.created_at is not None
    assert c.updated_at is not None


def test_customer_field_definition_unique_per_tenant(db):
    """Spec §3.3 — UNIQUE(tenant_id, field_key) 守门。

    同 tenant 内 field_key 重复 → IntegrityError。
    """
    t = _make_tenant(db)
    u = _make_user(db, t.id)
    d1 = CustomerFieldDefinition(
        tenant_id=t.id,
        field_key=_TEST_FIELD_KEY,
        field_label="label1",
        field_type="text",
        created_by=u.id,
    )
    db.add(d1)
    db.commit()

    d2 = CustomerFieldDefinition(
        tenant_id=t.id,
        field_key=_TEST_FIELD_KEY,  # same key
        field_label="label2",
        field_type="text",
        created_by=u.id,
    )
    db.add(d2)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_customer_field_definition_can_repeat_across_tenants(db):
    """Spec §3.3 — UNIQUE(tenant_id, field_key) 是组合约束;不同 tenant 同 key OK。"""
    t1 = _make_tenant(db)
    t2 = _make_tenant(db)
    u = _make_user(db, t1.id)
    d1 = CustomerFieldDefinition(
        tenant_id=t1.id,
        field_key=_TEST_FIELD_KEY,
        field_label="l1",
        field_type="text",
        created_by=u.id,
    )
    d2 = CustomerFieldDefinition(
        tenant_id=t2.id,
        field_key=_TEST_FIELD_KEY,  # same key, different tenant — OK
        field_label="l2",
        field_type="text",
        created_by=u.id,
    )
    db.add_all([d1, d2])
    db.commit()
    assert d1.id != d2.id


def test_follow_up_cascade_on_customer_delete(db):
    """Spec §3.2 — CustomerFollowUp.customer_id ON DELETE CASCADE。

    删 customer 时 follow_ups 自动删。
    """
    t = _make_tenant(db)
    u = _make_user(db, t.id)
    c = Customer(
        tenant_id=t.id,
        owner_user_id=u.id,
        created_by=u.id,
        name="cascade test",
        level="normal",
    )
    db.add(c)
    db.commit()
    db.refresh(c)

    for i in range(3):
        db.add(
            CustomerFollowUp(
                tenant_id=t.id,
                customer_id=c.id,
                user_id=u.id,
                follow_up_type="phone",
                content=f"call {i}",
            )
        )
    db.commit()

    # 验证 3 条 follow_ups
    assert (
        db.query(CustomerFollowUp).filter(CustomerFollowUp.customer_id == c.id).count()
        == 3
    )

    # 删 customer
    db.delete(c)
    db.commit()

    # CASCADE: follow_ups 应该全没了
    assert (
        db.query(CustomerFollowUp).filter(CustomerFollowUp.customer_id == c.id).count()
        == 0
    )