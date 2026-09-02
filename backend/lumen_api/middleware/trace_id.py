"""Phase 0 Unit 5 4.2 (2026-09-02):FastAPI trace_id 中间件。

**做什么**:
1. 收到请求时,读 ``X-Trace-Id`` / ``X-Request-Id`` / ``traceparent`` header
   - 存在 → set 到 lumen_core.tracing contextvar(透传)
   - 不存在 → 生成新 uuid4 hex,set + 透传
2. 处理请求
3. 响应 header 写回 ``X-Trace-Id``(让客户端也拿到,后续可粘到 bug report)

**挂载位置**:lumen_main.py app.add_middleware(TraceIdMiddleware)
—— 必须**最早**挂,后面所有 middleware / endpoint / 业务 log 都能拿到 trace_id。

**为什么用 contextvar 而非 request.state**:
- 跨 asyncio.Task 边界自动传(asyncio + FastAPI 异步路由)
- log formatter / httpx event_hooks / Celery signal 全能读同一份 ctx
- 不需要在每个 endpoint 加 Depends(get_request)
"""
from __future__ import annotations

import logging
from typing import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from lumen_core.tracing import (
    HEADER_NAMES,
    new_trace_id,
    set_trace_id,
)

logger = logging.getLogger(__name__)


# 响应里写回的 header 名(单一标准,不管客户端传的是哪种)
RESPONSE_HEADER = "X-Trace-Id"


class TraceIdMiddleware(BaseHTTPMiddleware):
    """每个请求:读/生成 trace_id → set ctx → 响应 header 写回。

    FastAPI 中间件按 LIFO 顺序执行:最后 add_middleware 的最先跑。
    所以 trace_id middleware 应该**最后** add_middleware(它最外层,
    包住其他所有中间件,确保 trace_id 在 request 整个生命周期可用)。
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        # 入口:从 header 拿,没有就生成
        incoming = None
        for h in HEADER_NAMES:
            v = request.headers.get(h)
            if v:
                # W3C traceparent 是 "00-{32hex}-{16hex}-{2hex}";Phase 0
                # 只取 trace-id 段(第二段,32 hex)。
                # 校验:必须 4 段且 trace-id 是 hex(避免 "garbage-no-dashes" 这种)
                if h == "traceparent":
                    parts = v.split("-")
                    if len(parts) >= 2:
                        candidate = parts[1]
                        # W3C spec: trace-id 是 32 hex chars(16 bytes)
                        if len(candidate) == 32 and all(
                            c in "0123456789abcdefABCDEF" for c in candidate
                        ):
                            incoming = candidate
                            break
                        # 不是合法 traceparent → 继续看下一个 header
                        continue
                    else:
                        continue
                else:
                    incoming = v
                    break

        if incoming:
            set_trace_id(incoming)
        else:
            incoming = new_trace_id()

        try:
            response = await call_next(request)
        finally:
            # 注意:不要在 finally 清 ctx —— 异步流式响应(sse-starlette)
            # 可能已经跨 task 把 ctx copy 走;清了就破坏下游 consumer。
            # 每个新请求 FastAPI 都会建独立 context,自然隔离。
            pass

        # 把 trace_id 写回 response header,客户端也能拿来 join 错误报告
        response.headers[RESPONSE_HEADER] = incoming
        return response


__all__ = ["TraceIdMiddleware", "RESPONSE_HEADER"]