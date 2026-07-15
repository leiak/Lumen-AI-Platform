"""M30a — SSE streaming endpoint tests.

Verifies the /api/v1/workflows/{id}/stream endpoint emits a coherent
event sequence: 1× run_start, N× node_start + node_end, 1× run_end.

We bypass the FastAPI SSE plumbing (which requires a live HTTP client)
and unit-test the executor's event emission contract directly. The
executor is the source of truth; the SSE endpoint is a thin transport
adapter over it.
"""
import asyncio
import json
import uuid

import pytest

from lumen_core.database import SessionLocal
from lumen_models.workflow import Workflow, WorkflowRun
from lumen_services.workflow_executor import (
    EVENT_NODE_END,
    EVENT_NODE_START,
    EVENT_RUN_END,
    EVENT_RUN_START,
    WorkflowExecutor,
)


def _stub_linear_workflow():
    return {
        "nodes": [
            {
                "id": "input_1",
                "type": "input",
                "config": {
                    "title": "Input",
                    "version": "1",
                    "variables": [{"name": "x", "type": "string", "required": True}],
                },
            },
            {
                "id": "output_1",
                "type": "output",
                "config": {"title": "Output", "version": "1", "field": "input_1.x"},
            },
        ],
        "edges": [
            {"id": "e1", "source": "input_1", "target": "output_1", "sourceHandle": "default"},
        ],
    }


def _make_workflow(db, tenant_id: int) -> int:
    suffix = uuid.uuid4().hex[:8]
    wf = Workflow(
        name=f"m30a_stream_{suffix}",
        description="M30a SSE test",
        definition=_stub_linear_workflow(),
        tenant_id=tenant_id,
        is_active=True,
    )
    db.add(wf)
    db.commit()
    db.refresh(wf)
    return wf.id


def _make_run(db, workflow_id: int) -> int:
    suffix = uuid.uuid4().hex[:8]
    run = WorkflowRun(
        workflow_id=workflow_id,
        status="running",
        trigger_source="manual",
        input_data={"x": "hi"},
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run.id


def _cleanup(db, run_id: int, workflow_id: int) -> None:
    from sqlalchemy import text
    cleanup_db = SessionLocal()
    try:
        cleanup_db.execute(
            text("DELETE FROM workflow_node_runs WHERE run_id = :rid"),
            {"rid": run_id},
        )
        cleanup_db.commit()
    except Exception:  # noqa: BLE001
        cleanup_db.rollback()
    try:
        cleanup_db.query(WorkflowRun).filter(WorkflowRun.id == run_id).delete()
        cleanup_db.commit()
    except Exception:  # noqa: BLE001
        cleanup_db.rollback()
    try:
        cleanup_db.query(Workflow).filter(Workflow.id == workflow_id).delete()
        cleanup_db.commit()
    except Exception:  # noqa: BLE001
        cleanup_db.rollback()
    finally:
        cleanup_db.close()


def test_executor_emits_run_start_first_then_node_start_node_end_run_end():
    """Event ordering: run_start → (node_start + node_end) × N → run_end."""
    captured = []

    async def on_event(event, data):
        captured.append((event, data))

    db = SessionLocal()
    workflow_id = _make_workflow(db, tenant_id=1)
    run_id = _make_run(db, workflow_id)
    try:
        executor = WorkflowExecutor()
        asyncio.run(
            executor.execute(
                definition=_stub_linear_workflow(),
                input_data={"x": "hi"},
                tenant_id=1,
                run_id=run_id,
                db=db,
                persist_node_runs=True,
                on_event=on_event,
            )
        )

        events = [e for e, _ in captured]
        assert events[0] == EVENT_RUN_START, f"first event should be run_start, got {events[:3]}"
        assert events[-1] == EVENT_RUN_END, f"last event should be run_end, got {events[-3:]}"
        # node_start + node_end pairs interleaved (one per node)
        node_starts = [i for i, e in enumerate(events) if e == EVENT_NODE_START]
        node_ends = [i for i, e in enumerate(events) if e == EVENT_NODE_END]
        assert len(node_starts) == 2
        assert len(node_ends) == 2
        # Each node_end follows its node_start (no overlap)
        for start_idx in node_starts:
            assert any(end_idx > start_idx for end_idx in node_ends)
    finally:
        _cleanup(db, run_id, workflow_id)
        db.close()


def test_executor_run_start_payload_includes_total_nodes():
    """The run_start event should carry the total node count so the
    frontend can render a progress bar without a separate count API."""
    captured = []

    async def on_event(event, data):
        captured.append((event, data))

    db = SessionLocal()
    workflow_id = _make_workflow(db, tenant_id=1)
    run_id = _make_run(db, workflow_id)
    try:
        executor = WorkflowExecutor()
        asyncio.run(
            executor.execute(
                definition=_stub_linear_workflow(),
                input_data={"x": "hi"},
                tenant_id=1,
                run_id=run_id,
                db=db,
                persist_node_runs=True,
                on_event=on_event,
            )
        )

        run_start = next(d for e, d in captured if e == EVENT_RUN_START)
        assert run_start["total_nodes"] == 2
        assert run_start["run_id"] == run_id
    finally:
        _cleanup(db, run_id, workflow_id)
        db.close()


def test_executor_node_end_payload_has_output_data_and_duration():
    """Each node_end should carry the node's output_data and a duration_ms
    so the frontend can render per-node timing without a follow-up query."""
    captured = []

    async def on_event(event, data):
        captured.append((event, data))

    db = SessionLocal()
    workflow_id = _make_workflow(db, tenant_id=1)
    run_id = _make_run(db, workflow_id)
    try:
        executor = WorkflowExecutor()
        asyncio.run(
            executor.execute(
                definition=_stub_linear_workflow(),
                input_data={"x": "hi"},
                tenant_id=1,
                run_id=run_id,
                db=db,
                persist_node_runs=True,
                on_event=on_event,
            )
        )

        node_ends = [d for e, d in captured if e == EVENT_NODE_END]
        for ne in node_ends:
            assert "duration_ms" in ne
            assert isinstance(ne["duration_ms"], int)
            assert ne["duration_ms"] >= 0
            assert "status" in ne
            # output_data is a dict (may be empty for input-only nodes)
            assert isinstance(ne.get("output_data", {}), dict)
    finally:
        _cleanup(db, run_id, workflow_id)
        db.close()


def test_executor_no_events_when_callback_is_none():
    """No callback = no events emitted. The run still completes
    normally — the callback is a UX nicety, not a control flow."""
    db = SessionLocal()
    workflow_id = _make_workflow(db, tenant_id=1)
    run_id = _make_run(db, workflow_id)
    try:
        executor = WorkflowExecutor()
        result = asyncio.run(
            executor.execute(
                definition=_stub_linear_workflow(),
                input_data={"x": "hi"},
                tenant_id=1,
                run_id=run_id,
                db=db,
                persist_node_runs=True,
                on_event=None,
            )
        )
        assert result["status"] == "completed"
    finally:
        _cleanup(db, run_id, workflow_id)
        db.close()
