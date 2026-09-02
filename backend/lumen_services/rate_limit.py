"""M30 P1-4 + Phase 0 Unit 3 (2026-09-02):Distributed sliding-window rate
limiter backed by Redis with fail-closed failure mode.

History:
- M30 P1-4: Replaces the in-memory ``_rate_limit_store`` dict in
  ``app/api/v1/admin_skills.py`` (M17) that didn't work across
  multiple uvicorn workers.
- Phase 0 Unit 3 (2026-09-02): Change Redis-down behavior from in-memory
  fallback to fail-closed. Reason: in-process dict doesn't share state
  across workers, so a malicious client can hit each worker once and
  bypass the limit. Fail-closed is the correct safety posture for a
  rate limiter.

Algorithm — sliding-window counter via Redis ZSET (one ZSET per
user, one entry per call, score = epoch seconds). On each check:

1. ``ZREMRANGEBYSCORE key 0 (now - window)`` — drop stale entries
2. ``ZCARD key`` — count remaining
3. If count >= limit → reject (don't add new entry)
4. Else ``ZADD key now now`` (member=now to dedupe within same
   millisecond) + ``EXPIRE key window``

Steps 1 + 4 are wrapped in a pipeline; ``ZREMRANGEBYSCORE`` and
``ZADD`` use the same score so we get sliding window semantics
within one redis round-trip.

Failure mode — if Redis is unreachable (dev without docker, or
network blip), **fail-closed**: return ``RateLimitResult(allowed=False,
degraded=True)``. Caller should treat ``degraded=True`` as 503
Service Unavailable, not 429 Too Many Requests — signals "rate
limiter is broken, please retry later", not "you exceeded the limit".
"""
from __future__ import annotations

import logging
import time
import uuid
from typing import Optional

logger = logging.getLogger(__name__)


class RateLimitResult:
    """Result of a ``check()`` call.

    Attributes:
        allowed: True iff the call may proceed.
        remaining: how many more calls are allowed in this window
            (0 when ``allowed`` is False).
        retry_after_seconds: hint for HTTP Retry-After header
            (``self._window`` when rate-limited, ``0.0`` when allowed
            or degraded-fail-closed).
        degraded: True iff the rate limiter is degraded (e.g. Redis
            unreachable) and the call was rejected on safety grounds.
            Caller MUST map this to 503 Service Unavailable, NOT 429.
    """

    __slots__ = ("allowed", "remaining", "retry_after_seconds", "degraded")

    def __init__(self, allowed: bool, remaining: int,
                 retry_after_seconds: float, degraded: bool = False):
        self.allowed = allowed
        self.remaining = remaining
        self.retry_after_seconds = retry_after_seconds
        self.degraded = degraded

    def __repr__(self) -> str:
        return (
            f"RateLimitResult(allowed={self.allowed}, remaining={self.remaining}, "
            f"retry_after={self.retry_after_seconds:.1f}s, degraded={self.degraded})"
        )


