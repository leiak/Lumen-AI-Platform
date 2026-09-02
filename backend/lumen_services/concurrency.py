"""Lumen AI Platform — 全局并发信号量池(Phase 0 Unit 3, 2026-09-02)。

**为什么**:Phase 0 之前,embedding / LLM / storage 全部客户端直连,无
任何并发上限。embedding 风暴可让 jina-clip-v2(3GB)OOM;workflow LLM
节点长任务挤占 chat;S3 多线程 PUT 触发连接池爆。

**设计**:
- 按"资源类型"分桶,每个桶独立 semaphore(`ollama_embed` / `ollama_chat` /
  `multimodal_embed` / `openai_api` / `es_query` / `s3_put` ...)。
- 同步用 `threading.Semaphore`(本项目 FastAPI 90% endpoint 是 `def`
  而非 `async def`,走 sync httpx / sync SQLAlchemy)。
- 异步用 `asyncio.Semaphore`(给 chat streaming / workflow async node)。
- 上限由代码 DEFAULT_LIMITS 决定,可被 `LUMEN_CONCURRENCY_<NAME>`
  环境变量覆盖(如 `LUMEN_CONCURRENCY_OLLAMA_CHAT=8`)。
- 超时抛 `ConcurrencyTimeoutError`,调用方决定是 429 还是 503。

**不是**:不是熔断器(roadmap §3 2.3 单独的 circuit_breaker.py);
不是限流(rate_limit.py 已经做 IP/user 维度)。本模块只限制瞬时并发
请求数,让上游资源不被击穿。

**不是全局**:`threading.Semaphore` 是进程内。多 worker 部署下每个
worker 独立持有 N 个槽位,全局上限 = N × DEFAULT_LIMITS[name]。
足够本项目 dev / Phase 1 gunicorn -w 4 部署;Phase 2 需要精确全局
控制再上 Redis-based 限流(roadmap §3 2.6 LLM rate limiter)。
"""
from __future__ import annotations

import asyncio
import os
import threading
from contextlib import asynccontextmanager, contextmanager
from typing import Iterator, Optional


# 默认上限(单 worker 视角)。多 worker 部署实际总并发 = limit × workers。
# Phase 1 切 gunicorn 时按实际 worker 数微调。
DEFAULT_LIMITS: dict[str, int] = {
    # Ollama 单 CPU 推理,embed 768 dim 单 batch < 1s;
    # 8 并发已吃满 1 核 CPU 的 LLM serving 线程。
    "ollama_embed": 8,
    # qwen2.5:7b ~6GB CPU 推理,4 并发已挤兑,降速换吞吐。
    "ollama_chat": 4,
    # OpenAI / Azure 等云端按官方 tier 限速(60k TPM / 3.5k RPM 量级),
    # 给 20 留 3 倍 headroom 给重试。
    "openai_api": 20,
    # M38.4 multimodal: jina-clip-v2 3GB / clip-B/32 600MB,2 并发是稳态上限。
    "multimodal_embed": 2,
    # ES 单节点查询桶,32 并发查询吃满 IO 不拖挂。
    "es_query": 32,
    # boto3 内部 thread-safe,16 PUT 并发约 80MB/s,网络瓶颈。
    "s3_put": 16,
    # MinIO 同 s3_put(共用 S3Backend,实际同一组 semaphore)。
    "minio_put": 16,
}


class ConcurrencyTimeoutError(Exception):
    """Semaphore acquire 超时 — 上游资源挤兑。"""
    pass


# ---- 同步 (threading.Semaphore) ----

_sync_lock = threading.Lock()
_sync_semaphores: dict[str, threading.Semaphore] = {}


def _resolve_limit(name: str) -> int:
    """从 env 读 LUMEN_CONCURRENCY_<NAME>,fallback DEFAULT_LIMITS,再 fallback 10。"""
    env_key = f"LUMEN_CONCURRENCY_{name.upper()}"
    val = os.getenv(env_key)
    if val:
        try:
            parsed = int(val)
            if parsed > 0:
                return parsed
        except ValueError:
            pass
    return DEFAULT_LIMITS.get(name, 10)


