"""M27 background path test — KB ingest works without a foreground user.

Verifies:
- Setting an EmbeddingCallContext with ``call_type="system.kb_ingest"``
  and ``user_id=None`` writes a row tagged correctly so the UI can
  distinguish background reindex from foreground chat retrieval.
- When NO context is set (the worker shouldn't ever skip install in
  practice, but if it did), the embedder still works (the wrapper is
  transparent).

Spec: docs/superpowers/specs/2026-06-15-embedding-trace-retention.md §"system.kb_ingest"
"""
import os
import sys
import uuid
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from lumen_models.tenant import Tenant  # noqa: F401
from lumen_models.knowledge import KnowledgeBase  # noqa: F401
from lumen_models.model_config import ModelConfig  # noqa: F401
from lumen_models.agent import Agent  # noqa: F401
from lumen_models.agent_team import AgentTeam  # noqa: F401
from lumen_models.workflow import Workflow, WorkflowRun  # noqa: F401
from lumen_models.external_app import ExternalApp, ExternalVisitor  # noqa: F401
from lumen_models.chat import Conversation  # noqa: F401
from lumen_core.database import SessionLocal, ensure_embedding_call_logs_table
from lumen_core.embedding_call_context import (
    EmbeddingCallContext,
    set_embedding_context,
    reset_embedding_context,
)
from lumen_models.embedding_call_log import EmbeddingCallLog
from lumen_services.embedding_logging import LoggingEmbeddings


@pytest.fixture(autouse=True, scope="module")
def _ensure_table():
    ensure_embedding_call_logs_table()


def _cleanup(call_id: str):
    db = SessionLocal()
    try:
        db.query(EmbeddingCallLog).filter(
            EmbeddingCallLog.call_id == call_id
        ).delete()
        db.commit()
    finally:
        db.close()


def test_background_reindex_writes_row_with_no_user():
    """Celery worker installs context with user_id=None, tenant_id from task.

    M27.1: filter on trace_id + is_batch, not on ctx.call_id (the
    wrapper now generates a fresh uuid4 per call).
    """
    trace_id = str(uuid.uuid4())

    token = set_embedding_context(EmbeddingCallContext(
        call_id="bg-root",  # will be replaced by wrapper
        trace_id=trace_id,
        parent_call_id=None,
        call_type="system.kb_ingest",
        call_index=0,
        tenant_id=1,
        user_id=None,  # background path
        knowledge_base_id=None,
        client_app="celery_worker",
        extra={"document_id": 42, "doc_type": "pdf"},
    ))

    inner = MagicMock()
    inner.embed_documents.return_value = [[0.1] * 768, [0.2] * 768]

    wrapper = LoggingEmbeddings(
        inner, model_type="ollama", model_name="nomic-embed-text",
        model_config_id=None,
    )

    try:
        wrapper.embed_documents(["chunk 1", "chunk 2"])
    finally:
        reset_embedding_context(token)

    db = SessionLocal()
    try:
        row = (
            db.query(EmbeddingCallLog)
            .filter(
                EmbeddingCallLog.trace_id == trace_id,
                EmbeddingCallLog.is_batch == True,  # noqa: E712
                EmbeddingCallLog.batch_size == 2,
            )
            .first()
        )
        assert row is not None
        assert row.call_type == "system.kb_ingest"
        assert row.user_id is None
        assert row.tenant_id == 1
        assert row.client_app == "celery_worker"
        assert row.batch_size == 2
        assert row.extra == {"document_id": 42, "doc_type": "pdf"}
        actual_call_id = row.call_id
    finally:
        db.close()
    _cleanup(actual_call_id)


def test_background_no_context_still_works():
    """If for some reason the background worker forgot to install context,
    the embed_query call still succeeds (no row written, no crash)."""
    inner = MagicMock()
    inner.embed_query.return_value = [0.1] * 768

    wrapper = LoggingEmbeddings(
        inner, model_type="ollama", model_name="nomic-embed-text",
        model_config_id=None,
    )

    db = SessionLocal()
    try:
        before = db.query(EmbeddingCallLog).count()
    finally:
        db.close()

    # No set_embedding_context here.
    result = wrapper.embed_query("background, no context")
    assert len(result) == 768

    db = SessionLocal()
    try:
        after = db.query(EmbeddingCallLog).count()
    finally:
        db.close()

    assert after == before
