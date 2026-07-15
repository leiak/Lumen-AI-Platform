"""M30d — node-types metadata API tests.

Verifies the /api/v1/workflow/node-types endpoint returns a list of
metadata blocks covering all 19 registered node types, each with
the expected shape (type/label/category/inputs/outputs).
"""
import pytest
from fastapi.testclient import TestClient

from lumen_core.workflow.node_types_metadata import (
    all_node_types_metadata,
    get_node_type_metadata,
)


def test_all_node_types_metadata_returns_19_unique_types():
    items = all_node_types_metadata()
    assert len(items) == 19, f"expected 19, got {len(items)}: {[i.type for i in items]}"
    types = [i.type for i in items]
    # No duplicates.
    assert len(set(types)) == len(types)


def test_every_metadata_has_required_fields():
    for meta in all_node_types_metadata():
        assert meta.type
        assert meta.label
        assert meta.category in (
            "input", "output", "process", "control", "integration", "variable"
        )
        assert meta.version == "1"


def test_get_node_type_metadata_returns_specific_block():
    llm = get_node_type_metadata("llm")
    assert llm is not None
    assert llm.label == "LLM 调用"
    assert "response" in [o.get("name") for o in llm.outputs]


def test_get_node_type_metadata_returns_none_for_unknown():
    assert get_node_type_metadata("nonexistent") is None


def test_metadata_endpoints_via_testclient():
    """M30d: the /api/v1/workflow/node-types endpoint returns the
    metadata wrapped in our standard SingleResponse envelope.
    """
    from lumen_main import app
    client = TestClient(app)
    # Login as admin.
    res = client.post(
        "/api/v1/auth/login",
        data={"username": "admin", "password": "admin123"},
    )
    if res.status_code != 200:
        pytest.skip("admin login failed — set up dev DB first")
    token = res.json()["data"]["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    res = client.get("/api/v1/workflows/node-types", headers=headers)
    assert res.status_code == 200
    body = res.json()
    assert body["code"] == 200
    items = body["data"]
    assert len(items) >= 19
    # Pick a few expected entries.
    types = {i["type"] for i in items}
    assert "input" in types
    assert "llm" in types
    assert "code" in types
    assert "knowledge_retrieval" in types
