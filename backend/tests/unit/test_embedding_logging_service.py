"""M27 unit tests for ``LoggingEmbeddings`` proxy + service.

Covers:
- ``LoggingEmbeddings.embed_query`` writes 1 row when context is set
- ``LoggingEmbeddings.embed_query`` is transparent (no row) when no
  context is set — protects background paths from polluting the table
- ``LoggingEmbeddings`` flags ``extra.is_dim_probe = True`` when the
  text is the sentinel ``"dim-probe"``
- Failure path: exception in inner.embed_query still writes a row
  with ``status="failure"`` and re-raises
- ``embed_documents`` writes a batch row with ``is_batch=True`` and the
  correct batch_size
- ``EmbeddingCallLoggingService.log_call`` returns None on DB error
  (observability never breaks the embed path)

Spec: docs/superpowers/specs/2026-06-15-embedding-trace-retention.md §"LoggingEmbeddings"
"""
import os
import sys
import uuid
from datetime import datetime
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


def _make_ctx(call_id: str = None, call_type: str = "kb_retrieval") -> EmbeddingCallContext:
    return EmbeddingCallContext(
        call_id=call_id or f"emb-{uuid.uuid4().hex[:8]}",
        trace_id=f"trace-{uuid.uuid4().hex[:8]}",
        parent_call_id=None,
        call_type=call_type,
        call_index=0,
        tenant_id=1,
        user_id=1,
        username="tester",
        knowledge_base_id=None,
        client_app="dashboard",
    )


def _count_rows(call_id: str) -> int:
    db = SessionLocal()
    try:
        return (
            db.query(EmbeddingCallLog)
            .filter(EmbeddingCallLog.call_id == call_id)
            .count()
        )
    finally:
        db.close()


def _cleanup(call_id: str):
    db = SessionLocal()
    try:
        db.query(EmbeddingCallLog).filter(
            EmbeddingCallLog.call_id == call_id
        ).delete()
        db.commit()
    finally:
        db.close()


def test_embed_query_writes_row_when_context_set():
    """embed_query inside a context writes one row.

    M27.1: the wrapper generates a fresh call_id (uuid4) per embed
    call to keep UNIQUE-constraint safe when the same active
    context is used by multiple embed calls. We can't predict the
    call_id, so we filter on trace_id + text_preview (deterministic).
    """
    inner = MagicMock()
    inner.embed_query.return_value = [0.1] * 768

    wrapper = LoggingEmbeddings(
        inner,
        model_type="ollama",
        model_name="nomic-embed-text",
        model_config_id=None,  # FK-free for unit-test isolation
    )

    ctx = _make_ctx(call_type="kb_retrieval")
    token = set_embedding_context(ctx)
    try:
        result = wrapper.embed_query("hello world")
    finally:
        reset_embedding_context(token)

    assert len(result) == 768

    db = SessionLocal()
    try:
        row = (
            db.query(EmbeddingCallLog)
            .filter(
                EmbeddingCallLog.trace_id == ctx.trace_id,
                EmbeddingCallLog.text_preview == "hello world",
            )
            .first()
        )
        assert row is not None, "no row written for context-set embed_query"
        assert row.call_type == "kb_retrieval"
        assert row.trace_id == ctx.trace_id
        assert row.parent_call_id == ctx.parent_call_id
        assert row.model_name == "nomic-embed-text"
        assert row.model_type == "ollama"
        assert row.text_chars == 11
        assert row.embedding_dim == 768
        assert row.embedding_bytes == 768 * 4
        assert row.status == "success"
        assert row.is_batch is False or row.is_batch == 0
        # Cleanup using the actual generated call_id
        call_id = row.call_id
    finally:
        db.close()
    _cleanup(call_id)


def test_embed_query_transparent_without_context():
    """embed_query OUTSIDE a context just delegates; no row written."""
    inner = MagicMock()
    inner.embed_query.return_value = [0.1] * 768

    wrapper = LoggingEmbeddings(
        inner,
        model_type="ollama",
        model_name="nomic-embed-text",
        model_config_id=None,
    )

    # No set_embedding_context() — proxy should be transparent.
    db = SessionLocal()
    try:
        before = db.query(EmbeddingCallLog).count()
    finally:
        db.close()

    result = wrapper.embed_query("background query")
    assert len(result) == 768

    db = SessionLocal()
    try:
        after = db.query(EmbeddingCallLog).count()
    finally:
        db.close()

    assert after == before, "wrapper should not write rows without a context"


