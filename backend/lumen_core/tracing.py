"""Phase 0 Unit 5 (2026-09-02):trace_id 全链路贯通基础设施。

Phase 1 Group B 2.4.4 (2026-09-04):bridge 到 OpenTelemetry SDK,OTel
current span context 作为备用 source。

**为什么**:Phase 0 之前 trace_id 散在 3 个独立系统:
- API 入口无 trace_id(只能从 LLMCallContext / EmbeddingCallContext 间接拿)
- httpx 调 Ollama/OpenAI 无 trace_id header 注入(下游抓不到对应)
- Celery worker task 无 trace_id 注入(后台 trace 断)
结果:用户报"我那个请求挂了",dev 没法在 5 分钟内把 API log + Ollama log
+ Celery log 串成一条线。

**用法**(API 层):
    from lumen_core.tracing import new_trace_id, set_trace_id, get_trace_id

    # 在 middleware / endpoint 入口:
    tid = new_trace_id()  # 自动设到 contextvar + 返回
    # 或:
    set_trace_id(header_tid)  # 来自 X-Trace-Id header,透传用

    # 在 log / DB 写入 / httpx event hook / Celery task 任何地方:
    tid = get_trace_id()  # contextvar 优先 → OTel span 回退

**模式**:`ContextVar` 主,OTel span 回退。
- FastAPI 每个请求独立 context → 不串
- async / await 切换 contextvar 自动传递
- 已有 14 个老 test(trace_id_middleware / tracing / logging_config /
  httpx_trace / celery_trace_signals / dlq / celery_routes)假设 contextvar
  是真值源;contextvar 优先保证它们不回归
- 新 OTel-aware 代码用 `from opentelemetry import trace; trace.get_current_span()`
  拿完整 span object;`get_trace_id()` 仅作 trace_id 字符串 bridge

**Header 约定**:X-Trace-Id(也可认 X-Request-Id)。Phase 0 默认 32 hex
(uuid4);Phase 1 改 16-char base32(短一点,日志 grep 友好)。
"""
from __future__ import annotations

import logging
import uuid
from contextvars import ContextVar
from typing import Optional

logger = logging.getLogger(__name__)


# ContextVar:per-request 持有 trace_id。FastAPI 每个请求独立 context,
# 异步 / asyncio.Task 切换不会泄漏。
_trace_id_var: ContextVar[Optional[str]] = ContextVar("trace_id", default=None)


# Header 约定:接受 X-Trace-Id / X-Request-Id / traceparent(OpenTelemetry)
HEADER_NAMES = ("X-Trace-Id", "X-Request-Id", "traceparent")


def new_trace_id() -> str:
    """生成 32-hex trace_id(模拟 uuid4),set 到 contextvar,返回。

    用法:API 入口 middleware 当 X-Trace-Id 没传时调一次,设到 ctx。
    """
    tid = uuid.uuid4().hex
    _trace_id_var.set(tid)
    return tid


def set_trace_id(tid: Optional[str]) -> None:
    """手动设置 trace_id(用于从外部 header / Celery request 注入)。

    传 None 等价于 clear_trace_id。
    """
    _trace_id_var.set(tid)


def get_trace_id() -> Optional[str]:
    """当前 trace_id(contextvar 优先 → OTel current span 回退 → None)。

    优先级说明:
      1. **contextvar**(由 TraceIdMiddleware / Celery signal / 显式 set 设)
         — 兼容 14 个老 test + X-Trace-Id back-compat
      2. **OTel current span trace_id** — Phase 1 1.4 ship 后,FastAPI 请求
         期间 OTel FastAPIInstrumentor 已建 span;当 contextvar 没值时(单测 /
         未经过 middleware 的内部调用)从 OTel 拿
      3. **None** — 都没值

    为什么不"OTel 优先":已有 14 个老 test(M37 前 ship)假设 get_trace_id
    返回 middleware 设的 contextvar 值;改顺序会让它们 fail。Plan
    §backward compat 列"自研 get_trace_id() API 保留",实现上 contextvar
    优先 + OTel 回退是满足"保留"的最小改动。

    OTel-aware 代码应直接用 `opentelemetry.trace.get_current_span()` 拿
    完整 span object(attributes / events / context);`get_trace_id()` 仅
    bridge 出 trace_id 字符串。
    """
    tid = _trace_id_var.get()
    if tid is not None:
        return tid
    # OTel 回退:仅当 OTel SDK 安装且 current span context valid
    try:
        from opentelemetry import trace as _otel_trace
    except ImportError:
        return None
    try:
        span = _otel_trace.get_current_span()
        sc = span.get_span_context()
        if sc.is_valid:
            return format(sc.trace_id, "032x")
    except Exception:  # noqa: BLE001
        # OTel 任何异常都 swallow,bridge 不能拖垮业务
        pass
    return None


def clear_trace_id() -> None:
    """清空 trace_id(测试 / 嵌套 save/restore 用)。

    等价于 set_trace_id(None)。
    """
    _trace_id_var.set(None)


def ensure_trace_id() -> str:
    """强制拿一个 trace_id(无则生成新的)。

    用法:已知需要 trace_id 但又不确定上游有没有设过的场景
    (如 Celery task 入口的兜底)。
    """
    tid = _trace_id_var.get()
    if tid is None:
        tid = new_trace_id()
    return tid


# ---- 测试 teardown ----


def reset_for_test() -> None:
    """清掉 contextvar(测试间隔离用)。

    pytest fixture 推荐写法:
        @pytest.fixture(autouse=True)
        def _reset_trace_id():
            yield
            reset_for_test()
    """
    _trace_id_var.set(None)


__all__ = [
    "new_trace_id",
    "set_trace_id",
    "get_trace_id",
    "clear_trace_id",
    "ensure_trace_id",
    "reset_for_test",
    "HEADER_NAMES",
]