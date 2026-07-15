"""Tests for GET /api/v1/users/assignable endpoint.

Spec: 客户管理 Spec §5.2 — 「负责人 Select (必填,默认当前用户)」。
需要任何已认证用户都能拿到同租户内可被指派的 active 用户列表(用于
客户 owner 选择的 Select 下拉)。不要求 superuser(转单是销售日常操作)。

Covers:
  - 鉴权: 未带 token → 401
  - 鉴权: inactive user → 403
  - 业务: 普通 active user(非 superuser)能拿到列表
  - 业务: inactive user 被过滤
  - 业务: 跨租户隔离(只返当前 tenant 的)
  - 业务: 分页参数生效
  - 业务: 响应只含简化字段(无 is_superuser / tenant_id / created_at)
"""
from __future__ import annotations

import itertools
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from lumen_core.database import SessionLocal, create_tables
from lumen_core.security import create_access_token, get_password_hash
from lumen_main import app
from lumen_models.tenant import Tenant
from lumen_models.user import User

create_tables()

_TENANT_CODE = "t-users-assignable"
_USERNAME = "u-users-assignable"
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
        s.query(User).filter(User.username.like(f"{_USERNAME}%")).delete(synchronize_session=False)
        s.query(Tenant).filter(Tenant.code.like(f"{_TENANT_CODE}%")).delete(synchronize_session=False)
        s.commit()
    except Exception:
        s.rollback()
    finally:
        s.close()


def _seed_users(
    db,
    *,
    n_active: int = 3,
    n_inactive: int = 1,
    other_tenant_active: int = 0,
) -> tuple[Tenant, list[User], list[User], list[User]]:
    """建 1 个 tenant + active/inactive 两种 user,返回 (tenant, active_users, inactive_users, other_tenant_users)。

    默认 active=3 个、inactive=1 个、其他 tenant active=0 个。
    第一个 active user 会作为 current user(non-superuser)。
    """
    t = Tenant(
        name="users assignable test",
        code=f"{_TENANT_CODE}-{_next_id()}",
        status=True,
        max_users=50,
    )
    db.add(t)
    db.flush()

    suffix = _next_id()
    actives: list[User] = []
    for i in range(n_active):
        u = User(
            username=f"{_USERNAME}-a-{suffix}-{i}",
            email=f"assignable-a-{suffix}-{i}@test.local",
            hashed_password=get_password_hash("x"),
            full_name=f"Active {i}",
            is_active=True,
            is_superuser=False,
            tenant_id=t.id,
        )
        db.add(u)
        actives.append(u)

    inactives: list[User] = []
    for i in range(n_inactive):
        u = User(
            username=f"{_USERNAME}-i-{suffix}-{i}",
            email=f"assignable-i-{suffix}-{i}@test.local",
            hashed_password=get_password_hash("x"),
            full_name=f"Inactive {i}",
            is_active=False,
            is_superuser=False,
            tenant_id=t.id,
        )
        db.add(u)
        inactives.append(u)

    other_users: list[User] = []
    if other_tenant_active:
        t2 = Tenant(
            name="other tenant",
            code=f"{_TENANT_CODE}-other-{suffix}",
            status=True,
            max_users=10,
        )
        db.add(t2)
        db.flush()
        for i in range(other_tenant_active):
            u = User(
                username=f"{_USERNAME}-o-{suffix}-{i}",
                email=f"assignable-o-{suffix}-{i}@test.local",
                hashed_password=get_password_hash("x"),
                full_name=f"Other {i}",
                is_active=True,
                is_superuser=False,
                tenant_id=t2.id,
            )
            db.add(u)
            other_users.append(u)

    db.commit()
    for u in actives + inactives + other_users:
        db.refresh(u)
    db.refresh(t)
    return t, actives, inactives, other_users


def _bearer(user: User) -> dict:
    token = create_access_token(
        data={"sub": user.username, "user_id": user.id, "tenant_id": user.tenant_id},
        expires_delta=timedelta(hours=1),
    )
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_assignable_requires_auth(db):
    """未带 token → 401。"""
    client = TestClient(app)
    resp = client.get("/api/v1/users/assignable")
    assert resp.status_code == 401


