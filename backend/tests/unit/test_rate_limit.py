"""M30 P1-4 + Phase 0 Unit 3 (2026-09-02):tests for services/rate_limit.py.

Covers:
- RedisRateLimiter sliding window correctness (allow up to limit,
  reject beyond, sliding window expires old entries)
- ``build_default_limiter`` uses Redis when reachable
- ``build_default_limiter`` FAIL-CLOSES when Redis is unreachable
  (Phase 0 改:in-memory fallback removed, returns degraded=True
  with allowed=False so callers map to 503, not 429)
"""
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

# FK targets must be registered first; mirrors main.py:35-53.
from lumen_models.tenant import Tenant  # noqa: F401
from lumen_models.user import User  # noqa: F401


class _FakeRedis:
    """In-memory ZSET implementation for testing without a real Redis.

    Implements the minimal subset that RedisRateLimiter uses:
    zadd, zremrangebyscore, zcard, zpopmax, expire, pipeline.
    """

    def __init__(self):
        self._z: dict = {}
        self._expire: dict = {}
        self.ping_calls = 0

    def ping(self):
        self.ping_calls += 1
        return True

    def pipeline(self):
        outer = self

        class _P:
            def __init__(self):
                self._ops = []

            def zremrangebyscore(self, key, mn, mx):
                self._ops.append(("zremrangebyscore", key, mn, mx))
                return self

            def zcard(self, key):
                self._ops.append(("zcard", key))
                return self

            def zadd(self, key, mapping):
                self._ops.append(("zadd", key, dict(mapping)))
                return self

            def expire(self, key, sec):
                self._ops.append(("expire", key, sec))
                return self

            def execute(self):
                results = []
                for op in self._ops:
                    if op[0] == "zremrangebyscore":
                        _, key, mn, mx = op
                        zk = outer._z.setdefault(key, {})
                        for m in list(zk.keys()):
                            if mn <= zk[m] <= mx:
                                del zk[m]
                        results.append(0)
                    elif op[0] == "zcard":
                        _, key = op
                        results.append(len(outer._z.get(key, {})))
                    elif op[0] == "zadd":
                        _, key, mapping = op
                        zk = outer._z.setdefault(key, {})
                        for m, score in mapping.items():
                            zk[m] = score
                        results.append(0)
                    elif op[0] == "expire":
                        _, key, sec = op
                        outer._expire[key] = sec
                        results.append(True)
                self._ops = []
                return results

        return _P()

    def zpopmax(self, key):
        zk = self._z.get(key, {})
        if not zk:
            return None
        # Highest score first
        m, s = max(zk.items(), key=lambda kv: kv[1])
        del zk[m]
        return [(m, s)]


def test_redis_limiter_allows_up_to_limit_then_rejects():
    from lumen_services.rate_limit import RedisRateLimiter
    fake = _FakeRedis()
    limiter = RedisRateLimiter(
        fake, bucket="test", limit=3, window_seconds=60,
    )
    # 5 calls under the SAME identity — the limiter rejects beyond 3.
    results = [limiter.check("alice") for _ in range(5)]
    # First 3 allowed, last 2 rejected.
    assert [r.allowed for r in results] == [True, True, True, False, False]
    # Remaining counts down.
    assert [r.remaining for r in results[:3]] == [3, 2, 1]
    # Rejected result has 0 remaining + window-length retry.
    assert results[3].remaining == 0
    assert results[3].retry_after_seconds == 60


def test_redis_limiter_sliding_window_expires_old_entries():
    """Calls older than the window should not count against the limit."""
    from lumen_services.rate_limit import RedisRateLimiter
    fake = _FakeRedis()
    limiter = RedisRateLimiter(
        fake, bucket="test", limit=2, window_seconds=1,
    )
    # First call: t=0, allowed, remaining 2
    r1 = limiter.check("user-x")
    assert r1.allowed and r1.remaining == 2
    # Fast-forward past the window
    time.sleep(1.1)
    # Old entry pruned, allowed again
    r2 = limiter.check("user-x")
    assert r2.allowed
    assert r2.remaining == 2


def test_redis_limiter_different_identities_independent():
    from lumen_services.rate_limit import RedisRateLimiter
    fake = _FakeRedis()
    limiter = RedisRateLimiter(
        fake, bucket="test", limit=1, window_seconds=60,
    )
    assert limiter.check("alice").allowed
    # Bob has his own bucket — alice being rate-limited doesn't affect him
    assert limiter.check("bob").allowed
    # But alice's 2nd call rejects
    assert not limiter.check("alice").allowed


