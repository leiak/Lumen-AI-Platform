"""M30b-d regression: DELETE /workflows/{id} must cascade to LLMCallLog +
EmbeddingCallLog rows that reference the workflow's run.

Root cause (2026-06-19): ``WorkflowRun`` had no SQLAlchemy relationship
to ``LLMCallLog`` / ``EmbeddingCallLog``, so ``db.delete(workflow)``
only walked the configured cascade chain
``Workflow → WorkflowRun → WorkflowNodeRun`` and stopped there. The
DB-level FK ``llm_call_logs.workflow_run_id → workflow_runs.id`` then
fired ``1451 Cannot delete or update a parent row`` and the HTTP
endpoint returned 500.

The fix added two relationships with ``cascade="all, delete-orphan"``
on ``WorkflowRun`` (see ``app/models/workflow.py``). These tests
verify both directions:
  1. The HTTP DELETE endpoint returns 200 when a run has call logs.
  2. ``WorkflowService.delete_workflow`` removes the call log rows.

We use the ``tmp_user`` fixture (root DB connection, not the
integration-test ``ai_user``) so this runs in the unit test suite.
"""
import json
import uuid

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from lumen_main import app
    return TestClient(app)


@pytest.fixture
def auth_header(tmp_user):
    from lumen_services.auth_service import create_access_token
    token = create_access_token(
        data={"sub": tmp_user.username, "user_id": tmp_user.id}
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def tmp_workflow_with_logs(tmp_user):
    """Create a Workflow + WorkflowRun + 1 LLMCallLog + 1 EmbeddingCallLog
    row all linked together. Yields (workflow_id, run_id, llm_log_id,
    emb_log_id). Cleans up the test-created rows after.
    """
    from lumen_core.database import SessionLocal
    from lumen_models.workflow import Workflow, WorkflowRun
    from lumen_models.llm_call_log import LLMCallLog
    from lumen_models.embedding_call_log import EmbeddingCallLog
    from lumen_services.auth_service import create_access_token

    db = SessionLocal()
    try:
        suffix = uuid.uuid4().hex[:8]
        wf = Workflow(
            name=f"delete-cascade-test-{suffix}",
            definition={"nodes": [], "edges": []},
            tenant_id=1,
            is_active=True,
        )
        db.add(wf)
        db.commit()
        db.refresh(wf)

        run = WorkflowRun(
            workflow_id=wf.id,
            status="completed",
            input_data={},
            output_data={},
        )
        db.add(run)
        db.commit()
        db.refresh(run)

        llm = LLMCallLog(
            call_id=f"cascade-test-llm-{suffix}",
            trace_id=f"trace-cascade-test-llm-{suffix}",
            tenant_id=1,
            call_type="workflow.llm",
            workflow_id=wf.id,
            workflow_run_id=run.id,
            model_type="test",
            model_name="test-model",
            started_at=__import__("datetime").datetime.utcnow(),
        )
        emb = EmbeddingCallLog(
            call_id=f"cascade-test-emb-{suffix}",
            trace_id=f"trace-cascade-test-emb-{suffix}",
            tenant_id=1,
            call_type="kb_retrieval",
            workflow_id=wf.id,
            workflow_run_id=run.id,
            model_type="test",
            model_name="test-embedding",
            started_at=__import__("datetime").datetime.utcnow(),
        )
        db.add(llm)
        db.add(emb)
        db.commit()
        db.refresh(llm)
        db.refresh(emb)

        yield wf.id, run.id, llm.id, emb.id
    finally:
        # Hard cleanup in case the test left rows behind (defensive;
        # service-level cascade should have removed them on the happy path).
        try:
            db.query(LLMCallLog).filter(
                LLMCallLog.id.in_([llm.id, emb.id])
            ).delete(synchronize_session=False)
            db.query(EmbeddingCallLog).filter(
                EmbeddingCallLog.id == emb.id
            ).delete(synchronize_session=False)
            db.query(WorkflowRun).filter(WorkflowRun.id == run.id).delete(
                synchronize_session=False
            )
            db.query(Workflow).filter(Workflow.id == wf.id).delete(
                synchronize_session=False
            )
            db.commit()
        except Exception:
            db.rollback()
        finally:
            db.close()


def test_http_delete_workflow_cascades_to_call_logs(
    client, auth_header, tmp_workflow_with_logs
):
    """End-to-end: DELETE /workflows/{id} returns 200 even when the run
    has linked LLMCallLog + EmbeddingCallLog rows. The pre-fix behavior
    was HTTP 500 (FK 1451).
    """
    wf_id, run_id, llm_id, emb_id = tmp_workflow_with_logs

    resp = client.delete(
        f"/api/v1/workflows/{wf_id}", headers=auth_header
    )
    assert resp.status_code == 200, (
        f"DELETE failed: {resp.status_code} {resp.text[:200]}"
    )
    body = resp.json()
    assert body.get("code") == 200
    assert "Deleted" in body.get("message", "")

    # Verify the call log rows were actually removed (cascade really fired).
    from lumen_core.database import SessionLocal
    from lumen_models.llm_call_log import LLMCallLog
    from lumen_models.embedding_call_log import EmbeddingCallLog
    from lumen_models.workflow import Workflow, WorkflowRun

    db = SessionLocal()
    try:
        assert db.query(Workflow).filter(Workflow.id == wf_id).first() is None
        assert db.query(WorkflowRun).filter(WorkflowRun.id == run_id).first() is None
        assert db.query(LLMCallLog).filter(LLMCallLog.id == llm_id).first() is None
        assert (
            db.query(EmbeddingCallLog)
            .filter(EmbeddingCallLog.id == emb_id)
            .first()
            is None
        )
    finally:
        db.close()


def test_service_delete_workflow_returns_true_with_call_logs(
    tmp_workflow_with_logs
):
    """Direct service call: ``WorkflowService.delete_workflow`` returns
    ``True`` and removes all linked rows in the same transaction.
    """
    from lumen_core.database import SessionLocal
    from lumen_models.llm_call_log import LLMCallLog
    from lumen_models.embedding_call_log import EmbeddingCallLog
    from lumen_models.workflow import Workflow, WorkflowRun
    from lumen_services.workflow_service import WorkflowService

    wf_id, run_id, llm_id, emb_id = tmp_workflow_with_logs

    db = SessionLocal()
    try:
        svc = WorkflowService()
        ok = svc.delete_workflow(db, wf_id, tenant_id=1)
        assert ok is True
        # Cascade side-effects visible on the same session.
        assert db.query(Workflow).filter(Workflow.id == wf_id).first() is None
        assert db.query(WorkflowRun).filter(WorkflowRun.id == run_id).first() is None
        assert db.query(LLMCallLog).filter(LLMCallLog.id == llm_id).first() is None
        assert (
            db.query(EmbeddingCallLog)
            .filter(EmbeddingCallLog.id == emb_id)
            .first()
            is None
        )
    finally:
        db.close()
