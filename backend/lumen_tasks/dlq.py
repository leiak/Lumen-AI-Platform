"""Phase 1 Group A 1.5 (2026-09-03): Celery 失败任务 DLQ handler。

**做什么**:注册 Celery ``task_failure`` 信号 handler,任务失败时把失败
信息 + traceback 写到 ``failed_tasks`` 表。admin 通过 ``/admin/tasks/failed``
查 / 重派 / ack。

**设计要点**:

1. **handler try/except 包死**:DLQ 写入失败不能让 Celery 主流程挂 —— fallback
   ``logger.error("dlq handler failed", exc_info=True)``,绝不抛。

2. **新开 ``SessionLocal()``**:不跟业务 session 共享事务(celery worker
   可能正在跑一个事务,DLQ 写入不能让那个事务 rollback)。

3. **args / kwargs 序列化安全兜底**:`json.dumps` 失败时(包含不可序列化
   对象如 datetime)fallback 到 ``repr()`` 字符串,而不是抛。

4. **trace_id 注入**:从 Celery message headers 拿 ``X-Trace-Id``(Phase 0
   trace_signals ship),存到 FailedTask.trace_id 让 admin 能跳日志。

5. **idempotent**:同一 ``task_id`` 多次失败 → update last_failed_at +
   retry_count,而不是 duplicate row(CUNIQUE 兜底)。

6. **retry_count 语义**:Celery 自动重试用 Celery 自家的 retry counter
   (state.retries);本表的 retry_count 是"admin 重派次数",不混。
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Optional

from sqlalchemy.exc import SQLAlchemyError

from lumen_core.database import SessionLocal
from lumen_models.failed_task import FailedTask
from lumen_tasks.trace_signals import CELERY_HEADER_KEY

logger = logging.getLogger(__name__)


def _safe_json_dumps(value: Any) -> Optional[str]:
    """json.dumps 失败时 fallback 到 str(repr()),不抛。"""
    if value is None:
        return None
    try:
        return json.dumps(value, default=str, ensure_ascii=False)
    except Exception:  # noqa: BLE001
        try:
            return repr(value)
        except Exception:  # noqa: BLE001
            return None


def _read_trace_id(task: Any) -> Optional[str]:
    """从 Celery task request headers 拿 trace_id(Phase 0 trace_signals 模式)。"""
    req = getattr(task, "request", None)
    if req is None:
        return None
    headers = getattr(req, "headers", None) or {}
    return headers.get(CELERY_HEADER_KEY)


def _resolve_tenant_id(task: Any, task_kwargs: dict) -> Optional[int]:
    """从 task kwargs 推断 tenant_id(项目 task 普遍传 tenant_id=...)。

    失败 fallback None —— admin 跨租户视图会兜底显示"无主任务"。
    """
    if isinstance(task_kwargs, dict):
        tid = task_kwargs.get("tenant_id")
        if isinstance(tid, int):
            return tid
    # task params 走 args 时,task_payload 第一个 dict 包含 tenant_id
    return None


def on_task_failure(
    sender: Any = None,
    task_id: Optional[str] = None,
    exception: Optional[BaseException] = None,
    args: Optional[Any] = None,
    kwargs: Optional[Any] = None,
    traceback: Optional[Any] = None,
    einfo: Optional[Any] = None,
    **extra: Any,
) -> None:
    """Celery ``task_failure`` 信号 handler:失败任务 → FailedTask row。

    注册方式(在 celery_app module 顶部):
        from celery.signals import task_failure
        task_failure.connect(on_task_failure)

    所有 DB 写入 + 日志 fallback 全 try/except 包死 —— 失败 handler 绝
    不污染 Celery 主流程。
    """
    task_name = getattr(sender, "name", "unknown")
    task_id_str = task_id or "unknown"

    # args / kwargs 安全序列化
    args_json = _safe_json_dumps(args)
    kwargs_json = _safe_json_dumps(kwargs)
    tb_text = None
    if isinstance(traceback, str):
        tb_text = traceback
    elif einfo is not None:
        # einfo 是 celery.exc.ExceptionInfo,自带 .traceback 字符串属性
        tb_text = getattr(einfo, "traceback", None)
    if not tb_text and exception is not None:
        tb_text = repr(exception)

    tenant_id = _resolve_tenant_id(sender, kwargs or {})
    trace_id = _read_trace_id(sender)
    queue = (
        getattr(getattr(sender, "request", None), "delivery_info", None) or {}
    ).get("routing_key") if sender else None

    db = SessionLocal()
    try:
        # upsert by task_id:已有 row → 更新 last_failed_at + retry_count;
        # 否则 INSERT
        existing = (
            db.query(FailedTask)
            .filter(FailedTask.task_id == task_id_str)
            .first()
        )
        if existing is not None:
            existing.last_failed_at = datetime.utcnow()  # type: ignore[assignment]
            existing.retry_count = (existing.retry_count or 0) + 1  # type: ignore[assignment]
            existing.max_retries_reached = True  # type: ignore[assignment]
            existing.traceback_text = tb_text or existing.traceback_text  # type: ignore[assignment]
            if trace_id and not existing.trace_id:
                existing.trace_id = trace_id  # type: ignore[assignment]
            if queue:
                existing.queue = queue  # type: ignore[assignment]
        else:
            row = FailedTask(
                tenant_id=tenant_id,
                task_id=task_id_str,
                task_name=task_name,
                queue=queue,
                args_json=args_json,
                kwargs_json=kwargs_json,
                traceback_text=tb_text,
                retry_count=0,
                max_retries_reached=True,
                first_failed_at=datetime.utcnow(),
                last_failed_at=datetime.utcnow(),
                trace_id=trace_id,
            )
            db.add(row)
        db.commit()
        logger.warning(
            "celery task_failure: persisted FailedTask task_id=%s name=%s "
            "tenant_id=%s trace_id=%s",
            task_id_str, task_name, tenant_id, (trace_id or "")[:8],
        )
    except SQLAlchemyError as e:  # DB 错误,fallback logger.error
        db.rollback()
        logger.error(
            "dlq handler SQLAlchemyError: task_id=%s name=%s err=%s",
            task_id_str, task_name, e,
        )
    except Exception as e:  # noqa: BLE001 — 兜底 catch 一切
        db.rollback()
        logger.error(
            "dlq handler unexpected error: task_id=%s name=%s err=%s",
            task_id_str, task_name, e, exc_info=True,
        )
    finally:
        db.close()


def install_dlq_signal() -> None:
    """注册 Celery ``task_failure`` 信号 handler。

    调用方:lumen_tasks.celery_app module 顶部,或在 worker_init 信号里
    装(后者更安全 — 每个 worker 进程独立注册,避免多 worker 重复 connect)。
    """
    from celery.signals import task_failure  # type: ignore[import-untyped]

    task_failure.connect(on_task_failure, weak=False)
    logger.info("celery task_failure dlq handler installed")


__all__ = ["on_task_failure", "install_dlq_signal"]