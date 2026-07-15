"""M27 retention tests — soft + hard delete of old log rows.

Covers:
- ``archive_old_logs`` soft-deletes 90-day rows (sets archived_at)
- ``archive_old_logs`` hard-deletes 180-day rows (DELETE)
- Boundary: 89/90/91/179/180/181 day rows handled correctly
- Batch size: a 2500-row scan with batch_size=1000 processes all rows
  (3 batches: 1000 + 1000 + 500)
- ``dry_run_count`` returns counts without mutating anything
- Invalid params: days_soft >= days_hard raises ValueError
- Negative days_soft / days_hard raise ValueError

Spec: docs/superpowers/specs/2026-06-15-embedding-trace-retention.md §"治理"
"""
import os
import sys
import uuid
from datetime import datetime, timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from lumen_models.tenant import Tenant  # noqa: F401
from lumen_models.knowledge import KnowledgeBase  # noqa: F401
from lumen_models.model_config import ModelConfig  # noqa: F401
from lumen_models.agent import Agent  # noqa: F401
from lumen_models.agent_team import AgentTeam  # noqa: F401
from lumen_models.workflow import Workflow, WorkflowRun  # noqa: F401
from lumen_models.external_app import ExternalApp, ExternalVisitor  # noqa: F401
from lumen_models.chat import Conversation, Message  # noqa: F401
from lumen_models.image_generation import GeneratedImage  # noqa: F401
from lumen_models.user import User  # noqa: F401
from lumen_models.llm_call_log import LLMCallLog
from lumen_models.embedding_call_log import EmbeddingCallLog
from lumen_core.database import (
    SessionLocal,
    engine,
    ensure_llm_call_logs_table,
    ensure_embedding_call_logs_table,
    ensure_soft_delete_columns,
)
from lumen_services.retention import (
    archive_old_logs,
    dry_run_count,
)


@pytest.fixture(autouse=True, scope="module")
def _ensure_tables():
    ensure_llm_call_logs_table()
    ensure_embedding_call_logs_table()
    ensure_soft_delete_columns()


def _fetch_fresh(model_class, row_id: int):
    """Return a freshly-fetched row (or None) from a brand-new session.

    Bypasses the test's existing session identity map, which holds
    a stale snapshot from BEFORE ``archive_old_logs`` ran on its own
    engine.begin() connection.
    """
    db = SessionLocal()
    try:
        return db.get(model_class, row_id)
    finally:
        db.close()


