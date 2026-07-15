"""knowledge.py should propagate current_user.id into task_params
and persist it on Document.created_by."""
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from lumen_main import app
    return TestClient(app)


@pytest.fixture
def document_task_module():
    """Eagerly load lumen_tasks.document_tasks so the test can patch
    `lumen_tasks.document_tasks.process_document_task`. The module is
    imported lazily inside the upload endpoint (see
    lumen_api/v1/knowledge.py) and the package __init__ is empty, so the
    attribute doesn't resolve otherwise. The two modules have a
    circular import — `document_tasks` needs `celery_app` to define
    the task decorator, and `celery_app` needs `document_tasks` to
    register the task. Loading celery_app first breaks the cycle
    because at that point the partial `celery_app` module already
    exposes the `celery_app` Celery instance (line 4 of celery_app.py)."""
    import lumen_tasks.celery_app  # noqa: F401
    import lumen_tasks.document_tasks  # noqa: F401
    return lumen_tasks.document_tasks


def _auth(tmp_user):
    from lumen_services.auth_service import create_access_token
    token = create_access_token(
        data={"sub": tmp_user.username, "user_id": tmp_user.id}
    )
    return {"Authorization": f"Bearer {token}"}


def test_upload_includes_user_id_in_task_params(client, tmp_user, tmp_kb, document_task_module):
    """When async_process=True (the default), task_params must carry user_id."""
    headers = _auth(tmp_user)
    with patch(
        "lumen_tasks.document_tasks.process_document_task"
    ) as mock_task:
        with open(__file__, "rb") as f:
            r = client.post(
                f"/api/v1/knowledge/{tmp_kb.id}/documents",
                headers=headers,
                files={"file": ("a.txt", f, "text/plain")},
                data={"doc_type": "txt", "async_process": "true"},
            )
        assert r.status_code == 200, r.text
        mock_task.delay.assert_called_once()
        params = mock_task.delay.call_args[0][0]
        assert params.get("user_id") == tmp_user.id


def test_upload_sets_created_by_on_document(client, tmp_user, tmp_kb, document_task_module):
    """Document row's created_by is set to current_user.id."""
    headers = _auth(tmp_user)
    with patch(
        "lumen_tasks.document_tasks.process_document_task"
    ):
        with open(__file__, "rb") as f:
            r = client.post(
                f"/api/v1/knowledge/{tmp_kb.id}/documents",
                headers=headers,
                files={"file": ("a.txt", f, "text/plain")},
                data={"doc_type": "txt", "async_process": "true"},
            )
        assert r.status_code == 200, r.text
    from lumen_models.knowledge import Document
    from lumen_core.database import SessionLocal
    db = SessionLocal()
    try:
        doc = db.query(Document).order_by(Document.id.desc()).first()
        assert doc.created_by == tmp_user.id
    finally:
        db.close()
