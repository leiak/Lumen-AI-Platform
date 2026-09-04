"""Phase 1 Group A 1.5 (2026-09-03): FailedTask admin read / retry schemas。

设计要点:
- ``FailedTaskRead`` 是 ORM ``FailedTask`` 的 Pydantic 投影,带可空字段
  (tenant_id 跨租户 admin 视图 / trace_id 关联日志)。
- ``FailedTaskRetryRequest`` 当前是空 schema(预留扩展点:未来支持
  强制覆盖 args/kwargs 或指定不同 queue);现在用空 body 派原任务。
- ``FailedTaskRetryResponse`` 返回 ``task_id``(Celery 新生成的 UUID),
  让 admin UI 能跳到 Celery flower 跟同一任务的最新执行。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class FailedTaskRead(BaseModel):
    """Celery 失败任务 DLQ row 读视图。

    ``model_config = ConfigDict(from_attributes=True)`` 允许
    ``FailedTaskRead.model_validate(failed_task_row)`` 直接吃 ORM 对象。
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: Optional[int] = None
    task_id: str
    task_name: str
    queue: Optional[str] = None
    args_json: Optional[Any] = None
    kwargs_json: Optional[Any] = None
    traceback_text: Optional[str] = None
    retry_count: int = 0
    max_retries_reached: bool = False
    first_failed_at: datetime
    last_failed_at: datetime
    acknowledged_at: Optional[datetime] = None
    acknowledged_by: Optional[int] = None
    trace_id: Optional[str] = None


class FailedTaskRetryRequest(BaseModel):
    """POST /admin/tasks/{id}/retry 请求体。

    当前所有字段都可选 — 不传 body 也行,默认用原任务记录的
    args_json / kwargs_json 重新派发。预留扩展:
    - ``args_override`` / ``kwargs_override``:把 args/kwargs 换成新值
    - ``queue_override``:把任务派到别的 queue(默认还是原 queue)
    - ``countdown: int``:延迟 N 秒后执行
    """


class FailedTaskRetryResponse(BaseModel):
    """POST /admin/tasks/{id}/retry 响应。

    ``new_task_id`` 是 Celery ``send_task`` 返回的 AsyncResult UUID;
    ``retry_count`` 是 FailedTask 表里"已被 admin 重派"次数(本表语义,
    不混 Celery 自动重试的 state.retries)。
    """

    new_task_id: str = Field(..., description="Celery 派发的新任务 UUID")
    retry_count: int = Field(..., description="本次重派后 FailedTask.retry_count")


class FailedTaskAckResponse(BaseModel):
    """POST /admin/tasks/{id}/ack 响应。"""

    id: int
    acknowledged_at: datetime
    acknowledged_by: int


__all__ = [
    "FailedTaskRead",
    "FailedTaskRetryRequest",
    "FailedTaskRetryResponse",
    "FailedTaskAckResponse",
]