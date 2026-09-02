"""Phase 0 Unit 4 (2026-09-02):分布式锁,基于 Redis SETNX + TTL。

**为什么**:Phase 0 之前无锁,后台任务并发跑有竞态 — 同一 doc 多个
celery worker 同时跑 retry / rechunk;同一 wx draft 多人重复发布;
同一 eval run dispatcher 重叠派任务。Phase 0 引入分布式锁避免
这种 race,Phase 1 / 2 在关键路径挂上。

**用法**:
    from lumen_services.dist_lock import acquire_lock

    with acquire_lock("doc:123", ttl=30):
        do_exclusive_work()
    # 退出自动释放(Lua 校验 token 防止误删别人的锁)

**特性**:
- Redis 单实例 SETNX + PX(毫秒级 TTL)
- token-based release:Lua 原子 check-and-delete,防锁过期被别人
  拿到后我误删
- 阻塞 acquire(可指定 timeout) + 非阻塞 acquire
- 模块级 default client(走 REDIS_HOST/PORT/DB env);测试可注入 mock
- TTL 防僵尸锁:进程 crash 后锁自动过期

**不是**:
- 不是事务性锁(不支持回滚)
- 不是公平锁(不支持 FIFO 排队)
- 不是读写锁
- Phase 0 只用单 Redis 主节点;Phase 1 切 Redis cluster 再评估
  Redlock 算法(4 节点 majority quorum)

**踩坑预警**:
- Redis ZSET 限流跟锁共用同一 Redis 实例;挂锁时注意隔离 key
  prefix(lumen:lock:doc:123 不会跟 lumen:ratelimit:foo 冲突)
- 锁 TTL 不能太短(< 实际工作时间),也不能太长(> 重试间隔);
  经验值 ttl = 预计工作时间 × 2
"""
from __future__ import annotations

import logging
import secrets
import time
from contextlib import contextmanager
from typing import Iterator, Optional

import redis

logger = logging.getLogger(__name__)


# Lua script:原子 check-and-delete。
# 防锁过期被别人拿到后,我误删别人的锁(del 时校验 token)。
_RELEASE_SCRIPT = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
else
    return 0
end
"""


class LockTimeoutError(Exception):
    """锁 acquire 超时(阻塞模式下 timeout 秒内未拿到)。"""


class LockAcquireFailed(Exception):
    """非阻塞模式立即拿不到锁。"""


# ---- 默认 Redis client (module-level singleton) ----

_default_client: Optional[redis.Redis] = None


def get_default_client() -> redis.Redis:
    """懒加载默认 Redis 客户端(走 .env REDIS_HOST/PORT/DB)。

    Phase 0 兼容 dev 启动期未读 .env 的场景:首次访问时读 env,后续
    复用。Redis 不可达时返 client 实例但不抛;acquire_lock 调用时
    才会真的连接失败(由调用方决定 fail-closed)。
    """
    global _default_client
    if _default_client is None:
        from lumen_core.config import settings  # local import:避免循环
        _default_client = redis.Redis(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            db=settings.REDIS_DB,
            socket_connect_timeout=0.2,  # 200ms — fail fast
            socket_timeout=0.2,
            decode_responses=True,
        )
    return _default_client


def reset_default_client() -> None:
    """清掉默认 client 引用,下次 get_default_client() 重建。

    测试在 setUp / tearDown 改 env 后调一次,让后续访问走新 client。
    不真正 close client(redis.Redis 没显式 close,GC 兜底)。
    """
    global _default_client
    _default_client = None


# ---- 内部 helper ----


def _try_acquire(client: redis.Redis, key: str, token: str, ttl_seconds: int) -> bool:
    """SETNX + PX(毫秒级 TTL)。SET 命令带 NX 选项原子上锁。"""
    return bool(client.set(key, token, nx=True, px=ttl_seconds * 1000))


def _try_release(client: redis.Redis, key: str, token: str) -> bool:
    """Lua 原子 check-and-delete:token 匹配才删,否则返 0。"""
    result = client.eval(_RELEASE_SCRIPT, 1, key, token)
    return bool(result)


# ---- 公开 API ----


@contextmanager
def acquire_lock(
    key: str,
    *,
    ttl: int = 60,
    timeout: Optional[float] = None,
    blocking: bool = True,
    client: Optional[redis.Redis] = None,
) -> Iterator[None]:
    """分布式锁 acquire,带 timeout 和 release。

    Args:
        key: 锁名。惯例 ``<resource>:<id>``,如 ``doc:123`` /
             ``draft:42``。Phase 1 建议加 ``lumen:lock:`` 前缀避免
             跟 ratelimit 等其他 Redis 数据撞 keyspace。
        ttl: 锁 TTL(秒)。进程 crash 后锁自动过期。建议值 = 预计
             工作时间 × 2,留余量给慢 IO。
        timeout: 等锁最久秒数。
            - ``None`` = 阻塞直到拿到(慎用,可能永久 hang)
            - 数字 = N 秒内等不到抛 ``LockTimeoutError``
            - 0 = 非阻塞,拿不到立即抛 ``LockAcquireFailed``
        blocking: 是否阻塞。``False`` 等价于 ``timeout=0``。
        client: 自定义 Redis client。``None`` 走
                :func:`get_default_client`。

    Raises:
        LockTimeoutError: 阻塞模式下 timeout 秒内未拿到锁。
        LockAcquireFailed: 非阻塞模式立即拿不到锁。
        redis.exceptions.ConnectionError: Redis 完全不可达
            (阻塞模式下走 timeout,非阻塞立即抛)。

    Yields:
        None。acquire 成功后才 yield,失败抛异常不进 with block。

    Example:
        >>> with acquire_lock("doc:42", ttl=120, timeout=30):
        ...     # 同一 doc 只会有 1 个 worker 跑这段
        ...     process_document(doc_id=42)
        # 退出自动 release(token mismatch 时不删别人锁)
    """
    if not blocking:
        timeout = 0.0

    c = client or get_default_client()
    # 128-bit 随机 token,防碰撞 + 防别人猜中
    token = secrets.token_hex(16)

    # 计算 deadline(只在阻塞模式下有意义)
    deadline = time.monotonic() + timeout if timeout is not None else None

    while True:
        if _try_acquire(c, key, token, ttl):
            break  # 拿到锁

        if deadline is None:
            # timeout=None = 无限等
            time.sleep(0.05)
            continue

        if time.monotonic() >= deadline:
            # 超时
            if blocking:
                raise LockTimeoutError(
                    f"lock '{key}' not acquired within {timeout}s"
                )
            raise LockAcquireFailed(f"lock '{key}' not immediately available")

        # 50ms retry interval — 避免过密打 Redis
        time.sleep(0.05)

    # ---- 进入临界区 ----
    try:
        yield
    finally:
        # Release:Lua 原子 check-and-delete。
        # token mismatch(锁过期被别的进程拿了)时不动对方锁。
        try:
            released = _try_release(c, key, token)
            if not released:
                # 不是自己的锁了(TTL 过短被抢 / 进程卡住超时)
                logger.warning(
                    "acquire_lock: release '%s' found token mismatch — "
                    "lock TTL too short or work overran ttl; "
                    "current owner kept the lock",
                    key,
                )
        except Exception as e:  # noqa: BLE001
            # Release 失败不阻断 — TTL 兜底过期
            logger.warning(
                "acquire_lock: release '%s' failed (%s); "
                "TTL will expire the lock automatically",
                key, e,
            )


__all__ = [
    "acquire_lock",
    "LockTimeoutError",
    "LockAcquireFailed",
    "get_default_client",
    "reset_default_client",
]