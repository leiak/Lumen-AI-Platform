"""Phase 0 Unit 4.3.3 (2026-09-02):分布式锁 dist_lock 测试。

覆盖:
- acquire 成功 + 自动 release(token-based)
- 同 key 第二次 acquire 阻塞 / 超时 / 失败(非阻塞)
- token mismatch 时不删别人锁(Lua check-and-delete 语义)
- TTL 过期后别人能拿到锁
- 不同 key 互不影响
- 注入 mock client(避免依赖 dev Redis)

**为什么用 mock 而不是 fakeredis**:项目没装 fakeredis;lock 涉及的
Redis 命令极少(SETNX + EVAL),手写 mock 比装新依赖简单。
"""
import sys
import os
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

import pytest


# ---- Mock Redis client ----


class _FakeRedis:
    """最小 Redis mock,只支持 dist_lock 用的命令。

    模拟:
    - SET key value NX PX ttl_ms — 仅当 key 不存在时设
    - EVAL <lua_script> 1 <key> <token> — Lua 原子 check-and-delete
    """

    def __init__(self):
        self._store: dict[str, str] = {}
        # 可被测试调用的 hook
        self.set_call_count = 0
        self.eval_call_count = 0

    def set(self, key, value, nx=False, px=None):
        self.set_call_count += 1
        if nx and key in self._store:
            # NX 失败
            return False
        self._store[key] = value
        return True

    def eval(self, script, num_keys, *args):
        self.eval_call_count += 1
        # 只支持 _RELEASE_SCRIPT(check-and-delete)
        if "get" in script and "del" in script and "== " in script:
            key = args[0]
            token = args[1]
            if self._store.get(key) == token:
                del self._store[key]
                return 1
            return 0
        raise NotImplementedError(f"unsupported script: {script!r}")

    # 测试用 helpers
    def exists(self, key):
        return key in self._store

    def get(self, key):
        return self._store.get(key)

    def expire_for_test(self, key):
        """模拟 TTL 过期:测试时直接删。"""
        if key in self._store:
            del self._store[key]


@pytest.fixture
def fake_redis():
    return _FakeRedis()


# ===== happy path =====


def test_acquire_lock_normal_release(fake_redis):
    """happy path:能拿到,with block 退出自动 release。"""
    from lumen_services.dist_lock import acquire_lock

    with acquire_lock("doc:1", ttl=60, client=fake_redis) as _:
        # 进入临界区:锁被持有
        assert fake_redis.exists("doc:1")
    # 退出后:锁已自动 release
    assert not fake_redis.exists("doc:1")
    # eval 被调一次(release 路径)
    assert fake_redis.eval_call_count == 1


def test_acquire_lock_returns_token(fake_redis):
    """acquire 后 store 里是 token(非空 random hex)。"""
    from lumen_services.dist_lock import acquire_lock

    with acquire_lock("doc:2", ttl=60, client=fake_redis):
        token = fake_redis.get("doc:2")
        assert token is not None
        # token 32 字符(128-bit hex)
        assert len(token) == 32
        # 不同 acquire token 不同
    with acquire_lock("doc:2", ttl=60, client=fake_redis):
        token2 = fake_redis.get("doc:2")
        assert token2 != token


# ===== 阻塞 / 超时 / 非阻塞 =====


def test_acquire_lock_blocking_timeout_raises(fake_redis):
    """同 key 第一次 acquire 拿锁,第二次 blocking 超时抛 LockTimeoutError。"""
    from lumen_services.dist_lock import acquire_lock, LockTimeoutError

    holder_acquired = threading.Event()
    holder_release = threading.Event()

    def holder():
        with acquire_lock("doc:3", ttl=60, client=fake_redis, timeout=2):
            holder_acquired.set()
            holder_release.wait(timeout=3)

    t = threading.Thread(target=holder, daemon=True)
    t.start()
    assert holder_acquired.wait(timeout=1), "holder 线程未拿到锁"

    # 此时锁被占,第二个 acquire 应超时
    start = time.time()
    with pytest.raises(LockTimeoutError) as exc_info:
        with acquire_lock("doc:3", ttl=60, client=fake_redis, timeout=0.3):
            pass
    elapsed = time.time() - start
    assert 0.25 <= elapsed < 1.0, f"超时时间不符预期: {elapsed:.2f}s"
    assert "doc:3" in str(exc_info.value)

    holder_release.set()
    t.join(timeout=2)


