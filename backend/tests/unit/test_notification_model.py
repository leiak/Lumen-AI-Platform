import pytest


def test_notification_model_imports():
    from lumen_models.notification import Notification
    assert Notification.__tablename__ == "notifications"


def test_notification_model_fields():
    from lumen_models.notification import Notification
    cols = {c.name for c in Notification.__table__.columns}
    for required in ("id", "user_id", "type", "title", "body",
                     "resource_type", "resource_id", "metadata_json",
                     "read_at", "created_at"):
        assert required in cols, f"missing column {required}"
