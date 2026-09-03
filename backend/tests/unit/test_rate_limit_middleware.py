"""Phase 1 Group A 2.1 (2026-09-03): RateLimitMiddleware 单元测试。"""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from lumen_api.middleware.rate_limit import (
    EXEMPT_PATHS,
    RATE_LIMITS,
    RateLimitMiddleware,
    _parse_rate_str,
)


# ---------------------------------------------------------------------------
# _parse_rate_str
# ---------------------------------------------------------------------------


def test_parse_rate_str_sec():
    assert _parse_rate_str("5/sec") == (5, 1)


def test_parse_rate_str_min():
    assert _parse_rate_str("10/min") == (10, 60)


def test_parse_rate_str_hour():
    assert _parse_rate_str("120/hour") == (120, 3600)


def test_parse_rate_str_invalid():
    with pytest.raises(ValueError):
        _parse_rate_str("10")  # no period
    with pytest.raises(ValueError):
        _parse_rate_str("10/day")  # unsupported period
    with pytest.raises(ValueError):
        _parse_rate_str("foo/min")


def test_parse_rate_str_strips_whitespace():
    assert _parse_rate_str("  30/min  ") == (30, 60)


# ---------------------------------------------------------------------------
# 默认 policy dict 完整性
# ---------------------------------------------------------------------------


def test_rate_limits_dict_has_default():
    assert "default" in RATE_LIMITS


def test_exempt_paths_includes_infra():
    for path in ("/", "/health", "/live", "/ready", "/startup", "/metrics",
                 "/docs", "/redoc", "/openapi.json"):
        assert path in EXEMPT_PATHS


# ---------------------------------------------------------------------------
# RedisLimiter mock helpers
# ---------------------------------------------------------------------------


class FakeRateLimitResult:
    def __init__(self, allowed: bool, remaining: int = 0,
                 retry_after_seconds: float = 0.0, degraded: bool = False):
        self.allowed = allowed
        self.remaining = remaining
        self.retry_after_seconds = retry_after_seconds
        self.degraded = degraded


def _build_app(limiter_check_result: FakeRateLimitResult,
               init_redis_failure: bool = False) -> FastAPI:
    """构造一个带 RateLimitMiddleware 的 mini FastAPI app。

    用 fake redis client + limiter 检查返固定结果。
    """
    app = FastAPI()

    @app.get("/api/v1/auth/login")
    def login():
        return {"ok": True}

    @app.get("/api/v1/chat")
    def chat():
        return {"ok": True}

    @app.get("/api/v1/health-protected")
    def protected():
        return {"ok": True}

    # mock redis client
    fake_redis = MagicMock()
    if init_redis_failure:
        fake_redis.ping.side_effect = ConnectionError("redis down")

    # mock limiter 直接构造 — 注入到 middleware 内部 cache
    mw = RateLimitMiddleware(
        app,
        rate_limits={
            "/api/v1/auth/login": {"ip": "2/min"},
            "/api/v1/chat": {"ip": "2/min"},
            "/api/v1/health-protected": {"ip": "5/min"},
            "default": {"ip": "100/min"},
        },
        exempt_paths={"/health", "/metrics"},
        exempt_prefixes=("/static/",),
        redis_client=fake_redis,
        enabled=True,
    )

    # 替换 limiter.check 行为
    def fake_check(identity: str) -> FakeRateLimitResult:
        return limiter_check_result

    # 注入到 cache: middleware 实例化后第一次 call 会创建 limiter,我们替换它的
    # _get_limiter 调用路径。最简单方法: monkeypatch RedisRateLimiter 实例。
    # 但因为 limiter 是 lazy 创建,我们让 fake_redis.pipe() 返回一个
    # MagicMock with .execute() 返回特定值。
    pipe_mock = MagicMock()
    pipe_mock.execute.return_value = [0, 1]  # ZCARD = 1 → allowed
    fake_redis.pipeline.return_value = pipe_mock
    fake_redis.zremrangebyscore = MagicMock()
    fake_redis.zcard = MagicMock(return_value=0)
    fake_redis.zadd = MagicMock()
    fake_redis.expire = MagicMock()
    fake_redis.zpopmax = MagicMock()

    return app


def _add_middleware(app: FastAPI, **kwargs: Any) -> None:
    """Helper: 通过 app.add_middleware() 注册 RateLimitMiddleware(starlette 推荐用法)。"""
    app.add_middleware(RateLimitMiddleware, **kwargs)


# ---------------------------------------------------------------------------
# 通过路径测试
# ---------------------------------------------------------------------------


def test_exempt_paths_pass_through():
    """白名单路径不触发限流,即使 redis 挂了也 200。"""
    app = FastAPI()

    @app.get("/health")
    def health():
        return {"status": "healthy"}

    # 故意 redis init 失败
    fake_redis = MagicMock()
    fake_redis.ping.side_effect = ConnectionError("redis down")

    _add_middleware(
        app,
        redis_client=fake_redis,
        enabled=True,
    )
    client = TestClient(app)
    r = client.get("/health")
    assert r.status_code == 200


def test_disabled_skips_all():
    """RATE_LIMIT_ENABLED=False 时,所有路径跳过限流。"""
    app = FastAPI()

    @app.get("/api/v1/auth/login")
    def login():
        return {"ok": True}

    fake_redis = MagicMock()
    fake_redis.ping.side_effect = ConnectionError("redis down")
    _add_middleware(app, redis_client=fake_redis, enabled=False)
    client = TestClient(app)
    # redis 挂了但 enabled=False → 200
    r = client.get("/api/v1/auth/login")
    assert r.status_code == 200


