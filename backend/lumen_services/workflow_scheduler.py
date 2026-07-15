import logging
from datetime import datetime
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.jobstores.memory import MemoryJobStore
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# Global scheduler instance
_scheduler: Optional[AsyncIOScheduler] = None


def get_scheduler() -> AsyncIOScheduler:
    """Get or create the global scheduler instance"""
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler(
            jobstores={"default": MemoryJobStore()},
            job_defaults={"coalesce": True, "max_instances": 1}
        )
    return _scheduler


def _strip_tz(dt):
    """APScheduler returns tz-aware datetimes; the column is naive."""
    if dt is None:
        return None
    if getattr(dt, "tzinfo", None) is not None:
        return dt.replace(tzinfo=None)
    return dt


class WorkflowSchedulerService:
    """Service for managing scheduled workflow executions"""

    def __init__(self):
        self.scheduler = get_scheduler()

    def _parse_cron(self, cron_expr: str) -> dict:
        """Parse cron expression into components"""
        parts = cron_expr.strip().split()
        if len(parts) != 5:
            raise ValueError(f"Invalid cron expression: {cron_expr}. Expected 5 parts (minute hour day month weekday)")

        return {
            "minute": parts[0],
            "hour": parts[1],
            "day": parts[2],
            "month": parts[3],
            "day_of_week": parts[4]
        }

    async def _execute_scheduled_workflow(self, workflow_id: int, tenant_id: int, input_data: dict):
        """
        Execute a scheduled workflow.

        Uses the unified ``WorkflowService.run_workflow`` so a real
        ``WorkflowRun`` row (with ``WorkflowNodeRun`` children) is
        persisted for every scheduled fire. ``last_run_at`` /
        ``next_run_at`` on the schedule itself are refreshed after
        completion.
        """
        from lumen_models.workflow import Workflow, WorkflowSchedule
        from lumen_services.workflow_service import WorkflowService
        from lumen_core.database import SessionLocal

        logger.info(f"Executing scheduled workflow {workflow_id} for tenant {tenant_id}")

        db = SessionLocal()
        try:
            workflow = db.query(Workflow).filter(
                Workflow.id == workflow_id,
                Workflow.tenant_id == tenant_id
            ).first()

            if not workflow:
                logger.error(f"Workflow {workflow_id} not found for tenant {tenant_id}")
                return

            if not workflow.is_active:
                logger.info(f"Workflow {workflow_id} is inactive, skipping execution")
                return

            service = WorkflowService()
            try:
                run = await service.run_workflow(
                    db,
                    workflow_id,
                    tenant_id,
                    input_data or {},
                    trigger_source="scheduled",
                )
                logger.info(
                    f"Scheduled workflow {workflow_id} run {run.id} status={run.status}"
                )
            except Exception as e:
                logger.error(f"Scheduled workflow {workflow_id} execution failed: {e}")

            # Refresh the schedule's run timestamps.
            schedule = (
                db.query(WorkflowSchedule)
                .filter(
                    WorkflowSchedule.workflow_id == workflow_id,
                    WorkflowSchedule.tenant_id == tenant_id,
                )
                .order_by(WorkflowSchedule.id.desc())
                .first()
            )
            if schedule is not None:
                schedule.last_run_at = datetime.utcnow()
                job = self.scheduler.get_job(f"workflow_{schedule.id}")
                if job is not None:
                    schedule.next_run_at = _strip_tz(job.next_run_time)
                try:
                    db.commit()
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Failed to update schedule run timestamps: %s", exc)

        except Exception as e:
            logger.error(f"Scheduled workflow {workflow_id} execution failed: {e}")
        finally:
            db.close()

    def add_schedule(
        self,
        schedule_id: int,
        workflow_id: int,
        tenant_id: int,
        cron_expression: str,
        input_data: dict = None,
    ) -> bool:
        """Add a scheduled job and persist ``next_run_at`` on the schedule row."""
        from lumen_models.workflow import WorkflowSchedule
        from lumen_core.database import SessionLocal

        try:
            cron_parts = self._parse_cron(cron_expression)
            trigger = CronTrigger(
                minute=cron_parts["minute"],
                hour=cron_parts["hour"],
                day=cron_parts["day"],
                month=cron_parts["month"],
                day_of_week=cron_parts["day_of_week"]
            )

            job_id = f"workflow_{schedule_id}"

            # Remove existing job if present
            if self.scheduler.get_job(job_id):
                self.scheduler.remove_job(job_id)

            self.scheduler.add_job(
                self._execute_scheduled_workflow,
                trigger=trigger,
                id=job_id,
                args=[workflow_id, tenant_id, input_data],
                replace_existing=True
            )

            # Persist next_run_at so callers can show "下次执行" without
            # poking the in-memory job store.
            try:
                db = SessionLocal()
                try:
                    schedule = db.query(WorkflowSchedule).filter(
                        WorkflowSchedule.id == schedule_id
                    ).first()
                    if schedule is not None:
                        job = self.scheduler.get_job(job_id)
                        schedule.next_run_at = _strip_tz(
                            job.next_run_time if job else None
                        )
                        db.commit()
                finally:
                    db.close()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to persist next_run_at for schedule %s: %s", schedule_id, exc)

            logger.info(f"Added schedule {schedule_id} for workflow {workflow_id} with cron {cron_expression}")
            return True

        except Exception as e:
            logger.error(f"Failed to add schedule {schedule_id}: {e}")
            return False

    def remove_schedule(self, schedule_id: int) -> bool:
        """Remove a scheduled job"""
        try:
            job_id = f"workflow_{schedule_id}"
            if self.scheduler.get_job(job_id):
                self.scheduler.remove_job(job_id)
                logger.info(f"Removed schedule {schedule_id}")
                return True
            return False
        except Exception as e:
            logger.error(f"Failed to remove schedule {schedule_id}: {e}")
            return False

    def update_schedule(
        self,
        schedule_id: int,
        workflow_id: int,
        tenant_id: int,
        cron_expression: str,
        input_data: dict = None,
        is_active: bool = True
    ) -> bool:
        """Update a scheduled job"""
        if not is_active:
            return self.remove_schedule(schedule_id)
        return self.add_schedule(schedule_id, workflow_id, tenant_id, cron_expression, input_data)

    def reload_schedules(self, db: Session) -> int:
        """
        Re-register every active schedule on the in-memory job store.

        Called from the FastAPI ``startup`` event so scheduled jobs
        survive an uvicorn worker restart (the in-memory job store is
        wiped on every process start).
        """
        from lumen_models.workflow import WorkflowSchedule

        count = 0
        try:
            active = (
                db.query(WorkflowSchedule)
                .filter(WorkflowSchedule.is_active == True)  # noqa: E712
                .all()
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to load schedules for reload: %s", exc)
            return 0

        for schedule in active:
            ok = self.add_schedule(
                schedule.id,
                schedule.workflow_id,
                schedule.tenant_id,
                schedule.cron_expression,
                schedule.input_data,
            )
            if ok:
                count += 1

        logger.info("Reloaded %d active schedule(s) from the database", count)
        return count

    def start(self):
        """Start the scheduler"""
        if not self.scheduler.running:
            self.scheduler.start()
            logger.info("Workflow scheduler started")

    def stop(self):
        """Stop the scheduler"""
        if self.scheduler.running:
            self.scheduler.shutdown()
            logger.info("Workflow scheduler stopped")


# Singleton instance
_scheduler_service: Optional[WorkflowSchedulerService] = None


def get_scheduler_service() -> WorkflowSchedulerService:
    """Get or create the scheduler service singleton"""
    global _scheduler_service
    if _scheduler_service is None:
        _scheduler_service = WorkflowSchedulerService()
    return _scheduler_service
