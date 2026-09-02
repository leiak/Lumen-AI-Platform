"""Phase 0 Unit 5 (2026-09-02):trace_id 全链路贯通基础设施。

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
    tid = get_trace_id()

**模式**:`ContextVar` 模式 — 跟 stdlib logging / asyncio.Task 同款。
- FastAPI 每个请求独立 context → 不串
- async / await 切换 contextvar 自动传递
- 测试 / 嵌套 save/restore:`ctx_var.set(val)` 返 token,`ctx_var.reset(token)` 还原

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
    """当前 contextvar 的 trace_id,无则 None。

    JSON log processor / DB writer / httpx hook 都从这里拿。
    """
    return _trace_id_var.get()


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