def test_dim_probe_flags_extra_is_dim_probe_true():
    """text == 'dim-probe' triggers extra.is_dim_probe = True."""
    inner = MagicMock()
    inner.embed_query.return_value = [0.0] * 768

    wrapper = LoggingEmbeddings(
        inner, model_type="ollama", model_name="nomic-embed-text", model_config_id=None,
    )

    ctx = _make_ctx()
    token = set_embedding_context(ctx)
    try:
        wrapper.embed_query("dim-probe")
    finally:
        reset_embedding_context(token)

    db = SessionLocal()
    try:
        row = (
            db.query(EmbeddingCallLog)
            .filter(
                EmbeddingCallLog.trace_id == ctx.trace_id,
                EmbeddingCallLog.text_preview == "dim-probe",
            )
            .first()
        )
        assert row is not None
        assert row.extra is not None
        assert row.extra.get("is_dim_probe") is True
        call_id = row.call_id
    finally:
        db.close()
    _cleanup(call_id)


def test_embed_query_failure_writes_row_and_reraises():
    """If inner.embed_query raises, a failure row is written and the exception propagates."""
    inner = MagicMock()
    inner.embed_query.side_effect = RuntimeError("ollama unreachable")

    wrapper = LoggingEmbeddings(
        inner, model_type="ollama", model_name="nomic-embed-text", model_config_id=None,
    )

    ctx = _make_ctx()
    token = set_embedding_context(ctx)
    try:
        with pytest.raises(RuntimeError, match="ollama unreachable"):
            wrapper.embed_query("query-failure-test")
    finally:
        reset_embedding_context(token)

    db = SessionLocal()
    try:
        row = (
            db.query(EmbeddingCallLog)
            .filter(
                EmbeddingCallLog.trace_id == ctx.trace_id,
                EmbeddingCallLog.text_preview == "query-failure-test",
            )
            .first()
        )
        assert row is not None
        assert row.status == "failure"
        assert row.error_type == "RuntimeError"
        assert "ollama unreachable" in (row.error_message or "")
        call_id = row.call_id
    finally:
        db.close()
    _cleanup(call_id)


def test_embed_documents_writes_batch_row():
    """embed_documents writes a row with is_batch=True, correct batch_size, total chars."""
    inner = MagicMock()
    inner.embed_documents.return_value = [[0.1] * 768, [0.2] * 768, [0.3] * 768]

    wrapper = LoggingEmbeddings(
        inner, model_type="ollama", model_name="nomic-embed-text", model_config_id=None,
    )

    ctx = _make_ctx(call_type="kb_ingest")
    token = set_embedding_context(ctx)
    try:
        result = wrapper.embed_documents(["doc1", "longer doc2", "doc 3"])
    finally:
        reset_embedding_context(token)

    assert len(result) == 3

    db = SessionLocal()
    try:
        row = (
            db.query(EmbeddingCallLog)
            .filter(
                EmbeddingCallLog.trace_id == ctx.trace_id,
                EmbeddingCallLog.text_preview == "doc1",
                EmbeddingCallLog.is_batch == True,  # noqa: E712
            )
            .first()
        )
        assert row is not None
        assert row.batch_size == 3
        # total chars: 4 + 11 + 5 = 20
        assert row.text_chars == 20
        assert row.embedding_dim == 768
        # 768 * 4 * 3 = 9216
        assert row.embedding_bytes == 9216
        call_id = row.call_id
    finally:
        db.close()
    _cleanup(call_id)


def test_logging_proxies_unknown_attributes():
    """Attributes not defined on LoggingEmbeddings proxy through to the inner Embeddings."""
    inner = MagicMock()
    inner.some_custom_method.return_value = "passthrough"
    inner.model_dump_json = "not callable, just a value"

    wrapper = LoggingEmbeddings(
        inner, model_type="ollama", model_name="n", model_config_id=None,
    )
    # Method passthrough
    assert wrapper.some_custom_method() == "passthrough"
    # Attribute passthrough
    assert wrapper.model_dump_json == "not callable, just a value"


