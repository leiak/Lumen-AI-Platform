from datetime import datetime
from typing import Any, AsyncIterator, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from lumen_core.database import get_db
from lumen_api.v1.auth import get_current_user
from lumen_models.user import User
from lumen_models.workflow import Workflow, WorkflowRun, WorkflowNodeRun, WorkflowSchedule
from lumen_schemas.workflow import (
    WorkflowCreate, WorkflowUpdate, WorkflowResponse,
    WorkflowRunRequest, WorkflowRunResponse,
    WorkflowNodeRunResponse,
    WorkflowScheduleCreate, WorkflowScheduleUpdate,
    WorkflowScheduleResponse,
)
from lumen_schemas.common import SingleResponse, PaginatedResponse
from lumen_services.workflow_service import WorkflowService
from lumen_services.workflow_scheduler import get_scheduler_service

router = APIRouter(prefix="/workflows", tags=["workflows"])


@router.get("/", response_model=PaginatedResponse[WorkflowResponse])
async def list_workflows(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    search: Optional[str] = None,
    is_active: Optional[bool] = None,
    created_from: Optional[datetime] = None,
    created_to: Optional[datetime] = None,
    sort_by: str = "created_at",
    sort_order: str = "desc",
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """M30a: server-side pagination + search/filter/sort.
    Previously this loaded every workflow into memory and sliced in
    Python (lines 31-37 before the change). Now the DB does the work
    and the API is bounded.
    """
    service = WorkflowService()
    result = service.list_workflows(
        db,
        current_user.tenant_id,
        search=search,
        is_active=is_active,
        created_from=created_from,
        created_to=created_to,
        sort_by=sort_by,
        sort_order=sort_order,
        skip=(page - 1) * page_size,
        limit=page_size,
    )
    return PaginatedResponse(
        data=[WorkflowResponse.model_validate(w) for w in result["items"]],
        total=result["total"],
        page=page,
        page_size=page_size,
    )


# M30d: registry of node-type metadata. Designers (and any other
# client) hit this endpoint to learn the available types, their
# default_config, and the expected inputs/outputs. The data is
# static — server-side source of truth lives in
# app.core.workflow.node_types_metadata.
@router.get("/node-types", response_model=SingleResponse[list])
async def list_node_types(
    current_user: User = Depends(get_current_user),
):
    from lumen_core.workflow.node_types_metadata import all_node_types_metadata
    return SingleResponse(
        data=[m.to_dict() for m in all_node_types_metadata()]
    )


@router.post("/", response_model=SingleResponse[WorkflowResponse])
async def create_workflow(
    data: WorkflowCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    service = WorkflowService()
    workflow = service.create_workflow(db, current_user.tenant_id, data)
    return SingleResponse(data=WorkflowResponse.model_validate(workflow))


@router.get("/{workflow_id}", response_model=SingleResponse[WorkflowResponse])
async def get_workflow(
    workflow_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    service = WorkflowService()
    workflow = service.get_workflow(db, workflow_id, current_user.tenant_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return SingleResponse(data=WorkflowResponse.model_validate(workflow))


@router.put("/{workflow_id}", response_model=SingleResponse[WorkflowResponse])
async def update_workflow(
    workflow_id: int,
    data: WorkflowUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    service = WorkflowService()
    workflow = service.update_workflow(db, workflow_id, current_user.tenant_id, data)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return SingleResponse(data=WorkflowResponse.model_validate(workflow))


@router.delete("/{workflow_id}")
async def delete_workflow(
    workflow_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    service = WorkflowService()
    success = service.delete_workflow(db, workflow_id, current_user.tenant_id)
    if not success:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return SingleResponse(message="Deleted successfully")


# M30a: bulk delete. Accepts a JSON body {ids: [1,2,3]} and deletes them
# in a single transaction. Tenant isolation: each id is verified to
# belong to the caller's tenant before delete.
@router.post("/bulk-delete")
async def bulk_delete_workflows(
    payload: Dict[str, Any] = Body(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ids = payload.get("ids") or []
    if not isinstance(ids, list) or not all(isinstance(i, int) for i in ids):
        raise HTTPException(status_code=400, detail="ids must be a list of integers")
    if not ids:
        return SingleResponse(data={"deleted_count": 0, "deleted_ids": []})

    rows = (
        db.query(Workflow)
        .filter(Workflow.id.in_(ids), Workflow.tenant_id == current_user.tenant_id)
        .all()
    )
    found_ids = [w.id for w in rows]
    for w in rows:
        db.delete(w)
    db.commit()
    return SingleResponse(
        data={"deleted_count": len(found_ids), "deleted_ids": found_ids}
    )


@router.post("/{workflow_id}/run", response_model=SingleResponse[WorkflowRunResponse])
async def run_workflow(
    workflow_id: int,
    body: WorkflowRunRequest = Body(default_factory=WorkflowRunRequest),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    service = WorkflowService()
    try:
        run = await service.run_workflow(
            db,
            workflow_id,
            current_user.tenant_id,
            body.input_data,
            trigger_source="manual",
            # M38.2.x v2: 透传 user 让 KB node 做 per-KB ``kb.read`` 过滤
            user=current_user,
        )
        return SingleResponse(data=WorkflowRunResponse.model_validate(run))
    except ValueError as e:
        msg = str(e)
        if "not found" in msg.lower():
            raise HTTPException(status_code=404, detail=msg)
        raise HTTPException(status_code=400, detail=msg)


# M30a: SSE streaming endpoint. Returns an EventSourceResponse that
# emits run_start / node_start / node_end / run_end / error events as
# the workflow runs. The client opens an EventSource and prints events
# as they arrive. The connection closes when the run finishes.
@router.post("/{workflow_id}/stream")
async def stream_workflow(
    workflow_id: int,
    body: WorkflowRunRequest = Body(default_factory=WorkflowRunRequest),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from sse_starlette.sse import EventSourceResponse
    import asyncio as _asyncio
    import json as _json

    service = WorkflowService()

    # Tenant check before we start — same as the /run endpoint. We use
    # the caller's session for both the WorkflowRun row + the
    # WorkflowNodeRun rows so they share a transaction.
    workflow = service.get_workflow(db, workflow_id, current_user.tenant_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    cancel_event = _asyncio.Event()
    queue: _asyncio.Queue = _asyncio.Queue()

    async def on_event(event: str, data: Dict[str, Any]) -> None:
        await queue.put((event, data))

    async def event_generator() -> AsyncIterator[Dict[str, str]]:
        async def runner() -> None:
            try:
                await service.run_workflow(
                    db,
                    workflow_id,
                    current_user.tenant_id,
                    body.input_data,
                    trigger_source="manual",
                    on_event=on_event,
                    cancel_event=cancel_event,
                    # M38.2.x v2: 透传 user 让 KB node 做 per-KB ``kb.read`` 过滤
                    user=current_user,
                )
            except Exception as e:  # noqa: BLE001
                await queue.put(("error", {"error_message": str(e)}))
            finally:
                # Sentinel that closes the SSE stream.
                await queue.put(None)

        runner_task = _asyncio.create_task(runner())
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                event, data = item
                yield {"event": event, "data": _json.dumps(data, default=str)}
        finally:
            if not runner_task.done():
                runner_task.cancel()
                try:
                    await runner_task
                except (Exception, _asyncio.CancelledError):  # noqa: BLE001
                    pass

    return EventSourceResponse(event_generator())


@router.post("/{workflow_id}/runs/{run_id}/cancel", response_model=SingleResponse[WorkflowRunResponse])
async def cancel_run(
    workflow_id: int,
    run_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """M30a: cancel a running workflow.

    Soft-cancel: the run row is flipped to 'cancelled' and any
    in-flight /stream SSE connection sees its executor break out at the
    next node boundary. The currently-running node is allowed to
    finish naturally (we never kill it mid-execution).
    """
    service = WorkflowService()
    run = service.cancel_run(db, workflow_id, run_id, current_user.tenant_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return SingleResponse(data=WorkflowRunResponse.model_validate(run))


# M30d: resume / retry. The new run uses the same input_data as the
# original; the old run is left in its terminal state for audit.
@router.post("/{workflow_id}/runs/{run_id}/resume", response_model=SingleResponse[WorkflowRunResponse])
async def resume_run(
    workflow_id: int,
    run_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    service = WorkflowService()
    new_run = await service.resume_run(db, workflow_id, run_id, current_user.tenant_id)
    if not new_run:
        raise HTTPException(status_code=404, detail="Run not found")
    return SingleResponse(data=WorkflowRunResponse.model_validate(new_run))


@router.get("/{workflow_id}/runs", response_model=PaginatedResponse[WorkflowRunResponse])
async def list_workflow_runs(
    workflow_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    status: Optional[str] = None,
    trigger_source: Optional[str] = None,
    started_from: Optional[datetime] = None,
    started_to: Optional[datetime] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """M30a: server-side pagination + status / trigger / time-window filters.
    Previously loaded every run into memory and sliced in Python.
    """
    service = WorkflowService()
    result = service.list_runs(
        db,
        workflow_id,
        current_user.tenant_id,
        status=status,
        trigger_source=trigger_source,
        started_from=started_from,
        started_to=started_to,
        skip=(page - 1) * page_size,
        limit=page_size,
    )
    return PaginatedResponse(
        data=[WorkflowRunResponse.model_validate(r) for r in result["items"]],
        total=result["total"],
        page=page,
        page_size=page_size,
    )


@router.post("/{workflow_id}/execute", response_model=SingleResponse[WorkflowRunResponse])
async def execute_workflow(
    workflow_id: int,
    body: WorkflowRunRequest = Body(default_factory=WorkflowRunRequest),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Alias of /run — kept for backwards compatibility."""
    return await run_workflow(
        workflow_id=workflow_id,
        body=body,
        current_user=current_user,
        db=db,
    )


@router.get(
    "/{workflow_id}/runs/{run_id}/nodes",
    response_model=SingleResponse[List[WorkflowNodeRunResponse]],
)
async def list_run_node_runs(
    workflow_id: int,
    run_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Per-node execution records for one run, ordered by execution_order.
    Tenant-scoped via the parent workflow's tenant_id — ``WorkflowRun``
    itself doesn't carry tenant_id, so a user can't peek at another
    tenant's node runs by guessing run ids.
    """
    # Tenant check via the parent workflow. A user with no access to this
    # workflow gets 404 here, before we touch the runs table.
    service = WorkflowService()
    workflow = service.get_workflow(db, workflow_id, current_user.tenant_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Run not found")

    run = db.query(WorkflowRun).filter(
        WorkflowRun.id == run_id,
        WorkflowRun.workflow_id == workflow_id,
    ).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    node_runs = (
        db.query(WorkflowNodeRun)
        .filter(WorkflowNodeRun.run_id == run_id)
        .order_by(
            WorkflowNodeRun.execution_order.is_(None),  # NULLs last
            WorkflowNodeRun.execution_order.asc(),
            WorkflowNodeRun.id.asc(),
        )
        .all()
    )
    return SingleResponse(
        data=[WorkflowNodeRunResponse.model_validate(n) for n in node_runs]
    )


# Schedule endpoints
@router.get("/{workflow_id}/schedules", response_model=PaginatedResponse[WorkflowScheduleResponse])
async def list_schedules(
    workflow_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    is_active: Optional[bool] = None,
    search: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """List all schedules for a workflow. M30a: server-side pagination
    + ``is_active`` + name LIKE search."""
    query = db.query(WorkflowSchedule).filter(
        WorkflowSchedule.workflow_id == workflow_id,
        WorkflowSchedule.tenant_id == current_user.tenant_id
    )
    if is_active is not None:
        query = query.filter(WorkflowSchedule.is_active == is_active)
    if search:
        like = f"%{search}%"
        query = query.filter(WorkflowSchedule.name.like(like))
    query = query.order_by(WorkflowSchedule.created_at.desc())
    total = query.count()
    items = query.offset((page - 1) * page_size).limit(page_size).all()
    return PaginatedResponse(
        data=[WorkflowScheduleResponse.model_validate(s) for s in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("/{workflow_id}/schedules", response_model=SingleResponse[WorkflowScheduleResponse])
async def create_schedule(
    workflow_id: int,
    data: WorkflowScheduleCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a new schedule for a workflow"""
    # Verify workflow exists
    workflow = db.query(Workflow).filter(
        Workflow.id == workflow_id,
        Workflow.tenant_id == current_user.tenant_id
    ).first()
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    schedule = WorkflowSchedule(
        workflow_id=workflow_id,
        tenant_id=current_user.tenant_id,
        name=data.name,
        cron_expression=data.cron_expression,
        input_data=data.input_data,
        is_active=data.is_active
    )
    db.add(schedule)
    db.commit()
    db.refresh(schedule)

    # Register with scheduler
    scheduler_service = get_scheduler_service()
    scheduler_service.add_schedule(
        schedule.id,
        workflow_id,
        current_user.tenant_id,
        data.cron_expression,
        data.input_data
    )

    return SingleResponse(data=WorkflowScheduleResponse.model_validate(schedule))


@router.put("/{workflow_id}/schedules/{schedule_id}", response_model=SingleResponse[WorkflowScheduleResponse])
async def update_schedule(
    workflow_id: int,
    schedule_id: int,
    data: WorkflowScheduleUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update a schedule"""
    schedule = db.query(WorkflowSchedule).filter(
        WorkflowSchedule.id == schedule_id,
        WorkflowSchedule.workflow_id == workflow_id,
        WorkflowSchedule.tenant_id == current_user.tenant_id
    ).first()
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")

    if data.name is not None:
        schedule.name = data.name
    if data.cron_expression is not None:
        schedule.cron_expression = data.cron_expression
    if data.input_data is not None:
        schedule.input_data = data.input_data
    if data.is_active is not None:
        schedule.is_active = data.is_active

    db.commit()
    db.refresh(schedule)

    # Update scheduler
    scheduler_service = get_scheduler_service()
    scheduler_service.update_schedule(
        schedule_id,
        workflow_id,
        current_user.tenant_id,
        schedule.cron_expression,
        schedule.input_data,
        schedule.is_active
    )

    return SingleResponse(data=WorkflowScheduleResponse.model_validate(schedule))


@router.delete("/{workflow_id}/schedules/{schedule_id}")
async def delete_schedule(
    workflow_id: int,
    schedule_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete a schedule"""
    schedule = db.query(WorkflowSchedule).filter(
        WorkflowSchedule.id == schedule_id,
        WorkflowSchedule.workflow_id == workflow_id,
        WorkflowSchedule.tenant_id == current_user.tenant_id
    ).first()
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")

    db.delete(schedule)
    db.commit()

    # Remove from scheduler
    scheduler_service = get_scheduler_service()
    scheduler_service.remove_schedule(schedule_id)

    return SingleResponse(message="Schedule deleted successfully")
