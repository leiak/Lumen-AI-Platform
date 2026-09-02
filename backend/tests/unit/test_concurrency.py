"""Phase 0 Unit 3 (2026-09-02):全局并发 semaphore 测试。

覆盖:
- sync acquire 正常路径
- sync acquire 超时 → ConcurrencyTimeoutError
- sync semaphore 复用(同 name 拿到同一 limit)
- env override(LUMEN_CONCURRENCY_<NAME>)
- async acquire 正常路径
- async acquire 超时 → ConcurrencyTimeoutError
- get_all_limits 返回所有已知桶
- reset_all 清除缓存
"""
import asyncio
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

import pytest


@pytest.fixture(autouse=True)
def _reset_semaphores():
    """每个 test 后清空 semaphore 缓存,避免 env var 改动不生效。"""
    from lumen_services import concurrency
    yield
    concurrency.reset_all()


# ===== sync semaphore =====


def test_sync_acquire_normal_path():
    """happy path:能拿到 semaphore,with block 内运行,退出释放。"""
    from lumen_services.concurrency import acquire_sync

    with acquire_sync("ollama_embed", timeout=1):
        # 占着 semaphore 时,内部运行 user code
        pass  # ok
    # 退出后释放,下次 acquire 立即成功
    with acquire_sync("ollama_embed", timeout=0.1):
        pass


def test_sync_acquire_timeout_raises():
    """占满所有 semaphore 后再 acquire 应超时。"""
    from lumen_services.concurrency import acquire_sync, ConcurrencyTimeoutError

    # 把 ollama_embed 临时改成 limit=1(走 env var)
    os.environ["LUMEN_CONCURRENCY_OLLAMA_EMBED"] = "1"

    # 第一个 acquire 拿到后 hold 住
    holder_acquired = threading.Event()
    holder_release = threading.Event()
    holder_error: list[Exception] = []

    def holder():
        try:
            with acquire_sync("ollama_embed", timeout=1):
                holder_acquired.set()
                holder_release.wait(timeout=2)
        except Exception as e:
            holder_error.append(e)

    t = threading.Thread(target=holder, daemon=True)
    t.start()
    assert holder_acquired.wait(timeout=2), "holder 线程未拿到 semaphore"

    # 此时 semaphore 已满,第二个 acquire 应超时
    start = time.time()
    with pytest.raises(ConcurrencyTimeoutError) as exc_info:
        with acquire_sync("ollama_embed", timeout=0.3):
            pass
    elapsed = time.time() - start
    assert 0.25 <= elapsed < 1.0, f"超时时间不符预期: {elapsed:.2f}s"
    assert "ollama_embed" in str(exc_info.value)
    assert "busy" in str(exc_info.value)

    # 释放 holder
    holder_release.set()
    t.join(timeout=2)
    assert not holder_error, f"holder 异常: {holder_error}"

    del os.environ["LUMEN_CONCURRENCY_OLLAMA_EMBED"]


def test_sync_semaphore_reuses_same_limit_per_name():
    """同 name 的 semaphore 复用(进程内单例)。"""
    from lumen_services.concurrency import _get_sync_semaphore

    s1 = _get_sync_semaphore("ollama_embed")
    s2 = _get_sync_semaphore("ollama_embed")
    assert s1 is s2

    s3 = _get_sync_semaphore("ollama_chat")
    assert s3 is not s1


def test_sync_env_override():
    """LUMEN_CONCURRENCY_<NAME> env 覆盖 DEFAULT_LIMITS。"""
    from lumen_services.concurrency import _get_sync_semaphore, _resolve_limit

    os.environ["LUMEN_CONCURRENCY_OLLAMA_EMBED"] = "3"
    assert _resolve_limit("ollama_embed") == 3

    sem = _get_sync_semaphore("ollama_embed")
    # threading.Semaphore 没暴露 _value,但能 acquire 3 次后第 4 次阻塞可验证。
    # 用 .acquire(blocking=False) 探测槽位数。
    acquired_count = 0
    while sem.acquire(blocking=False):
        acquired_count += 1
    assert acquired_count == 3, f"env override 没生效,期望 3 槽位,得 {acquired_count}"
    # 释放回去
    for _ in range(acquired_count):
        sem.release()

    del os.environ["LUMEN_CONCURRENCY_OLLAMA_EMBED"]


def test_sync_unknown_name_falls_back_to_10():
    """未列在 DEFAULT_LIMITS 的 name 走兜底 10(防止 typo 静默 0 上限)。"""
    from lumen_services.concurrency import _resolve_limit, _get_sync_semaphore

    sem = _get_sync_semaphore("my_custom_resource")
    acquired = 0
    while sem.acquire(blocking=False):
        acquired += 1
    assert acquired == 10, f"未知 name 兜底应为 10,得 {acquired}"
    for _ in range(acquired):
        sem.release()


# ===== async semaphore =====


def test_async_acquire_normal_path():
    """happy path async:能拿到 + 退出释放。"""
    from lumen_services.concurrency import acquire_async

    async def run():
        async with acquire_async("ollama_chat", timeout=1):
            await asyncio.sleep(0.01)
        return "ok"

    assert asyncio.run(run()) == "ok"


def test_async_acquire_timeout_raises():
    """async acquire 超时 → ConcurrencyTimeoutError。"""
    from lumen_services.concurrency import acquire_async, ConcurrencyTimeoutError

    os.environ["LUMEN_CONCURRENCY_OLLAMA_CHAT"] = "1"

    async def run():
        holder_done = asyncio.Event()
        holder_task = asyncio.create_task(_async_holder(holder_done))
        await asyncio.wait_for(holder_done.wait(), timeout=2)

        start = time.time()
        with pytest.raises(ConcurrencyTimeoutError) as exc_info:
            async with acquire_async("ollama_chat", timeout=0.3):
                pass
        elapsed = time.time() - start
        assert 0.25 <= elapsed < 1.0, f"async 超时时间不符: {elapsed:.2f}s"
        assert "ollama_chat" in str(exc_info.value)

        holder_task.cancel()
        try:
            await holder_task
        except asyncio.CancelledError:
            pass

    asyncio.run(run())
    del os.environ["LUMEN_CONCURRENCY_OLLAMA_CHAT"]


async def _async_holder(done_event: asyncio.Event):
    """test_async_acquire_timeout_raises 的辅助:占着 semaphore 等 cancel。"""
    from lumen_services.concurrency import acquire_async
    async with acquire_async("ollama_chat", timeout=1):
        done_event.set()
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            raise


# ===== 管理接口 =====


def test_get_all_limits():
    """返回所有 DEFAULT_LIMITS 当前上限(读 env 后)。"""
    from lumen_services.concurrency import get_all_limits

    limits = get_all_limits()
    assert "ollama_embed" in limits
    assert "ollama_chat" in limits
    assert "multimodal_embed" in limits
    assert "s3_put" in limits
    assert limits["multimodal_embed"] == 2  # 验证默认值的常量


def test_reset_all_clears_cache():
    """reset_all 清掉缓存,下次 _get_* 重新读 env。"""
    from lumen_services.concurrency import (
        _get_sync_semaphore,
        _sync_semaphores,
        reset_all,
    )

    s_before = _get_sync_semaphore("ollama_embed")
    assert s_before in _sync_semaphores.values()

    reset_all()
    assert _sync_semaphores == {}

    s_after = _get_sync_semaphore("ollama_embed")
    # reset 后是不同实例(进程内单例被重建)
    assert s_after is not s_before