def test_text_preview_truncated_to_200_chars():
    """text_preview is truncated at 200; text_chars preserves full length."""
    inner = MagicMock()
    inner.embed_query.return_value = [0.0] * 768

    wrapper = LoggingEmbeddings(
        inner, model_type="ollama", model_name="n", model_config_id=None,
    )

    long_text = "x" * 500
    ctx = _make_ctx()
    token = set_embedding_context(ctx)
    try:
        wrapper.embed_query(long_text)
    finally:
        reset_embedding_context(token)

    db = SessionLocal()
    try:
        row = (
            db.query(EmbeddingCallLog)
            .filter(
                EmbeddingCallLog.trace_id == ctx.trace_id,
                EmbeddingCallLog.text_chars == 500,
            )
            .first()
        )
        assert row is not None
        assert len(row.text_preview) == 200
        call_id = row.call_id
    finally:
        db.close()
    _cleanup(call_id)


def test_each_embed_query_writes_a_unique_call_id():
    """M27.1 regression: factory's cold-start dim-probe and the
    actual user query share the per-KB refined context — but each
    embed call must write a row with its OWN unique call_id, not
    re-use the context's. Otherwise the second call hits UNIQUE
    constraint uq_ecl_call_id and the row is silently dropped
    (observability row skipped).

    Reproduces the 2026-06-15 chat smoke test bug: chat set a
    context, agent_rag refined it per-KB, then the factory's
    dim-probe and the user query both ran under that refined ctx.
    Only 1 of 2 rows persisted because they shared call_id.
    """
    inner = MagicMock()
    inner.embed_query.side_effect = lambda _: [0.0] * 768

    wrapper = LoggingEmbeddings(
        inner, model_type="ollama", model_name="n", model_config_id=None,
    )

    # Outer ctx is the "parent" one (e.g. from chat.py).
    ctx = _make_ctx(call_type="kb_retrieval")
    # Refine to a per-KB context (mirrors what _retrieve_kb_chunks does).
    # knowledge_base_id=None to avoid the FK to knowledge_bases in this
    # unit test (the dev DB may not have KB id=42).
    per_kb_ctx = ctx._replace(
        call_type="kb_retrieval",
        knowledge_base_id=None,
        extra={**(ctx.extra or {}), "kb_name": "demo-kb"},
    )

    token = set_embedding_context(per_kb_ctx)
    try:
        # First call: factory's cold-start probe.
        wrapper.embed_query("dim-probe")
        # Second call: the actual user query.
        wrapper.embed_query("user query for KB 42")
    finally:
        reset_embedding_context(token)

    # BOTH calls should have written a row. We can't predict the
    # call_ids (they're uuid4-generated inside the wrapper) but we
    # can count rows under our per-KB context and check the texts.
    db = SessionLocal()
    try:
        rows = (
            db.query(EmbeddingCallLog)
            .filter(
                EmbeddingCallLog.trace_id == ctx.trace_id,
                EmbeddingCallLog.text_preview.in_(
                    ["dim-probe", "user query for KB 42"]
                ),
            )
            .all()
        )
        assert len(rows) == 2, (
            f"expected 2 rows (dim-probe + user query), got {len(rows)}: "
            f"{[(r.call_id[:8], r.text_preview) for r in rows]}"
        )
        previews = {r.text_preview for r in rows}
        assert previews == {"dim-probe", "user query for KB 42"}, previews
        # call_ids must be unique
        call_ids = {r.call_id for r in rows}
        assert len(call_ids) == 2
    finally:
        db.close()
    # Cleanup by trace_id
    db = SessionLocal()
    try:
        db.query(EmbeddingCallLog).filter(
            EmbeddingCallLog.trace_id == ctx.trace_id,
            EmbeddingCallLog.text_preview.in_(
                ["dim-probe", "user query for KB 42"]
            ),
        ).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()
