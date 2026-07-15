"""Tests for the soft-delete Conversation endpoint and the soft-delete
filter on the list endpoint."""
import pytest
import uuid
from fastapi.testclient import TestClient


# Shared helper lives in tests/conftest.py (see make_conv).
from tests.conftest import make_conv


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


def test_delete_soft_deletes_and_returns_envelope(client, auth_header, tmp_user):
    """DELETE /chat/conversations/{id} sets deleted_at; row remains in DB;
    response is the standard SingleResponse envelope with code=200."""
    from lumen_core.database import SessionLocal
    from lumen_models.chat import Conversation

    db = SessionLocal()
    try:
        conv = make_conv(db, user_id=tmp_user.id, tenant_id=tmp_user.tenant_id, title="to be soft-deleted")
        conv_id = conv.id
    finally:
        db.close()

    r = client.delete(f"/api/v1/chat/conversations/{conv_id}", headers=auth_header)

    assert r.status_code == 200
    body = r.json()
    assert body["code"] == 200
    assert body["message"] == "Deleted successfully"
    assert body["data"] is None

    # Row still exists; deleted_at is set
    db = SessionLocal()
    try:
        row = db.query(Conversation).filter(Conversation.id == conv_id).first()
        assert row is not None
        assert row.deleted_at is not None
    finally:
        db.close()


def test_delete_other_users_conversation_returns_404(client, tmp_user):
    """User A cannot delete user B's conversation (no IDOR leak via 404)."""
    from lumen_core.database import SessionLocal
    from lumen_models.user import User
    from lumen_services.auth_service import create_access_token

    db = SessionLocal()
    try:
        # Create a second user in the same tenant
        suffix = uuid.uuid4().hex[:8]
        other = User(
            username=f"other_{suffix}",
            email=f"other_{suffix}@example.com",
            hashed_password="x",
            tenant_id=tmp_user.tenant_id,
            is_active=True,
        )
        db.add(other)
        db.commit()
        db.refresh(other)

        # Other user creates a conversation
        conv = make_conv(db, user_id=other.id, tenant_id=tmp_user.tenant_id, title="other user's")
        conv_id = conv.id

        # tmp_user attempts to delete it
        token = create_access_token(
            data={"sub": tmp_user.username, "user_id": tmp_user.id}
        )
        headers = {"Authorization": f"Bearer {token}"}

        r = client.delete(f"/api/v1/chat/conversations/{conv_id}", headers=headers)
    finally:
        db.close()

    assert r.status_code == 404
    assert "not found" in r.json().get("detail", "").lower()


def test_delete_nonexistent_returns_404(client, auth_header):
    """A non-existent conv_id returns 404."""
    r = client.delete("/api/v1/chat/conversations/99999999", headers=auth_header)
    assert r.status_code == 404


def test_delete_hides_from_list(client, auth_header, tmp_user):
    """After soft-delete, GET /chat/conversations no longer includes the row."""
    from lumen_core.database import SessionLocal

    db = SessionLocal()
    try:
        keep = make_conv(db, user_id=tmp_user.id, tenant_id=tmp_user.tenant_id, title="keep me")
        gone = make_conv(db, user_id=tmp_user.id, tenant_id=tmp_user.tenant_id, title="delete me")
        keep_id, gone_id = keep.id, gone.id
    finally:
        db.close()

    # Before delete: both are listed
    r1 = client.get("/api/v1/chat/conversations", headers=auth_header)
    assert r1.status_code == 200
    ids_before = {c["id"] for c in r1.json()["data"]}
    assert keep_id in ids_before and gone_id in ids_before

    # Soft-delete `gone`
    r_del = client.delete(f"/api/v1/chat/conversations/{gone_id}", headers=auth_header)
    assert r_del.status_code == 200

    # After delete: only `keep` is listed
    r2 = client.get("/api/v1/chat/conversations", headers=auth_header)
    assert r2.status_code == 200
    ids_after = {c["id"] for c in r2.json()["data"]}
    assert keep_id in ids_after
    assert gone_id not in ids_after
