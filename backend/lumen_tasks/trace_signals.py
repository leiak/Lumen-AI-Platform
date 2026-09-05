"""Phase 0 Unit 5 4.2 (2026-09-02):Celery trace_id 贯通信号。

Phase 1 Group B 2.4.4 (2026-09-04) Day 2 演进:跟 ``CeleryInstrumentor``
(W3C traceparent header)共存 — 双 header 都注入,worker 端优先 OTel
current span,无 OTel span 时回退 X-Trace-Id。

**做什么**:Celery 任务 producer 把 trace_id 放到 task request 的 headers
里(走 `apply_async(headers={"X-Trace-Id": "..."})` 或 worker 端
prestore),worker `task_prerun` 信号里读出来,set 到当前进程 contextvar,
这样 worker 内的 logger / DB writer / httpx call 都能 join 同一 trace。

**用法**(任务 producer):
    from lumen_tasks.trace_signals import apply_async_with_trace
    apply_async_with_trace(task, args=[...], kwargs={...})

**用法**(task 自动接受 trace_id):
    Celery task body 里调 ``from lumen_core.tracing import get_trace_id``
    拿当前 trace_id(已被 signal 注入)。

**Celery 信号约定**:
- ``before_task_publish`` (sender side):从 ctx 拿 trace_id 写到 message headers
- ``task_prerun`` (worker side):从 message headers 读 trace_id 写回 ctx

**Phase 1 4.4 Day 2:OTel 共存**:
- ``CeleryInstrumentor().instrument()`` 装好后,每个 task 自动建 parent span
  + inject W3C ``traceparent`` header
- 自研 handler 保留 X-Trace-Id 路径作为兼容(老客户端不识别 traceparent
  也能 join trace)
- worker 端 ``task_prerun`` 优先用 OTel current span 的 trace_id(避免
  X-Trace-Id ≠ traceparent 时日志 / span 分裂),无 OTel span 时回退
  X-Trace-Id header

**踩坑**:
- celery worker 是独立进程,每个 task 在独立 asyncio loop(实际是 billiard
  worker 同步跑),ctx 通过 `headers={"X-Trace-Id": ...}` 走 Redis 序列化
  传过去
- ``set_trace_id`` 必须放 task_prerun 早的位置,否则下游业务 log 拿不到
- ``task_postrun`` / ``task_failure`` 清理 ctx(避免下一个 task 串)
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from lumen_core.tracing import (
    HEADER_NAMES,
    clear_trace_id,
    get_trace_id,
    set_trace_id,
)

logger = logging.getLogger(__name__)


# Celery header key(消息层 key,非 HTTP header 大小写无关)
CELERY_HEADER_KEY = "X-Trace-Id"


def _read_trace_id_from_task_headers(task: Any) -> Optional[str]:
    """从 Celery task instance 拿 trace_id(headers 在 request 里)。

    Phase 0:celery headers 是 dict-like,通过 ``task.request.headers`` 访问。
    不同 celery 版本字段位置略不同,这里兼容 5.x 主流写法。
    """
    req = getattr(task, "request", None)
    if req is None:
        return None
    headers = getattr(req, "headers", None) or {}
    if not headers:
        return None
    # dict / CaseInsensitiveDict 都行
    for key in (CELERY_HEADER_KEY, "X-Request-Id", "traceparent"):
        v = headers.get(key)
        if v:
            # traceparent 是 W3C "00-{trace-id}-{span-id}-{flags}",取 trace-id 段
            if key == "traceparent" and "-" in v:
                parts = v.split("-")
                if len(parts) >= 2:
                    return parts[1]
            return v
    return None


def _has_valid_otel_span() -> bool:
    """Phase 1 4.4 Day 2:检查当前 OTel context 是否有 valid span。

    如果有 → CeleryInstrumentor 已经 inject 了 traceparent header,worker
    端 task_prerun 已经从 traceparent 建好 span。此时不应该用 X-Trace-Id
    header 覆盖 contextvar(可能不一致)。

    OTel SDK 未装 / import 失败 → 返 False,继续走 X-Trace-Id 路径。
    """
    try:
        from opentelemetry import trace as _otel_trace
    except ImportError:
        return False
    try:
        sc = _otel_trace.get_current_span().get_span_context()
        return bool(sc and sc.is_valid)
    except Exception:  # noqa: BLE001
        # OTel 内部异常 swallow,跟 tracing.get_trace_id() 行为一致
        return False


def task_prerun_handler(task_id: str, task: Any, **kwargs) -> None:
    """Celery ``task_prerun`` 信号 handler:在 task body 跑前注入 trace_id。

    注册方式:lumen_celery_app worker_init() 里
        from celery import signals
        signals.task_prerun.connect(task_prerun_handler)
        signals.task_postrun.connect(task_postrun_handler)

    Phase 1 4.4 Day 2 演进:
    - 如果 CeleryInstrumentor 已经建了 valid OTel span → 不动 contextvar,
      让 ``get_trace_id()`` 通过 OTel bridge 拿 trace_id(避免不一致)
    - 如果 OTel 未装 / 无 valid span → 走老路径:从 X-Trace-Id header 拿
      trace_id set 到 contextvar
    """
    if _has_valid_otel_span():
        logger.debug(
            "celery task_prerun: OTel span valid, deferring to OTel bridge task=%s",
            task.name,
        )
        return

    tid = _read_trace_id_from_task_headers(task)
    if tid:
        set_trace_id(tid)
        logger.debug(
            "celery task_prerun: injected trace_id=%s task=%s", tid[:8], task.name,
        )
    else:
        # 无 trace_id → 清空(避免上一个 task 的 tid 残留)
        clear_trace_id()
        logger.debug(
            "celery task_prerun: no trace_id in headers, cleared ctx task=%s",
            task.name,
        )


def task_postrun_handler(task_id: str, task: Any, **kwargs) -> None:
    """Celery ``task_postrun`` 信号 handler:task 跑完清 ctx。

    防下一个 task 串 / 防 shutdown 期间的 log 还带旧 tid。

    Phase 1 4.4 Day 2:即便 OTel 已接管,清 contextvar 是 back-compat
    守门(代码里很多地方直接调 get_trace_id() 拿 contextvar,而不是走
    OTel bridge)。
    """
    clear_trace_id()


def before_task_publish_handler(
    sender: str = None,
    headers: Optional[dict] = None,
    body: Optional[Any] = None,
    **kwargs,
) -> None:
    """Celery ``before_task_publish`` 信号 handler:从 ctx 拿 trace_id 写到 headers。

    Producer 端(API / caller)发 task 前调,把当前 trace_id 塞到 task
    message headers,worker 端 task_prerun 读出来。

    注意:必须**就地改 headers**(celery 的 hook 拿到的是 mutable dict,
    in-place 修改生效)。

    Phase 1 4.4 Day 2:CeleryInstrumentor 也通过这个 signal 注入 W3C
    traceparent header(从 OTel current span context 拿 trace_id +
    span_id)。两个 handler 都跑,Redis message 里同时有 X-Trace-Id +
    traceparent 两个 header。worker 端根据 OTel 是否有效优先选 OTel
    (见 task_prerun_handler)。
    """
    if headers is None:
        return
    tid = get_trace_id()
    if tid and CELERY_HEADER_KEY not in headers:
        headers[CELERY_HEADER_KEY] = tid


def apply_async_with_trace(
    task: Any,
    args: Optional[list] = None,
    kwargs: Optional[dict] = None,
    **extra: Any,
) -> Any:
    """便捷包装:apply_async 时把当前 trace_id 写到 headers。

    Mirror Celery 的 ``Task.apply_async`` 签名,直接转发 args / kwargs /
    countdown / eta 等。**唯一新增**:ctx 有 trace_id 时注入到 headers。

    用法:
        apply_async_with_trace(my_task, args=[1, 2])
        apply_async_with_trace(my_task, kwargs={"x": 1}, countdown=10)
    """
    headers = extra.pop("headers", None) or {}
    tid = get_trace_id()
    if tid and CELERY_HEADER_KEY not in headers:
        headers[CELERY_HEADER_KEY] = tid
    return task.apply_async(
        args=args, kwargs=kwargs, headers=headers, **extra,
    )


def install_celery_signals() -> None:
    """注册全部 Celery signal handlers(worker 启动时调一次)。

    调用方:lumen_celery_app / celery worker_init hook。
    Phase 0:懒注册 + 幂等(避免重复 connect)。
    """
    from celery import signals

    # signals.connect 默认是 weak ref,允许多次 connect(每次都生效);
    # 用 sender=None 表示监听所有 task。
    signals.task_prerun.connect(
        task_prerun_handler, weak=False,
    )
    signals.task_postrun.connect(
        task_postrun_handler, weak=False,
    )
    signals.before_task_publish.connect(
        before_task_publish_handler, weak=False,
    )
    logger.info("celery trace_id signal handlers installed")


__all__ = [
    "task_prerun_handler",
    "task_postrun_handler",
    "before_task_publish_handler",
    "apply_async_with_trace",
    "install_celery_signals",
    "CELERY_HEADER_KEY",
    "_has_valid_otel_span",
]