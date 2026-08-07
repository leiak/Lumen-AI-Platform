"""End-to-end tests for POST /api/v1/external/auth/token.

Exercises every documented 401 / 403 / 429 path + the happy path.
Uses the dev seed app created in Task 4 (``lc_pub_dev_demo_only_replace_in_prod``).

Spec: ``docs/superpowers/specs/2026-06-08-external-chat-widget-design.md`` § 5.
"""
import gc

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select


@pytest.fixture
def client():
    from lumen_main import app
    return TestClient(app)


@pytest.fixture(autouse=True)
def _dispose_engine_after_test():
    """Force-close all pooled connections after each test.

    Mirrors the workaround in ``test_chat_user_id_nullable_regression.py``:
    the autouse ``get_db`` FastAPI dependency calls ``db.close()`` in its
    finally block, which returns the connection to the pool — but in a
    long-running pytest process the underlying DBAPI connection's
    transaction state (and any InnoDB metadata lock it holds) can survive
    the close because the ``Session`` object is still alive in a
    generator-local frame that hasn't been garbage-collected yet. When
    the next test in the suite issues a DDL on a related table, the
    orphaned connection blocks the DDL — observable as the full
    ``pytest tests/unit/`` suite "hanging" at ~20%. ``gc.collect()`` forces
    the unreferenced ``Session`` objects to finalize, and then
    ``engine.dispose()`` closes all checked-in connections.
    """
    yield
    from lumen_core.database import engine
    gc.collect()
    engine.dispose()


def _seed_dev_app_for_test():
    """Force the dev seed to run so we don't depend on uvicorn startup."""
    from lumen_scripts.seed_external_app import seed_dev_external_app
    seed_dev_external_app()