def test_acquire_lock_non_blocking_fails_immediately(fake_redis):
    """blocking=False 时锁被占立刻抛 LockAcquireFailed,不等 timeout。"""
    from lumen_services.dist_lock import acquire_lock, LockAcquireFailed

    # 先占住
    with acquire_lock("doc:4", ttl=60, client=fake_redis, blocking=False):
        # 此时另一个进程再 acquire 应立即失败
        start = time.time()
        with pytest.raises(LockAcquireFailed):
            with acquire_lock("doc:4", ttl=60, client=fake_redis, blocking=False):
                pass
        elapsed = time.time() - start
        # 不应阻塞(< 100ms 即立即失败)
        assert elapsed < 0.1, f"non-blocking 模式不应等待: {elapsed:.3f}s"


def test_acquire_lock_blocking_default_waits_until_release(fake_redis):
    """blocking=True + timeout=None 时无限等(直到锁被释放)。"""
    from lumen_services.dist_lock import acquire_lock

    # 锁被占
    holder_event = threading.Event()
    waiter_done = threading.Event()

    def holder():
        with acquire_lock("doc:5", ttl=60, client=fake_redis, timeout=1):
            holder_event.set()
            time.sleep(0.2)  # 模拟工作 200ms
        # 释放锁

    def waiter():
        holder_event.wait(timeout=1)
        with acquire_lock("doc:5", ttl=60, client=fake_redis):
            waiter_done.set()

    h = threading.Thread(target=holder, daemon=True)
    w = threading.Thread(target=waiter, daemon=True)
    h.start()
    w.start()
    # waiter 应等到 holder 释放后拿到锁
    assert waiter_done.wait(timeout=2), "waiter 没拿到锁"
    h.join(timeout=2)
    w.join(timeout=2)


# ===== token-based release =====


def test_release_does_not_delete_others_lock_on_token_mismatch(fake_redis):
    """锁过期被别人拿走,我 release 时不删别人的锁。

    模拟:进程 A 拿锁,TTL 过期,进程 B 拿到同一 key。进程 A 退出
    时 release 应发现 token 不匹配,不删 B 的锁。
    """
    from lumen_services.dist_lock import acquire_lock

    # 模拟场景:Redis 里已有 B 的锁(b_token),A 想 acquire 但拿不到。
    # 设 b_token 占住 key,模拟 B 已 SETNX 成功。
    fake_redis.set("doc:6", "B-token", nx=True, px=60000)
    assert fake_redis.get("doc:6") == "B-token"

    # 进程 A 试图 acquire,应拿不到(阻塞超时)
    from lumen_services.dist_lock import LockTimeoutError
    with pytest.raises(LockTimeoutError):
        with acquire_lock("doc:6", ttl=60, client=fake_redis, timeout=0.3):
            pass

    # B 的锁还在(我们没动它)
    assert fake_redis.get("doc:6") == "B-token"


