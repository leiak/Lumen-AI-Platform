"""Phase 1 Group A 1.5 (2026-09-03): admin DLQ endpoints for failed Celery tasks。

提供 3 个 endpoint:
- ``GET /api/v1/admin/tasks/failed`` — 分页列出失败任务,可按
  ``tenant_id`` / ``task_name`` / ``acknowledged`` 过滤。
- ``POST /api/v1/admin/tasks/{id}/retry`` — 通过 ``celery_app.send_task()``
  重新派发,把 ``retry_count`` + 1 + ``last_failed_at`` 更新到当前。
  **不删除 row**(保留为审计轨迹;后续真正成功的任务不入 DLQ,下一次
  同样 task_id 再失败会走 upsert 累加 retry_count)。
- ``POST /api/v1/admin/tasks/{id}/ack`` — 把 ``acknowledged_at`` +
  ``acknowledged_by`` 写入,前端默认只展示未 ack 的告警。

设计要点:
- 复用 ``admin_skills._require_admin()`` 模式(``is_superuser`` 校验);
  跨租户 admin(没有 tenant_id 限制)直接看所有 FailedTask。
- 重派走 ``celery_app.send_task(task_name, args=args, kwargs=kwargs,
  queue=queue)``,不重新构造 task object —— 这样能命中 ``task_routes``
  跟 ``acks_late`` 等所有 celery_app 配置(``@celery_app.task`` 装饰过的
  task 名走 ``app.tasks`` 也能命中)。
- 重派新生成的 task_id 跟 FailedTask.task_id **不同**,所以 DLQ row
  不会被 on_task_failure upsert 覆盖(UNIQUE on task_id);用户想
  跟踪重派结果要看 celery flower / 日志,或者靠 trace_id 关联。
- handler / endpoint 全 try/except 包死,DB 错误返 500(让 admin UI
  提示"失败,请重试");DB 成功返 200 + 更新后的 row。
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from lumen_api.v1.auth import get_current_user
from lumen_core.database import get_db
from lumen_models.failed_task import FailedTask
from lumen_models.user import User
from lumen_schemas.common import PaginatedResponse, SingleResponse
from lumen_schemas.failed_task import (
    FailedTaskAckResponse,
    FailedTaskRead,
    FailedTaskRetryResponse,
)
from lumen_tasks.celery_app import celery_app

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/tasks", tags=["admin-tasks"])


def _require_admin(user: User) -> None:
    """复用 admin_skills.py 同样的 superuser 校验模式。"""
    if not getattr(user, "is_superuser", False):
        raise HTTPException(status_code=403, detail="Admin only")


@router.get("/failed", response_model=PaginatedResponse[FailedTaskRead])
async def list_failed_tasks(
    tenant_id: Optional[int] = Query(
        None, description="按 tenant_id 过滤;None = 所有租户(跨租户 admin 视图)"
    ),
    task_name: Optional[str] = Query(
        None, description="按 task_name 精确过滤(如 'lumen_tasks.document_tasks.process_document')"
    ),
    acknowledged: Optional[bool] = Query(
        None,
        description="True = 仅已 ack;False = 仅未 ack;None = 全部。"
        "默认 admin UI 想看未处理告警用 acknowledged=false",
    ),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Any:
    """Admin: list failed Celery tasks (DLQ)."""
    _require_admin(current_user)

    q = db.query(FailedTask)
    if tenant_id is not None:
        q = q.filter(FailedTask.tenant_id == tenant_id)
    if task_name is not None:
        q = q.filter(FailedTask.task_name == task_name)
    if acknowledged is True:
        q = q.filter(FailedTask.acknowledged_at.isnot(None))
    elif acknowledged is False:
        q = q.filter(FailedTask.acknowledged_at.is_(None))

    # 默认按 last_failed_at DESC(最近失败在前,符合 admin 排障心智)
    q = q.order_by(FailedTask.last_failed_at.desc())

    total = q.count()
    rows = q.offset((page - 1) * page_size).limit(page_size).all()
    return PaginatedResponse(
        data=[FailedTaskRead.model_validate(r) for r in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("/{task_id}/retry", response_model=SingleResponse[FailedTaskRetryResponse])
async def retry_failed_task(
    task_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Any:
    """Admin: 重派 failed_task row。"""
    _require_admin(current_user)

    row = db.query(FailedTask).filter(FailedTask.id == task_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail=f"FailedTask id={task_id} not found")

    # 解 args / kwargs — FailedTask 表存的 JSON 字段(FailedTask.args_json
    # / kwargs_json),重新喂给 celery_app.send_task。json.loads 把 None / 缺
    # 失 → None。
    raw_args = row.args_json
    raw_kwargs = row.kwargs_json
    args: tuple = tuple(raw_args) if isinstance(raw_args, list) else ()
    kwargs: dict = raw_kwargs if isinstance(raw_kwargs, dict) else {}

    try:
        async_result = celery_app.send_task(
            row.task_name,
            args=args,
            kwargs=kwargs,
            queue=row.queue,
        )
    except Exception as e:  # noqa: BLE001 — celery broker 挂等
        logger.exception(
            "admin retry failed: celery_app.send_task raised FailedTask id=%s err=%s",
            task_id,
            e,
        )
        raise HTTPException(
            status_code=503,
            detail=f"Celery broker 派任务失败: {e}",
            headers={"Retry-After": "5"},
        )

    new_task_id = async_result.id
    # 更新 DLQ row — retry_count++ + last_failed_at = NOW(语义:上次失败时间)
    # 不改名 task_id(保留原 UUID),admin 能用 page trace_id 串联老失败 +
    # 新重派;trace_signals 同步会让 producer 端 trace_id 注入新 task header。
    row.retry_count = (row.retry_count or 0) + 1  # type: ignore[assignment]
    row.last_failed_at = datetime.utcnow()  # type: ignore[assignment]
    # 重派后默认清 ack(算新的告警)
    row.acknowledged_at = None  # type: ignore[assignment]
    row.acknowledged_by = None  # type: ignore[assignment]
    db.commit()

    logger.info(
        "admin retried FailedTask id=%s task_name=%s new_task_id=%s by user=%s",
        task_id,
        row.task_name,
        new_task_id,
        current_user.id,
    )
    return SingleResponse(
        data=FailedTaskRetryResponse(
            new_task_id=new_task_id,
            retry_count=row.retry_count,  # type: ignore[arg-type]
        )
    )


@router.post("/{task_id}/ack", response_model=SingleResponse[FailedTaskAckResponse])
async def acknowledge_failed_task(
    task_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Any:
    """Admin: 标记 FailedTask row 已处理(不再显示在未 ack 告警列表)。"""
    _require_admin(current_user)

    row = db.query(FailedTask).filter(FailedTask.id == task_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail=f"FailedTask id={task_id} not found")

    now = datetime.utcnow()
    row.acknowledged_at = now  # type: ignore[assignment]
    row.acknowledged_by = current_user.id  # type: ignore[assignment]
    db.commit()
    db.refresh(row)

    return SingleResponse(
        data=FailedTaskAckResponse(
            id=row.id,  # type: ignore[arg-type]
            acknowledged_at=row.acknowledged_at,  # type: ignore[arg-type]
            acknowledged_by=row.acknowledged_by,  # type: ignore[arg-type]
        )
    )


__all__ = ["router"]