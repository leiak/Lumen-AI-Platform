"""M27 model-level tests for ``embedding_call_logs``.

Mirrors ``test_llm_call_log_model.py`` (M26). Pin down:

- ORM model construction with required + optional fields
- JSON column round-trip on ``extra``
- Table exists after ``ensure_embedding_call_logs_table()`` runs
- ``ensure_embedding_call_logs_table`` is idempotent
- Composite indexes exist
- UNIQUE constraint on ``call_id``

Spec: docs/superpowers/specs/2026-06-15-embedding-trace-retention.md
"""
import os
import sys
import uuid
from datetime import datetime

import pytest
from sqlalchemy import inspect

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

# FK targets must be registered first; mirrors main.py import ordering.
from lumen_models.tenant import Tenant  # noqa: F401
from lumen_models.knowledge import KnowledgeBase  # noqa: F401
from lumen_models.model_config import ModelConfig  # noqa: F401
from lumen_models.agent import Agent  # noqa: F401
from lumen_models.agent_team import AgentTeam  # noqa: F401
from lumen_models.workflow import Workflow, WorkflowRun  # noqa: F401
from lumen_models.external_app import ExternalApp, ExternalVisitor  # noqa: F401
from lumen_models.chat import Conversation  # noqa: F401
from lumen_core.database import (
    SessionLocal,
    ensure_embedding_call_logs_table,
    ensure_soft_delete_columns,
    engine,
)
from lumen_models.embedding_call_log import EmbeddingCallLog


def test_table_created_with_expected_columns():
    ensure_embedding_call_logs_table()
    ensure_soft_delete_columns()
    insp = inspect(engine)
    cols = {c["name"]: c for c in insp.get_columns("embedding_call_logs")}
    expected = [
        "call_id", "parent_call_id", "trace_id", "call_type", "call_index",
        "tenant_id", "user_id", "username", "client_app",
        "conversation_id", "agent_id", "team_id",
        "workflow_id", "workflow_run_id", "workflow_node_id",
        "knowledge_base_id",
        "model_type", "model_name", "model_config_id",
        "text_preview", "text_chars", "is_batch", "batch_size",
        "embedding_dim", "embedding_bytes",
        "started_at", "finished_at", "duration_ms",
        "status", "error_type", "error_message", "retry_count",
        "request_ip", "user_agent", "extra",
        "archived_at",
        # From BaseModel
        "id", "created_at", "updated_at",
    ]
    for col in expected:
        assert col in cols, f"missing column: {col}"


def test_migration_is_idempotent():
    """Running ensure_embedding_call_logs_table() multiple times must not raise."""
    ensure_embedding_call_logs_table()
    ensure_embedding_call_logs_table()
    ensure_embedding_call_logs_table()


def test_soft_delete_columns_idempotent():
    """ensure_soft_delete_columns() must be safe to re-run."""
    ensure_embedding_call_logs_table()
    ensure_soft_delete_columns()
    ensure_soft_delete_columns()
    ensure_soft_delete_columns()


def test_insert_and_fetch_row_basic():
    """Round-trip: insert a minimal row, fetch by call_id, check fields."""
    call_id = f"emb-{uuid.uuid4().hex[:8]}"
    trace_id = f"etrace-{uuid.uuid4().hex[:8]}"
    db = SessionLocal()
    try:
        row = EmbeddingCallLog(
            call_id=call_id,
            trace_id=trace_id,
            call_type="kb_retrieval",
            call_index=0,
            tenant_id=1,
            user_id=1,
            username="tester",
            model_name="nomic-embed-text",
            model_type="ollama",
            text_preview="hello world",
            text_chars=11,
            is_batch=False,
            embedding_dim=768,
            embedding_bytes=3072,
            started_at=datetime.utcnow(),
            status="success",
            duration_ms=42,
        )
        db.add(row)
        db.commit()
        db.refresh(row)

        fetched = (
            db.query(EmbeddingCallLog)
            .filter(EmbeddingCallLog.call_id == call_id)
            .first()
        )
        assert fetched is not None
        assert fetched.call_id == call_id
        assert fetched.trace_id == trace_id
        assert fetched.call_type == "kb_retrieval"
        assert fetched.embedding_dim == 768
        assert fetched.embedding_bytes == 3072
        assert fetched.is_batch is False or fetched.is_batch == 0
        assert fetched.status == "success"
    finally:
        db.query(EmbeddingCallLog).filter(
            EmbeddingCallLog.call_id == call_id
        ).delete()
        db.commit()
        db.close()


