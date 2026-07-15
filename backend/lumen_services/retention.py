"""M27 retention service — soft + hard delete of old log rows.

3-stage retention strategy:

- ``< days_soft`` days old → keep as-is
- ``days_soft`` ≤ age < ``days_hard`` → set ``archived_at = NOW()`` (soft delete)
- ``≥ days_hard`` days old → DELETE row (hard delete)

Soft delete preserves the row for compliance audit but tags it so
client queries (the ``/logs/llm-calls`` UI list) can filter it out.
Hard delete reclaims storage.

Batch size keeps DB load bounded for tables with many millions of rows.
MySQL doesn't support ``DELETE ... LIMIT N`` directly inside an
``IN`` subquery without ordering quirks; we use a 2-step pattern:

1. ``SELECT id ... LIMIT N`` to gather the batch.
2. ``DELETE FROM ... WHERE id IN (...)`` with the gathered ids.

Both stages run in a single transaction per batch to keep MDL hold time
minimal.

Spec: docs/superpowers/specs/2026-06-15-embedding-trace-retention.md §"治理"
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from sqlalchemy import text

from lumen_core.database import engine

logger = logging.getLogger(__name__)


DEFAULT_DAYS_SOFT = 90
DEFAULT_DAYS_HARD = 180
DEFAULT_BATCH_SIZE = 1000


def _soft_delete_batch(
    conn, table: str, cutoff: datetime, batch_size: int
) -> int:
    """Mark up to ``batch_size`` rows older than ``cutoff`` as archived.

    Returns the number of rows actually updated.
    """
    rows = conn.execute(text(
        f"SELECT id FROM {table} "
        f"WHERE created_at < :cutoff AND archived_at IS NULL "
        f"LIMIT :n"
    ), {"cutoff": cutoff, "n": batch_size}).fetchall()
    if not rows:
        return 0
    ids = [r[0] for r in rows]
    placeholders = ", ".join([str(int(i)) for i in ids])
    # Use a positional SQL string to avoid the pymysql IN-clause expansion
    # cost on long batches. ``ids`` come from a trusted SELECT we just
    # issued, so there's no injection risk.
    conn.execute(text(
        f"UPDATE {table} SET archived_at = NOW() WHERE id IN ({placeholders})"
    ))
    return len(ids)


def _hard_delete_batch(
    conn, table: str, cutoff: datetime, batch_size: int
) -> int:
    """Delete up to ``batch_size`` rows older than ``cutoff``.

    Returns the number of rows actually deleted.
    """
    rows = conn.execute(text(
        f"SELECT id FROM {table} WHERE created_at < :cutoff LIMIT :n"
    ), {"cutoff": cutoff, "n": batch_size}).fetchall()
    if not rows:
        return 0
    ids = [r[0] for r in rows]
    placeholders = ", ".join([str(int(i)) for i in ids])
    conn.execute(text(
        f"DELETE FROM {table} WHERE id IN ({placeholders})"
    ))
    return len(ids)


def _loop_batches(
    table: str,
    cutoff: datetime,
    batch_size: int,
    step_fn,
) -> int:
    """Repeatedly invoke ``step_fn(conn, table, cutoff, batch_size)``
    until it returns 0 (no more rows in scope). Returns the total
    affected count across all batches.

    Each batch runs in its own short transaction so a long retention
    pass doesn't hold one giant lock.
    """
    total = 0
    while True:
        with engine.begin() as conn:
            n = step_fn(conn, table, cutoff, batch_size)
        if n == 0:
            break
        total += n
        if n < batch_size:
            # Last partial batch — no point asking for another.
            break
    return total


def archive_old_logs(
    *,
    days_soft: int = DEFAULT_DAYS_SOFT,
    days_hard: int = DEFAULT_DAYS_HARD,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> Dict[str, int]:
    """Run the retention sweep across ``llm_call_logs`` and
    ``embedding_call_logs``.

    Returns counts in a dict::

        {
          "soft_deleted_llm": N,
          "hard_deleted_llm": N,
          "soft_deleted_emb": N,
          "hard_deleted_emb": N,
        }

    Failures on one table do NOT abort the other; we log and continue.
    """
    if days_soft <= 0 or days_hard <= 0:
        raise ValueError(
            f"days_soft and days_hard must be > 0 (got {days_soft}, {days_hard})"
        )
    if days_hard <= days_soft:
        raise ValueError(
            f"days_hard ({days_hard}) must be > days_soft ({days_soft})"
        )

    now = datetime.utcnow()
    soft_cutoff = now - timedelta(days=days_soft)
    hard_cutoff = now - timedelta(days=days_hard)

    result = {
        "soft_deleted_llm": 0,
        "hard_deleted_llm": 0,
        "soft_deleted_emb": 0,
        "hard_deleted_emb": 0,
    }

    for table, soft_key, hard_key in [
        ("llm_call_logs", "soft_deleted_llm", "hard_deleted_llm"),
        ("embedding_call_logs", "soft_deleted_emb", "hard_deleted_emb"),
    ]:
        # Hard delete first — those rows would also match the soft
        # cutoff but should just be removed, not flagged.
        try:
            n_hard = _loop_batches(table, hard_cutoff, batch_size, _hard_delete_batch)
            result[hard_key] = n_hard
            logger.info("retention: hard-deleted %d rows from %s", n_hard, table)
        except Exception:  # noqa: BLE001
            logger.exception("retention: hard-delete failed on %s", table)

        try:
            n_soft = _loop_batches(table, soft_cutoff, batch_size, _soft_delete_batch)
            result[soft_key] = n_soft
            logger.info("retention: soft-deleted %d rows from %s", n_soft, table)
        except Exception:  # noqa: BLE001
            logger.exception("retention: soft-delete failed on %s", table)

    return result


def dry_run_count(
    *,
    days_soft: int = DEFAULT_DAYS_SOFT,
    days_hard: int = DEFAULT_DAYS_HARD,
) -> Dict[str, int]:
    """Return how many rows WOULD be soft / hard deleted, without
    actually changing anything. Useful for CLI dry-runs.
    """
    if days_soft <= 0 or days_hard <= 0 or days_hard <= days_soft:
        raise ValueError("invalid days_soft/days_hard")
    now = datetime.utcnow()
    soft_cutoff = now - timedelta(days=days_soft)
    hard_cutoff = now - timedelta(days=days_hard)

    result = {
        "would_soft_delete_llm": 0,
        "would_hard_delete_llm": 0,
        "would_soft_delete_emb": 0,
        "would_hard_delete_emb": 0,
    }
    for table, soft_key, hard_key in [
        ("llm_call_logs", "would_soft_delete_llm", "would_hard_delete_llm"),
        ("embedding_call_logs", "would_soft_delete_emb", "would_hard_delete_emb"),
    ]:
        try:
            with engine.connect() as conn:
                soft_n = conn.execute(text(
                    f"SELECT COUNT(*) FROM {table} "
                    f"WHERE created_at < :cutoff AND archived_at IS NULL"
                ), {"cutoff": soft_cutoff}).scalar() or 0
                hard_n = conn.execute(text(
                    f"SELECT COUNT(*) FROM {table} WHERE created_at < :cutoff"
                ), {"cutoff": hard_cutoff}).scalar() or 0
                result[soft_key] = int(soft_n)
                result[hard_key] = int(hard_n)
        except Exception:  # noqa: BLE001
            logger.exception("retention dry-run query failed on %s", table)
    return result
