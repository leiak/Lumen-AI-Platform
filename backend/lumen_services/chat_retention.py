"""2.1 C.1: 软删 chat conversation hard-delete 服务(30d 窗口)。

``DELETE /api/v1/chat/conversations/{id}`` 只设 ``Conversation.deleted_at``,
row 保留 30d 留作误删恢复窗口。30d 后本服务 hard-delete 整行,连同关联行。

**删除顺序**(重要 — FK 链):
1. ``audit_logs.resource_id`` (resource_type='conversation', id=str(conv_id))
   设 NULL。audit_logs.resource_id 是 str 弱引用,不是 FK,但保留指向已删除
   conversation 的 audit row 会让 admin dashboard 看到 orphan reference。
2. ``llm_call_logs.conversation_id`` / ``embedding_call_logs.conversation_id``
   设 NULL。两张表 FK 可空,直接 NULL 不破 FK。
3. ``messages`` 走 SQLAlchemy ``cascade="all, delete-orphan"``,删除 conversation
   时自动级联清理。
4. ``DELETE FROM conversations WHERE id IN (...)`` —— 最后一步,之前不删 conv
   则 audit_logs / call_logs 的 SET NULL 没法 narrow 到具体 conv。

**为什么不走纯 ORM cascade**:audit_logs / llm_call_logs 不是 SQLAlchemy relationship
(只有 weak string reference),ORM 不会自动清理。需要走 explicit NULL-out pass。

**为什么不用 celery beat**:项目惯例是 APScheduler in-process(M27 retention + workflow
schedule),不另起 celery_beat container。``chat_retention_scheduler.py`` 复用
``workflow_scheduler.get_scheduler()`` 单例。

Spec: docs-internal/superpowers/specs/2026-09-07-lumen-2.1-spec.md §Phase 0 C.1
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Dict

from sqlalchemy import text

from lumen_core.database import engine

logger = logging.getLogger(__name__)


DEFAULT_DAYS_HARD = 30
DEFAULT_BATCH_SIZE = 500


def _null_audit_log_resource_ids(conn, conv_ids: list[int]) -> int:
    """把 audit_logs.resource_id 指向即将被删 conv 的 row 改 NULL。

    Returns affected row count.

    audit_logs.resource_id 是 str(实际是 ``str(conv.id)``),所以用
    ``WHERE resource_type = :rtype AND resource_id IN (:ids)`` 命中。
    """
    if not conv_ids:
        return 0
    placeholders = ", ".join([f"'{str(int(i))}'" for i in conv_ids])
    result = conn.execute(text(
        f"UPDATE audit_logs SET resource_id = NULL "
        f"WHERE resource_type = 'conversation' AND resource_id IN ({placeholders})"
    ))
    return int(result.rowcount or 0)


def _null_call_log_conv_ids(
    conn, table: str, conv_ids: list[int],
) -> int:
    """``llm_call_logs`` / ``embedding_call_logs`` 的 ``conversation_id`` 设 NULL。"""
    if not conv_ids:
        return 0
    placeholders = ", ".join([str(int(i)) for i in conv_ids])
    result = conn.execute(text(
        f"UPDATE {table} SET conversation_id = NULL "
        f"WHERE conversation_id IN ({placeholders})"
    ))
    return int(result.rowcount or 0)


def _delete_conversation_batch(conn, cutoff: datetime, batch_size: int) -> list[int]:
    """选一批 ``deleted_at < cutoff`` 的 conversation id,跑 4 步删除序列。

    Returns the list of deleted conv ids(给上层 caller log 用)。

    每批跑在一个事务里(``engine.begin()``);批次之间不持有跨 batch 的锁。
    """
    rows = conn.execute(text(
        "SELECT id FROM conversations "
        "WHERE deleted_at IS NOT NULL AND deleted_at < :cutoff "
        "ORDER BY deleted_at ASC LIMIT :n"
    ), {"cutoff": cutoff, "n": batch_size}).fetchall()
    if not rows:
        return []
    conv_ids = [int(r[0]) for r in rows]

    # 步骤 1:audit_logs.resource_id → NULL(弱引用清理)
    _null_audit_log_resource_ids(conn, conv_ids)

    # 步骤 2:llm_call_logs / embedding_call_logs.conversation_id → NULL
    _null_call_log_conv_ids(conn, "llm_call_logs", conv_ids)
    _null_call_log_conv_ids(conn, "embedding_call_logs", conv_ids)

    # 步骤 3 + 4:删 conversation,messages 走 SQLAlchemy cascade="all, delete-orphan"
    # 自动级联清理。注意:raw SQL DELETE 不会触发 ORM cascade,所以本步骤之前必须
    # 显式 DELETE messages。
    placeholders = ", ".join([str(i) for i in conv_ids])
    conn.execute(text(
        f"DELETE FROM messages WHERE conversation_id IN ({placeholders})"
    ))
    conn.execute(text(
        f"DELETE FROM conversations WHERE id IN ({placeholders})"
    ))
    return conv_ids


def purge_old_chat_conversations(
    *,
    days_hard: int = DEFAULT_DAYS_HARD,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> Dict[str, int]:
    """Hard-delete ``deleted_at < utcnow() - days_hard`` 的 conversations。

    Returns counts::

        {
          "deleted_conversations": N,
          "deleted_messages": M,        # ORM cascade + 显式 DELETE
          "nulled_audit_log_refs": A,
          "nulled_llm_call_log_refs": L,
          "nulled_embedding_call_log_refs": E,
        }

    失败处理:一个 batch 失败抛异常,让上层 scheduler log 后下次再跑 —— 不 swallow
    否则 dashboard 会觉得永远 0 deletions。
    """
    if days_hard <= 0:
        raise ValueError(f"days_hard must be > 0 (got {days_hard})")

    now = datetime.utcnow()
    cutoff = now - timedelta(days=days_hard)

    total_deleted_convs = 0
    total_deleted_msgs = 0
    total_nulled_audit = 0
    total_nulled_llm = 0
    total_nulled_emb = 0

    while True:
        with engine.begin() as conn:
            # 选批
            rows = conn.execute(text(
                "SELECT id FROM conversations "
                "WHERE deleted_at IS NOT NULL AND deleted_at < :cutoff "
                "ORDER BY deleted_at ASC LIMIT :n"
            ), {"cutoff": cutoff, "n": batch_size}).fetchall()
            if not rows:
                break
            conv_ids = [int(r[0]) for r in rows]

            # 步骤 1:audit_logs.resource_id → NULL
            n_audit = _null_audit_log_resource_ids(conn, conv_ids)
            total_nulled_audit += n_audit

            # 步骤 2:llm_call_logs / embedding_call_logs.conversation_id → NULL
            n_llm = _null_call_log_conv_ids(conn, "llm_call_logs", conv_ids)
            n_emb = _null_call_log_conv_ids(conn, "embedding_call_logs", conv_ids)
            total_nulled_llm += n_llm
            total_nulled_emb += n_emb

            # 步骤 3:删 messages
            placeholders = ", ".join([str(i) for i in conv_ids])
            msg_result = conn.execute(text(
                f"DELETE FROM messages WHERE conversation_id IN ({placeholders})"
            ))
            n_msgs = int(msg_result.rowcount or 0)
            total_deleted_msgs += n_msgs

            # 步骤 4:删 conversations
            conv_result = conn.execute(text(
                f"DELETE FROM conversations WHERE id IN ({placeholders})"
            ))
            n_convs = int(conv_result.rowcount or 0)
            total_deleted_convs += n_convs

            logger.info(
                "chat_retention: deleted %d convs + %d msgs (batch conv_ids=%s)",
                n_convs, n_msgs, conv_ids,
            )

        # 短批 = 已经扫完,跳出
        if len(conv_ids) < batch_size:
            break

    result = {
        "deleted_conversations": total_deleted_convs,
        "deleted_messages": total_deleted_msgs,
        "nulled_audit_log_refs": total_nulled_audit,
        "nulled_llm_call_log_refs": total_nulled_llm,
        "nulled_embedding_call_log_refs": total_nulled_emb,
    }
    if total_deleted_convs > 0:
        logger.info("chat_retention done: %s", result)
    return result


def dry_run_count(days_hard: int = DEFAULT_DAYS_HARD) -> Dict[str, int]:
    """返回将有几行被 hard-delete,不动数据。CLI dry-run 用。"""
    if days_hard <= 0:
        raise ValueError(f"days_hard must be > 0 (got {days_hard})")
    cutoff = datetime.utcnow() - timedelta(days=days_hard)
    with engine.connect() as conn:
        n = conn.execute(text(
            "SELECT COUNT(*) FROM conversations "
            "WHERE deleted_at IS NOT NULL AND deleted_at < :cutoff"
        ), {"cutoff": cutoff}).scalar() or 0
    return {"would_hard_delete_conversations": int(n)}