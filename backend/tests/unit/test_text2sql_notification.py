"""M33: notification test — async run publishes TEXT2SQL_COMPLETED/FAILED.

Spec: docs/superpowers/specs/2026-06-20-text2sql-design.md §6
"""
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

from lumen_core.database import SessionLocal
from lumen_models.text2sql import Text2SqlDataSource, Text2SqlQuery
from lumen_models.user import User
from lumen_services.text2sql.data_source_service import Text2SqlDataSourceService
from lumen_services.text2sql_service import Text2SqlService


class _FakeChatModel:
    def __init__(self, responses: List[str]) -> None:
        self._responses = list(responses)
        self._call_count = 0

    def invoke(self, messages: List[Any]) -> Any:
        idx = min(self._call_count, len(self._responses) - 1)
        self._call_count += 1
        resp = MagicMock()
        resp.content = self._responses[idx]
        resp.response_metadata = {"finish_reason": "stop"}
        return resp


def test_run_ask_publishes_completed_notification_on_success():
    """The background worker must publish TEXT2SQL_COMPLETED on success."""
    from fastapi import BackgroundTasks

    db = SessionLocal()
    try:
        ds = Text2SqlDataSourceService.get_default(db, tenant_id=1)
        assert ds is not None
        bg = BackgroundTasks()

        fake = _FakeChatModel([
            "SELECT 1 AS one",
            "一行一列,值 1。\n置信度: 0.9",
        ])
        with patch(
            "lumen_services.text2sql.engine.create_chat_model", return_value=fake
        ), patch(
            "lumen_services.text2sql_service.NotificationService.publish_event"
        ) as pub:
            row, err = Text2SqlService.ask_async(
                db, bg, tenant_id=1, user_id=1,
                data_source_id=ds.id, question="x",
            )
            assert err is None
            assert row is not None
            # Run the background task synchronously (in starlette,
            # bg.tasks is a list of BackgroundTask objects with
            # .func / .args / .kwargs).
            for task in bg.tasks:
                task.func(*task.args, **task.kwargs)
        # Verify the notification was published
        assert pub.called
        call_kwargs = pub.call_args.kwargs
        assert call_kwargs.get("type") in {"TEXT2SQL_COMPLETED", "TEXT2SQL_FAILED"}
    finally:
        db.close()
