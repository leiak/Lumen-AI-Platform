"""Phase 0 Unit 5 4.2 (2026-09-02):httpx event_hooks trace_id 注入测试。

覆盖:
- traced_event_hooks() 返 {"request": [fn]} dict
- ctx 有 trace_id → request 出去时带 X-Trace-Id
- ctx 无 trace_id → 不挂 header(不污染)
- 调用方显式设了 header → 不覆盖(优先级:调用方 > trace_id)
- 同步 / 异步 httpx client 都生效
- 跨 ctx 切换:不同 ctx 的 trace_id 走不同 header
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

import httpx
import pytest

from lumen_core import tracing
from lumen_services.httpx_trace import (
    HEADER_NAME,
    _inject_trace_id_header_async,
    _inject_trace_id_header_sync,
    traced_async_event_hooks,
    traced_event_hooks,
)


@pytest.fixture(autouse=True)
def _reset_trace():
    """每个 test 后清 trace_id contextvar。"""
    tracing.reset_for_test()


# ===== _inject_trace_id_header 直接测 =====


def test_inject_adds_header_when_trace_id_present():
    """ctx 有 trace_id → request 加 X-Trace-Id header。"""
    tracing.set_trace_id("trace-abc")
    request = httpx.Request("GET", "http://example.com/api")
    _inject_trace_id_header_sync(request)
    assert request.headers[HEADER_NAME] == "trace-abc"


def test_inject_skips_when_no_trace_id():
    """ctx 无 trace_id → 不挂 header(不污染)。"""
    request = httpx.Request("GET", "http://example.com/api")
    _inject_trace_id_header_sync(request)
    assert HEADER_NAME not in request.headers


def test_inject_does_not_override_explicit_header():
    """调用方已设 X-Trace-Id → middleware 不覆盖。"""
    tracing.set_trace_id("auto-trace")
    request = httpx.Request(
        "GET",
        "http://example.com/api",
        headers={HEADER_NAME: "explicit-trace"},
    )
    _inject_trace_id_header_sync(request)
    # 显式值不被自动注入覆盖
    assert request.headers[HEADER_NAME] == "explicit-trace"


# ===== traced_event_hooks API =====


def test_traced_event_hooks_returns_dict_with_request_hook():
    """traced_event_hooks() 返 {"request": [fn]}(sync 版本)。"""
    hooks = traced_event_hooks()
    assert "request" in hooks
    assert len(hooks["request"]) == 1
    assert callable(hooks["request"][0])


def test_traced_async_event_hooks_returns_dict_with_request_hook():
    """traced_async_event_hooks() 返 {"request": [coroutine_fn]}。"""
    import inspect
    hooks = traced_async_event_hooks()
    assert "request" in hooks
    assert len(hooks["request"]) == 1
    # async hook 必须是 coroutine function
    assert inspect.iscoroutinefunction(hooks["request"][0])


# ===== 端到端:同步 httpx.Client =====


def test_sync_httpx_client_injects_trace_id():
    """httpx.Client 用 traced_event_hooks → 发出去的 request 带 trace_id。"""
    from unittest.mock import MagicMock

    captured: list = []
    transport = httpx.MockTransport(lambda req: captured.append(req) or httpx.Response(200))

    tracing.set_trace_id("sync-trace")
    client = httpx.Client(event_hooks=traced_event_hooks(), transport=transport)
    client.get("http://example.com/api")

    assert captured[0].headers[HEADER_NAME] == "sync-trace"


def test_sync_httpx_client_no_trace_id_no_header():
    """ctx 无 trace_id → request 不带 X-Trace-Id。"""
    from unittest.mock import MagicMock

    captured: list = []
    transport = httpx.MockTransport(lambda req: captured.append(req) or httpx.Response(200))

    client = httpx.Client(event_hooks=traced_event_hooks(), transport=transport)
    client.get("http://example.com/api")

    assert HEADER_NAME not in captured[0].headers


# ===== 端到端:异步 httpx.AsyncClient =====


import asyncio


def test_async_httpx_client_injects_trace_id():
    """httpx.AsyncClient 用 traced_async_event_hooks → 发出去的 request 带 trace_id。"""
    captured: list = []

    async def handler(req):
        captured.append(req)
        return httpx.Response(200)

    transport = httpx.MockTransport(handler)

    async def run():
        tracing.set_trace_id("async-trace")
        async with httpx.AsyncClient(
            event_hooks=traced_async_event_hooks(),
            transport=transport,
        ) as client:
            await client.get("http://example.com/api")

    asyncio.run(run())
    assert captured[0].headers[HEADER_NAME] == "async-trace"


# ===== ctx 切换:不同 ctx 走不同 trace_id =====


def test_different_contexts_produce_different_trace_ids():
    """ctx A / ctx B 各自的 httpx call 带各自的 trace_id(不串)。"""
    captured: list = []
    transport = httpx.MockTransport(lambda req: captured.append(req) or httpx.Response(200))

    # ctx A
    tracing.set_trace_id("trace-a")
    client = httpx.Client(event_hooks=traced_event_hooks(), transport=transport)
    client.get("http://example.com/a")
    # 切 ctx
    tracing.set_trace_id("trace-b")
    client.get("http://example.com/b")

    assert captured[0].headers[HEADER_NAME] == "trace-a"
    assert captured[1].headers[HEADER_NAME] == "trace-b"