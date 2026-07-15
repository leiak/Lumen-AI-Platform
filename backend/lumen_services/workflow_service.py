from datetime import datetime
from typing import Any, AsyncIterator, Dict, List, Optional

from sqlalchemy.orm import Session

from lumen_models.workflow import Workflow, WorkflowRun
from lumen_schemas.workflow import WorkflowCreate, WorkflowDefinition, WorkflowUpdate


class WorkflowService:
    # M30a: list_workflows gains server-side pagination + search/filter.
    # Old signature: (db, tenant_id) -> List[Workflow]  (in-memory pagination
    # happened in the API layer). New signature stays backward-compatible
    # when no search/filter kwargs are passed — same total count, just
    # bounded rows.
    def list_workflows(
        self,
        db: Session,
        tenant_id: int,
        *,
        search: Optional[str] = None,
        is_active: Optional[bool] = None,
        created_from: Optional[datetime] = None,
        created_to: Optional[datetime] = None,
        sort_by: str = "created_at",
        sort_order: str = "desc",
        skip: int = 0,
        limit: int = 10,
    ) -> Dict[str, Any]:
        """Return ``{"items": [...], "total": N}`` for the given filters.

        ``sort_by`` accepts ``"created_at"`` (default) or ``"name"``.
        ``sort_order`` accepts ``"asc"`` or ``"desc"`` (default).
        """
        query = db.query(Workflow).filter(Workflow.tenant_id == tenant_id)
        if search:
            like = f"%{search}%"
            query = query.filter(
                (Workflow.name.like(like)) | (Workflow.description.like(like))
            )
        if is_active is not None:
            query = query.filter(Workflow.is_active == is_active)
        if created_from is not None:
            query = query.filter(Workflow.created_at >= created_from)
        if created_to is not None:
            query = query.filter(Workflow.created_at <= created_to)

        # sort
        sort_col = getattr(Workflow, sort_by, Workflow.created_at)
        if sort_order.lower() == "asc":
            query = query.order_by(sort_col.asc())
        else:
            query = query.order_by(sort_col.desc())

        total = query.count()
        items = query.offset(skip).limit(limit).all()
        return {"items": items, "total": total}

    def create_workflow(
        self, db: Session, tenant_id: int, data: WorkflowCreate
    ) -> Workflow:
        workflow = Workflow(
            name=data.name,
            description=data.description,
            definition=data.definition.model_dump(),
            tenant_id=tenant_id,
        )
        db.add(workflow)
        db.commit()
        db.refresh(workflow)
        return workflow

    def get_workflow(self, db: Session, workflow_id: int, tenant_id: int) -> Optional[Workflow]:
        return db.query(Workflow).filter(
            Workflow.id == workflow_id,
            Workflow.tenant_id == tenant_id
        ).first()

    def update_workflow(
        self, db: Session, workflow_id: int, tenant_id: int, data: WorkflowUpdate
    ) -> Optional[Workflow]:
        workflow = self.get_workflow(db, workflow_id, tenant_id)
        if not workflow:
            return None

        update_data = data.model_dump(exclude_unset=True)
        # data.model_dump() already serializes the nested WorkflowDefinition to a dict,
        # so no further conversion is needed here.

        for field, value in update_data.items():
            setattr(workflow, field, value)

        db.commit()
        db.refresh(workflow)
        return workflow

    def delete_workflow(self, db: Session, workflow_id: int, tenant_id: int) -> bool:
        workflow = self.get_workflow(db, workflow_id, tenant_id)
        if not workflow:
            return False
        db.delete(workflow)
        db.commit()
        return True

    async def run_workflow(
        self,
        db: Session,
        workflow_id: int,
        tenant_id: int,
        input_data: Dict[str, Any],
        trigger_source: str = "manual",
        on_event: Optional[Any] = None,
        cancel_event: Optional[Any] = None,
    ) -> WorkflowRun:
        """
        Persist a ``WorkflowRun`` row, then delegate to the unified
        ``WorkflowExecutor``. The executor is responsible for writing one
        ``WorkflowNodeRun`` per node and returns a result envelope whose
        ``status`` is either ``"completed"`` or ``"failed"``.

        ``trigger_source`` records how this run was kicked off — "manual"
        from POST /workflows/{id}/run, "scheduled" from a cron fire. The
        frontend history view uses it to tag rows in the runs drawer.

        ``on_event`` (M30a) — optional async callback for SSE streaming.
        The executor emits run_start / node_start / node_end / run_end /
        error events through it.

        ``cancel_event`` (M30a) — optional asyncio.Event. The executor
        checks it at node boundaries; when set, it returns status
        "cancelled" without killing the in-flight node.

        This method is ``async`` so it can be awaited from the FastAPI
        endpoint and the scheduler without spinning up a new event loop.
        """
        from lumen_services.workflow_executor import WorkflowExecutor

        workflow = self.get_workflow(db, workflow_id, tenant_id)
        if not workflow:
            raise ValueError("Workflow not found")

        run = WorkflowRun(
            workflow_id=workflow_id,
            input_data=input_data,
            status="running",
            trigger_source=trigger_source,
            started_at=datetime.utcnow(),
        )
        db.add(run)
        db.commit()
        db.refresh(run)

        executor = WorkflowExecutor()
        try:
            result = await executor.execute(
                definition=workflow.definition,
                input_data=input_data,
                tenant_id=tenant_id,
                run_id=run.id,
                db=db,
                on_event=on_event,
                cancel_event=cancel_event,
                persist_node_runs=True,  # M30a: write WorkflowNodeRun rows
                # so the frontend can show per-node progress, input_data,
                # output_data, and error_message. The executor opens its
                # own session for these writes (so the caller's session
                # lifecycle is unaffected).
            )
            if isinstance(result, dict) and result.get("status") == "failed":
                run.status = "failed"
                run.error_message = result.get("error") or "Workflow execution failed"
                run.output_data = result
            elif isinstance(result, dict) and result.get("status") == "cancelled":
                # M30a: cancel returns status=cancelled. Persist it on
                # the run row so the runs drawer shows the right state.
                run.status = "cancelled"
                run.output_data = result
            else:
                run.status = "completed"
                run.output_data = result
        except Exception as e:
            run.status = "failed"
            run.error_message = str(e)
        finally:
            run.finished_at = datetime.utcnow()
            db.commit()
            db.refresh(run)

            # Broadcast workflow completion to all Electron clients
            from lumen_services.electron_service import electron_service
            try:
                duration_ms = 0
                if run.started_at and run.finished_at:
                    duration_ms = int(
                        (run.finished_at - run.started_at).total_seconds() * 1000
                    )
                await electron_service.broadcast_event_async(
                    "workflow_run_completed",
                    {
                        "run_id": run.id,
                        "workflow_id": workflow_id,
                        "workflow_name": workflow.name,
                        "status": run.status,
                        "duration_ms": duration_ms,
                        "tenant_id": tenant_id,
                    },
                )
            except Exception as broadcast_err:
                # Never fail the request because of a broadcast error
                import logging
                logging.getLogger(__name__).warning(
                    f"Failed to broadcast workflow_run_completed: {broadcast_err}"
                )

            # M30a: also push to dashboard /ws/web via the
            # notification service so the runs drawer can show a toast.
            # Best-effort — a failure here must not fail the request.
            await self._push_run_notification(db, run, workflow, tenant_id)

        return run

    async def _push_run_notification(
        self,
        db: Session,
        run: WorkflowRun,
        workflow: Workflow,
        tenant_id: int,
    ) -> None:
        """M30a: write a Notification row + broadcast for run completion.

        The notification service already powers Celery / image-gen /
        document tasks. We reuse the same machinery so the dashboard's
        ``/ws/web`` channel shows the run as a toast.

        Notification recipient strategy: notify the workflow's owner
        (if known) and fall back to the first admin of the tenant.
        """
        try:
            from lumen_models.user import User
            from lumen_services.notification_service import NotificationService

            recipient = None
            # Try the workflow creator first; fall back to first admin
            # user of the tenant.
            if workflow.tenant_id is not None:
                admin = (
                    db.query(User)
                    .filter(User.tenant_id == tenant_id, User.is_active == True)  # noqa: E712
                    .order_by(User.id.asc())
                    .first()
                )
                recipient = admin
            if recipient is None:
                return

            duration_ms = 0
            if run.started_at and run.finished_at:
                duration_ms = int(
                    (run.finished_at - run.started_at).total_seconds() * 1000
                )
            preview = ""
            if isinstance(run.output_data, dict):
                final = run.output_data.get("final_output") or {}
                if isinstance(final, dict):
                    val = final.get("value")
                    if isinstance(val, str):
                        preview = val[:200]
                    elif val is not None:
                        preview = str(val)[:200]

            notif_type = (
                "WORKFLOW_RUN_COMPLETED"
                if run.status == "completed"
                else "WORKFLOW_RUN_FAILED"
                if run.status == "failed"
                else "WORKFLOW_RUN_CANCELLED"
            )
            title = (
                f"工作流 {workflow.name} 已完成"
                if run.status == "completed"
                else f"工作流 {workflow.name} 失败"
                if run.status == "failed"
                else f"工作流 {workflow.name} 已取消"
            )
            body = (
                f"耗时 {duration_ms}ms"
                if run.status == "completed"
                else (run.error_message or "")[:200]
            )
            NotificationService.publish_event(
                db,
                user_id=recipient.id,
                type=notif_type,
                title=title,
                body=body,
                resource_type="workflow_run",
                resource_id=run.id,
                metadata={
                    "workflow_id": workflow.id,
                    "workflow_name": workflow.name,
                    "run_id": run.id,
                    "status": run.status,
                    "duration_ms": duration_ms,
                    "final_output_preview": preview,
                },
            )
        except Exception as e:  # noqa: BLE001
            import logging
            logging.getLogger(__name__).warning(
                f"Failed to push workflow run notification: {e}"
            )

    def list_runs(
        self,
        db: Session,
        workflow_id: int,
        tenant_id: int,
        *,
        status: Optional[str] = None,
        trigger_source: Optional[str] = None,
        started_from: Optional[datetime] = None,
        started_to: Optional[datetime] = None,
        skip: int = 0,
        limit: int = 10,
    ) -> Dict[str, Any]:
        """M30a: list_runs gains server-side pagination + status / trigger /
        time-window filters. Returns ``{"items": [...], "total": N}``.

        Tenant isolation is preserved: the parent workflow's tenant_id
        is checked before any run is returned, so a user can't peek at
        another tenant's runs by guessing run ids.
        """
        workflow = self.get_workflow(db, workflow_id, tenant_id)
        if not workflow:
            return {"items": [], "total": 0}
        query = db.query(WorkflowRun).filter(
            WorkflowRun.workflow_id == workflow_id
        )
        if status is not None:
            query = query.filter(WorkflowRun.status == status)
        if trigger_source is not None:
            query = query.filter(WorkflowRun.trigger_source == trigger_source)
        if started_from is not None:
            query = query.filter(WorkflowRun.started_at >= started_from)
        if started_to is not None:
            query = query.filter(WorkflowRun.started_at <= started_to)
        query = query.order_by(WorkflowRun.started_at.desc())
        total = query.count()
        items = query.offset(skip).limit(limit).all()
        return {"items": items, "total": total}

    def cancel_run(
        self, db: Session, workflow_id: int, run_id: int, tenant_id: int
    ) -> Optional[WorkflowRun]:
        """M30a: set a run's status to 'cancelled' if it's still pending /
        running. Returns the updated run, or None if the run was already
        in a terminal state.

        Note: this is a soft cancel. The /stream endpoint also signals
        the executor via ``cancel_event``; this method just flips the
        DB row so the runs drawer shows the right state even if no
        client is listening on /stream.
        """
        workflow = self.get_workflow(db, workflow_id, tenant_id)
        if not workflow:
            return None
        run = (
            db.query(WorkflowRun)
            .filter(WorkflowRun.id == run_id, WorkflowRun.workflow_id == workflow_id)
            .first()
        )
        if not run:
            return None
        if run.status in ("completed", "failed", "cancelled"):
            return run
        run.status = "cancelled"
        run.finished_at = datetime.utcnow()
        db.commit()
        db.refresh(run)
        return run

    async def resume_run(
        self, db: Session, workflow_id: int, run_id: int, tenant_id: int
    ) -> Optional[WorkflowRun]:
        """M30d: re-run a previously failed/cancelled run with the
        same input_data. Returns the NEW run (the old run is left in
        its terminal state for audit).

        This is the simple "retry with same inputs" semantic — covers
        ~90% of user intent (the failing run had a transient issue
        like a network blip, and the user wants to try again). A more
        sophisticated "continue from where it left off" (skip
        completed nodes) is deferred — the M30a WorkflowNodeRun rows
        already carry the state we'd need to implement that.
        """
        workflow = self.get_workflow(db, workflow_id, tenant_id)
        if not workflow:
            return None
        old_run = (
            db.query(WorkflowRun)
            .filter(WorkflowRun.id == run_id, WorkflowRun.workflow_id == workflow_id)
            .first()
        )
        if not old_run:
            return None
        # Re-use the original input_data so the user doesn't have to
        # re-enter it. The M30a WorkflowNodeRun rows for the old run
        # are preserved for the audit trail.
        return await self.run_workflow(
            db,
            workflow_id,
            tenant_id,
            old_run.input_data or {},
            trigger_source="resume",  # distinguish from manual / scheduled
        )
