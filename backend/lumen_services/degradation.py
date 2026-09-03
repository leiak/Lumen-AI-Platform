"""Phase 1 Group A 2.4 (2026-09-03): @degradable 优雅降级装饰器。

**为什么需要**: Phase 1 2.3 ship 的 CircuitBreaker 在故障期间抛
``CircuitOpenError`` 让业务层 fast-fail,但 KB 检索 / ES 查询 / MCP 远程
调用等场景不应该让用户看到 503,应该走 fallback 返回部分数据(比如空列表
+ ``_degraded=True`` metadata)而不是错误。

**设计要点**:

1. **统一装饰器** ``@degradable(breaker_name=..., fallback=..., exceptions=...)``:
   业务代码只要在客户端入口包一层,breaker open 或业务异常时自动走 fallback。

2. **breaker 协同**: 指定 ``breaker_name`` 时,装饰器先把函数调用包进
   ``CircuitBreaker.call_async`` / ``call_sync``;失败抛 ``CircuitOpenError``
   时也走 fallback。breaker 跟 fallback 是正交的:breaker 决定"要不要走函数
   体",fallback 决定"函数体抛错后返什么"。

3. **fallback 形式**:
   - 可调用 ``callable(*args, **kwargs)``: 装饰器调它,传同 args。
   - 字面值 ``fallback="default_value"``: 直接返回。
   - ``None``: 不走 fallback,原异常向上抛(默认行为,业务自己处理)。

4. **降级 metadata**: 当 fallback 返回 dict 时,装饰器 mutate 注入
   ``_degraded=True`` 和 ``_degraded_reason=str(e)[:200]``。前端可识别
   这个 flag 显示「部分可用」徽章,跟 503 区分开。

5. **sync + async 都支持**: 装饰器检测 ``asyncio.iscoroutinefunction``
   自动选 wrapper 类型,业务代码无感。

6. **不打乱 retry 层**: ``@degradable`` 装饰 outer func,跟 2.5
   ``@async_retry_transient`` 装饰 inner func 正交 — 一个处理"故障期
   是否调函数体",一个处理"函数体内 transient 重试"。
"""
from __future__ import annotations

import asyncio
import functools
import inspect
import logging
from typing import Any, Callable, Optional, Tuple, Type, Union

logger = logging.getLogger(__name__)


def _inject_degraded_metadata(
    result: Any, exc: Optional[BaseException]
) -> Any:
    """fallback 返回 dict 时注入 _degraded=True + _degraded_reason。

    非 dict 返回值保持不变(不污染 caller 期望)。
    """
    if isinstance(result, dict) and exc is not None:
        result.setdefault("_degraded", True)
        result.setdefault("_degraded_reason", str(exc)[:200])
    return result


def _build_wrapper(
    func: Callable[..., Any],
    *,
    breaker_name: Optional[str],
    fallback: Optional[Union[Callable[..., Any], Any]],
    log_warning: bool,
    exceptions: Tuple[Type[BaseException], ...],
    on_degraded_callback: Optional[Callable[[BaseException], None]],
) -> Callable[..., Any]:
    """根据 func 是 sync / async 选 wrapper。"""

    # 延迟 import 避免循环(circuit_breaker 不依赖 degradation)
    from lumen_services.circuit_breaker import (
        CircuitBreakerRegistry,
        CircuitOpenError,
    )

    caught_exceptions: Tuple[Type[BaseException], ...] = (CircuitOpenError, *exceptions)

    def _maybe_log(exc: BaseException, func_name: str) -> None:
        if log_warning:
            logger.warning(
                "degraded: func=%s exc=%s err=%s",
                func_name, type(exc).__name__, str(exc)[:200],
            )

    def _maybe_callback(exc: BaseException) -> None:
        if on_degraded_callback is None:
            return
        try:
            on_degraded_callback(exc)
        except Exception:  # noqa: BLE001
            logger.exception("degradable on_degraded_callback raised; ignored")

    def _resolve_fallback(*args: Any, **kwargs: Any) -> Any:
        if fallback is None:
            raise  # 让上层处理 — caller 没提供 fallback 就当正常异常
        if callable(fallback):
            return fallback(*args, **kwargs)
        return fallback

    if asyncio.iscoroutinefunction(func):

        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                if breaker_name:
                    breaker = CircuitBreakerRegistry.get(breaker_name)

                    async def _runner() -> Any:
                        return await func(*args, **kwargs)

                    return await breaker.call_async(_runner)
                return await func(*args, **kwargs)
            except caught_exceptions as e:
                _maybe_log(e, func.__name__)
                _maybe_callback(e)
                try:
                    result = _resolve_fallback(*args, **kwargs)
                except Exception:
                    raise
                return _inject_degraded_metadata(result, e)

        return async_wrapper

    @functools.wraps(func)
    def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            if breaker_name:
                breaker = CircuitBreakerRegistry.get(breaker_name)

                def _runner() -> Any:
                    return func(*args, **kwargs)

                return breaker.call_sync(_runner)
            return func(*args, **kwargs)
        except caught_exceptions as e:
            _maybe_log(e, func.__name__)
            _maybe_callback(e)
            try:
                result = _resolve_fallback(*args, **kwargs)
            except Exception:
                raise
            return _inject_degraded_metadata(result, e)

    return sync_wrapper


def degradable(
    *,
    breaker_name: Optional[str] = None,
    fallback: Optional[Union[Callable[..., Any], Any]] = None,
    log_warning: bool = True,
    exceptions: Tuple[Type[BaseException], ...] = (Exception,),
    on_degraded_callback: Optional[Callable[[BaseException], None]] = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """装饰客户端入口,在故障期走 fallback 而不是抛 503。

    用法::

        @degradable(breaker_name="ollama", fallback=lambda *a, **kw: [])
        async def search_kb(query: str) -> list:
            ...

    Args:
        breaker_name: 关联的熔断器名(可选)。None 时不接 breaker。
        fallback: 失败时的替代返回:
            * callable ``(*args, **kwargs)``: 装饰器调它。
            * 字面值: 直接返回。
            * None: 不走 fallback,原异常向上抛。
        log_warning: 是否写 warning log。
        exceptions: 哪些异常触发降级。默认 ``(Exception,)`` 兜底所有;
            业务可收紧到 ``(httpx.HTTPError, ValueError)`` 等。
        on_degraded_callback: 降级触发时的回调(可选,用于 metric / 告警
            注入)。内部 try/except 包死,失败不影响降级主流程。

    Returns:
        装饰后的函数,签名与原函数一致(sync / async 自动判断)。
    """
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        return _build_wrapper(
            func,
            breaker_name=breaker_name,
            fallback=fallback,
            log_warning=log_warning,
            exceptions=exceptions,
            on_degraded_callback=on_degraded_callback,
        )

    return decorator


__all__ = ["degradable"]
