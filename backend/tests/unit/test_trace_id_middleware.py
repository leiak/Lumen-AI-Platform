"""Phase 0 Unit 5 4.2 (2026-09-02):FastAPI trace_id middleware 测试。

覆盖:
- 客户端带 X-Trace-Id → middleware 透传到 ctx + 响应 header
- 客户端不带 → middleware 生成新 trace_id,响应 header 写回
- X-Request-Id / traceparent 也兼容
- 响应 header 总是有 X-Trace-Id
- 多请求独立 trace_id
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from lumen_api.middleware.trace_id import TraceIdMiddleware
from lumen_core import tracing


@pytest.fixture(autouse=True)
def _reset_trace():
    """每个 test 后清 trace_id contextvar。"""
    tracing.reset_for_test()


def _build_app():
    """最小 Starlette app + TraceIdMiddleware。

    handler echo 当前 ctx 里的 trace_id(便于断言)。
    """
    async def echo_trace(request: Request):
        tid = tracing.get_trace_id()
        return JSONResponse({"trace_id": tid})

    app = Starlette(routes=[Route("/echo", echo_trace, methods=["GET"])])
    app.add_middleware(TraceIdMiddleware)
    return app


# ===== 客户端带 X-Trace-Id → 透传 =====


def test_client_x_trace_id_passes_through_to_ctx():
    """客户端 X-Trace-Id: abc123 → ctx 里就是 abc123。"""
    app = _build_app()
    c = TestClient(app)
    r = c.get("/echo", headers={"X-Trace-Id": "abc123"})
    assert r.status_code == 200
    assert r.json() == {"trace_id": "abc123"}


def test_response_header_writes_back_incoming_trace_id():
    """客户端传的 trace_id 在响应 header 里能找到。"""
    app = _build_app()
    c = TestClient(app)
    r = c.get("/echo", headers={"X-Trace-Id": "incoming-tid"})
    assert r.headers["X-Trace-Id"] == "incoming-tid"


# ===== 客户端不带 → middleware 生成 =====


def test_no_header_generates_new_trace_id():
    """客户端没 header → middleware 生成新 trace_id(32 hex)并 set ctx。"""
    app = _build_app()
    c = TestClient(app)
    r = c.get("/echo")
    body = r.json()
    tid = body["trace_id"]
    assert tid is not None
    assert len(tid) == 32
    assert all(ch in "0123456789abcdef" for ch in tid)
    # 跟 response header 一致
    assert r.headers["X-Trace-Id"] == tid


# ===== 多 header 兼容 =====


def test_x_request_id_is_also_recognized():
    """X-Request-Id 兼容(行业惯例)。"""
    app = _build_app()
    c = TestClient(app)
    r = c.get("/echo", headers={"X-Request-Id": "from-request-id"})
    assert r.json() == {"trace_id": "from-request-id"}
    assert r.headers["X-Trace-Id"] == "from-request-id"


def test_traceparent_w3c_format_parsed():
    """W3C traceparent 格式 "00-{32hex}-{16hex}-{2hex}" 取第二段(trace-id)。"""
    app = _build_app()
    c = TestClient(app)
    r = c.get(
        "/echo",
        # W3C spec: trace-id 是 16 bytes = 32 hex chars
        headers={"traceparent": "00-deadbeefcafebabe1234567890abcdef-0000000000000001-01"},
    )
    assert r.json() == {"trace_id": "deadbeefcafebabe1234567890abcdef"}


def test_traceparent_invalid_format_falls_back_to_generate():
    """traceparent 格式坏了 → fallback 生成新(不抛错)。"""
    app = _build_app()
    c = TestClient(app)
    r = c.get("/echo", headers={"traceparent": "garbage-no-dashes"})
    # 不传,生成新的
    tid = r.json()["trace_id"]
    assert tid is not None
    assert len(tid) == 32


# ===== Header 优先级 =====


def test_x_trace_id_takes_precedence_over_x_request_id():
    """多个 header 都传,X-Trace-Id 优先(HEADER_NAMES 顺序)。"""
    app = _build_app()
    c = TestClient(app)
    r = c.get(
        "/echo",
        headers={
            "X-Trace-Id": "primary",
            "X-Request-Id": "fallback",
        },
    )
    assert r.json() == {"trace_id": "primary"}


# ===== 多请求隔离 =====


def test_each_request_gets_independent_trace_id():
    """多个并发请求各自的 trace_id(不会串)。"""
    app = _build_app()
    c = TestClient(app)
    seen: list = []
    for _ in range(5):
        r = c.get("/echo")
        seen.append(r.json()["trace_id"])
    # 5 个都不同
    assert len(set(seen)) == 5


# ===== 不影响其他 endpoint =====


def test_post_request_also_gets_trace_id():
    """POST 请求也走 middleware。"""
    async def echo_post(request: Request):
        return JSONResponse({"trace_id": tracing.get_trace_id()})

    app = Starlette(routes=[Route("/echo", echo_post, methods=["POST"])])
    app.add_middleware(TraceIdMiddleware)
    c = TestClient(app)
    r = c.post("/echo", headers={"X-Trace-Id": "post-tid"})
    assert r.json() == {"trace_id": "post-tid"}
    assert r.headers["X-Trace-Id"] == "post-tid"