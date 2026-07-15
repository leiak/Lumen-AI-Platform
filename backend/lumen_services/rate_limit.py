"""M30 P1-4 — Distributed sliding-window rate limiter backed by Redis.

Replaces the in-memory ``_rate_limit_store`` dict in
``app/api/v1/admin_skills.py`` (M17) that didn't work across
multiple uvicorn workers — each worker had its own dict and a
client hitting worker A then worker B was never rate-limited.

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
network blip), fall back to an in-memory dict (same buggy
behavior as M17, but at least the endpoint doesn't 500). The
fallback logs a warning so ops sees it in dev.
"""
from __future__ import annotations

import logging
import time
import uuid
from typing import Optional

logger = logging.getLogger(__name__)


class RateLimitResult:
    """Result of a ``check()`` call."""

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

    Args:
        redis_client: a configured ``redis.Redis`` instance.
        bucket: short namespace (e.g. ``"skill_test_run"``).
        limit: max calls per window.
        window_seconds: window length in seconds.
        fallback: an in-memory dict fallback (kept in the caller).
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
        """
        now = time.time()
        cutoff = now - self._window
        key = self._key(identity)

        try:
            # Pipeline: prune old + add new + set TTL — one round-trip.
            pipe = self._r.pipeline()
            pipe.zremrangebyscore(key, 0, cutoff)
            pipe.zcard(key)
            pipe.zadd(key, {f"{now:.6f}-{uuid.uuid4().hex[:8]}": now})
            pipe.expire(key, self._window)
            results = pipe.execute()
            current_count = int(results[1])  # ZCARD result, before our ZADD
        except Exception as e:  # noqa: BLE001
            # Redis is down / network blip. Per design, fall back to
            # caller-provided in-memory limiter. We return a result
            # the caller will replace via ``_fallback_check``.
            logger.warning(
                "RedisRateLimiter: Redis unavailable (%s); using fallback",
                e,
            )
            raise

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
    """Construct a limiter using the project's ``REDIS_HOST``/``REDIS_PORT``
    settings, with an in-memory fallback dict for when Redis is
    unavailable (dev without docker, transient network blip).
    """
    from lumen_core.config import settings  # local import: avoid circular

    client: Optional[object] = None
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
        # Probe — fail fast if unreachable
        client.ping()
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "build_default_limiter: Redis not reachable at %s:%s (%s); "
            "using in-memory fallback",
            getattr(settings, "REDIS_HOST", "?"),
            getattr(settings, "REDIS_PORT", "?"),
            e,
        )
        client = None

    fallback: dict = {}

    def limiter_fn(identity: str) -> RateLimitResult:
        if client is not None:
            try:
                limiter = RedisRateLimiter(
                    client, bucket="skill_test_run",
                    limit=limit, window_seconds=window_seconds,
                )
                return limiter.check(identity)
            except Exception:
                pass  # fall through to in-memory
        # In-memory fallback — same algorithm, just in Python.
        now = time.time()
        cutoff = now - window_seconds
        bucket = fallback.setdefault(identity, [])
        # Prune old + count
        bucket[:] = [t for t in bucket if t >= cutoff]
        if len(bucket) >= limit:
            return RateLimitResult(False, 0, window_seconds, degraded=True)
        bucket.append(now)
        return RateLimitResult(True, limit - len(bucket), 0.0, degraded=True)

    return limiter_fn
