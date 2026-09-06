"""Phase 0 Unit 5 4.2 (2026-09-02):httpx event_hooks 注入 trace_id。

.. deprecated::
    Phase 1 Group B 4.4 Day 5 (2026-09-06):本模块 **deprecated**。
    现在用 ``opentelemetry-instrumentation-httpx`` 的
    ``HTTPXClientInstrumentor`` 自动注入 W3C ``traceparent`` header
    (见 ``lumen_core.otel._instrument_httpx``)。OTel SDK 的自动
    instrumentation 是 W3C Trace Context 规范,跨服务 / 跨语言兼容,
    比本模块自研的 ``X-Trace-Id`` header 更标准。

    本模块保留 + 仍工作,仅 import 时发 ``DeprecationWarning``:
    - 调用方代码 0 改动 —— 函数签名 / 行为不变
    - 但新代码请直接用 ``httpx.Client()`` 不传 ``event_hooks``,
      OTel instrumentor 自动处理

**做什么**:任何 httpx.Client / httpx.AsyncClient 在发请求时,自动从
lumen_core.tracing.get_trace_id() 拿当前 trace_id,塞进 ``X-Trace-Id``
header。下游服务(Ollama / OpenAI / 我们自己的 API)就能 join 同一 trace。

**用法(legacy,不推荐新代码用)**:
    from lumen_services.httpx_trace import (
        traced_event_hooks, traced_async_event_hooks,
    )

    # 同步 client:
    client = httpx.Client(event_hooks=traced_event_hooks())

    # 异步 client:
    aclient = httpx.AsyncClient(event_hooks=traced_async_event_hooks())

**新代码推荐**:什么都不用做 —— ``setup_tracing()`` 已自动 instrument
httpx,所有 httpx.Client / AsyncClient 实例自动写 ``traceparent`` header。

**为什么独立模块而不是 monkey-patch httpx**:
- monkey-patch 全局,影响所有 httpx 调用(包括第三方库),改不动时
  (httpx 内部版本变化) blast radius 大
- 显式 event_hooks 让调用方明确"我接受 trace_id 注入"opt-in
- 测试可以关掉 event_hooks,避免 mock 污染

**为什么 sync / async 分两套 hook**:
httpx 0.27 在 sync Client 调 hook(request) 直接调(无 await),
在 AsyncClient 调 await hook(request) 强制 await。一个 sync 函数
被 AsyncClient await 会 raise TypeError('NoneType has no __await__');
反之 async 函数被 sync Client 调会返 coroutine 永不 await,header
不写。
所以 sync / async 必须配对调用。

**踩坑**:
- httpx 0.27+ 的 event_hooks API 稳定(event_hooks={"request": [fn]})
- 无 trace_id 时不挂 header(避免空字符串)
"""
from __future__ import annotations

import logging
import warnings
from typing import Callable

import httpx

from lumen_core.tracing import get_trace_id

logger = logging.getLogger(__name__)


HEADER_NAME = "X-Trace-Id"


# Phase 1 Group B 4.4 Day 5 (2026-09-06): DeprecationWarning 守门。
# Module-level 一次性 warn:不让每次 import 都重复(只在第一次发出),
# 避免 pytest -W error 把所有调用点炸成 fail。
_warned_deprecation = False


def _emit_deprecation_warning() -> None:
    """发一次 DeprecationWarning,后续静默(避免 pytest noise)。"""
    global _warned_deprecation
    if not _warned_deprecation:
        warnings.warn(
            "lumen_services.httpx_trace is deprecated as of Phase 1 4.4 Day 5 "
            "(2026-09-06); use OTel HTTPXClientInstrumentor for W3C traceparent "
            "injection (auto-enabled by lumen_core.otel.setup_tracing).",
            DeprecationWarning,
            stacklevel=3,  # caller -> public fn -> this helper
        )
        _warned_deprecation = True


# ---- sync hook (httpx.Client) ----


def _inject_trace_id_header_sync(request: httpx.Request) -> None:
    """sync event_hook:塞 trace_id 到 request header。"""
    tid = get_trace_id()
    if tid and HEADER_NAME not in request.headers:
        request.headers[HEADER_NAME] = tid


# ---- async hook (httpx.AsyncClient) ----


async def _inject_trace_id_header_async(request: httpx.Request) -> None:
    """async event_hook:httpx.AsyncClient 走 ``await hook(request)``,
    所以这里必须是 coroutine function。
    """
    tid = get_trace_id()
    if tid and HEADER_NAME not in request.headers:
        request.headers[HEADER_NAME] = tid


def traced_event_hooks() -> dict[str, list[Callable]]:
    """返 sync hooks — 配 httpx.Client 用。

    .. deprecated::
        Use OTel ``HTTPXClientInstrumentor`` (auto via ``setup_tracing()``)
        for W3C ``traceparent`` injection instead。

    用法:
        httpx.Client(event_hooks=traced_event_hooks())
    """
    _emit_deprecation_warning()
    return {"request": [_inject_trace_id_header_sync]}


def traced_async_event_hooks() -> dict[str, list[Callable]]:
    """返 async hooks — 配 httpx.AsyncClient 用。

    .. deprecated::
        Use OTel ``HTTPXClientInstrumentor`` (auto via ``setup_tracing()``)
        for W3C ``traceparent`` injection instead。

    用法:
        httpx.AsyncClient(event_hooks=traced_async_event_hooks())
    """
    _emit_deprecation_warning()
    return {"request": [_inject_trace_id_header_async]}


__all__ = [
    "traced_event_hooks",
    "traced_async_event_hooks",
    "_inject_trace_id_header_sync",
    "_inject_trace_id_header_async",
    "HEADER_NAME",
]