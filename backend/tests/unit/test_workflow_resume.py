"""M30d — resume / retry-from-failed tests.

The M30d resume endpoint re-runs a workflow with the same
input_data as the original run. The original run is preserved
(its row keeps status=failed, M30a WorkflowNodeRun rows are not
touched) and a NEW run is created with trigger_source="resume".
"""
import asyncio
import uuid

import pytest

from lumen_core.database import SessionLocal
from lumen_models.workflow import Workflow, WorkflowRun, WorkflowNodeRun


def _make_workflow(db, tenant_id: int = 1) -> int:
    """Create a tiny input→output workflow for the resume test."""
    suffix = uuid.uuid4().hex[:8]
    wf = Workflow(
        name=f"m30d_resume_{suffix}",
        definition={
            "nodes": [
                {"id": "in", "type": "input", "config": {"version": "1"}},
                {"id": "out", "type": "output", "config": {"version": "1", "field": "in.x"}},
            ],
            "edges": [
                {"id": "e1", "source": "in", "target": "out", "sourceHandle": "default"},
            ],
        },
        tenant_id=tenant_id,
        is_active=True,
    )
    db.add(wf)
    db.commit()
    db.refresh(wf)
    return wf.id


def _make_run(db, workflow_id: int, status: str, input_data: dict) -> int:
    suffix = uuid.uuid4().hex[:8]
    run = WorkflowRun(
        workflow_id=workflow_id,
        status=status,
        trigger_source="manual",
        input_data=input_data,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run.id


def _cleanup(db, run_ids, workflow_id):
    from sqlalchemy import text
    for rid in run_ids:
        try:
            db.execute(
                text("DELETE FROM workflow_node_runs WHERE run_id = :rid"),
                {"rid": rid},
            )
            db.commit()
        except Exception:  # noqa: BLE001
            db.rollback()
    try:
        db.query(WorkflowRun).filter(WorkflowRun.workflow_id == workflow_id).delete()
        db.commit()
    except Exception:  # noqa: BLE001
        db.rollback()
    try:
        db.query(Workflow).filter(Workflow.id == workflow_id).delete()
        db.commit()
    except Exception:  # noqa: BLE001
        db.rollback()


def test_resume_creates_new_run_with_same_input_data():
    """Resume a failed run → new run with trigger_source=resume,
    preserving the original input_data.
    """
    from lumen_services.workflow_service import WorkflowService

    db = SessionLocal()
    workflow_id = _make_workflow(db)
    original_input = {"x": "retry-me"}
    original_run_id = _make_run(db, workflow_id, "failed", original_input)
    try:
        service = WorkflowService()
        new_run = asyncio.run(
            service.resume_run(db, workflow_id, original_run_id, tenant_id=1)
        )
        assert new_run is not None
        assert new_run.id != original_run_id
        assert new_run.input_data == original_input
        # The new run uses the resume trigger so it's distinguishable
        # from manual / scheduled in the runs drawer.
        assert new_run.trigger_source == "resume"
    finally:
        # Find all run ids we may have created.
        run_ids = [r.id for r in db.query(WorkflowRun).filter(
            WorkflowRun.workflow_id == workflow_id
        ).all()]
        _cleanup(db, run_ids, workflow_id)
        db.close()


def test_resume_preserves_failed_run_for_audit():
    """The original failed run stays in 'failed' status — only a
    new run is created. Important for the audit trail: a user can
    later inspect why a particular attempt failed even after they
    resumed.
    """
    from lumen_services.workflow_service import WorkflowService

    db = SessionLocal()
    workflow_id = _make_workflow(db)
    original_run_id = _make_run(db, workflow_id, "failed", {"x": "x"})
    try:
        service = WorkflowService()
        asyncio.run(
            service.resume_run(db, workflow_id, original_run_id, tenant_id=1)
        )
        # Re-fetch the original run.
        original = db.query(WorkflowRun).filter(
            WorkflowRun.id == original_run_id
        ).first()
        assert original is not None
        assert original.status == "failed", (
            f"resume must not flip original run status (got {original.status})"
        )
    finally:
        run_ids = [r.id for r in db.query(WorkflowRun).filter(
            WorkflowRun.workflow_id == workflow_id
        ).all()]
        _cleanup(db, run_ids, workflow_id)
        db.close()
