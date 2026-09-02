"""Phase 0 Unit 5 4.3 (2026-09-02):PrometheusMiddleware 行为测试。

覆盖:
- 正常请求 → http_requests_total{method, path, status} +1
- 正常请求 → http_request_duration_seconds{method, path} observe
- path label 用 route template(/users/{user_id}),不爆 cardinality
- 404 路径也记录(用 url.path fallback)
- 异常路径 → status=500,metric 仍 inc
- /metrics 端点本身也被记录(说明注释明确说允许)
"""
from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from lumen_api.middleware.prometheus import (
    PrometheusMiddleware,
    _resolve_route_template,
)
from lumen_core.metrics import (
    get_metric_value,
    http_request_duration_seconds,
    http_requests_total,
    reset_metrics_for_test,
)


# ===== test app 构造 =====


def _make_app() -> FastAPI:
    """最小 FastAPI app 装 PrometheusMiddleware,几个测试路由。"""
    app = FastAPI()
    app.add_middleware(PrometheusMiddleware)

    @app.get("/api/v1/users/{user_id}")
    def get_user(user_id: int):
        return {"id": user_id, "name": "alice"}

    @app.get("/api/v1/health")
    def health():
        return {"ok": True}

    @app.get("/api/v1/boom")
    def boom():
        raise HTTPException(status_code=500, detail="boom")

    @app.get("/api/v1/error")
    def error():
        # 触发未捕获异常路径
        raise RuntimeError("unexpected")

    @app.get("/metrics")
    def metrics_stub():
        """模拟真实 /metrics 端点(在 lumen_main.py 里挂 prom text 渲染)。"""
        return {"ok": True}

    return app


@pytest.fixture
def client():
    """每个 test 用全新 app + reset registry,避免 sample 串。"""
    reset_metrics_for_test()
    app = _make_app()
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    reset_metrics_for_test()


# ===== 正常路径 =====


def test_request_increments_http_requests_total(client):
    """一次 GET → http_requests_total counter +1。"""
    client.get("/api/v1/health")
    value = get_metric_value(
        "http_requests_total",
        {"method": "GET", "path": "/api/v1/health", "status": "200"},
    )
    assert value == 1.0


def test_request_observes_duration(client):
    """duration histogram 有 sample(>=1 observation)。"""
    client.get("/api/v1/health")
    # histogram 的 _count sample 名带 _count 后缀
    value = get_metric_value(
        "http_request_duration_seconds_count",
        {"method": "GET", "path": "/api/v1/health"},
    )
    assert value is not None
    assert value >= 1


def test_path_uses_route_template_for_param_route(client):
    """参数化路由用 template(/users/{user_id})而非实际 URL。"""
    client.get("/api/v1/users/42")
    client.get("/api/v1/users/12345")

    # 实际 URL 不同但 template 相同 → metric 是同一行
    value = get_metric_value(
        "http_requests_total",
        {"method": "GET", "path": "/api/v1/users/{user_id}", "status": "200"},
    )
    assert value == 2.0  # 两次请求累计

    # 实际 URL 不会成为 label(防 cardinality 爆炸)
    real_path_value = get_metric_value(
        "http_requests_total",
        {"method": "GET", "path": "/api/v1/users/42", "status": "200"},
    )
    assert real_path_value is None


def test_different_status_codes_recorded_separately(client):
    """200 / 500 走不同 status label(同 path 也分开计数)。"""
    client.get("/api/v1/health")  # 200
    client.get("/api/v1/boom")    # 500

    val_200 = get_metric_value(
        "http_requests_total",
        {"method": "GET", "path": "/api/v1/health", "status": "200"},
    )
    val_500 = get_metric_value(
        "http_requests_total",
        {"method": "GET", "path": "/api/v1/boom", "status": "500"},
    )
    assert val_200 == 1.0
    assert val_500 == 1.0


# ===== 404 路径 =====


def test_404_path_records_with_url_fallback(client):
    """没匹配上 route → path label 走 url.path(避免漏报)。"""
    client.get("/api/v1/this-does-not-exist")

    value = get_metric_value(
        "http_requests_total",
        {"method": "GET", "path": "/api/v1/this-does-not-exist", "status": "404"},
    )
    assert value == 1.0


# ===== 异常路径 =====


def test_uncaught_exception_records_status_500(client):
    """raise_server_exceptions=False 下 RuntimeError → status=500 仍被记录。"""
    client.get("/api/v1/error")

    value = get_metric_value(
        "http_requests_total",
        {"method": "GET", "path": "/api/v1/error", "status": "500"},
    )
    assert value == 1.0


def test_uncaught_exception_still_observes_duration(client):
    """异常路径也要 observe duration(metric 不能漏)。"""
    client.get("/api/v1/error")
    value = get_metric_value(
        "http_request_duration_seconds_count",
        {"method": "GET", "path": "/api/v1/error"},
    )
    assert value is not None
    assert value >= 1


# ===== /metrics 端点本身 =====


def test_metrics_endpoint_is_recorded_too(client):
    """/metrics 自身也会被 middleware 记录(spec 注释明确允许)。

    不 skip —— 否则 scrape 自身不计入总请求数,debug 时困惑。
    """
    client.get("/metrics")
    value = get_metric_value(
        "http_requests_total",
        {"method": "GET", "path": "/metrics", "status": "200"},
    )
    assert value == 1.0


# ===== _resolve_route_template helper =====


def test_resolve_route_template_returns_url_path_when_no_route():
    """scope['route'] 不存在 → fallback 到 url.path(404 / 中间件异常路径)。"""
    from starlette.requests import Request

    # 构造最小 Request 对象
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/some/path",
        "headers": [],
    }
    request = Request(scope)
    assert _resolve_route_template(request) == "/some/path"


def test_resolve_route_template_uses_route_path_when_present():
    """scope['route'] 存在 → 用 route.path(template)。"""
    from starlette.requests import Request
    from starlette.routing import Route

    async def endpoint(req):
        pass

    route = Route("/users/{user_id}", endpoint=endpoint)
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/users/42",
        "headers": [],
        "route": route,
    }
    request = Request(scope)
    assert _resolve_route_template(request) == "/users/{user_id}"
