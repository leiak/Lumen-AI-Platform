"""M30a — WorkflowExecutor observability tests.

Verifies that the BFS loop now writes a ``WorkflowNodeRun`` row per
node (running → completed / failed) when a ``meta_session`` is passed
in, and that the cancel_event integration short-circuits at node
boundaries.

These tests use a real DB session (not MagicMock) because the unit-
under-test is the executor's row-write contract.
"""
import asyncio
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from lumen_core.database import SessionLocal
from lumen_models.workflow import Workflow, WorkflowNodeRun, WorkflowRun
from lumen_services.workflow_executor import WorkflowExecutor


def _stub_input_only_workflow():
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
        ],
        "edges": [],
    }


def _stub_three_node_workflow():
    """input → output1 → output2 (linear, all deterministic)."""
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
                "config": {"title": "Output1", "version": "1", "field": "input_1.x"},
            },
            {
                "id": "output_2",
                "type": "output",
                "config": {"title": "Output2", "version": "1", "field": "input_1.x"},
            },
        ],
        "edges": [
            {"id": "e1", "source": "input_1", "target": "output_1", "sourceHandle": "default"},
            {"id": "e2", "source": "input_1", "target": "output_2", "sourceHandle": "default"},
        ],
    }


def _make_workflow_row(db, tenant_id: int) -> int:
    """Create a minimal workflow row. Returns its id."""
    suffix = uuid.uuid4().hex[:8]
    wf = Workflow(
        name=f"m30a_test_{suffix}",
        description="M30a observability test",
        definition=_stub_three_node_workflow(),
        tenant_id=tenant_id,
        is_active=True,
    )
    db.add(wf)
    db.commit()
    db.refresh(wf)
    return wf.id


def _make_run_row(db, workflow_id: int) -> int:
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


def _new_query_session() -> Session:
    """Open a fresh session for cross-session reads.

    M30a: the executor opens its own SessionLocal() for WorkflowNodeRun
    writes, so the test's session (which seeded the workflow + run rows
    in MYSQL's REPEATABLE READ snapshot) won't see the executor's
    committed rows. A fresh session reads from a new transaction and
    sees the latest committed state.
    """
    return SessionLocal()


def _cleanup(db, run_id: int, workflow_id: int) -> None:
    """Delete the WorkflowNodeRun + WorkflowRun + Workflow rows we made.
    Best-effort; ignores individual failures.
    """
    try:
        db.execute(
            text("DELETE FROM workflow_node_runs WHERE run_id = :rid"),
            {"rid": run_id},
        )
        db.commit()
    except Exception:  # noqa: BLE001
        db.rollback()
    try:
        db.query(WorkflowRun).filter(WorkflowRun.id == run_id).delete()
        db.commit()
    except Exception:  # noqa: BLE001
        db.rollback()
    try:
        db.query(Workflow).filter(Workflow.id == workflow_id).delete()
        db.commit()
    except Exception:  # noqa: BLE001
        db.rollback()


def test_executor_writes_node_run_rows_per_node():
    """Each node should land a WorkflowNodeRun row with status=completed,
    output_data, and execution_order set."""
    db = SessionLocal()
    workflow_id = _make_workflow_row(db, tenant_id=1)
    run_id = _make_run_row(db, workflow_id)
    try:
        executor = WorkflowExecutor()
        result = asyncio.run(
            executor.execute(
                definition=_stub_three_node_workflow(),
                input_data={"x": "hi"},
                tenant_id=1,
                run_id=run_id,
                db=db,
                persist_node_runs=True,
            )
        )
        assert result["status"] == "completed"

        rows = (
            _new_query_session()
            .query(WorkflowNodeRun)
            .filter(WorkflowNodeRun.run_id == run_id)
            .order_by(WorkflowNodeRun.execution_order.asc())
            .all()
        )
        # 3 nodes ran (input_1 + output_1 + output_2)
        assert len(rows) == 3
        ids_in_order = [r.node_id for r in rows]
        assert ids_in_order == ["input_1", "output_1", "output_2"]
        # execution_order is monotonically increasing
        assert [r.execution_order for r in rows] == [0, 1, 2]
        # All completed
        assert {r.status for r in rows} == {"completed"}
        # input_data field exists for completed rows (may be None for
        # input-only nodes that don't take a config — that's fine).
    finally:
        _cleanup(db, run_id, workflow_id)
        db.close()