def test_assignable_rejects_inactive_user(db):
    """当前用户 is_active=False → 403(不允许查租户内成员)。"""
    t, actives, inactives, _ = _seed_users(db, n_active=1, n_inactive=1)
    headers = _bearer(inactives[0])
    client = TestClient(app)

    resp = client.get("/api/v1/users/assignable", headers=headers)
    assert resp.status_code == 403


def test_assignable_returns_active_users_only(db):
    """普通 active user(非 superuser)拿到 active 列表,inactive 被过滤。"""
    t, actives, inactives, _ = _seed_users(db, n_active=3, n_inactive=2)
    headers = _bearer(actives[0])
    client = TestClient(app)

    resp = client.get("/api/v1/users/assignable", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 200
    assert body["total"] == 3
    assert len(body["data"]) == 3
    # inactive 一定不返
    returned_ids = {u["id"] for u in body["data"]}
    for u in inactives:
        assert u.id not in returned_ids
    for u in actives:
        assert u.id in returned_ids


def test_assignable_filters_other_tenant(db):
    """跨租户隔离:只返当前租户的用户,其他 tenant 的 active 用户被过滤。"""
    t, actives, _, other_users = _seed_users(
        db, n_active=2, n_inactive=0, other_tenant_active=3,
    )
    headers = _bearer(actives[0])
    client = TestClient(app)

    resp = client.get("/api/v1/users/assignable", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 2
    returned_ids = {u["id"] for u in body["data"]}
    for u in other_users:
        assert u.id not in returned_ids


def test_assignable_response_shape_is_minimal(db):
    """响应只含简化字段(无 is_superuser / tenant_id / created_at)。"""
    t, actives, _, _ = _seed_users(db, n_active=1)
    headers = _bearer(actives[0])
    client = TestClient(app)

    resp = client.get("/api/v1/users/assignable", headers=headers)
    assert resp.status_code == 200
    item = resp.json()["data"][0]
    # 必有
    assert "id" in item
    assert "username" in item
    assert "email" in item
    assert "full_name" in item
    # 不该有(简化版裁掉)
    assert "is_superuser" not in item
    assert "tenant_id" not in item
    assert "is_active" not in item
    assert "created_at" not in item
    assert "hashed_password" not in item


def test_assignable_pagination(db):
    """分页参数生效:page_size=2 → 第一页 2 个,total=5。"""
    t, actives, _, _ = _seed_users(db, n_active=5)
    headers = _bearer(actives[0])
    client = TestClient(app)

    resp = client.get(
        "/api/v1/users/assignable?page=1&page_size=2", headers=headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 5
    assert len(body["data"]) == 2
    assert body["page"] == 1
    assert body["page_size"] == 2

    resp2 = client.get(
        "/api/v1/users/assignable?page=3&page_size=2", headers=headers,
    )
    assert resp2.status_code == 200
    body2 = resp2.json()
    assert body2["page"] == 3
    assert len(body2["data"]) == 1  # 5 条 → 第 3 页剩 1 条


def test_assignable_ordered_by_id_asc(db):
    """按 id 升序,便于前端默认选第一个。"""
    t, actives, _, _ = _seed_users(db, n_active=3)
    headers = _bearer(actives[0])
    client = TestClient(app)

    resp = client.get("/api/v1/users/assignable", headers=headers)
    body = resp.json()
    ids = [u["id"] for u in body["data"]]
    assert ids == sorted(ids)


def test_assignable_route_not_shadowed_by_get_user_id(db):
    """回归:确认 ``GET /users/assignable`` 不会被 ``GET /users/{user_id}`` 吞掉。

    之前 router 里 ``/{user_id}`` 排在 ``/`` 之后,新增 ``/assignable``
    必须排在 ``/{user_id}`` 前面,否则会把 "assignable" 当作 user_id 解析
    成 422("Input should be a valid integer")。"""
    t, actives, _, _ = _seed_users(db, n_active=1)
    headers = _bearer(actives[0])
    client = TestClient(app)

    resp = client.get("/api/v1/users/assignable", headers=headers)
    # 不能 422(Input should be a valid integer, ...),必须是 200
    assert resp.status_code == 200, f"expected 200, got {resp.status_code}: {resp.text}"
    assert resp.json()["code"] == 200