def test_build_default_limiter_failcloses_when_redis_unreachable_at_init(monkeypatch):
    """Phase 0 Unit 3 (2026-09-02):Redis init ping fails → fail-closed.

    Old behavior (pre-Phase 0) was to fall back to an in-memory dict that
    per-worker doesn't share state, allowing a malicious client to bypass
    the limit by hitting different workers. New behavior: ALL calls
    return ``RateLimitResult(allowed=False, degraded=True)`` so callers
    map to HTTP 503 (not 429). admin endpoint sees 503 + Retry-After.
    """
    from lumen_services import rate_limit

    class _DeadRedis:
        def ping(self):
            raise ConnectionError("redis is down")

    # Inject a connection-FAILING redis by patching the redis.Redis
    # constructor (our build_default_limiter probes it).
    import redis
    monkeypatch.setattr(redis, "Redis", lambda **kwargs: _DeadRedis())

    limiter = rate_limit.build_default_limiter(limit=2, window_seconds=60)
    assert limiter.init_failed is True

    # All 3 calls reject (fail-closed, NOT 2 allowed + 1 rejected)
    for i in range(3):
        r = limiter("alice")
        assert not r.allowed, f"call {i}: expected allowed=False, got {r}"
        assert r.degraded, f"call {i}: expected degraded=True (fail-closed), got {r}"
        assert r.remaining == 0
        assert r.retry_after_seconds == 0.0


def test_build_default_limiter_failcloses_when_redis_fails_on_call(monkeypatch):
    """Init ping 成功但 per-call Redis 抛 → 同样 fail-closed。

    模拟 Redis 中途挂:init OK,然后 pipeline.execute() 抛。
    """
    from lumen_services import rate_limit

    class _HalfDeadRedis:
        """Init OK 但 pipeline 调用挂的 redis。"""

        def __init__(self):
            self._pipeline_calls = 0
            self._fail_calls = 2  # 前 2 次 pipeline 抛

        def ping(self):
            return True

        def pipeline(self):
            outer = self

            class _P:
                def zremrangebyscore(self, *a, **kw): return self
                def zcard(self, *a, **kw): return self
                def zadd(self, *a, **kw): return self
                def expire(self, *a, **kw): return self
                def execute(self_inner):
                    outer._pipeline_calls += 1
                    if outer._pipeline_calls <= outer._fail_calls:
                        raise ConnectionError("redis went down mid-call")
                    # 第三次 OK — 给后续 test 一个 clean recovery path 用
                    return [0, 0]

            return _P()

    fake = _HalfDeadRedis()
    import redis
    monkeypatch.setattr(redis, "Redis", lambda **kwargs: fake)

    limiter = rate_limit.build_default_limiter(limit=2, window_seconds=60)
    assert limiter.init_failed is False  # init OK

    # 前 2 次 fail-closed
    for i in range(2):
        r = limiter("alice")
        assert not r.allowed and r.degraded, f"call {i}: expected fail-closed, got {r}"

    # 第 3 次 Redis 恢复 → 应返回正常 RateLimitResult(degraded=False)
    # 注:fake 不返回正确的 zadd 结果,所以走的不是 happy path,
    # 但应该不再 degraded=True。
    r3 = limiter("alice")
    assert not r3.degraded, f"Redis recovered后不应再 degraded: {r3}"


def test_build_default_limiter_returns_init_failed_attr(monkeypatch):
    """Phase 0:limiter_fn 上挂 init_failed 属性,便于 monitoring / debug。"""
    from lumen_services import rate_limit

    class _DeadRedis:
        def ping(self):
            raise ConnectionError("down")

    import redis
    monkeypatch.setattr(redis, "Redis", lambda **kwargs: _DeadRedis())

    limiter = rate_limit.build_default_limiter(limit=10, window_seconds=60)
    assert hasattr(limiter, "init_failed")
    assert limiter.init_failed is True
    # Don't test "init_failed=False" here — dev Redis 在 pytest 里可达性
    # 不确定(macOS / Linux / Windows / dev DB 状态都可能变)。
    # 只验证属性存在 + DeadRedis 路径下 = True,正面 case 由真集成覆盖。


def test_build_default_limiter_uses_redis_when_reachable():
    """When redis is reachable, the limiter uses Redis (degraded=False)."""
    from lumen_services import rate_limit
    fake = _FakeRedis()
    import redis
    # The limiter probes via Redis() ctor + .ping() — patch both.
    monkey_local = pytest.MonkeyPatch()
    monkey_local.setattr(redis, "Redis", lambda **kwargs: fake)
    try:
        limiter = rate_limit.build_default_limiter(limit=2, window_seconds=60)
        r1 = limiter("alice")
        assert r1.allowed and not r1.degraded
        assert r1.remaining == 2
    finally:
        monkey_local.undo()