class RedisRateLimiter:
    """Sliding-window rate limiter keyed by ``(bucket, key)``.

    Raises:
        Any redis exception when Redis is unreachable. Caller
        (``build_default_limiter``) catches and converts to a
        fail-closed ``RateLimitResult(allowed=False, degraded=True)``.
    """

    def __init__(
        self,
        redis_client,
        *,
        bucket: str,
        limit: int,
        window_seconds: int,
    ):
        self._r = redis_client
        self._bucket = bucket
        self._limit = limit
        self._window = window_seconds

    def _key(self, identity: str) -> str:
        return f"ratelimit:{self._bucket}:{identity}"

    def check(self, identity: str) -> RateLimitResult:
        """Atomically check + record one call for ``identity``. Returns
        ``RateLimitResult.allowed`` = True iff the call may proceed.

        Raises redis exceptions on Redis failure — caller decides
        whether to fail-open (allow) or fail-closed (reject).
        """
        now = time.time()
        cutoff = now - self._window
        key = self._key(identity)

        # Pipeline: prune old + count + add new + set TTL — one round-trip.
        pipe = self._r.pipeline()
        pipe.zremrangebyscore(key, 0, cutoff)
        pipe.zcard(key)
        pipe.zadd(key, {f"{now:.6f}-{uuid.uuid4().hex[:8]}": now})
        pipe.expire(key, self._window)
        results = pipe.execute()
        current_count = int(results[1])  # ZCARD result, before our ZADD

        # current_count already includes the entry we just added.
        if current_count >= self._limit:
            # Rejected. Remove the entry we optimistically added to keep
            # the count clean for the next window.
            try:
                # Pop the most recent (highest score) entry — that's ours.
                self._r.zpopmax(key)
            except Exception:
                pass
            return RateLimitResult(
                allowed=False,
                remaining=0,
                retry_after_seconds=self._window,
                degraded=False,
            )
        return RateLimitResult(
            allowed=True,
            remaining=self._limit - current_count,
            retry_after_seconds=0.0,
            degraded=False,
        )


def build_default_limiter(limit: int = 10, window_seconds: int = 300):
    """Construct a Redis-backed limiter using ``REDIS_HOST``/``REDIS_PORT``.

    **Phase 0 fail-closed contract**: when Redis is unreachable (init
    probe fails OR per-call Redis call raises), the returned
    ``limiter_fn`` returns ``RateLimitResult(allowed=False,
    degraded=True)`` — fail-closed. Callers MUST map ``degraded=True``
    to HTTP 503, not 429 (so clients don't think they're being
    rate-limited when in fact the rate limiter is broken).

    **Module-load safety**: init Redis ping failure is logged but
    does NOT raise — admin endpoint module imports (``admin_skills.py``
    line 30 module-level call) must succeed even if Redis is down, so
    the rest of the app continues to serve (with the admin endpoint
    returning 503 on its own).

    Args:
        limit: max calls per window per identity.
        window_seconds: window length in seconds.

    Returns:
        A callable ``limiter_fn(identity: str) -> RateLimitResult``.
    """
    from lumen_core.config import settings  # local import: avoid circular

    client: Optional[object] = None
    init_failed = False
    try:
        import redis  # local: keep top-level imports lean
        client = redis.Redis(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            db=settings.REDIS_DB,
            socket_connect_timeout=0.2,  # 200ms — fail fast in dev
            socket_timeout=0.2,
            decode_responses=True,
        )
        # Probe — record init health but don't raise (module-load safety)
        client.ping()
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "build_default_limiter: Redis not reachable at %s:%s (%s); "
            "FAIL-CLOSED — rate limit will reject all requests until "
            "Redis recovers",
            getattr(settings, "REDIS_HOST", "?"),
            getattr(settings, "REDIS_PORT", "?"),
            e,
        )
        client = None
        init_failed = True

    def limiter_fn(identity: str) -> RateLimitResult:
        # 路径 A:init 时 Redis 已挂 → 直接 fail-closed,不浪费时间再 ping
        if client is None:
            return RateLimitResult(
                allowed=False, remaining=0, retry_after_seconds=0.0, degraded=True,
            )

        # 路径 B:init OK 但 per-call 时 Redis 挂 → 抛异常后 fail-closed
        try:
            limiter = RedisRateLimiter(
                client, bucket="skill_test_run",
                limit=limit, window_seconds=window_seconds,
            )
            return limiter.check(identity)
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "build_default_limiter: per-call Redis error (%s); "
                "FAIL-CLOSED for this identity=%s",
                e, identity,
            )
            return RateLimitResult(
                allowed=False, remaining=0, retry_after_seconds=0.0, degraded=True,
            )

    # Expose init status for monitoring / debugging.
    limiter_fn.init_failed = init_failed  # type: ignore[attr-defined]
    return limiter_fn