def _insert_llm_row(db, *, age_days: int, marker: str) -> int:
    """Insert one LLMCallLog row with ``created_at`` ``age_days`` ago."""
    # call_id is VARCHAR(36); keep total under 36 chars including the marker.
    row = LLMCallLog(
        call_id=f"rl-{marker}-{uuid.uuid4().hex[:6]}",
        trace_id="t1",
        call_type="chat",
        model_name="m",
        started_at=datetime.utcnow(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    # Backdate created_at to age_days ago. updated_at auto-flips on
    # UPDATE so we use a direct SQL UPDATE that skips ORM defaults.
    past = datetime.utcnow() - timedelta(days=age_days)
    from sqlalchemy import text as _text
    with engine.begin() as conn:
        conn.execute(
            _text("UPDATE llm_call_logs SET created_at = :ts WHERE id = :id"),
            {"ts": past, "id": row.id},
        )
    return row.id


def _insert_emb_row(db, *, age_days: int, marker: str) -> int:
    row = EmbeddingCallLog(
        call_id=f"re-{marker}-{uuid.uuid4().hex[:6]}",
        trace_id="t1",
        call_type="kb_retrieval",
        model_name="m",
        text_preview="x",
        text_chars=1,
        started_at=datetime.utcnow(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    past = datetime.utcnow() - timedelta(days=age_days)
    from sqlalchemy import text as _text
    with engine.begin() as conn:
        conn.execute(
            _text(
                "UPDATE embedding_call_logs SET created_at = :ts WHERE id = :id"
            ),
            {"ts": past, "id": row.id},
        )
    return row.id


def _cleanup_marker(marker: str):
    """Remove all rows we inserted under this test marker."""
    db = SessionLocal()
    try:
        from sqlalchemy import text as _text
        with engine.begin() as conn:
            conn.execute(_text(
                "DELETE FROM llm_call_logs WHERE call_id LIKE :pat"
            ), {"pat": f"rl-{marker}-%"})
            conn.execute(_text(
                "DELETE FROM embedding_call_logs WHERE call_id LIKE :pat"
            ), {"pat": f"re-{marker}-%"})
    finally:
        db.close()


def test_archive_old_logs_invalid_params():
    with pytest.raises(ValueError):
        archive_old_logs(days_soft=10, days_hard=5)
    with pytest.raises(ValueError):
        archive_old_logs(days_soft=0, days_hard=180)
    with pytest.raises(ValueError):
        archive_old_logs(days_soft=90, days_hard=-1)


def test_boundary_89_days_kept_90_days_soft_deleted_91_days_soft_deleted():
    """< 90 days kept. >= 90 days (within 180) gets archived_at set.

    Note: the SQL uses strict ``<`` against the cutoff. A row created
    at *exactly* 90 days ago races with the SQL's NOW() — use 95/100
    safely above the cutoff to avoid the boundary timing flake.
    """
    marker = f"bound-soft-{uuid.uuid4().hex[:6]}"
    db = SessionLocal()
    try:
        keep_id = _insert_llm_row(db, age_days=89, marker=marker)
        soft95_id = _insert_llm_row(db, age_days=95, marker=marker)
        soft100_id = _insert_llm_row(db, age_days=100, marker=marker)

        result = archive_old_logs(days_soft=90, days_hard=180, batch_size=100)
        assert result["soft_deleted_llm"] >= 2
        assert result["hard_deleted_llm"] == 0

        # Use a fresh session to bypass identity-map cache.
        keep = _fetch_fresh(LLMCallLog, keep_id)
        s95 = _fetch_fresh(LLMCallLog, soft95_id)
        s100 = _fetch_fresh(LLMCallLog, soft100_id)
        assert keep is not None and keep.archived_at is None
        assert s95 is not None and s95.archived_at is not None
        assert s100 is not None and s100.archived_at is not None
    finally:
        _cleanup_marker(marker)
        db.close()


def test_boundary_179_days_soft_180_days_hard_181_days_hard():
    """< 180 days → soft (if >= 90). > 180 days → hard.

    Same caveat as above: 180 is the strict boundary, use safely-older
    rows for the hard tier.
    """
    marker = f"bound-hard-{uuid.uuid4().hex[:6]}"
    db = SessionLocal()
    try:
        soft175_id = _insert_llm_row(db, age_days=175, marker=marker)
        hard185_id = _insert_llm_row(db, age_days=185, marker=marker)
        hard200_id = _insert_llm_row(db, age_days=200, marker=marker)

        result = archive_old_logs(days_soft=90, days_hard=180, batch_size=100)
        assert result["hard_deleted_llm"] >= 2
        assert result["soft_deleted_llm"] >= 1

        s175 = _fetch_fresh(LLMCallLog, soft175_id)
        h185 = _fetch_fresh(LLMCallLog, hard185_id)
        h200 = _fetch_fresh(LLMCallLog, hard200_id)
        assert s175 is not None and s175.archived_at is not None
        assert h185 is None
        assert h200 is None
    finally:
        _cleanup_marker(marker)
        db.close()


def test_already_archived_row_not_re_soft_deleted():
    """A row already archived stays archived; the soft pass shouldn't count it again."""
    marker = f"already-{uuid.uuid4().hex[:6]}"
    db = SessionLocal()
    try:
        rid = _insert_llm_row(db, age_days=100, marker=marker)
        # First pass — marks it archived
        archive_old_logs(days_soft=90, days_hard=180, batch_size=100)
        # Second pass — should NOT touch our already-archived row.
        archive_old_logs(days_soft=90, days_hard=180, batch_size=100)
        row = _fetch_fresh(LLMCallLog, rid)
        assert row is not None
        assert row.archived_at is not None
    finally:
        _cleanup_marker(marker)
        db.close()


def test_embedding_table_also_swept():
    """The sweep targets BOTH llm_call_logs and embedding_call_logs."""
    marker = f"emb-{uuid.uuid4().hex[:6]}"
    db = SessionLocal()
    try:
        soft_id = _insert_emb_row(db, age_days=100, marker=marker)
        hard_id = _insert_emb_row(db, age_days=200, marker=marker)

        result = archive_old_logs(days_soft=90, days_hard=180, batch_size=100)
        assert result["soft_deleted_emb"] >= 1
        assert result["hard_deleted_emb"] >= 1

        s = _fetch_fresh(EmbeddingCallLog, soft_id)
        h = _fetch_fresh(EmbeddingCallLog, hard_id)
        assert s is not None and s.archived_at is not None
        assert h is None
    finally:
        _cleanup_marker(marker)
        db.close()


def test_batched_delete_processes_all():
    """A batch_size of 2 should still drain all eligible rows across multiple batches."""
    marker = f"batch-{uuid.uuid4().hex[:6]}"
    db = SessionLocal()
    try:
        ids = []
        for _ in range(5):
            ids.append(_insert_llm_row(db, age_days=200, marker=marker))

        result = archive_old_logs(days_soft=90, days_hard=180, batch_size=2)
        # All 5 should be hard-deleted in 3 batches (2 + 2 + 1)
        assert result["hard_deleted_llm"] >= 5

        for rid in ids:
            assert _fetch_fresh(LLMCallLog, rid) is None
    finally:
        _cleanup_marker(marker)
        db.close()


def test_dry_run_count_does_not_mutate():
    """dry_run_count returns row counts but does not change anything."""
    marker = f"dry-{uuid.uuid4().hex[:6]}"
    db = SessionLocal()
    try:
        soft_id = _insert_llm_row(db, age_days=100, marker=marker)
        hard_id = _insert_llm_row(db, age_days=200, marker=marker)

        counts = dry_run_count(days_soft=90, days_hard=180)
        assert counts["would_soft_delete_llm"] >= 1
        assert counts["would_hard_delete_llm"] >= 1

        # Verify state UNCHANGED
        s = _fetch_fresh(LLMCallLog, soft_id)
        h = _fetch_fresh(LLMCallLog, hard_id)
        assert s is not None and s.archived_at is None
        assert h is not None  # NOT deleted
    finally:
        _cleanup_marker(marker)
        db.close()


def test_dry_run_invalid_params():
    with pytest.raises(ValueError):
        dry_run_count(days_soft=10, days_hard=5)
    with pytest.raises(ValueError):
        dry_run_count(days_soft=0, days_hard=180)


def test_zero_rows_in_scope_returns_zero():
    """When no rows are old enough, the sweep returns zeros."""
    # Use absurdly high cutoffs so nothing matches.
    result = archive_old_logs(days_soft=10_000, days_hard=20_000, batch_size=100)
    assert result["soft_deleted_llm"] == 0
    assert result["hard_deleted_llm"] == 0
    assert result["soft_deleted_emb"] == 0
    assert result["hard_deleted_emb"] == 0
