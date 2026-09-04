"""Phase 1 Group A 1.5 (2026-09-03): Celery 失败任务 DLQ ORM。

**做什么**:Celery `task_failure` 信号触发时,把失败任务 + traceback 落到
``failed_tasks`` 表里,让 admin 能查 / 重派 / ack。Phase 0 默认 Celery
失败任务默默丢,只有 celery worker 日志能看 —— 生产环境不便排障。

**为什么不用 Celery 自带 result backend**:Celery result backend 主要设计
是"任务成功结果缓存",失败任务也会写但用不同的 meta 字段,查询不友好。
独立 DLQ 表让 admin 视图 / 监控 / 告警独立演化,不污染 result backend。

**Schema 设计**:
- ``task_id`` UNIQUE —— Celery UUID,upsert 友好(同一 task retry 累加
  retry_count,而不是新 row)。
- ``tenant_id`` NULLABLE —— 跨租户 admin 视图(FAIL_ADMIN 可看所有租户)。
- ``trace_id`` VARCHAR(32) —— 跟 Phase 0 ship 的 trace_id 关联,admin
  跳日志。
- ``max_retries_reached`` —— 默认 ``autoretry_for=(), max_retries=0``
  的项目语境下永远 True;但保留 flag 让未来引入 retry policy 的 task
  能区分"已重试用尽"和"首次失败"。
- ``acknowledged_at`` / ``acknowledged_by`` —— admin mark 看的告警已
  处理(类似 mail 的 read 标记)。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)

from lumen_core.database import Base
from lumen_models.base import BaseModel


class FailedTask(BaseModel):
    """Celery 失败任务 DLQ row。

    ORM model 字段顺序匹配 DB DDL(see ``ensure_failed_tasks_table``):
    - id / task_id / task_name 是主键 + 唯一约束
    - args / kwargs JSON 让 admin retry 时能完整重派
    - traceback_text TEXT 留 64KB 限制外的 traceback(MEDIUMTEXT 65535,
      常见 celery 失败 traceback ~10KB,留 64KB 富余)
    - retry_count 记录"这个 task 已经被 admin 重派过几次",不混 Celery
      的自动重试(项目语境下 autoretry_for=() max_retries=0,不混)
    """

    __tablename__ = "failed_tasks"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    # 跨租户 admin 视图:tenant_id NULL 表示 task 跟租户无关(系统级 task)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=True, index=True)
    task_id = Column(String(64), nullable=False, unique=True, index=True)
    task_name = Column(String(200), nullable=False, index=True)
    queue = Column(String(50), nullable=True)
    args_json = Column(JSON, nullable=True)
    kwargs_json = Column(JSON, nullable=True)
    traceback_text = Column(Text, nullable=True)
    retry_count = Column(Integer, default=0, nullable=False)
    max_retries_reached = Column(Boolean, default=False, nullable=False)
    first_failed_at = Column(
        DateTime, default=datetime.utcnow, nullable=False,
    )
    last_failed_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )
    # trace_id VARCHAR(32) 跟 lumen_core.tracing.set_trace_id 设的 32 字符 hex 一致
    trace_id = Column(String(32), nullable=True, index=True)
    # admin 处理的标记
    acknowledged_at = Column(DateTime, nullable=True)
    acknowledged_by = Column(Integer, ForeignKey("users.id"), nullable=True)

    __table_args__ = (
        Index("ix_failed_tasks_unacknowledged", "acknowledged_at", "last_failed_at"),
        UniqueConstraint("task_id", name="uq_failed_tasks_task_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<FailedTask id={self.id} task_id={self.task_id} "
            f"name={self.task_name} retry_count={self.retry_count}>"
        )


__all__ = ["FailedTask"]