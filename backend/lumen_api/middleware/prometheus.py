"""Phase 0 Unit 5 4.3 (2026-09-02):Prometheus HTTP 请求 metrics 中间件。

**做什么**:
1. 每个 HTTP 请求记录:
   - ``http_requests_total{method, path, status}.inc()``
   - ``http_request_duration_seconds{method, path}.observe(duration)``

2. ``path`` 用 starlette route template(``/api/v1/users/{user_id}``),
   不是实际 URL —— 防 cardinality 爆炸(用户 id / doc id 无限增长)。

**挂载位置**:lumen_main.py app.add_middleware(PrometheusMiddleware)。
**最外层**(TraceIdMiddleware 之后),保证 trace_id 已有。

**注意**:``/metrics`` 端点本身也要被 metrics 记录(避免漏报 scrape 本身)。
如果你不想被 metrics 抓,在中间件里 skip /metrics 路径。

**路径提取**:route.template 优先;没匹配上 fallback 到 request.url.path
(404 / 405 等找不到 route 时也得有 path)。
"""
from __future__ import annotations

import logging
import time
from typing import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Match

from lumen_core.metrics import (
    http_request_duration_seconds,
    http_requests_total,
)

logger = logging.getLogger(__name__)


def _resolve_route_template(request: Request) -> str:
    """从 request scope 拿 route template,无则 fallback 到 url.path。

    防 cardinality:用 ``/users/{user_id}`` 而不是 ``/users/42``。
    """
    # starlette 在 request.scope["route"] 里设当前 match 的 route
    # (BaseHTTPMiddleware 已经处理过 routing)。但路由层 Match 信息
    # 可能没在 scope 里,这里 fallback 直接读 url.path。
    scope = request.scope
    route = scope.get("route")
    if route is not None and getattr(route, "path", None):
        return route.path
    # 兜底:实际 path(404 / middleware 异常路径会走到这)
    return request.url.path


class PrometheusMiddleware(BaseHTTPMiddleware):
    """每个请求 inc counter + observe histogram。"""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        method = request.method
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            # 异常路径:status=500,inc + log
            # 异常路径 route 通常没匹配上,走 url.path fallback
            duration = time.perf_counter() - start
            path = _resolve_route_template(request)
            status = "500"
            try:
                http_requests_total.labels(
                    method=method, path=path, status=status,
                ).inc()
                http_request_duration_seconds.labels(
                    method=method, path=path,
                ).observe(duration)
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    "PrometheusMiddleware: failed to record error metric (%s)", e,
                )
            raise

        duration = time.perf_counter() - start
        # call_next 之后 resolve path —— 此时 Starlette routing 已把
        # matched route 写到 scope['route'],拿到的是 template
        # (/users/{user_id}) 而非实际 URL(/users/42),防 cardinality 爆炸
        path = _resolve_route_template(request)
        status = str(response.status_code)
        try:
            http_requests_total.labels(
                method=method, path=path, status=status,
            ).inc()
            http_request_duration_seconds.labels(
                method=method, path=path,
            ).observe(duration)
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "PrometheusMiddleware: failed to record metric (%s)", e,
            )

        return response


__all__ = ["PrometheusMiddleware", "_resolve_route_template"]