def test_insert_extra_json_roundtrip():
    """``extra`` JSON column must round-trip arbitrary dicts."""
    call_id = f"emb-extra-{uuid.uuid4().hex[:8]}"
    db = SessionLocal()
    try:
        extra = {
            "is_dim_probe": True,
            "top_k": 5,
            "filter_expr": "tenant_id == 1 and kb_id == 2",
            "kb_ids": [1, 2, 3],
        }
        row = EmbeddingCallLog(
            call_id=call_id,
            trace_id="t1",
            call_type="kb_retrieval",
            model_name="nomic-embed-text",
            text_preview="query",
            text_chars=5,
            is_batch=False,
            embedding_dim=768,
            embedding_bytes=3072,
            started_at=datetime.utcnow(),
            duration_ms=11,
            extra=extra,
        )
        db.add(row)
        db.commit()
        db.refresh(row)

        fetched = (
            db.query(EmbeddingCallLog)
            .filter(EmbeddingCallLog.call_id == call_id)
            .first()
        )
        assert fetched.extra == extra
    finally:
        db.query(EmbeddingCallLog).filter(
            EmbeddingCallLog.call_id == call_id
        ).delete()
        db.commit()
        db.close()


def test_unique_call_id_constraint():
    """call_id has a UNIQUE constraint — duplicate insert must fail."""
    call_id = f"emb-dup-{uuid.uuid4().hex[:8]}"
    db = SessionLocal()
    try:
        a = EmbeddingCallLog(
            call_id=call_id, trace_id="t1", call_type="kb_retrieval",
            model_name="m", text_chars=1, text_preview="a",
            started_at=datetime.utcnow(),
        )
        db.add(a)
        db.commit()
        b = EmbeddingCallLog(
            call_id=call_id, trace_id="t2", call_type="kb_retrieval",
            model_name="m", text_chars=1, text_preview="b",
            started_at=datetime.utcnow(),
        )
        db.add(b)
        with pytest.raises(Exception):
            db.commit()
        db.rollback()
    finally:
        db.query(EmbeddingCallLog).filter(
            EmbeddingCallLog.call_id == call_id
        ).delete()
        db.commit()
        db.close()


def test_composite_indexes_exist():
    """The 6 composite indexes from the spec must be created."""
    ensure_embedding_call_logs_table()
    insp = inspect(engine)
    indexes = {ix["name"]: ix for ix in insp.get_indexes("embedding_call_logs")}
    expected = [
        "idx_ecl_tenant_time",
        "idx_ecl_model_time",
        "idx_ecl_kb",
        "idx_ecl_trace",
        "idx_ecl_status_time",
        "idx_ecl_call_type_time",
    ]
    for ix in expected:
        assert ix in indexes, f"missing composite index: {ix}"


def test_is_batch_default_false():
    """is_batch defaults to False (used for embed_query path)."""
    call_id = f"emb-batch-{uuid.uuid4().hex[:8]}"
    db = SessionLocal()
    try:
        row = EmbeddingCallLog(
            call_id=call_id,
            trace_id="t1",
            call_type="kb_retrieval",
            model_name="m",
            text_preview="q",
            text_chars=1,
            started_at=datetime.utcnow(),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        # is_batch column default applies at insert time
        assert row.is_batch is False or row.is_batch == 0
    finally:
        db.query(EmbeddingCallLog).filter(
            EmbeddingCallLog.call_id == call_id
        ).delete()
        db.commit()
        db.close()
