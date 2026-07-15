"""M27 integration test for embedding_factory + LoggingEmbeddings.

Verifies that ``get_embeddings_for_config`` returns a ``LoggingEmbeddings``
proxy wrapped around the real Ollama / OpenAI Embeddings instance, so
every caller in the codebase automatically gets observability without
modifying its call site.

Uses ``patch`` to swap ``OllamaEmbeddings`` for a stub so we don't need
a live Ollama at port 11434 to run the test.

Spec: docs/superpowers/specs/2026-06-15-embedding-trace-retention.md §"插桩策略"
"""
import os
import sys
import uuid
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from lumen_models.tenant import Tenant  # noqa: F401
from lumen_models.knowledge import KnowledgeBase  # noqa: F401
from lumen_models.model_config import ModelConfig
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
from lumen_services import embedding_factory
from lumen_services.embedding_logging import LoggingEmbeddings


@pytest.fixture(autouse=True, scope="module")
def _ensure_table():
    ensure_embedding_call_logs_table()


def _make_test_model_config(db) -> ModelConfig:
    """Create a throwaway embedding ModelConfig for testing.

    Uses a unique model_name so concurrent test runs don't clash.
    """
    name = f"test-nomic-{uuid.uuid4().hex[:8]}"
    cfg = ModelConfig(
        tenant_id=1,
        name=name,
        model_type="ollama",
        model_name=name,
        base_url="http://localhost:11434",
        api_key=None,
        is_active=True,
        is_embedding=True,
        is_default=False,
    )
    db.add(cfg)
    db.commit()
    db.refresh(cfg)
    return cfg


def test_factory_returns_logging_embeddings_proxy():
    """``get_embeddings_for_config`` returns a LoggingEmbeddings proxy."""
    embedding_factory.invalidate_cache()

    fake_inner = MagicMock()
    # The probe inside the factory calls embed_query("dim-probe") to
    # detect the dimension. Return a 768d vector so dim=768.
    fake_inner.embed_query.return_value = [0.0] * 768

    db = SessionLocal()
    try:
        cfg = _make_test_model_config(db)
        cfg_id = cfg.id

        with patch.object(
            embedding_factory, "OllamaEmbeddings", return_value=fake_inner
        ):
            emb, dim = embedding_factory.get_embeddings_for_config(cfg_id, db)

        assert isinstance(emb, LoggingEmbeddings)
        assert dim == 768

        # Hitting cache the second time should return the SAME proxy.
        emb2, dim2 = embedding_factory.get_embeddings_for_config(cfg_id, db)
        assert emb2 is emb
        assert dim2 == 768
    finally:
        # Cleanup
        embedding_factory.invalidate_cache()
        db.query(ModelConfig).filter(ModelConfig.id == cfg_id).delete()
        db.commit()
        db.close()


def test_factory_probe_writes_one_row_when_context_set():
    """If a context is active during cold-start probe, the dim-probe gets logged.

    M27.1: the wrapper generates a fresh uuid4 call_id per embed call,
    so we filter on trace_id + text_preview (both deterministic)
    rather than the ctx.call_id.
    """
    embedding_factory.invalidate_cache()

    fake_inner = MagicMock()
    fake_inner.embed_query.return_value = [0.0] * 768

    db = SessionLocal()
    try:
        cfg = _make_test_model_config(db)
        cfg_id = cfg.id

        trace_id = f"factory-trace-{uuid.uuid4().hex[:8]}"
        ctx = EmbeddingCallContext(
            call_id=f"factory-probe-{uuid.uuid4().hex[:8]}",
            trace_id=trace_id,
            parent_call_id=None,
            call_type="kb_retrieval",
            call_index=0,
            tenant_id=1,
            user_id=1,
            username="probe-tester",
            knowledge_base_id=None,
        )

        token = set_embedding_context(ctx)
        try:
            with patch.object(
                embedding_factory, "OllamaEmbeddings", return_value=fake_inner
            ):
                emb, dim = embedding_factory.get_embeddings_for_config(cfg_id, db)
            assert dim == 768
        finally:
            reset_embedding_context(token)

        # Probe should have written exactly one row tagged is_dim_probe=True.
        db_check = SessionLocal()
        try:
            rows = (
                db_check.query(EmbeddingCallLog)
                .filter(
                    EmbeddingCallLog.trace_id == trace_id,
                    EmbeddingCallLog.text_preview == "dim-probe",
                )
                .all()
            )
            assert len(rows) == 1
            assert rows[0].extra is not None
            assert rows[0].extra.get("is_dim_probe") is True
            assert rows[0].model_config_id == cfg_id
            # Cleanup using trace_id (M27.1: call_id is fresh uuid4)
            db_check.query(EmbeddingCallLog).filter(
                EmbeddingCallLog.trace_id == trace_id,
            ).delete(synchronize_session=False)
            db_check.commit()
        finally:
            db_check.close()
    finally:
        embedding_factory.invalidate_cache()
        db.query(ModelConfig).filter(ModelConfig.id == cfg_id).delete()
        db.commit()
        db.close()


def test_factory_caches_per_id_and_invalidate_clears():
    """``invalidate_cache(id)`` drops the wrapper so next call rebuilds."""
    embedding_factory.invalidate_cache()

    fake_inner = MagicMock()
    fake_inner.embed_query.return_value = [0.0] * 768

    db = SessionLocal()
    try:
        cfg = _make_test_model_config(db)
        cfg_id = cfg.id

        with patch.object(
            embedding_factory, "OllamaEmbeddings", return_value=fake_inner
        ):
            emb1, _ = embedding_factory.get_embeddings_for_config(cfg_id, db)
            embedding_factory.invalidate_cache(cfg_id)
            emb2, _ = embedding_factory.get_embeddings_for_config(cfg_id, db)

        # After invalidate, a new wrapper should be built (different object id).
        assert emb1 is not emb2
        assert isinstance(emb2, LoggingEmbeddings)
    finally:
        embedding_factory.invalidate_cache()
        db.query(ModelConfig).filter(ModelConfig.id == cfg_id).delete()
        db.commit()
        db.close()
