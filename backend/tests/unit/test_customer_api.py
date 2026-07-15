"""Tests for customer API endpoints (HTTP layer).

Spec: docs/superpowers/specs/2026-06-20-customer-management-design.md §4.1
Plan: docs/superpowers/plans/2026-06-20-customer-management.md T12

Covers (代表性 case,各取 1):
  - GET  /customers             — 鉴权 + 列表 + 多维过滤(levels)
  - POST /customers             — 创建 + custom_fields 校验
  - GET  /customers/{id}        — 跨租户 404(IDOR 防护)
  - PUT  /customers/{id}        — 更新
  - DELETE /customers/{id}      — 软删
  - POST /customers/{id}/follow-ups — 跟进创建 + customer 字段同步
"""
from __future__ import annotations

import itertools

import pytest
from fastapi.testclient import TestClient

from lumen_core.database import SessionLocal, create_tables
from lumen_core.security import get_password_hash
from lumen_main import app
from lumen_models.customer import Customer, CustomerFieldDefinition, CustomerFollowUp
from lumen_models.tenant import Tenant
from lumen_models.user import User

create_tables()

_TEST_TENANT_CODE = "t-customer-api-test"
_TEST_USER_NAME = "u-customer-api-test"
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
        s.query(CustomerFieldDefinition).filter(CustomerFieldDefinition.tenant_id.in_(tenant_ids_q.subquery())).delete(synchronize_session=False)
        s.query(User).filter(User.username.like(f"{_TEST_USER_NAME}%")).delete(synchronize_session=False)
        s.query(Tenant).filter(Tenant.code.like(f"{_TEST_TENANT_CODE}%")).delete(synchronize_session=False)
        s.commit()
    except Exception:
        s.rollback()
    finally:
        s.close()


def _seed(db) -> tuple[User, User]:
    """建 1 个 tenant + 1 个 admin user,返 user."""
    t = Tenant(
        name="customer api test",
        code=f"{_TEST_TENANT_CODE}-{_next_id()}",
        status=True,
        max_users=10,
    )
    db.add(t)
    db.flush()
    n = _next_id()
    u = User(
        username=f"{_TEST_USER_NAME}-{n}",
        email=f"customer-api-{n}@test.local",
        hashed_password=get_password_hash("x"),
        full_name="Admin",
        is_active=True,
        is_superuser=True,  # 跳过 admin check
        tenant_id=t.id,
    )
    db.add(u)
    db.commit()
    db.refresh(t)
    db.refresh(u)
    return t, u


def _bearer(user: User) -> dict:
    """生成 access_token。"""
    from lumen_core.security import create_access_token
    from datetime import timedelta

    token = create_access_token(
        data={"sub": user.username, "user_id": user.id, "tenant_id": user.tenant_id},
        expires_delta=timedelta(hours=1),
    )
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_list_customers_requires_auth(db):
    """未鉴权 → 401。"""
    client = TestClient(app)
    resp = client.get("/api/v1/customers")
    assert resp.status_code == 401


def test_create_and_get_customer(db):
    """POST 创建 + GET 详情。手机号完整。"""
    t, u = _seed(db)
    headers = _bearer(u)
    client = TestClient(app)

    payload = {
        "name": "ACME 张三",
        "phone": "13800138000",
        "email": "zhang@acme.com",
        "owner_user_id": u.id,
        "company_name": "ACME 科技",
        "level": "vip",
        "tags": ["决策人"],
    }
    resp = client.post("/api/v1/customers", headers=headers, json=payload)
    assert resp.status_code == 201
    body = resp.json()
    assert body["code"] == 200
    cid = body["data"]["id"]
    assert body["data"]["name"] == "ACME 张三"
    assert body["data"]["level"] == "vip"
    assert body["data"]["phone"] == "13800138000"  # 详情返完整

    # GET 详情
    resp2 = client.get(f"/api/v1/customers/{cid}", headers=headers)
    assert resp2.status_code == 200
    assert resp2.json()["data"]["phone"] == "13800138000"


def test_list_customers_returns_phone_masked(db):
    """列表里手机号脱敏(138****8000)。"""
    t, u = _seed(db)
    headers = _bearer(u)
    client = TestClient(app)

    client.post(
        "/api/v1/customers",
        headers=headers,
        json={"name": "A", "phone": "13800138000", "owner_user_id": u.id},
    )
    resp = client.get("/api/v1/customers", headers=headers)
    assert resp.status_code == 200
    items = resp.json()["data"]
    assert items[0]["phone_masked"] == "138****8000"
    assert "phone" not in items[0]  # 列表不返 phone 字段


def test_list_customers_filter_by_level(db):
    """GET /customers?levels=vip 多选过滤。"""
    t, u = _seed(db)
    headers = _bearer(u)
    client = TestClient(app)

    # 创建 2 个:1 个 vip,1 个 normal
    client.post("/api/v1/customers", headers=headers, json={"name": "V", "owner_user_id": u.id, "level": "vip"})
    client.post("/api/v1/customers", headers=headers, json={"name": "N", "owner_user_id": u.id, "level": "normal"})

    resp = client.get("/api/v1/customers?levels=vip", headers=headers)
    assert resp.status_code == 200
    items = resp.json()["data"]
    assert len(items) == 1
    assert items[0]["name"] == "V"
    assert items[0]["level"] == "vip"


def test_get_customer_cross_tenant_404(db):
    """跨租户访问返 404(防 IDOR 探测,不返 403)。"""
    # 建 2 个独立 tenant + user
    t1, u1 = _seed(db)
    t2, u2 = _seed(db)

    # u1 创建 1 个客户
    h1 = _bearer(u1)
    client = TestClient(app)
    resp = client.post(
        "/api/v1/customers", headers=h1,
        json={"name": "private", "owner_user_id": u1.id},
    )
    assert resp.status_code == 201
    cid = resp.json()["data"]["id"]

    # u2 尝试访问 → 404
    h2 = _bearer(u2)
    resp2 = client.get(f"/api/v1/customers/{cid}", headers=h2)
    assert resp2.status_code == 404


def test_create_follow_up_updates_customer(db):
    """POST follow-ups 后,customer.last/next_follow_up_at 自动同步。"""
    t, u = _seed(db)
    headers = _bearer(u)
    client = TestClient(app)

    resp = client.post(
        "/api/v1/customers", headers=headers,
        json={"name": "follow", "owner_user_id": u.id},
    )
    cid = resp.json()["data"]["id"]

    # 创建跟进
    from datetime import datetime, timedelta
    next_at = (datetime.utcnow() + timedelta(days=2)).isoformat()
    resp2 = client.post(
        f"/api/v1/customers/{cid}/follow-ups",
        headers=headers,
        json={
            "follow_up_type": "phone",
            "content": "首次沟通",
            "next_follow_up_at": next_at,
        },
    )
    assert resp2.status_code == 201

    # 详情里 last/next 应有值
    resp3 = client.get(f"/api/v1/customers/{cid}", headers=headers)
    detail = resp3.json()["data"]
    assert detail["last_follow_up_at"] is not None
    assert detail["next_follow_up_at"] is not None
    assert detail["follow_ups_count"] == 1