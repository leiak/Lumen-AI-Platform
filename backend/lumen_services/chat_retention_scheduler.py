"""2.1 C.1: 注册 chat hard-delete APScheduler cron 任务。

镜像 ``retention_scheduler.py`` 套路,复用 ``workflow_scheduler.get_scheduler()``
单例。每天 02:37 跑(避开 retention 02:17/02:27 + workflow scheduler 整点触发,
拉 10 分钟让 MySQL 不同时被 3 个 cron job 命中)。

max_instances=1 + coalesce=True:防止 worker crash 重叠跑 / 短窗口内累积多次
触发被合并成一次执行。

Spec: docs-internal/superpowers/specs/2026-09-07-lumen-2.1-spec.md §Phase 0 C.1
"""
from __future__ import annotations

import logging
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from lumen_services.chat_retention import (
    DEFAULT_DAYS_HARD,
    purge_old_chat_conversations,
)
from lumen_services.workflow_scheduler import get_scheduler

logger = logging.getLogger(__name__)


JOB_ID_CHAT_RETENTION = "chat_retention_hard"


def _run_chat_retention_hard():
    """02:37 每天触发 — hard-delete 30d+ soft-deleted conversations。"""
    try:
        result = purge_old_chat_conversations(days_hard=DEFAULT_DAYS_HARD)
        logger.info("chat_retention_hard cron: %s", result)
    except Exception:
        logger.exception("chat_retention_hard cron failed")


def register_chat_retention_jobs(
    scheduler: Optional[AsyncIOScheduler] = None,
) -> None:
    """注册 chat hard-delete cron job。Idempotent(replace_existing=True)。

    仅在 uvicorn WORKER_RANK=0 worker 跑(由 ``lumen_main.py`` lifespan 守门),
    防止 gunicorn 多 worker 同时跑同一个 cron。
    """
    if scheduler is None:
        scheduler = get_scheduler()

    scheduler.add_job(
        _run_chat_retention_hard,
        CronTrigger(hour=2, minute=37),
        id=JOB_ID_CHAT_RETENTION,
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    logger.info(
        "2.1 C.1 chat retention job registered (hard 02:37, days_hard=%d)",
        DEFAULT_DAYS_HARD,
    )