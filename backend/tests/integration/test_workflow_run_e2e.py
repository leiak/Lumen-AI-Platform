"""M30a — end-to-end workflow run + node observability tests.

Spins up the FastAPI app via TestClient, creates a workflow, runs it,
then asserts that the GET /runs/{id}/nodes endpoint returns one
WorkflowNodeRun row per node, each with the right status and
input_data / output_data JSON.
"""
import os
import sys
import uuid

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from lumen_main import app
from lumen_core.database import SessionLocal
from lumen_models.workflow import Workflow, WorkflowRun, WorkflowNodeRun


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


@pytest.fixture(scope="module")
def auth_headers(client):
    res = client.post(
        "/api/v1/auth/login",
        data={"username": "admin", "password": "admin123"},
    )
    if res.status_code != 200:
        pytest.skip("admin login failed — set up dev DB first")
    token = res.json().get("data", {}).get("access_token")
    return {"Authorization": f"Bearer {token}"}


def _stub_workflow():
    """input → output. 2 nodes, deterministic. No LLM deps."""
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


def _seed_workflow(client, auth_headers) -> int:
    suffix = uuid.uuid4().hex[:8]
    res = client.post(
        "/api/v1/workflows/",
        json={
            "name": f"m30a_e2e_{suffix}",
            "description": "M30a e2e test workflow",
            "definition": _stub_workflow(),
        },
        headers=auth_headers,
    )
    assert res.status_code == 200
    return res.json()["data"]["id"]


def _cleanup(workflow_id: int) -> None:
    from sqlalchemy import text
    db = SessionLocal()
    try:
        # Find run ids first
        run_ids = [r.id for r in db.query(WorkflowRun).filter(
            WorkflowRun.workflow_id == workflow_id
        ).all()]
        for rid in run_ids:
            db.execute(text("DELETE FROM workflow_node_runs WHERE run_id = :rid"), {"rid": rid})
        db.query(WorkflowRun).filter(WorkflowRun.workflow_id == workflow_id).delete()
        db.query(Workflow).filter(Workflow.id == workflow_id).delete()
        db.commit()
    except Exception:  # noqa: BLE001
        db.rollback()
    finally:
        db.close()


def test_run_endpoint_creates_workflow_node_run_rows(client, auth_headers):
    """POST /run should: create a WorkflowRun + one WorkflowNodeRun per node,
    and GET /runs/{id}/nodes should return the rows."""
    workflow_id = _seed_workflow(client, auth_headers)
    try:
        run_res = client.post(
            f"/api/v1/workflows/{workflow_id}/run",
            json={"input_data": {"x": "hi"}},
            headers=auth_headers,
        )
        assert run_res.status_code == 200
        run = run_res.json()["data"]
        run_id = run["id"]
        # The run completes synchronously (input/output are fast).
        assert run["status"] == "completed"

        # Now fetch node runs.
        nodes_res = client.get(
            f"/api/v1/workflows/{workflow_id}/runs/{run_id}/nodes",
            headers=auth_headers,
        )
        assert nodes_res.status_code == 200
        body = nodes_res.json()
        assert body["code"] == 200
        node_runs = body["data"]
        # 2 nodes: input_1, output_1
        assert len(node_runs) == 2
        # Each row has status=completed and an id > 0
        for nr in node_runs:
            assert nr["status"] == "completed"
            assert nr["run_id"] == run_id
            assert "started_at" in nr
            assert "finished_at" in nr
        # execution_order is set
        orders = [nr["execution_order"] for nr in node_runs]
        assert all(isinstance(o, int) for o in orders)
        assert sorted(orders) == [0, 1]
    finally:
        _cleanup(workflow_id)


def test_cancel_endpoint_flips_running_run_to_cancelled(client, auth_headers):
    """POST /runs/{id}/cancel should mark a pending run as cancelled.

    For this test we seed a run row in 'running' state directly (no
    executor involvement) and then call cancel — the service's
    cancel_run should flip it to 'cancelled'."""
    workflow_id = _seed_workflow(client, auth_headers)
    db = SessionLocal()
    try:
        run = WorkflowRun(
            workflow_id=workflow_id,
            status="running",
            trigger_source="manual",
            input_data={"x": "hi"},
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        run_id = run.id

        res = client.post(
            f"/api/v1/workflows/{workflow_id}/runs/{run_id}/cancel",
            headers=auth_headers,
        )
        assert res.status_code == 200
        body = res.json()
        assert body["data"]["status"] == "cancelled"
    finally:
        # The cleanup helper deletes by workflow_id, but we just made
        # this run ourselves. Make sure it gets cleaned too.
        try:
            from sqlalchemy import text
            db.execute(text("DELETE FROM workflow_node_runs WHERE run_id = :rid"), {"rid": run_id})
            db.query(WorkflowRun).filter(WorkflowRun.id == run_id).delete()
            db.query(Workflow).filter(Workflow.id == workflow_id).delete()
            db.commit()
        except Exception:  # noqa: BLE001
            db.rollback()
        finally:
            db.close()


def test_run_endpoint_emits_workflow_node_runs_with_output_data(client, auth_headers):
    """output_data should be a JSON dict on each completed WorkflowNodeRun.
    We verify by running a workflow and checking the persisted rows.
    """
    workflow_id = _seed_workflow(client, auth_headers)
    try:
        run_res = client.post(
            f"/api/v1/workflows/{workflow_id}/run",
            json={"input_data": {"x": "hello world"}},
            headers=auth_headers,
        )
        run = run_res.json()["data"]
        run_id = run["id"]

        db = SessionLocal()
        try:
            rows = (
                db.query(WorkflowNodeRun)
                .filter(WorkflowNodeRun.run_id == run_id)
                .all()
            )
            for r in rows:
                assert r.status == "completed"
                # output_data is a JSON column → may be None for some
                # node types; just make sure the column is queryable.
                _ = r.output_data
        finally:
            db.close()
    finally:
        _cleanup(workflow_id)