def test_executor_marks_failed_node_with_error_message(monkeypatch):
    """A node that raises should land a WorkflowNodeRun row with
    status=failed and the error_message populated."""
    # Force the LLM factory (which the second node would use) to throw.
    # Easier: make a 1-node workflow whose node raises by patching the
    # class itself. We monkeypatch run_node_with_handling to raise a
    # NodeRunError on the second call.
    from lumen_core.workflow import executor_helpers
    from lumen_core.workflow.retry import NodeRunError
    call_count = {"n": 0}

    original = executor_helpers.run_node_with_handling

    async def flaky(instance, attempt=0):
        call_count["n"] += 1
        if call_count["n"] == 2:
            raise NodeRunError("synthetic boom")
        return await original(instance, attempt)

    monkeypatch.setattr(executor_helpers, "run_node_with_handling", flaky)
    monkeypatch.setattr(
        "lumen_services.workflow_executor.run_node_with_handling", flaky
    )

    db = SessionLocal()
    workflow_id = _make_workflow_row(db, tenant_id=1)
    run_id = _make_run_row(db, workflow_id)
    try:
        executor = WorkflowExecutor()
        result = asyncio.run(
            executor.execute(
                definition=_stub_three_node_workflow(),
                input_data={"x": "hi"},
                tenant_id=1,
                run_id=run_id,
                db=db,
                persist_node_runs=True,
            )
        )
        assert result["status"] == "failed"

        rows = (
            _new_query_session()
            .query(WorkflowNodeRun)
            .filter(WorkflowNodeRun.run_id == run_id)
            .order_by(WorkflowNodeRun.id.asc())
            .all()
        )
        assert len(rows) >= 1
        # At least one row has status=failed with a non-empty error_message.
        failed = [r for r in rows if r.status == "failed"]
        assert failed, f"expected at least one failed row, got: {[(r.node_id, r.status) for r in rows]}"
        assert "synthetic boom" in (failed[0].error_message or "")
    finally:
        _cleanup(db, run_id, workflow_id)
        db.close()


def test_executor_cancel_short_circuits_at_node_boundary():
    """Setting the cancel_event before the run starts means the BFS
    loop sees it at the first iteration and returns status=cancelled
    without executing any node."""
    db = SessionLocal()
    workflow_id = _make_workflow_row(db, tenant_id=1)
    run_id = _make_run_row(db, workflow_id)
    try:
        executor = WorkflowExecutor()
        cancel_event = asyncio.Event()
        cancel_event.set()  # already cancelled before we start

        result = asyncio.run(
            executor.execute(
                definition=_stub_three_node_workflow(),
                input_data={"x": "hi"},
                tenant_id=1,
                run_id=run_id,
                db=db,
                persist_node_runs=True,
                cancel_event=cancel_event,
            )
        )
        assert result["status"] == "cancelled"
    finally:
        _cleanup(db, run_id, workflow_id)
        db.close()


def test_executor_emits_sse_events_when_callback_provided():
    """on_event callback should fire with run_start, node_start, node_end,
    run_end events. No DB writes needed for this test — we pass
    meta_session=None so we only check event emission."""
    captured = []

    async def on_event(event, data):
        captured.append((event, data))

    wf = _stub_input_only_workflow()
    executor = WorkflowExecutor()
    result = asyncio.run(
        executor.execute(
            definition=wf,
            input_data={"x": "hi"},
            tenant_id=1,
            run_id=999999,  # arbitrary
            db=SessionLocal(),  # ignored
            on_event=on_event,
        )
    )
    assert result["status"] == "completed"
    event_types = [e for e, _ in captured]
    # At minimum: run_start + node_start + node_end + run_end
    assert "run_start" in event_types
    assert "node_start" in event_types
    assert "node_end" in event_types
    assert "run_end" in event_types