def _get_sync_semaphore(name: str) -> threading.Semaphore:
    """懒加载 sync semaphore,首次访问时创建(线程安全)。"""
    if name not in _sync_semaphores:
        with _sync_lock:
            if name not in _sync_semaphores:
                _sync_semaphores[name] = threading.Semaphore(_resolve_limit(name))
    return _sync_semaphores[name]


@contextmanager
def acquire_sync(name: str, *, timeout: Optional[float] = None) -> Iterator[None]:
    """同步 semaphore acquire,timeout 秒内拿不到抛 ConcurrencyTimeoutError。

    Usage:
        with acquire_sync("ollama_embed", timeout=5):
            embedding = ollama.embed_query(text)

    Args:
        name: 资源桶名(必须出现在 DEFAULT_LIMITS 或自定义)
        timeout: 秒;None = 阻塞至拿到为止(慎用,可能永久 hang)。

    Raises:
        ConcurrencyTimeoutError: timeout 秒内未拿到锁
    """
    sem = _get_sync_semaphore(name)
    acquired = sem.acquire(timeout=timeout)
    if not acquired:
        raise ConcurrencyTimeoutError(
            f"sync semaphore '{name}' busy (>{timeout}s); "
            f"上游资源挤兑,请求被并发限流拒绝"
        )
    try:
        yield
    finally:
        sem.release()


# ---- 异步 (asyncio.Semaphore) ----

_async_semaphores: dict[str, asyncio.Semaphore] = {}
_async_init_lock: Optional[asyncio.Lock] = None


def _get_async_init_lock() -> asyncio.Lock:
    """asyncio.Lock 必须在 event loop 内创建,懒加载。"""
    global _async_init_lock
    if _async_init_lock is None:
        _async_init_lock = asyncio.Lock()
    return _async_init_lock


async def _get_async_semaphore(name: str) -> asyncio.Semaphore:
    """懒加载 async semaphore,首次访问时创建。"""
    if name not in _async_semaphores:
        async with _get_async_init_lock():
            if name not in _async_semaphores:
                _async_semaphores[name] = asyncio.Semaphore(_resolve_limit(name))
    return _async_semaphores[name]


@asynccontextmanager
async def acquire_async(name: str, *, timeout: Optional[float] = None):
    """异步 semaphore acquire,timeout 秒内拿不到抛 ConcurrencyTimeoutError。

    Usage:
        async with acquire_async("ollama_chat", timeout=30):
            response = await chat_ollama(messages)

    Args:
        name: 资源桶名
        timeout: 秒;None = 阻塞至拿到为止。

    Raises:
        ConcurrencyTimeoutError: timeout 秒内未拿到锁
    """
    sem = await _get_async_semaphore(name)
    if timeout is None:
        await sem.acquire()
        acquired = True
    else:
        try:
            await asyncio.wait_for(sem.acquire(), timeout=timeout)
            acquired = True
        except asyncio.TimeoutError:
            acquired = False

    if not acquired:
        raise ConcurrencyTimeoutError(
            f"async semaphore '{name}' busy (>{timeout}s); "
            f"上游资源挤兑,请求被并发限流拒绝"
        )
    try:
        yield
    finally:
        sem.release()


# ---- 测试 / 管理 ----


def reset_all() -> None:
    """清空所有 semaphore(单测 teardown 用)。"""

    def _noop(*args, **kwargs):
        pass

    with _sync_lock:
        # threading.Semaphore 没有显式 close,GC 会回收;
        # 重置 dict 让下次 _get_* 重新读 env(测试改 env 后调一次)。
        _sync_semaphores.clear()
    _async_semaphores.clear()


def get_all_limits() -> dict[str, int]:
    """返回所有已知资源桶的当前上限(监控 / debug 用)。"""
    result = {}
    for name in DEFAULT_LIMITS:
        result[name] = _resolve_limit(name)
    return result


__all__ = [
    "ConcurrencyTimeoutError",
    "acquire_sync",
    "acquire_async",
    "reset_all",
    "get_all_limits",
    "DEFAULT_LIMITS",
]