def test_no_match_policy_passes_through():
    """policy 找不到(default 没匹配)时透传。"""
    app = FastAPI()

    @app.get("/some/random/path")
    def handler():
        return {"ok": True}

    fake_redis = MagicMock()
    fake_redis.ping.return_value = True
    pipe = MagicMock()
    pipe.execute.return_value = [0, 1]
    fake_redis.pipeline.return_value = pipe

    _add_middleware(
        app,
        rate_limits={"default": {"ip": "100/min"}},  # 故意让 some/random/path 不匹配
        redis_client=fake_redis,
    )
    client = TestClient(app)
    r = client.get("/some/random/path")
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# Redis fail-closed 503
# ---------------------------------------------------------------------------


def test_redis_init_failure_returns_503():
    """Redis init 失败 → fail-closed 503 + Retry-After。"""
    app = FastAPI()

    @app.post("/api/v1/auth/login")
    def login():
        return {"ok": True}

    fake_redis = MagicMock()
    fake_redis.ping.side_effect = ConnectionError("redis down")
    _add_middleware(app, redis_client=fake_redis, enabled=True)
    client = TestClient(app)
    r = client.post("/api/v1/auth/login")
    assert r.status_code == 503
    assert r.headers.get("Retry-After") == "5"


def test_redis_per_call_failure_returns_503():
    """Init OK 但 per-call Redis 抛错 → fail-closed 503。"""
    app = FastAPI()

    @app.get("/api/v1/auth/login")
    def login():
        return {"ok": True}

    fake_redis = MagicMock()
    fake_redis.ping.return_value = True
    fake_redis.pipeline.side_effect = ConnectionError("redis dropped mid-call")

    _add_middleware(app, redis_client=fake_redis, enabled=True)
    client = TestClient(app)
    r = client.get("/api/v1/auth/login")
    assert r.status_code == 503
    assert r.headers.get("Retry-After") == "5"


# ---------------------------------------------------------------------------
# 429 超限
# ---------------------------------------------------------------------------


def test_rate_limit_rejection_returns_429():
    """达到 limit → 429 + Retry-After + X-RateLimit-* headers。"""
    app = FastAPI()

    @app.get("/api/v1/auth/login")
    def login():
        return {"ok": True}

    fake_redis = MagicMock()
    fake_redis.ping.return_value = True
    # ZREMRANGEBYSCORE = 0 entries removed
    # ZCARD = 2 (already at limit)
    # ZADD successful
    # ZPOPMAX successful
    pipe = MagicMock()
    pipe.execute.return_value = [0, 2, 1, 1]
    fake_redis.pipeline.return_value = pipe
    fake_redis.zpopmax.return_value = [("member", 1.0)]

    _add_middleware(
        app,
        rate_limits={"/api/v1/auth/login": {"ip": "2/min"}},
        redis_client=fake_redis,
        enabled=True,
    )
    client = TestClient(app)
    r = client.get("/api/v1/auth/login")
    assert r.status_code == 429
    assert int(r.headers["Retry-After"]) >= 1
    assert r.headers["X-RateLimit-Limit"] == "2"
    assert r.headers["X-RateLimit-Remaining"] == "0"


# ---------------------------------------------------------------------------
# 通过请求附 X-RateLimit-* headers
# ---------------------------------------------------------------------------


def test_passing_request_includes_rate_limit_headers():
    """通过请求的 response 带 X-RateLimit-Limit/Remaining/Window。"""
    app = FastAPI()

    @app.get("/api/v1/auth/login")
    def login():
        return {"ok": True}

    fake_redis = MagicMock()
    fake_redis.ping.return_value = True
    pipe = MagicMock()
    pipe.execute.return_value = [0, 0, 1, 1]  # ZCARD=0 → allowed
    fake_redis.pipeline.return_value = pipe

    _add_middleware(
        app,
        rate_limits={"/api/v1/auth/login": {"ip": "10/min"}},
        redis_client=fake_redis,
        enabled=True,
    )
    client = TestClient(app)
    r = client.get("/api/v1/auth/login")
    assert r.status_code == 200
    assert r.headers["X-RateLimit-Limit"] == "10"
    assert r.headers["X-RateLimit-Remaining"] == "10"
    assert r.headers["X-RateLimit-Window"] == "60"


# ---------------------------------------------------------------------------
# Longest-prefix 匹配
# ---------------------------------------------------------------------------


def test_longest_prefix_match():
    """/api/v1/auth/login 精确匹配,不被 default 拦截。"""
    app = FastAPI()

    @app.post("/api/v1/auth/login")
    def login():
        return {"ok": True}

    fake_redis = MagicMock()
    fake_redis.ping.return_value = True
    pipe = MagicMock()
    pipe.execute.return_value = [0, 0, 1, 1]
    fake_redis.pipeline.return_value = pipe

    _add_middleware(
        app,
        rate_limits={
            "/api/v1/auth/login": {"ip": "10/min"},
            "default": {"ip": "5/min"},  # 较小,精确路径优先
        },
        redis_client=fake_redis,
        enabled=True,
    )
    client = TestClient(app)
    r = client.post("/api/v1/auth/login")
    assert r.status_code == 200
    # 精确匹配生效,limit=10 不是 5
    assert r.headers["X-RateLimit-Limit"] == "10"
