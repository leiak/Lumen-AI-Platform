"""NotificationService.publish_event unit tests"""
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime


@pytest.fixture
def db():
    """In-memory session stand-in. publish_event calls db.add, db.commit,
    db.refresh — we only need to assert the row's fields and the broadcast
    call. We use a MagicMock that records the added object."""
    session = MagicMock()
    added = {}

    def add(obj):
        added["obj"] = obj
    session.add.side_effect = add

    def refresh(obj):
        obj.id = 1
        obj.created_at = datetime(2026, 6, 4, 12, 0, 0)
    session.refresh.side_effect = refresh

    return session, added


def test_publish_event_writes_row(db):
    from lumen_services.notification_service import NotificationService

    session, added = db
    with patch(
        "lumen_services.notification_service.broadcast_event_sync"
    ) as mock_bcast:
        n = NotificationService.publish_event(
            session,
            user_id=42,
            type="knowledge_parse_completed",
            title="文档「a.txt」处理完成",
            body=None,
            resource_type="document",
            resource_id=7,
            metadata={"kb_id": 3, "filename": "a.txt", "status": "completed"},
        )

    obj = added["obj"]
    assert obj.user_id == 42
    assert obj.type == "knowledge_parse_completed"
    assert obj.title == "文档「a.txt」处理完成"
    assert obj.body is None
    assert obj.resource_type == "document"
    assert obj.resource_id == 7
    assert obj.metadata_json == {"kb_id": 3, "filename": "a.txt", "status": "completed"}
    assert session.commit.called
    assert session.refresh.called


def test_publish_event_broadcasts_with_target_user(db):
    from lumen_services.notification_service import NotificationService

    session, _ = db
    with patch(
        "lumen_services.notification_service.broadcast_event_sync"
    ) as mock_bcast:
        NotificationService.publish_event(
            session,
            user_id=42, type="knowledge_parse_failed",
            title="x", body="boom",
            resource_type="document", resource_id=7,
            metadata={"kb_id": 3},
        )

    mock_bcast.assert_called_once()
    kwargs = mock_bcast.call_args.kwargs
    assert kwargs["event"] == "notification_created"
    assert kwargs["target_user_id"] == 42
    payload = kwargs["payload"]
    assert payload["id"] == 1
    assert payload["type"] == "knowledge_parse_failed"
    assert payload["title"] == "x"
    assert payload["body"] == "boom"
    assert payload["resource_type"] == "document"
    assert payload["resource_id"] == 7
    assert payload["metadata"] == {"kb_id": 3}
    assert "created_at" in payload


def test_image_gen_notification_types_defined():
    from lumen_services.notification_service import (
        NOTIFICATION_TYPE_IMAGE_GEN_COMPLETED,
        NOTIFICATION_TYPE_IMAGE_GEN_FAILED,
    )
    assert NOTIFICATION_TYPE_IMAGE_GEN_COMPLETED == "IMAGE_GENERATION_COMPLETED"
    assert NOTIFICATION_TYPE_IMAGE_GEN_FAILED == "IMAGE_GENERATION_FAILED"