def test_token_issue_happy_path(client):
    _seed_dev_app_for_test()
    r = client.post(
        "/api/v1/external/auth/token",
        json={"app_key": "lc_pub_dev_demo_only_replace_in_prod", "visitor_id": "test-visitor-001"},
        headers={"Origin": "http://localhost:11337"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["code"] == 200
    data = body["data"]
    assert data["token"]
    assert data["expires_in"] == 1800
    assert data["visitor_id"] > 0
    assert isinstance(data["allowed_agents"], list)
    assert isinstance(data["allowed_teams"], list)
    # The dev seed has empty allowed_agent_ids / allowed_team_ids so the
    # lists come back empty — but if they were ever populated, each entry
    # must carry a ``type`` discriminator ("agent" or "team") so the
    # widget can render the agent switcher without an extra round-trip.
    for entry in data["allowed_agents"]:
        assert entry["type"] == "agent"
    for entry in data["allowed_teams"]:
        assert entry["type"] == "team"


def test_token_issue_invalid_app_key_401(client):
    r = client.post(
        "/api/v1/external/auth/token",
        json={"app_key": "lc_pub_nonexistent", "visitor_id": "test-visitor-002"},
        headers={"Origin": "http://localhost:11337"},
    )
    assert r.status_code == 401


def test_token_issue_origin_not_whitelisted_403(client):
    _seed_dev_app_for_test()
    r = client.post(
        "/api/v1/external/auth/token",
        json={"app_key": "lc_pub_dev_demo_only_replace_in_prod", "visitor_id": "test-visitor-003"},
        headers={"Origin": "https://evil.com"},
    )
    assert r.status_code == 403


def test_token_issue_missing_origin_403(client):
    """不携带 Origin 头必须被拒(spec §5.3:Referer fallback 已移除)。

    Referer 不能作为 origin allowlist 的依据 —— 可被 redirect 欺骗 / 浏览器
    referrer-policy 剥离 / 携带完整 URL(suffix attack + 信息泄露)。缺 Origin
    的请求直接 403,逼调用方走浏览器 fetch() 路径。
    """
    _seed_dev_app_for_test()
    r = client.post(
        "/api/v1/external/auth/token",
        json={"app_key": "lc_pub_dev_demo_only_replace_in_prod", "visitor_id": "test-visitor-missing-origin"},
    )
    assert r.status_code == 403, r.text
    body = r.json()
    assert body["detail"] == "origin not allowed"


def test_token_issue_referer_only_still_403(client):
    """只发 Referer(不 Origin)→ 403。

    这是历史安全洞的关键回归测试。修复前代码读 ``Origin or Referer``,
    Referer 即使单独存在也能让请求通过。修复后 match_origin() 拿到空字符串
    → 立即 False → 403。
    """
    _seed_dev_app_for_test()
    r = client.post(
        "/api/v1/external/auth/token",
        json={"app_key": "lc_pub_dev_demo_only_replace_in_prod", "visitor_id": "test-visitor-referer-only"},
        headers={"Referer": "http://localhost:11337/some/path?token=stolen"},
    )
    assert r.status_code == 403, r.text
    body = r.json()
    assert body["detail"] == "origin not allowed"


def test_token_issue_visitor_id_too_short_422(client):
    """Pydantic body validation surfaces as 422 (not 400).

    ``TokenRequest.visitor_id`` is constrained by ``Field(min_length=8)``,
    and FastAPI emits 422 Unprocessable Entity for request-body validation
    failures. The plan's test was originally named ``_400`` — the real
    status is 422. Renamed to match the actual behavior so a future
    refactor can't silently swap the response code without test fallout.
    """
    _seed_dev_app_for_test()
    r = client.post(
        "/api/v1/external/auth/token",
        json={"app_key": "lc_pub_dev_demo_only_replace_in_prod", "visitor_id": "x"},
        headers={"Origin": "http://localhost:11337"},
    )
    assert r.status_code == 422


def test_token_issue_inactive_app_401(client):
    """Disable the seed app temporarily, expect 401."""
    _seed_dev_app_for_test()
    from lumen_core.database import SessionLocal
    from lumen_models.external_app import ExternalApp
    db = SessionLocal()
    try:
        app = db.scalar(select(ExternalApp).where(
            ExternalApp.app_key == "lc_pub_dev_demo_only_replace_in_prod"))
        original = app.is_active
        app.is_active = False
        db.commit()
        try:
            r = client.post(
                "/api/v1/external/auth/token",
                json={"app_key": "lc_pub_dev_demo_only_replace_in_prod", "visitor_id": "test-visitor-004"},
                headers={"Origin": "http://localhost:11337"},
            )
            assert r.status_code == 401
        finally:
            # Always restore, even if the assertion above failed.
            app.is_active = original
            db.commit()
    finally:
        db.close()


def test_token_issue_rate_limited_after_threshold(client):
    """Force the in-process rate-limit to deny and expect 429.

    We monkey-patch ``check_rate_limit`` on the service module so we
    don't have to exhaust the seed app's generous dev bucket
    (``rate_limit_per_min=600``). This also verifies the rate-limit
    check happens BEFORE the visitor UPSERT — a rate-limited request
    must not pollute the ``external_visitors`` table.
    """
    _seed_dev_app_for_test()
    # Capture the visitor count BEFORE the rate-limited request, so we
    # can verify the rate-limit check fires before the upsert.
    from lumen_core.database import SessionLocal
    from lumen_models.external_app import ExternalVisitor
    from sqlalchemy import select as _select
    from lumen_models.external_app import ExternalApp
    db_before = SessionLocal()
    try:
        seed_app = db_before.scalar(_select(ExternalApp).where(
            ExternalApp.app_key == "lc_pub_dev_demo_only_replace_in_prod"))
        from sqlalchemy import func
        count_before = db_before.scalar(
            _select(func.count(ExternalVisitor.id)).where(
                ExternalVisitor.app_id == seed_app.id
            )
        )
    finally:
        db_before.close()

    import lumen_services.external_auth_service as svc
    original = svc.check_rate_limit
    svc.check_rate_limit = lambda **kw: False  # force rate-limit
    try:
        r = client.post(
            "/api/v1/external/auth/token",
            json={"app_key": "lc_pub_dev_demo_only_replace_in_prod", "visitor_id": "test-visitor-005"},
            headers={"Origin": "http://localhost:11337"},
        )
        assert r.status_code == 429, r.text
        # Spec § 5.6 requires a Retry-After header on 429. The sliding
        # window is 60s, so the client should wait that long before
        # retrying.
        assert r.headers.get("Retry-After") == "60"
    finally:
        svc.check_rate_limit = original

    # Verify the visitor table was NOT polluted by the rate-limited
    # request. The rate-limit check must short-circuit BEFORE the
    # upsert_visitor call.
    db_after = SessionLocal()
    try:
        count_after = db_after.scalar(
            _select(func.count(ExternalVisitor.id)).where(
                ExternalVisitor.app_id == seed_app.id
            )
        )
        assert count_after == count_before, (
            f"rate-limited request polluted visitor table: {count_before} -> {count_after}"
        )
    finally:
        db_after.close()
