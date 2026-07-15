"""M27 trace propagation test — embedding rows share trace_id with LLM rows.

When ``/chat/stream`` installs an LLMCallContext with trace_id=X and a
parallel EmbeddingCallContext also using trace_id=X, the resulting rows
in ``llm_call_logs`` and ``embedding_call_logs`` should be co-located by
trace_id so the M27 trace timeline UI can fetch them together.

This test verifies the context wiring directly (no live ollama needed):
- set both LLM + Embedding contexts under the same trace_id
- invoke a fake embedder via LoggingEmbeddings
- assert the resulting embedding_call_logs row has the expected trace_id

Spec: docs/superpowers/specs/2026-06-15-embedding-trace-retention.md §"trace 视图"
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
    get_embedding_context,
)
from lumen_core.llm_call_context import (
    LLMCallContext,
    set_call_context,
    reset_call_context,
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


def test_embedding_row_shares_trace_id_with_llm_context():
    """When chat/stream sets both LLM and Embedding contexts under one
    trace_id, the embedding row's trace_id matches.

    M27.1: the wrapper generates a fresh call_id per embed call, so
    we filter on trace_id + text_preview rather than the ctx.call_id.
    """
    trace_id = str(uuid.uuid4())
    llm_call_id = trace_id  # M26 root pattern: call_id == trace_id for chat root

    # Mimic chat.py's wiring:
    llm_token = set_call_context(LLMCallContext(
        call_id=llm_call_id,
        trace_id=trace_id,
        parent_call_id=None,
        call_type="chat",
        call_index=0,
        tenant_id=1,
        user_id=1,
        username="tester",
        client_app="dashboard",
    ))
    emb_token = set_embedding_context(EmbeddingCallContext(
        call_id="root-emb",  # will be replaced by wrapper
        trace_id=trace_id,  # SAME trace as LLM
        parent_call_id=llm_call_id,
        call_type="kb_retrieval",
        call_index=0,
        tenant_id=1,
        user_id=1,
        username="tester",
        client_app="dashboard",
    ))

    inner = MagicMock()
    inner.embed_query.return_value = [0.1] * 768

    wrapper = LoggingEmbeddings(
        inner, model_type="ollama", model_name="nomic-embed-text",
        model_config_id=None,
    )

    try:
        wrapper.embed_query("hello world")
    finally:
        reset_embedding_context(emb_token)
        reset_call_context(llm_token)

    db = SessionLocal()
    try:
        row = (
            db.query(EmbeddingCallLog)
            .filter(
                EmbeddingCallLog.trace_id == trace_id,
                EmbeddingCallLog.text_preview == "hello world",
            )
            .first()
        )
        assert row is not None
        assert row.trace_id == trace_id  # KEY ASSERTION: shared trace
        assert row.parent_call_id == llm_call_id
        assert row.call_type == "kb_retrieval"
        # call_id is fresh uuid4, not the ctx's
        assert row.call_id != "root-emb"
        assert row.call_id != llm_call_id
        actual_call_id = row.call_id
    finally:
        db.close()
    _cleanup(actual_call_id)


def test_kb_id_refined_per_kb_inside_agent_rag():
    """``_retrieve_kb_chunks`` refines the per-call ctx with
    ``knowledge_base_id=kb.id``. We can't easily test the real
    function without seeded KBs; we verify the pattern by mutating
    a ctx via ``._replace`` like agent_rag does."""
    base_ctx = EmbeddingCallContext(
        call_id="base",
        trace_id="trace-a",
        parent_call_id=None,
        call_type="kb_retrieval",
        call_index=0,
        tenant_id=1,
        agent_id=42,
        extra={"top_k": 3},
    )

    refined = base_ctx._replace(
        call_id="per-kb-call",
        knowledge_base_id=7,
        extra={**(base_ctx.extra or {}), "kb_name": "demo-kb"},
    )

    # Same trace_id (so timeline view groups them)
    assert refined.trace_id == base_ctx.trace_id
    # Per-kb call_id (distinct row per KB inside one fan-out)
    assert refined.call_id == "per-kb-call"
    # KB id wired
    assert refined.knowledge_base_id == 7
    # Extra extended (not replaced)
    assert refined.extra == {"top_k": 3, "kb_name": "demo-kb"}


def _pool_worker_observe():
    """Module-level worker so the cross-thread global lookup of
    ``get_embedding_context`` doesn't hit a NameError under
    ``executor.submit`` (which can be picky about closure names)."""
    return get_embedding_context()


def test_agent_rag_uses_pass_context_as_arg_for_workers():
    """Pin down the exact pattern agent_rag uses (M27.1 fix).

    The simplest reliable approach to ContextVar propagation across
    stdlib ThreadPoolExecutor workers is: pass the context as a
    regular arg, install it locally in the worker, reset on exit.
    This sidesteps both:

    - "no context at all" (copy_context() inside worker misses parent)
    - "context already entered" (shared snapshot re-entrancy)

    Reads the source code and asserts the pattern is in place so a
    refactor that drops it triggers a test failure.
    """
    import inspect
    from lumen_services.agent_rag import (
        build_agent_kb_context,
        _retrieve_kb_chunks_with_ctx,
    )

    src = inspect.getsource(build_agent_kb_context)
    helper_src = inspect.getsource(_retrieve_kb_chunks_with_ctx)

    # The helper must install the context with set_embedding_context
    # and reset it on exit (try/finally).
    assert "set_embedding_context" in helper_src, (
        "_retrieve_kb_chunks_with_ctx must call set_embedding_context"
    )
    assert "reset_embedding_context" in helper_src, (
        "_retrieve_kb_chunks_with_ctx must reset_embedding_context in finally"
    )
    # The dispatcher must capture the parent's context BEFORE the
    # executor so it can pass it to each worker.
    assert "get_embedding_context()" in src, (
        "build_agent_kb_context must call get_embedding_context() to "
        "snapshot the parent's context before dispatching per-KB work"
    )
    assert "_retrieve_kb_chunks_with_ctx" in src, (
        "build_agent_kb_context must dispatch via "
        "_retrieve_kb_chunks_with_ctx (the context-passing wrapper)"
    )
