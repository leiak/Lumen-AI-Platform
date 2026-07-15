"""Notifications REST API: list / unread-count / mark-read / mark-all-read"""
import pytest
import uuid
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


def test_list_returns_only_my_notifications(client, auth_header, tmp_user):
    from lumen_models.notification import Notification
    from lumen_core.database import SessionLocal

    # Seed: 2 for me, 1 for another user
    db = SessionLocal()
    try:
        from lumen_models.user import User
        # uuid suffix avoids the unique-username/email collision when the
        # test is re-run against the same DB.
        suffix = uuid.uuid4().hex[:8]
        other = User(
            username=f"notif_other_{suffix}", email=f"o_{suffix}@t.local",
            hashed_password="x", tenant_id=1, is_active=True,
        )
        db.add(other); db.commit(); db.refresh(other)
        for _ in range(2):
            db.add(Notification(
                user_id=tmp_user.id, type="knowledge_parse_completed",
                title="t", body=None, resource_type="document",
                resource_id=1, metadata_json={"kb_id": 1},
            ))
        db.add(Notification(
            user_id=other.id, type="knowledge_parse_completed",
            title="other", body=None, resource_type=None,
            resource_id=None, metadata_json=None,
        ))
        db.commit()
    finally:
        db.close()

    r = client.get("/api/v1/notifications", headers=auth_header)
    assert r.status_code == 200
    body = r.json()
    items = body["data"]["items"]
    assert len(items) == 2
    for it in items:
        assert it["user_id"] == tmp_user.id


def test_unread_count(client, auth_header, tmp_user):
    from lumen_models.notification import Notification
    from lumen_core.database import SessionLocal
    db = SessionLocal()
    try:
        for i in range(3):
            db.add(Notification(
                user_id=tmp_user.id, type="x", title=f"t{i}",
                body=None, resource_type=None, resource_id=None,
                metadata_json=None,
            ))
        db.commit()
    finally:
        db.close()

    r = client.get("/api/v1/notifications/unread-count", headers=auth_header)
    assert r.json()["data"]["count"] == 3


def test_mark_read_is_idempotent(client, auth_header, tmp_user):
    from lumen_models.notification import Notification
    from lumen_core.database import SessionLocal
    db = SessionLocal()
    try:
        n = Notification(
            user_id=tmp_user.id, type="x", title="t",
            body=None, resource_type=None, resource_id=None,
            metadata_json=None,
        )
        db.add(n); db.commit(); db.refresh(n)
        nid = n.id
    finally:
        db.close()

    r1 = client.post(f"/api/v1/notifications/{nid}/read", headers=auth_header)
    r2 = client.post(f"/api/v1/notifications/{nid}/read", headers=auth_header)
    assert r1.status_code == 200
    assert r2.status_code == 200


def test_mark_all_read(client, auth_header, tmp_user):
    from lumen_models.notification import Notification
    from lumen_core.database import SessionLocal
    db = SessionLocal()
    try:
        for _ in range(4):
            db.add(Notification(
                user_id=tmp_user.id, type="x", title="t",
                body=None, resource_type=None, resource_id=None,
                metadata_json=None,
            ))
        db.commit()
    finally:
        db.close()

    r = client.post("/api/v1/notifications/read-all", headers=auth_header)
    assert r.status_code == 200
    assert r.json()["data"]["affected"] == 4


def test_other_user_cannot_mark_my_notification(client, tmp_user):
    """Cross-user isolation: user A cannot mark user B's notification."""
    from lumen_models.notification import Notification
    from lumen_models.user import User
    from lumen_services.auth_service import create_access_token
    from lumen_core.database import SessionLocal

    db = SessionLocal()
    try:
        n = Notification(
            user_id=tmp_user.id, type="x", title="t",
            body=None, resource_type=None, resource_id=None,
            metadata_json=None,
        )
        db.add(n); db.commit(); db.refresh(n)
        nid = n.id
        # Make a second user and get their token
        suffix = uuid.uuid4().hex[:8]
        a = User(
            username=f"notif_attacker_{suffix}", email=f"a_{suffix}@t.local",
            hashed_password="x", tenant_id=1, is_active=True,
        )
        db.add(a); db.commit(); db.refresh(a)
        token = create_access_token(
            data={"sub": a.username, "user_id": a.id}
        )
    finally:
        db.close()

    r = client.post(
        f"/api/v1/notifications/{nid}/read",
        headers={"Authorization": f"Bearer {token}"},
    )
    # 404 (not visible to attacker) is acceptable; 403 also OK.
    assert r.status_code in (403, 404)