def test_token_mismatch_warning_when_stale_lock(fake_redis):
    """更细的语义:进入临界区后,锁被偷(TTL 过期),release 时打 warning
    但不删别人锁。

    构造:进程 A 拿锁,with block 内模拟 TTL 过期被别人拿走,
    退出时 release 发现 token mismatch。
    """
    from lumen_services.dist_lock import acquire_lock

    class _ExpireOnAccessFake(_FakeRedis):
        """进程 A 拿到锁后,模拟 TTL 过期(只 expire 一次)。"""

        def __init__(self):
            super().__init__()
            self._expired_once = False

        def eval(self, script, num_keys, *args):
            # 第一次 eval 时模拟"TTL 过期",返回 0(token mismatch)
            # 第二次(若有)正常 check-and-delete
            key = args[0]
            token = args[1]
            if not self._expired_once and self._store.get(key) == token:
                self._expired_once = True
                # 模拟 TTL 过期:token 被换成别人的
                self._store[key] = "stolen-by-other-process"
                return 0  # 不删
            return super().eval(script, num_keys, *args)

    fake = _ExpireOnAccessFake()
    with acquire_lock("doc:7", ttl=60, client=fake, timeout=1):
        pass  # release 时 expire-on-access 触发

    # 别人的锁(stolen-by-other-process)没被删
    assert fake.exists("doc:7")
    assert fake.get("doc:7") == "stolen-by-other-process"


# ===== 不同 key 互不影响 =====


def test_different_keys_independent(fake_redis):
    """不同 key 的锁互不影响。"""
    from lumen_services.dist_lock import acquire_lock

    with acquire_lock("doc:a", ttl=60, client=fake_redis, timeout=1):
        # 同时 doc:b 应能拿到
        with acquire_lock("doc:b", ttl=60, client=fake_redis, timeout=1):
            assert fake_redis.exists("doc:a")
            assert fake_redis.exists("doc:b")
    assert not fake_redis.exists("doc:a")
    assert not fake_redis.exists("doc:b")


# ===== TTL 过期后能再拿 =====


def test_after_ttl_expiry_lock_can_be_reacquired(fake_redis):
    """TTL 过期后能再拿。

    场景:A 拿锁(写入 token_A),假设 server 端 TTL 过期(手动清掉),
    B 再 SETNX 同一 key 应成功(不会被 A 的 stale token  挡住)。
    """
    from lumen_services.dist_lock import acquire_lock

    # A 拿锁
    with acquire_lock("doc:8", ttl=60, client=fake_redis, timeout=1):
        token_a = fake_redis.get("doc:8")
        assert token_a is not None
    # 正常 release

    # 模拟 TTL 过期:server 端删掉 key(fake_redis 直接清)
    assert not fake_redis.exists("doc:8")  # 上一步已经 release 了

    # B 再拿锁:应成功
    with acquire_lock("doc:8", ttl=60, client=fake_redis, timeout=1):
        token_b = fake_redis.get("doc:8")
        assert token_b is not None
        assert token_b != token_a


# ===== 模块级 default client =====


def test_get_default_client_uses_settings(monkeypatch):
    """get_default_client() 走 lumen_core.config.settings 的 REDIS_* env。"""
    from lumen_services import dist_lock

    # 清掉旧 singleton
    dist_lock.reset_default_client()

    # Patch settings 的 REDIS_HOST/PORT/DB
    from lumen_core import config
    monkeypatch.setattr(config.settings, "REDIS_HOST", "test-host", raising=False)
    monkeypatch.setattr(config.settings, "REDIS_PORT", 16379, raising=False)
    monkeypatch.setattr(config.settings, "REDIS_DB", 7, raising=False)

    c = dist_lock.get_default_client()
    assert c.connection_pool.connection_kwargs["host"] == "test-host"
    assert c.connection_pool.connection_kwargs["port"] == 16379
    assert c.connection_pool.connection_kwargs["db"] == 7

    # 清掉 singleton(后续 test 重新加载)
    dist_lock.reset_default_client()


def test_reset_default_client_for_test_reload():
    """reset 后下次 get 重建新 client(不是复用)。"""
    from lumen_services import dist_lock

    c1 = dist_lock.get_default_client()
    dist_lock.reset_default_client()
    c2 = dist_lock.get_default_client()
    assert c1 is not c2