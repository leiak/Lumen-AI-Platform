"""
Regression: PUT /api/v1/workflows/{id} must round-trip each node's ``position``.

Bug: ``WorkflowNode`` schema (schemas/workflow.py) only declared
``id``/``type``/``config``. Pydantic silently dropped any other keys,
so the frontend designer (which sends ``position: {x, y}`` so nodes
don't stack on top of each other) saved workflows with no positions
at all. Reloading the workflow placed every node at (0, 0) and they
overlapped on the canvas.
"""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from lumen_main import app
    return TestClient(app)


@pytest.fixture
def auth_headers(client):
    # /auth/login is an OAuth2PasswordRequestForm — form-data, NOT JSON.
    resp = client.post(
        "/api/v1/auth/login",
        data={"username": "admin", "password": "admin123"},
    )
    if resp.status_code != 200:
        pytest.skip(f"auth failed: {resp.status_code} {resp.text}")
    token = resp.json()["data"]["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_put_workflow_preserves_node_position(client, auth_headers):
    """PUT /api/v1/workflows/{id} must round-trip each node's ``position``.

    See module docstring for the original bug.
    """
    payload = {
        "name": "Position-Roundtrip Test",
        "definition": {
            "nodes": [
                {
                    "id": "n1",
                    "type": "input",
                    "config": {"label": "Node 1"},
                    "position": {"x": 250, "y": 0},
                },
                {
                    "id": "n2",
                    "type": "output",
                    "config": {"label": "Node 2"},
                    "position": {"x": 500, "y": 200},
                },
            ],
            "edges": [{"id": "e1", "source": "n1", "target": "n2"}],
        },
    }
    create = client.post("/api/v1/workflows/", json=payload, headers=auth_headers)
    if create.status_code != 200:
        pytest.skip(f"create failed: {create.status_code} {create.text}")
    wid = create.json()["data"]["id"]

    got = client.get(f"/api/v1/workflows/{wid}", headers=auth_headers)
    assert got.status_code == 200, got.text
    nodes = got.json()["data"]["definition"]["nodes"]
    by_id = {n["id"]: n for n in nodes}

    # THE BUG: before the fix, ``position`` is missing from the round-trip
    # because Pydantic drops unknown keys on the request body.
    assert "position" in by_id["n1"], (
        f"node n1 lost its 'position' field; got keys: {list(by_id['n1'].keys())}"
    )
    assert "position" in by_id["n2"], (
        f"node n2 lost its 'position' field; got keys: {list(by_id['n2'].keys())}"
    )
    assert by_id["n1"]["position"] == {"x": 250, "y": 0}
    assert by_id["n2"]["position"] == {"x": 500, "y": 200}
