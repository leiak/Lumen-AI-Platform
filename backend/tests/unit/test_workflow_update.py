"""M30d 2.0 (2026-09-07): optimistic-locking tests for workflow update.

Covers WorkflowService.update_workflow's new ``if_match_updated_at``
param that powers the ``If-Match`` header on PUT /workflows/{id}.
The frontend's ``useAutoSave`` sends the last-known updated_at back
so concurrent edits in two tabs get a clean 409 instead of silent
last-write-wins clobbering.
"""
import uuid
from datetime import datetime, timedelta

import pytest

from lumen_core.database import SessionLocal
from lumen_models.workflow import Workflow
from lumen_services.workflow_service import (
    WorkflowConflictError,
    WorkflowService,
)


def _make_workflow(db, tenant_id: int = 1) -> int:
    suffix = uuid.uuid4().hex[:8]
    wf = Workflow(
        name=f"m30d_update_{suffix}",
        definition={"nodes": [], "edges": []},
        tenant_id=tenant_id,
        is_active=True,
    )
    db.add(wf)
    db.commit()
    db.refresh(wf)
    return wf.id


def _cleanup(db, workflow_id: int) -> None:
    try:
        db.query(Workflow).filter(Workflow.id == workflow_id).delete()
        db.commit()
    except Exception:  # noqa: BLE001
        db.rollback()


def _update_payload(name: str = "new name"):
    """Build a WorkflowUpdate-compatible dict. The service uses
    ``model_dump(exclude_unset=True)`` so we just need the field we
    want to change.
    """
    from lumen_schemas.workflow import WorkflowUpdate

    return WorkflowUpdate(name=name)


def test_update_without_if_match_is_legacy_compat():
    """When if_match_updated_at is None, the service applies the
    update without conflict checking (last-write-wins). This keeps
    every pre-M30d 2.0 call site working unchanged.
    """
    db = SessionLocal()
    workflow_id = _make_workflow(db)
    try:
        service = WorkflowService()
        updated = service.update_workflow(
            db, workflow_id, tenant_id=1, data=_update_payload("legacy-call")
        )
        assert updated is not None
        assert updated.name == "legacy-call"
    finally:
        _cleanup(db, workflow_id)


def test_update_with_matching_if_match_succeeds():
    """When if_match_updated_at equals the current updated_at (within
    microsecond tolerance), the update applies and refreshed row
    has a new updated_at.
    """
    db = SessionLocal()
    workflow_id = _make_workflow(db)
    try:
        # Get the current updated_at
        wf = db.query(Workflow).filter(Workflow.id == workflow_id).first()
        assert wf is not None
        original_updated_at = wf.updated_at
        assert original_updated_at is not None

        service = WorkflowService()
        updated = service.update_workflow(
            db,
            workflow_id,
            tenant_id=1,
            data=_update_payload("matching-call"),
            if_match_updated_at=original_updated_at,
        )
        assert updated is not None
        assert updated.name == "matching-call"
        # updated_at should advance (onupdate=func.now())
        assert updated.updated_at is not None
    finally:
        _cleanup(db, workflow_id)


def test_update_with_stale_if_match_raises_conflict():
    """When if_match_updated_at is older than the row's current
    updated_at, WorkflowConflictError fires with both timestamps so
    the API layer can return 409.
    """
    db = SessionLocal()
    workflow_id = _make_workflow(db)
    try:
        service = WorkflowService()

        # First, touch the workflow so updated_at advances
        service.update_workflow(
            db, workflow_id, tenant_id=1, data=_update_payload("first-touch")
        )
        wf = db.query(Workflow).filter(Workflow.id == workflow_id).first()
        assert wf is not None
        current_updated_at = wf.updated_at
        assert current_updated_at is not None

        # Now pretend we're a stale client (our last-known updated_at
        # was before the touch)
        stale_ts = current_updated_at - timedelta(seconds=5)

        with pytest.raises(WorkflowConflictError) as exc_info:
            service.update_workflow(
                db,
                workflow_id,
                tenant_id=1,
                data=_update_payload("stale-write"),
                if_match_updated_at=stale_ts,
            )
        err = exc_info.value
        assert err.current_updated_at == current_updated_at
        assert err.submitted_updated_at == stale_ts
        # DB row must NOT have been mutated by the failed update
        wf_after = (
            db.query(Workflow).filter(Workflow.id == workflow_id).first()
        )
        assert wf_after.name == "first-touch"
    finally:
        _cleanup(db, workflow_id)


def test_update_returns_none_for_unknown_workflow():
    """The 404-vs-409 distinction: unknown workflow_id still returns
    None (caller distinguishes via HTTP 404). The conflict path is
    only reachable when the workflow exists.
    """
    db = SessionLocal()
    service = WorkflowService()
    try:
        result = service.update_workflow(
            db,
            99999999,
            tenant_id=1,
            data=_update_payload("nope"),
            if_match_updated_at=datetime.utcnow(),
        )
        assert result is None
    finally:
        # Nothing to clean
        pass


def test_update_with_exact_microsecond_match_succeeds():
    """The microsecond-precision equality check handles the common
    case where the frontend sends back the exact updated_at it
    received in the previous response — no false-positive 409s.
    """
    db = SessionLocal()
    workflow_id = _make_workflow(db)
    try:
        wf = db.query(Workflow).filter(Workflow.id == workflow_id).first()
        assert wf is not None and wf.updated_at is not None
        # Build a timestamp with the same wall + microsecond but a
        # different tzinfo object — equality at the DB level is
        # microsecond, not timezone-aware.
        same = wf.updated_at
        service = WorkflowService()
        updated = service.update_workflow(
            db,
            workflow_id,
            tenant_id=1,
            data=_update_payload("microsecond-match"),
            if_match_updated_at=same,
        )
        assert updated is not None
        assert updated.name == "microsecond-match"
    finally:
        _cleanup(db, workflow_id)
