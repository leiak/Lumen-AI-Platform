"""M33: integration tests for /api/v1/text2sql/* endpoints.

Spec: docs/superpowers/specs/2026-06-20-text2sql-design.md §6

We mock the LLM to keep tests deterministic. The HTTP layer,
auth, schema serialisation, and tenant scoping are exercised
end-to-end against the real DB.
"""
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from lumen_core.database import SessionLocal
from lumen_main import app
from lumen_models.text2sql import Text2SqlDataSource, Text2SqlQuery
from lumen_models.user import User
from lumen_core.security import get_password_hash


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def auth_headers():
    """Issue a real JWT for the bootstrap admin user."""
    from lumen_core.security import create_access_token

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.tenant_id == 1).first()
        if user is None:
            pytest.skip("No user in tenant 1; cannot auth")
        token = create_access_token(data={"sub": user.username})
        return {"Authorization": f"Bearer {token}"}
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# /ask                                                                        #
# --------------------------------------------------------------------------- #


def test_ask_sync_happy_path(client, auth_headers):
    """Sync /ask runs the engine and returns the result."""
    fake = MagicMock()
    fake.invoke.return_value = MagicMock(
        content="SELECT 1 AS one",
        response_metadata={"finish_reason": "stop"},
    )
    with patch("lumen_services.text2sql.engine.create_chat_model", return_value=fake), \
         patch(
             "lumen_services.text2sql.engine.render_explanation_user",
             return_value="x",
         ):
        # We need the LLM to return both generate and explain. Set up
        # the fake to cycle through both.
        fake.invoke.side_effect = [
            MagicMock(content="SELECT 1 AS one", response_metadata={}),
            MagicMock(content="一行一列,值 1。\n置信度: 0.95",
                      response_metadata={}),
        ]
        # Use data_source_id=1 (the seeded default for tenant 1)
        resp = client.post(
            "/api/v1/text2sql/ask",
            headers=auth_headers,
            json={"data_source_id": 1, "question": "test question", "async_run": False},
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["code"] == 200
    assert body["data"]["status"] == "success"
    assert body["data"]["row_count"] == 1
    assert "SELECT" in body["data"]["generated_sql"].upper()


def test_ask_returns_404_for_missing_data_source(client, auth_headers):
    resp = client.post(
        "/api/v1/text2sql/ask",
        headers=auth_headers,
        json={"data_source_id": 999999, "question": "test", "async_run": False},
    )
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"]


def test_ask_async_returns_pending(client, auth_headers):
    """Async /ask must return immediately with status=pending."""
    resp = client.post(
        "/api/v1/text2sql/ask",
        headers=auth_headers,
        json={"data_source_id": 1, "question": "async test", "async_run": True},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["status"] == "pending"
    assert body["data"]["query_id"] > 0


# --------------------------------------------------------------------------- #
# /history                                                                    #
# --------------------------------------------------------------------------- #


def test_history_list_returns_paginated(client, auth_headers):
    """The history list endpoint must return paginated rows + total."""
    # Insert a few rows first
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.tenant_id == 1).first()
        for i in range(3):
            db.add(Text2SqlQuery(
                tenant_id=1, user_id=user.id, data_source_id=1,
                question=f"q{i}", status="success",
            ))
        db.commit()
    finally:
        db.close()

    resp = client.get(
        "/api/v1/text2sql/history?page=1&page_size=10",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 200
    assert body["page"] == 1
    assert body["page_size"] == 10
    assert body["total"] >= 3
