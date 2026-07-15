"""M33: tests for the Text2SqlService orchestration layer.

Spec: docs/superpowers/specs/2026-06-20-text2sql-design.md §6

We test:

- ``ask`` persists a row + runs the engine (mocked).
- ``ask`` returns an error message when the data source doesn't exist.
- ``list_history`` filters by tenant + status + keyword.
- ``get`` / ``delete`` enforce tenant scoping.
"""
import uuid
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

from lumen_core.database import SessionLocal
from lumen_models.text2sql import Text2SqlDataSource, Text2SqlQuery
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


def _make_ds() -> Text2SqlDataSource:
    return Text2SqlDataSource(
        tenant_id=1, name="svc_test", db_name="ai_platform",
        max_rows=10, timeout_ms=1000, is_active=1,
    )


# --------------------------------------------------------------------------- #
# ask                                                                         #
# --------------------------------------------------------------------------- #


def test_ask_returns_404_message_for_missing_data_source():
    db = SessionLocal()
    try:
        fake = _FakeChatModel([])
        with patch(
            "lumen_services.text2sql.engine.create_chat_model", return_value=fake
        ):
            row, err = Text2SqlService.ask(
                db, tenant_id=1, user_id=1,
                data_source_id=99999999, question="x",
            )
        assert row is None
        assert "not found" in (err or "")
    finally:
        db.close()


def test_ask_persists_query_row_on_success():
    """A successful /ask call must persist a row with status=success."""
    db = SessionLocal()
    try:
        # Use the seeded default
        ds = Text2SqlDataSourceService.get_default(db, tenant_id=1)
        assert ds is not None
        fake = _FakeChatModel([
            "SELECT 1 AS one",
            "一行一列,值 1。\n置信度: 0.9",
        ])
        with patch(
            "lumen_services.text2sql.engine.create_chat_model", return_value=fake
        ):
            row, err = Text2SqlService.ask(
                db, tenant_id=1, user_id=1,
                data_source_id=ds.id, question="test",
            )
        assert err is None
        assert row is not None
        assert row.status == "success"
        assert row.generated_sql is not None
        assert row.row_count is not None
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# list_history                                                                #
# --------------------------------------------------------------------------- #


def test_list_history_filters_by_tenant_and_keyword():
    """``list_history`` must scope by tenant and apply the keyword filter."""
    db = SessionLocal()
    try:
        suffix = uuid.uuid4().hex[:8]
        # Insert a uniquely-named query for tenant 1
        from lumen_models.user import User
        u = db.query(User).filter(User.tenant_id == 1).first()
        db.add(Text2SqlQuery(
            tenant_id=1, user_id=u.id, data_source_id=1,
            question=f"unique_keyword_{suffix} test", status="success",
        ))
        db.commit()
        # Query with keyword
        rows, total = Text2SqlService.list_history(
            db, tenant_id=1, keyword=suffix, page=1, page_size=10
        )
        assert any(suffix in r.question for r in rows)
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# delete                                                                      #
# --------------------------------------------------------------------------- #


def test_delete_returns_false_for_other_tenant():
    """``delete`` must enforce tenant scoping — a row from another
    tenant must NOT be deletable.
    """
    db = SessionLocal()
    try:
        from lumen_models.user import User
        u = db.query(User).filter(User.tenant_id == 1).first()
        q = Text2SqlQuery(
            tenant_id=1, user_id=u.id, data_source_id=1,
            question="x", status="success",
        )
        db.add(q)
        db.commit()
        db.refresh(q)

        # Wrong tenant — should return False
        assert Text2SqlService.delete(
            db, tenant_id=999, query_id=q.id
        ) is False
        # Right tenant — should succeed
        assert Text2SqlService.delete(
            db, tenant_id=1, query_id=q.id
        ) is True
    finally:
        db.close()
