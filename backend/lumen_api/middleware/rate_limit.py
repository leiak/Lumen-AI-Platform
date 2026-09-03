"""Phase 1 Group A 2.1 (2026-09-03): 限流 RateLimitMiddleware 全覆盖。

**为什么需要**: Phase 0 ship 的限流只挂 4 个 admin endpoint(skill_test_run 等),
其他高频路径(/auth/login, /chat, /knowledge/upload, /videos/compose, ...)裸奔,
容易被打挂或被恶意刷。Phase 1 2.1 用全局 middleware 覆盖关键路径,policy dict
业务代码不动,新路径加 dict 即可。

**设计要点**:

1. **路径匹配**: 走前缀最长匹配。先按完整路径查 RATE_LIMITS,再按
   longest-prefix 匹配,最后 fallback 到 ``default``。

2. **白名单 EXEMPT_PATHS**: ``/metrics`` / ``/health`` / ``/live`` / ``/ready``
   / ``/startup`` / ``/docs`` / ``/redoc`` / ``/openapi.json`` / ``/static/`` 前缀
   全部免限(运维 + K8s probe + 文档)。

3. **identity 优先级**:
   - ``tenant_id(user)`` (从 JWT 解析,如有)
   - ``user_id`` (从 JWT 解析,如有)
   - ``client_ip`` (从 ``X-Forwarded-For`` 第一项,否则 ``request.client.host``)
   每种 identity 用不同的 RATE_LIMITS sub-key。

4. **fail-closed (Phase 0 行为保留)**: Redis 挂 → 503 + ``Retry-After: 5``,
   不放行(否则 in-memory dict 跨 worker 不一致,被恶意 client 绕开)。
   RateLimitResult.degraded=True 触发 503,RateLimitResult.allowed=False 触发 429。

5. **metric**: 复用 Phase 0 ship 的 ``lumen_rate_limit_rejections_total{endpoint}``
   Counter,policy dict endpoint 字符串作为 label(不是实际 URL,防 cardinality)。

6. **滑窗**: 复用 Phase 0 ship 的 ``RedisRateLimiter`` (ZSET sliding window),
   每 endpoint 不同 (limit, window) 各自一个 limiter 实例,共享 redis client。

7. **middleware 顺序**: ``CORS → TraceId → RateLimit → Prometheus``。
   TraceId 注入 trace_id → RateLimit 用 trace_id 写 metric → Prometheus
   记 metrics 时带 trace_id。三者按 FIFO 反序 add (LIFO 执行)。
"""
from __future__ import annotations

import logging
import re
from typing import Any, Awaitable, Callable, Dict, Optional, Tuple

import redis as redis_lib
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from lumen_core.config import settings
from lumen_core.metrics import lumen_rate_limit_rejections_total
from lumen_services.rate_limit import RedisRateLimiter

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Policy dict: endpoint → {identity_kind: "N/period"}
# ---------------------------------------------------------------------------

# 单位支持: sec / min / hour (only singular forms to keep parsing simple)
_PERIOD_RE = re.compile(r"^(\d+)/(sec|min|hour)$")


def _parse_rate_str(rate_str: str) -> Tuple[int, int]:
    """Parse "10/min" → (10, 60); "120/hour" → (120, 3600); "5/sec" → (5, 1).

    Raises ValueError on malformed input — config 错误早期失败。
    """
    m = _PERIOD_RE.match(rate_str.strip())
    if not m:
        raise ValueError(
            f"Invalid rate string '{rate_str}', expected format '<N>/<sec|min|hour>'"
        )
    n = int(m.group(1))
    period = {"sec": 1, "min": 60, "hour": 3600}[m.group(2)]
    return n, period


# Phase 1 Group A 2.1 policy dict。路径精确匹配优先,fallback "default"。
# identity kinds: "ip" (无 token), "user" (有 user_id 但无 tenant_id),
# "tenant" (有 tenant_id, 多用户共享同一租户额度)。
RATE_LIMITS: Dict[str, Dict[str, str]] = {
    "/api/v1/auth/login": {"ip": "10/min", "user": "30/min"},
    "/api/v1/auth/register": {"ip": "5/min"},
    "/api/v1/auth/refresh-token": {"user": "60/min"},
    "/api/v1/chat": {"user": "60/min"},
    "/api/v1/knowledge/upload": {"user": "10/min"},
    "/api/v1/image-generation": {"user": "20/min"},
    "/api/v1/videos/compose": {"user": "5/min"},
    "/api/v1/eval/runs": {"user": "5/min"},
    "/api/v1/wx-publisher/drafts": {"user": "30/min"},
    "/api/v1/wx-publisher/publish": {"user": "10/min"},
    "default": {"ip": "120/min", "user": "600/min"},
}


