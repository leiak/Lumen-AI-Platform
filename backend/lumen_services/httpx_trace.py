"""Phase 0 Unit 5 4.2 (2026-09-02):httpx event_hooks 注入 trace_id。

**做什么**:任何 httpx.Client / httpx.AsyncClient 在发请求时,自动从
lumen_core.tracing.get_trace_id() 拿当前 trace_id,塞进 ``X-Trace-Id``
header。下游服务(Ollama / OpenAI / 我们自己的 API)就能 join 同一 trace。

**用法**:
    from lumen_services.httpx_trace import (
        traced_event_hooks, traced_async_event_hooks,
    )

    # 同步 client:
    client = httpx.Client(event_hooks=traced_event_hooks())

    # 异步 client:
    aclient = httpx.AsyncClient(event_hooks=traced_async_event_hooks())

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
from typing import Callable

import httpx

from lumen_core.tracing import get_trace_id

logger = logging.getLogger(__name__)


HEADER_NAME = "X-Trace-Id"


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

    用法:
        httpx.Client(event_hooks=traced_event_hooks())
    """
    return {"request": [_inject_trace_id_header_sync]}


def traced_async_event_hooks() -> dict[str, list[Callable]]:
    """返 async hooks — 配 httpx.AsyncClient 用。

    用法:
        httpx.AsyncClient(event_hooks=traced_async_event_hooks())
    """
    return {"request": [_inject_trace_id_header_async]}


__all__ = [
    "traced_event_hooks",
    "traced_async_event_hooks",
    "_inject_trace_id_header_sync",
    "_inject_trace_id_header_async",
    "HEADER_NAME",
]