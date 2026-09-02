"""Phase 0 Unit 3 (2026-09-02):_check_rate_limit fail-closed 行为测试。

覆盖 admin_skills.py 内 _check_rate_limit 的状态码区分:
- allowed=True → 不抛异常
- allowed=False, degraded=False → 429
- allowed=False, degraded=True → 503 + Retry-After header

为什么:Phase 0 2.7 把 rate limit 从 in-memory fallback 改成 fail-closed,
admin endpoint 必须区分 429(真限流)vs 503(限流组件坏),前端可分别处理。
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))


def test_check_rate_limit_allows_when_allowed_true():
    """allowed=True → 不抛,正常 continue。"""
    from lumen_services.rate_limit import RateLimitResult
    from lumen_api.v1 import admin_skills

    original = admin_skills._skill_test_run_limiter
    admin_skills._skill_test_run_limiter = lambda uid: RateLimitResult(
        allowed=True, remaining=5, retry_after_seconds=0.0, degraded=False,
    )
    try:
        admin_skills._check_rate_limit(user_id=42)  # 不抛
    finally:
        admin_skills._skill_test_run_limiter = original


def test_check_rate_limit_raises_429_when_allowed_false_normal():
    """allowed=False + degraded=False → 429 Too Many Requests。"""
    import pytest
    from fastapi import HTTPException
    from lumen_services.rate_limit import RateLimitResult
    from lumen_api.v1 import admin_skills

    admin_skills._skill_test_run_limiter = lambda uid: RateLimitResult(
        allowed=False, remaining=0, retry_after_seconds=300.0, degraded=False,
    )
    with pytest.raises(HTTPException) as exc_info:
        admin_skills._check_rate_limit(user_id=42)
    assert exc_info.value.status_code == 429
    assert "10 calls / 5min" in exc_info.value.detail


def test_check_rate_limit_raises_503_when_degraded():
    """allowed=False + degraded=True → 503 + Retry-After header。"""
    import pytest
    from fastapi import HTTPException
    from lumen_services.rate_limit import RateLimitResult
    from lumen_api.v1 import admin_skills

    admin_skills._skill_test_run_limiter = lambda uid: RateLimitResult(
        allowed=False, remaining=0, retry_after_seconds=0.0, degraded=True,
    )
    with pytest.raises(HTTPException) as exc_info:
        admin_skills._check_rate_limit(user_id=42)
    assert exc_info.value.status_code == 503
    assert "限流组件异常" in exc_info.value.detail or "degraded" in exc_info.value.detail
    # Retry-After 必须存在(前端可拿来 wait 后重试)
    assert exc_info.value.headers is not None
    assert exc_info.value.headers.get("Retry-After") == "30"