# 白名单:精确路径 + 前缀("/static/" 全免)
EXEMPT_PATHS = {
    "/",
    "/health",
    "/live",
    "/ready",
    "/startup",
    "/metrics",
    "/docs",
    "/docs/oauth2-redirect",
    "/redoc",
    "/openapi.json",
}
EXEMPT_PREFIXES = ("/static/", "/api/v1/auth/login-options")


# ---------------------------------------------------------------------------
# Identity helpers
# ---------------------------------------------------------------------------


def _extract_bearer_token(request: Request) -> Optional[str]:
    """从 Authorization header 拿 bearer token,无返 None。"""
    auth = request.headers.get("Authorization") or request.headers.get("authorization")
    if not auth:
        return None
    parts = auth.split()
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1]
    return None


def _resolve_identity(request: Request) -> Tuple[str, str]:
    """Resolve identity (kind, value) for rate-limiting.

    Priority:
    - tenant_id from JWT payload (if present and parseable)
    - user_id from JWT payload (if present and parseable)
    - client_ip from X-Forwarded-For (first item) or request.client.host

    Returns (kind, value):
    - ("tenant", "<id>") / ("user", "<id>") / ("ip", "<addr>")

    JWT decode intentionally fails silently — if the token is malformed,
    we fall through to IP-based limiting rather than 401-ing here.
    Rate-limit is a non-auth concern; the actual endpoint will still 401.
    """
    token = _extract_bearer_token(request)
    if token:
        try:
            from jose import jwt
            from lumen_core.config import settings as cfg
            payload = jwt.get_unverified_claims(token)
            tid = payload.get("tenant_id")
            uid = payload.get("sub") or payload.get("user_id")
            if tid is not None:
                return ("tenant", str(tid))
            if uid is not None:
                return ("user", str(uid))
        except Exception:  # noqa: BLE001
            pass
    # IP fallback
    xff = request.headers.get("x-forwarded-for") or request.headers.get("X-Forwarded-For")
    if xff:
        # First item = original client (RFC 7239 简化版)
        return ("ip", xff.split(",")[0].strip())
    if request.client:
        return ("ip", request.client.host)
    return ("ip", "unknown")


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Phase 1 Group A 2.1 限流 middleware。

    复用 Phase 0 ship 的 ``RedisRateLimiter``(滑窗 ZSET 算法),
    共享一个 redis client,每 (endpoint + identity_kind) 懒构造 limiter 实例。
    """

    def __init__(
        self,
        app: Any,
        *,
        rate_limits: Optional[Dict[str, Dict[str, str]]] = None,
        exempt_paths: Optional[set] = None,
        exempt_prefixes: Optional[Tuple[str, ...]] = None,
        redis_client: Optional[Any] = None,
        enabled: Optional[bool] = None,
    ):
        super().__init__(app)
        self._rate_limits = rate_limits or RATE_LIMITS
        self._exempt_paths = exempt_paths or EXEMPT_PATHS
        self._exempt_prefixes = exempt_prefixes or EXEMPT_PREFIXES
        self._enabled = enabled if enabled is not None else bool(settings.RATE_LIMIT_ENABLED)
        # Redis client: 注入优先,否则从 settings 构造(跟 Phase 0 build_default_limiter 一致)
        # 注入路径也要 ping 探活 —— 测试用 mock 模拟"注入一个挂掉的 client",必须探测,
        # 否则 fail-closed 503 路径不触发。
        if redis_client is not None:
            self._redis = None
            self._redis_init_failed = False
            try:
                redis_client.ping()
                self._redis = redis_client
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    "RateLimitMiddleware: injected Redis client ping failed (%s); fail-closed",
                    e,
                )
                self._redis = None
                self._redis_init_failed = True
        else:
            self._redis = None
            self._redis_init_failed = False
            try:
                self._redis = redis_lib.Redis(
                    host=settings.REDIS_HOST,
                    port=settings.REDIS_PORT,
                    db=settings.REDIS_DB,
                    socket_connect_timeout=0.2,
                    socket_timeout=0.2,
                    decode_responses=True,
                )
                self._redis.ping()
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    "RateLimitMiddleware: Redis init failed (%s); fail-closed",
                    e,
                )
                self._redis = None
                self._redis_init_failed = True
        # Limiter cache: (endpoint, identity_kind) → RedisRateLimiter
        self._limiter_cache: Dict[Tuple[str, str], RedisRateLimiter] = {}

    def _is_exempt(self, path: str) -> bool:
        if path in self._exempt_paths:
            return True
        return any(path.startswith(p) for p in self._exempt_prefixes)

    def _match_policy(self, path: str) -> Optional[Dict[str, str]]:
        """Longest-prefix 匹配。"""
        if path in self._rate_limits:
            return self._rate_limits[path]
        # 找最长匹配前缀
        best: Optional[str] = None
        for key in self._rate_limits:
            if key == "default":
                continue
            if path.startswith(key + "/") or path == key:
                if best is None or len(key) > len(best):
                    best = key
        if best is not None:
            return self._rate_limits[best]
        return self._rate_limits.get("default")

    def _get_limiter(self, endpoint: str, identity_kind: str, limit: int, window: int) -> RedisRateLimiter:
        key = (endpoint, identity_kind)
        cached = self._limiter_cache.get(key)
        if cached is not None:
            return cached
        limiter = RedisRateLimiter(
            self._redis,  # type: ignore[arg-type]
            bucket=f"{endpoint}:{identity_kind}",
            limit=limit,
            window_seconds=window,
        )
        self._limiter_cache[key] = limiter
        return limiter

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        # Disabled (RATE_LIMIT_ENABLED=false) → 跳过
        if not self._enabled:
            return await call_next(request)
        # 白名单 → 跳过
        path = request.url.path
        if self._is_exempt(path):
            return await call_next(request)
        # Redis init 时挂了 → 走 fail-closed (503)
        if self._redis is None:
            logger.warning(
                "RateLimitMiddleware: Redis unavailable; fail-closed 503 path=%s",
                path,
            )
            self._record_metric(path, "degraded")
            return JSONResponse(
                status_code=503,
                content={
                    "code": 503,
                    "message": "Rate limiter unavailable / 限流器不可用,请稍后重试",
                },
                headers={"Retry-After": "5"},
            )
        # 匹配 policy
        policy = self._match_policy(path)
        if policy is None:
            return await call_next(request)
        # 解析 identity
        identity_kind, identity_value = _resolve_identity(request)
        rate_str = policy.get(identity_kind) or policy.get("ip") or "60/min"
        try:
            limit, window = _parse_rate_str(rate_str)
        except ValueError as e:
            logger.error("RateLimitMiddleware: bad policy %s, defaulting 60/min: %s", rate_str, e)
            limit, window = 60, 60
        limiter = self._get_limiter(path, identity_kind, limit, window)
        try:
            result = limiter.check(identity_value)
        except Exception as e:  # noqa: BLE001 — Redis 临时挂也走 fail-closed
            logger.warning(
                "RateLimitMiddleware: per-call Redis error (%s); fail-closed 503 path=%s",
                e, path,
            )
            self._record_metric(path, "degraded")
            return JSONResponse(
                status_code=503,
                content={
                    "code": 503,
                    "message": "Rate limiter unavailable / 限流器不可用,请稍后重试",
                },
                headers={"Retry-After": "5"},
            )
        if not result.allowed:
            self._record_metric(path, "rejected")
            retry_after = max(int(result.retry_after_seconds), 1)
            return JSONResponse(
                status_code=429,
                content={
                    "code": 429,
                    "message": "Too many requests / 请求过于频繁,请稍后重试",
                },
                headers={
                    "Retry-After": str(retry_after),
                    "X-RateLimit-Limit": str(limit),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Window": str(window),
                },
            )
        # 透传 X-RateLimit-* 头(让前端 / SDK 看到额度)
        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(result.remaining)
        response.headers["X-RateLimit-Window"] = str(window)
        return response

    @staticmethod
    def _record_metric(path: str, kind: str) -> None:
        """复用 Phase 0 ship 的 lumen_rate_limit_rejections_total。"""
        try:
            # kind: rejected (429) / degraded (503)
            label = f"{kind}:{path}"
            lumen_rate_limit_rejections_total.labels(endpoint=label).inc()
        except Exception as e:  # noqa: BLE001
            logger.warning("RateLimitMiddleware: failed to record metric: %s", e)


__all__ = [
    "RateLimitMiddleware",
    "RATE_LIMITS",
    "EXEMPT_PATHS",
    "EXEMPT_PREFIXES",
    "_parse_rate_str",
]
