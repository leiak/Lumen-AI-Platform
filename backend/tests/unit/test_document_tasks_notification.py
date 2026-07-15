"""document_tasks._emit_notification: writes row + broadcasts."""
import pytest
from unittest.mock import MagicMock, patch


def _fake_doc():
    d = MagicMock()
    d.id = 7
    d.filename = "a.txt"
    # M29.1 regression guard: the real ORM attribute is
    # ``knowledge_base_id`` (NOT ``kb_id``). Use the correct field name
    # here so a future refactor that re-introduces ``doc.kb_id`` in
    # _emit_notification would surface as a MagicMock leak in
    # ``metadata['kb_id']`` rather than the expected 3.
    d.knowledge_base_id = 3
    d.error_message = "boom"
    return d


def test_emit_success_publishes_completed():
    from lumen_tasks.document_tasks import _emit_notification
    db = MagicMock()
    with patch("lumen_tasks.document_tasks.NotificationService") as mock_svc:
        _emit_notification(
            db,
            task_params={"user_id": 42, "document_id": 7},
            doc=_fake_doc(), error=False,
        )
    mock_svc.publish_event.assert_called_once()
    kwargs = mock_svc.publish_event.call_args.kwargs
    assert kwargs["user_id"] == 42
    assert kwargs["type"] == "knowledge_parse_completed"
    assert kwargs["title"] == "文档「a.txt」处理完成"
    assert kwargs["body"] is None
    assert kwargs["resource_type"] == "document"
    assert kwargs["resource_id"] == 7
    assert kwargs["metadata"]["kb_id"] == 3
    assert kwargs["metadata"]["status"] == "completed"


def test_emit_failure_publishes_failed():
    from lumen_tasks.document_tasks import _emit_notification
    db = MagicMock()
    with patch("lumen_tasks.document_tasks.NotificationService") as mock_svc:
        _emit_notification(
            db,
            task_params={"user_id": 42},
            doc=_fake_doc(), error=True,
        )
    kwargs = mock_svc.publish_event.call_args.kwargs
    assert kwargs["type"] == "knowledge_parse_failed"
    assert kwargs["title"] == "文档「a.txt」处理失败"
    assert kwargs["body"] == "boom"
    assert kwargs["metadata"]["kb_id"] == 3
    assert kwargs["metadata"]["status"] == "failed"


def test_emit_skips_when_user_id_missing():
    from lumen_tasks.document_tasks import _emit_notification
    db = MagicMock()
    with patch("lumen_tasks.document_tasks.NotificationService") as mock_svc:
        _emit_notification(
            db, task_params={"document_id": 7}, doc=_fake_doc(), error=False
        )
    mock_svc.publish_event.assert_not_called()


def test_emit_reflects_doc_status_failed():
    """If the success-path call site passes error=doc.status=='failed',
    the emitted type should be 'knowledge_parse_failed' even from the
    'happy' branch (embedding failure case)."""
    from lumen_tasks.document_tasks import _emit_notification
    db = MagicMock()
    doc = _fake_doc()
    doc.status = "failed"  # actual doc state after embedding failure
    with patch("lumen_tasks.document_tasks.NotificationService") as mock_svc:
        _emit_notification(
            db,
            task_params={"user_id": 42},
            doc=doc,
            error=(doc.status == "failed"),
        )
    kwargs = mock_svc.publish_event.call_args.kwargs
    assert kwargs["type"] == "knowledge_parse_failed"
    assert kwargs["title"] == "文档「a.txt」处理失败"
    assert kwargs["body"] == "boom"
    assert kwargs["metadata"]["kb_id"] == 3
    assert kwargs["metadata"]["status"] == "failed"


def test_emit_reflects_doc_status_completed():
    """If the success-path call site passes error=False and doc.status is
    'completed', the emitted type should be 'knowledge_parse_completed'."""
    from lumen_tasks.document_tasks import _emit_notification
    db = MagicMock()
    doc = _fake_doc()
    doc.status = "completed"
    with patch("lumen_tasks.document_tasks.NotificationService") as mock_svc:
        _emit_notification(
            db,
            task_params={"user_id": 42},
            doc=doc,
            error=(doc.status == "failed"),
        )
    kwargs = mock_svc.publish_event.call_args.kwargs
    assert kwargs["type"] == "knowledge_parse_completed"
    assert kwargs["title"] == "文档「a.txt」处理完成"
    assert kwargs["body"] is None
    assert kwargs["metadata"]["status"] == "completed"
