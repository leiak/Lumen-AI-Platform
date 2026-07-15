"""M30a — list endpoint search/filter/pagination tests.

These tests use FastAPI's TestClient with a real auth flow (admin /
admin123) and a real DB. The ``tmp_user`` fixture is not used because
we want to test the list endpoint scoped to the default tenant
(tenant_id=1), which is where the seeded admin lives.
"""
import sys
import os
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from lumen_main import app
from lumen_core.database import SessionLocal
from lumen_models.workflow import Workflow, WorkflowRun, WorkflowNodeRun
from lumen_models.user import User
from lumen_core.security import get_password_hash


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


@pytest.fixture
def tmp_workflows():
    """Seed N workflow rows in tenant 1, then clean up. Returns the
    list of (id, name) tuples so the test can assert on names.
    """
    db = SessionLocal()
    suffix = uuid.uuid4().hex[:8]
    created: list[tuple[int, str]] = []
    try:
        for i in range(5):
            wf = Workflow(
                name=f"m30a_search_{suffix}_{i}",
                description=f"M30a search test {i}",
                definition={"nodes": [], "edges": []},
                tenant_id=1,
                is_active=True,
            )
            db.add(wf)
            db.commit()
            db.refresh(wf)
            created.append((wf.id, wf.name))
        yield created
    finally:
        try:
            db.query(Workflow).filter(
                Workflow.name.like(f"m30a_search_{suffix}_%")
            ).delete(synchronize_session=False)
            db.commit()
        except Exception:  # noqa: BLE001
            db.rollback()
        finally:
            db.close()


def test_list_workflows_search_filters_by_name(client, auth_headers, tmp_workflows):
    """?search=foo should return only rows whose name OR description LIKE foo."""
    # Use a unique token from the seeded names so we only see our test rows.
    first_name = tmp_workflows[0][1]
    token = first_name.split("_")[-1]  # the suffix segment
    res = client.get(
        f"/api/v1/workflows/?search=m30a_search_{first_name.split('_')[2]}",
        headers=auth_headers,
    )
    assert res.status_code == 200
    body = res.json()
    assert body["code"] == 200
    # We should see at least our 5 rows; the dev DB may have others, so
    # the safer assertion is: every returned row's name starts with our
    # marker.
    for w in body["data"]:
        assert "m30a_search_" in w["name"]


def test_list_workflows_pagination_returns_total_count(client, auth_headers, tmp_workflows):
    """page_size=2 + page=1 should return 2 items + total=5 (from our seed)."""
    first_name = tmp_workflows[0][1]
    marker = first_name.split("_")[2]
    res = client.get(
        f"/api/v1/workflows/?page=1&page_size=2&search=m30a_search_{marker}",
        headers=auth_headers,
    )
    assert res.status_code == 200
    body = res.json()
    assert body["page"] == 1
    assert body["page_size"] == 2
    assert body["total"] == 5
    assert len(body["data"]) == 2


def test_list_workflows_pagination_walks_pages(client, auth_headers, tmp_workflows):
    """page=1 + page=2 should yield disjoint sets of ids (no overlap)."""
    first_name = tmp_workflows[0][1]
    marker = first_name.split("_")[2]
    p1 = client.get(
        f"/api/v1/workflows/?page=1&page_size=2&search=m30a_search_{marker}",
        headers=auth_headers,
    ).json()
    p2 = client.get(
        f"/api/v1/workflows/?page=2&page_size=2&search=m30a_search_{marker}",
        headers=auth_headers,
    ).json()
    p3 = client.get(
        f"/api/v1/workflows/?page=3&page_size=2&search=m30a_search_{marker}",
        headers=auth_headers,
    ).json()
    ids1 = {w["id"] for w in p1["data"]}
    ids2 = {w["id"] for w in p2["data"]}
    ids3 = {w["id"] for w in p3["data"]}
    assert ids1.isdisjoint(ids2)
    assert ids2.isdisjoint(ids3)
    assert ids1.isdisjoint(ids3)
    assert len(ids1 | ids2 | ids3) == 5


def test_list_workflows_is_active_filter(client, auth_headers, tmp_workflows):
    """?is_active=true should return only active rows."""
    db = SessionLocal()
    try:
        # Flip one to inactive and check it's filtered out.
        wf_id = tmp_workflows[0][0]
        db.query(Workflow).filter(Workflow.id == wf_id).update({"is_active": False})
        db.commit()
        marker = tmp_workflows[0][1].split("_")[2]
        res = client.get(
            f"/api/v1/workflows/?is_active=true&search=m30a_search_{marker}",
            headers=auth_headers,
        )
        body = res.json()
        for w in body["data"]:
            assert w["is_active"] is True
        assert wf_id not in {w["id"] for w in body["data"]}
    finally:
        # Restore so cleanup works (is_active is fine either way, but
        # the cleanup query matches by name, not by is_active).
        try:
            db.query(Workflow).filter(Workflow.id == wf_id).update({"is_active": True})
            db.commit()
        except Exception:  # noqa: BLE001
            db.rollback()
        finally:
            db.close()


def test_list_workflows_sort_by_name_ascending(client, auth_headers, tmp_workflows):
    """?sort_by=name&sort_order=asc should return names in alphabetical order."""
    marker = tmp_workflows[0][1].split("_")[2]
    res = client.get(
        f"/api/v1/workflows/?sort_by=name&sort_order=asc&page_size=100&search=m30a_search_{marker}",
        headers=auth_headers,
    )
    body = res.json()
    names = [w["name"] for w in body["data"]]
    assert names == sorted(names)


def test_bulk_delete_workflows(client, auth_headers, tmp_workflows):
    """POST /workflows/bulk-delete should delete multiple ids in one tx."""
    ids_to_delete = [w[0] for w in tmp_workflows[:3]]
    res = client.post(
        "/api/v1/workflows/bulk-delete",
        json={"ids": ids_to_delete},
        headers=auth_headers,
    )
    assert res.status_code == 200
    body = res.json()
    assert body["code"] == 200
    deleted = body["data"]["deleted_ids"]
    assert set(deleted) == set(ids_to_delete)
    assert body["data"]["deleted_count"] == 3

    # Verify the rows are gone.
    db = SessionLocal()
    try:
        remaining = (
            db.query(Workflow)
            .filter(Workflow.id.in_(ids_to_delete))
            .all()
        )
        assert remaining == []
    finally:
        db.close()
