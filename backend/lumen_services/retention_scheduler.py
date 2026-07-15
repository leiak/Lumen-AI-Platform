"""M27 retention scheduler — registers two APScheduler cron jobs.

Mirrors the singleton pattern from ``workflow_scheduler.py``. We reuse
the same global ``AsyncIOScheduler`` instance that the workflow
service started (``get_scheduler()``) so we have exactly one scheduler
running per uvicorn worker. Both jobs run in the same process as the
API server (no separate Celery worker) — they're DB-only sweeps and
they self-bound their batch size, so they're cheap enough to be
in-process.

Cron schedule (chosen to avoid the :00 / :30 mark per Claude Code
``CronCreate`` guidance: jobs that hit the API at the same instant
across deployments cause thundering herds).

- ``retention_hard``: 02:17 every day — hard-delete rows older than
  ``DEFAULT_DAYS_HARD`` (180 days)
- ``retention_soft``: 02:27 every day — soft-delete rows older than
  ``DEFAULT_DAYS_SOFT`` (90 days)

The hard sweep runs FIRST so a row at age=181 gets deleted rather than
first soft-flagged then deleted on the next pass (two writes per row
instead of one).

Spec: docs/superpowers/specs/2026-06-15-embedding-trace-retention.md §"治理"
"""
from __future__ import annotations

import logging
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from lumen_services.retention import (
    DEFAULT_DAYS_HARD,
    DEFAULT_DAYS_SOFT,
    archive_old_logs,
)
from lumen_services.workflow_scheduler import get_scheduler

logger = logging.getLogger(__name__)


# Job ids — used by callers to inspect / pause / replace.
JOB_ID_RETENTION_HARD = "retention_hard"
JOB_ID_RETENTION_SOFT = "retention_soft"


def _run_retention_hard_only():
    """Wrapper that hard-deletes only — used at 02:17 daily."""
    try:
        result = archive_old_logs(
            days_soft=DEFAULT_DAYS_SOFT,
            days_hard=DEFAULT_DAYS_HARD,
        )
        logger.info("retention_hard cron: %s", result)
    except Exception:
        logger.exception("retention_hard cron failed")


def _run_retention_soft_only():
    """Wrapper that runs the full sweep — soft-delete pass.

    Note: ``archive_old_logs`` already does both passes in a single
    call; this wrapper exists to keep job decomposition tidy in
    APScheduler (one job id per cron entry) and for future per-pass
    tuning. Today the soft pass is a no-op after the hard pass
    finished a few minutes earlier (it already picked up the
    180+-day rows), so this is just the 90-180 day band.
    """
    try:
        result = archive_old_logs(
            days_soft=DEFAULT_DAYS_SOFT,
            days_hard=DEFAULT_DAYS_HARD,
        )
        logger.info("retention_soft cron: %s", result)
    except Exception:
        logger.exception("retention_soft cron failed")


def register_retention_jobs(
    scheduler: Optional[AsyncIOScheduler] = None,
) -> None:
    """Register the two retention cron jobs on the shared scheduler.

    Idempotent: ``replace_existing=True`` so a uvicorn restart
    re-registers cleanly.
    """
    if scheduler is None:
        scheduler = get_scheduler()

    scheduler.add_job(
        _run_retention_hard_only,
        CronTrigger(hour=2, minute=17),
        id=JOB_ID_RETENTION_HARD,
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        _run_retention_soft_only,
        CronTrigger(hour=2, minute=27),
        id=JOB_ID_RETENTION_SOFT,
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    logger.info("M27 retention jobs registered (hard 02:17, soft 02:27)")
