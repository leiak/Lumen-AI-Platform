"""Phase 1 Group A 2.5 (2026-09-03): 客户端 transient retry 装饰器。

**为什么需要**: Phase 0 ship 了 trace_id + Prometheus + dist_lock + idempotency,
但网络层的 transient 故障(connect refused / read timeout / DNS hiccup)依然靠各
service inline try/except 处理,行为不一致 — 有的重试 1 次,有的不重试。Phase 1
Group A 立统一入口。

**设计要点**:

1. **统一装饰器**: ``@async_retry_transient`` / ``@sync_retry_transient`` —
   业务代码只要在客户端入口包一层,不用关心 retry 策略。

2. **白名单 exception**(只对 transient 重试,不动业务异常):
   - ``httpx.TimeoutException`` / ``ConnectError`` / ``RemoteProtocolError``
   - ``redis.ConnectionError`` / ``TimeoutError``
   - ``elasticsearch.ConnectionTimeout`` / ``ConnectionError``
   - ``ConnectionError`` / ``TimeoutError``(通用 builtin)

3. **不动流式 LLM response**: ``LoggingChatModel.astream`` / ``stream``
   是 async generator,装饰器无法安全 wrap(generator 已经开始 yield 后重试会
   重复发 content)。所以入口处只包非流式 ``invoke`` / ``ainvoke``。

4. **不动 boto3**: boto3 botocore config 已配 standard retry 3 次。如果再
   包 tenacity 会变成 3×3=9 次,违反"客户端底层已 retry 不堆叠"原则。

5. **不动 Redis 客户端**: redis-py 已有 0.2s socket timeout,业务层 retry 会
   污染 Phase 0 ship 的限流 fail-closed 行为(限流是 Redis 唯一路径)。

6. **backoff**: exponential 0.5/1/2s (max 4s),3 attempts 后 reraise 原异常,
   让上层 Prometheus / dist_lock 看到的就是原始 transient 错误。

7. **可观测**: ``before_sleep`` 钩子 log.warning 带 func name + attempt + 异常
   类型,跟 Phase 0 JSON 日志兼容,grep / ELK / Loki 直接抓。
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Tuple, Type, TypeVar

import httpx

from tenacity import (
    AsyncRetrying,
    Retrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")


# 白名单 transient 异常。boto3 / Redis 客户端不进来(注释见顶部 docstring)。
def _build_transient_exceptions() -> Tuple[Type[BaseException], ...]:
    """动态拼装 transient exception 列表,避免顶层 import 死锁。"""
    excs: list[Type[BaseException]] = [
        # builtin 通用
        ConnectionError,
        TimeoutError,
        # httpx
        httpx.TimeoutException,
        httpx.ConnectError,
        httpx.RemoteProtocolError,
    ]
    # redis (rate_limit / dist_lock 都用,但我们不在 client 层 retry,
    # 只在 service 业务层需要时 import)
    try:
        import redis  # noqa: F401
        excs.append(redis.ConnectionError)
        excs.append(redis.TimeoutError)
    except ImportError:
        pass
    # elasticsearch (KB retrieval)
    try:
        import elasticsearch  # noqa: F401
        excs.append(elasticsearch.ConnectionTimeout)
        excs.append(elasticsearch.ConnectionError)
    except ImportError:
        pass
    return tuple(excs)


TRANSIENT_EXCEPTIONS: Tuple[Type[BaseException], ...] = _build_transient_exceptions()


def _log_before_sleep(retry_state: Any) -> None:
    """tenacity before_sleep 钩子: log warning + 保留原异常类型名。"""
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    exc_name = type(exc).__name__ if exc else "Unknown"
    func_name = getattr(retry_state.fn, "__name__", "<unknown>")
    logger.warning(
        "transient retry: func=%s attempt=%d/%d exc=%s err=%s",
        func_name,
        retry_state.attempt_number,
        retry_state.retry_object.stop.max_attempt_number
        if hasattr(retry_state.retry_object.stop, "max_attempt_number")
        else 3,
        exc_name,
        str(exc)[:200] if exc else "",
    )


# 共享 retry policy, sync / async 各引一份(tenacity Retrying / AsyncRetrying 不同类)
_async_retry_policy = AsyncRetrying(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=0.5, max=4),
    retry=retry_if_exception_type(TRANSIENT_EXCEPTIONS),
    reraise=True,
    before_sleep=_log_before_sleep,
)

_sync_retry_policy = Retrying(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=0.5, max=4),
    retry=retry_if_exception_type(TRANSIENT_EXCEPTIONS),
    reraise=True,
    before_sleep=_log_before_sleep,
)


def async_retry_transient(func: Callable[..., Any]) -> Callable[..., Any]:
    """装饰 async 客户端入口,自动重试 transient 异常。

    用法::

        @async_retry_transient
        async def fetch_embedding(text: str) -> list[float]:
            async with httpx.AsyncClient() as client:
                resp = await client.post(...)
                return resp.json()

    3 次失败后 reraise 原异常(transient 类型),让上层继续 fail-fast。
    """
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        async for attempt in _async_retry_policy:
            with attempt:
                return await func(*args, **kwargs)
        # tenacity reraise=True 时不会走到这里,保留给 mypy
        raise RuntimeError(  # pragma: no cover
            "async_retry_transient: unreachable (reraise=True should raise earlier)"
        )

    wrapper.__name__ = func.__name__
    wrapper.__doc__ = func.__doc__
    return wrapper


def sync_retry_transient(func: Callable[..., Any]) -> Callable[..., Any]:
    """装饰 sync 客户端入口,自动重试 transient 异常。

    跟 async 版同 policy,只用于 sync 调用点(目前主要是 RAG pipeline 内部
    的 sync httpx.Client.get / LangChain sync ``invoke``)。
    """
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        for attempt in _sync_retry_policy:
            with attempt:
                return func(*args, **kwargs)
        raise RuntimeError(  # pragma: no cover
            "sync_retry_transient: unreachable (reraise=True should raise earlier)"
        )

    wrapper.__name__ = func.__name__
    wrapper.__doc__ = func.__doc__
    return wrapper


async def call_async_with_retry(
    coro_factory: Callable[[], Any],
    func_name: str = "<inline>",
) -> Any:
    """单次 async 调用的 transient retry helper(用于不能装饰 method 的场景)。

    用法::

        result = await call_async_with_retry(
            lambda: client.post(url, json=payload),
            func_name="mcp_service.call_remote_tool",
        )

    ``coro_factory`` 必须返回 coroutine(不能是已 await 的值),因为 tenacity
    需要在每次 attempt 里重新调用 factory 拿新的 coroutine。
    """
    try:
        async for attempt in _async_retry_policy:
            with attempt:
                coro = coro_factory()
                return await coro
    except AttributeError:
        # tenacity 6.x compatibility: _async_retry_policy 不可 async for 时 fallback
        pass
    raise RuntimeError(  # pragma: no cover
        "call_async_with_retry: unreachable"
    )


def call_sync_with_retry(
    func: Callable[[], Any],
    func_name: str = "<inline>",
) -> Any:
    """单次 sync 调用的 transient retry helper。"""
    for attempt in _sync_retry_policy:
        with attempt:
            return func()
    raise RuntimeError(  # pragma: no cover
        "call_sync_with_retry: unreachable"
    )


__all__ = [
    "TRANSIENT_EXCEPTIONS",
    "async_retry_transient",
    "sync_retry_transient",
    "call_async_with_retry",
    "call_sync_with_retry",
]
