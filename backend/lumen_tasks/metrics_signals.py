"""2.1 C.5:Celery 任务 → ``lumen_celery_tasks_total`` Prometheus Counter 写入。

**为什么**:
``lumen_celery_tasks_total{queue, status}`` counter 在 Phase 1 Group B 2.4.5
ship 时就定义了,但**没有实际写入点** —— Celery 任务跑完 / 失败时没人
inc()它,Prometheus 一直显示 0,Grafana ``slo:celery_success:sli_5m``
分母为 0 走 ``clamp_min(_, 0.001)`` 兜底,dashboard 永远 100%。Phase 1 留
TODO 给后续(``monitoring/slo_definitions.yaml:99-101`` 注释明写)。

**修法**:注册 Celery ``task_success`` / ``task_failure`` 信号 handler,每条
task 完成 / 失败时 inc 一次 ``lumen_celery_tasks_total{queue=<>,status=<>}``。
``queue`` 标签从 ``task_prerun`` 时拿到的 ``delivery_info`` 读
(``task.request.delivery_info`` 含 ``routing_key`` 即 celery queue 名)。

**handler 失败容错**:inc() 自身基本不可能失败(Prometheus client 是 in-memory
Counter,纯 Python dict inc),handler 用 try/except 包死,绝不让 metrics 上报
故障影响 Celery 主流程 —— 可观测性挂了不应挂业务。

**安装位置**:
``lumen_tasks.celery_app._on_worker_init`` 里调 ``install_metrics_signals()``,
每个 worker 进程启动时装一次。Celery fork 后 signal handler 必须重连
(``task_success.connect(...)`` 在主进程装的话,fork 后子进程拿不到)——
所以放 ``worker_init`` hook,镜像 ``install_dlq_signal`` 模式。

**status 语义**:
- ``success`` — ``task_success`` 信号触发(tasksuceeded 状态)
- ``error`` — ``task_failure`` 信号触发(任务最终失败,包括 retry 全部用尽)
- ``retry`` — ``task_retry`` 信号触发(Celery 自动重试)
"""
from __future__ import annotations

import logging
from typing import Any

from celery import signals  # type: ignore[import-untyped]

logger = logging.getLogger(__name__)


def _resolve_queue(task: Any) -> str:
    """从 task instance 拿 Celery queue 名。

    路径:
      1. ``task.request.delivery_info.routing_key`` —— 这是 Celery 把 task
         publish 到 broker 时用的 routing key,跟 ``task_routes`` 映射后的
         queue 名一致(doc_parse / ppt_gen / eval_run / default)
      2. fallback ``getattr(task, "name", "unknown")`` —— 没有 delivery_info
         时(罕见,eager 模式 / 直接调用),用 task 函数名兜底

    不抛异常:queue 拿不到就 "unknown",不要因为 metrics 路径崩溃影响主流程。
    """
    try:
        request = getattr(task, "request", None)
        if request is not None:
            delivery_info = getattr(request, "delivery_info", None)
            if delivery_info and isinstance(delivery_info, dict):
                routing_key = delivery_info.get("routing_key")
                if routing_key:
                    return str(routing_key)
    except Exception:  # noqa: BLE001
        # metrics 路径不能挂,吞掉
        pass
    return "unknown"


def _on_task_success(sender: Any, **_: Any) -> None:
    """``task_success`` 信号 handler:inc success 计数。

    注意:Celery 文档说 ``sender`` 是 task class 本身,但实际 signal dispatch
    时传的是 task instance(包含 ``.request``)。两侧都兼容。
    """
    try:
        from lumen_core.metrics import lumen_celery_tasks_total

        queue = _resolve_queue(sender)
        lumen_celery_tasks_total.labels(queue=queue, status="success").inc()
    except Exception as e:  # noqa: BLE001
        # metrics 上报失败不能影响 Celery 主流程,只记日志
        logger.warning("celery task_success metrics inc failed: %s", e)


def _on_task_failure(sender: Any, **_: Any) -> None:
    """``task_failure`` 信号 handler:inc error 计数。

    跟 DLQ ``on_task_failure`` 是同一个 Celery 信号,但职责独立:
      - DLQ handler 写 ``failed_tasks`` 表给 admin 查 / 重派 / ack
      - 本 handler 只 bump Prometheus Counter,给 Grafana / Alertmanager 用

    两个 handler 各自 try/except 独立,一个挂了不影响另一个。
    """
    try:
        from lumen_core.metrics import lumen_celery_tasks_total

        queue = _resolve_queue(sender)
        lumen_celery_tasks_total.labels(queue=queue, status="error").inc()
    except Exception as e:  # noqa: BLE001
        logger.warning("celery task_failure metrics inc failed: %s", e)


def _on_task_retry(sender: Any, **_: Any) -> None:
    """``task_retry`` 信号 handler:inc retry 计数。

    Celery 自动重试(retries=N + autoretry_for)触发本信号。retry 算半失败:
    业务上还没死,但每 retry 一次任务延迟 / worker 池占用都增加,
    dashboard 看 retry rate 能定位"配 retry 上限过大 / 任务上游不稳"。

    注:retry 后续真正失败时,``task_failure`` 会再触发一次 error inc,
    所以 dashboard 看到 success+error+retry 三者叠加 = task 总数。
    """
    try:
        from lumen_core.metrics import lumen_celery_tasks_total

        queue = _resolve_queue(sender)
        lumen_celery_tasks_total.labels(queue=queue, status="retry").inc()
    except Exception as e:  # noqa: BLE001
        logger.warning("celery task_retry metrics inc failed: %s", e)


def install_metrics_signals() -> None:
    """注册 Celery task_success / task_failure / task_retry 信号 handler。

    调用方:lumen_tasks.celery_app._on_worker_init 末尾,跟 dlq + trace_signals
    同一时机装(每个 worker 进程独立 connect,避免多 worker 重复注册)。

    重复 connect 安全:每个 handler 内部用 logger.warning 兜异常,``connect()``
    本身是 idempotent(同 handler 连多次只生效一次)。但**handler 函数引用
    不变**,所以重复 connect 不会重复 inc —— 安全。
    """
    signals.task_success.connect(_on_task_success, weak=False)
    signals.task_failure.connect(_on_task_failure, weak=False)
    signals.task_retry.connect(_on_task_retry, weak=False)
    logger.info("celery metrics signals installed (task_success / failure / retry)")


__all__ = [
    "install_metrics_signals",
    "_on_task_success",
    "_on_task_failure",
    "_on_task_retry",
    "_resolve_queue",
]
