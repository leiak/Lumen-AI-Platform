"""2.1 C.1: chat soft-delete hard-delete 服务测试(30d 窗口)。

测试要点:
- 最近软删(< 30d)的不动
- 超过 30d 软删的真删
- 删除顺序对:audit_logs.resource_id 先 NULL → messages 删 → convs 删
- audit_logs 只 NULL resource_type='conversation' + resource_id=str(conv_id),不污染其他 resource
- llm_call_logs / embedding_call_logs.conversation_id 同步 NULL
- 边界:无效 days_hard 抛 ValueError
- 边界:删一批后 batch_size < len 跳出
"""
from __future__ import annotations

import importlib
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


# ---- fixtures ----


@pytest.fixture
def fake_engine():
    """mock lumen_core.database.engine,事务用同一个连接返回多步结果。

    ``engine.begin()`` 上下文管理器返一个 conn;我们让 ``conn.execute(...)``
    按调用顺序返不同结果(SELECT id → UPDATE audit → UPDATE llm → UPDATE emb
    → DELETE messages → DELETE conversations)。
    """
    engine = MagicMock()
    conn = MagicMock()
    engine.begin.return_value.__enter__.return_value = conn
    engine.begin.return_value.__exit__.return_value = False
    engine.connect.return_value.__enter__.return_value = conn
    engine.connect.return_value.__exit__.return_value = False
    return engine, conn


def _select_ids_result(ids):
    """模拟 ``SELECT id FROM conversations WHERE deleted_at < ...`` 返 row 列表。

    SQLAlchemy ``fetchall()`` 返 Row tuple,支持 ``r[0]`` 索引。用 tuple 模拟。
    """
    return [(i,) for i in ids]


def _exec_result(rowcount=0):
    """模拟 UPDATE / DELETE 返 rowcount。"""
    return SimpleNamespace(rowcount=rowcount)


# ---- happy path ----


def test_purge_old_chat_conversations_dry_run_no_old_convs(fake_engine):
    """DB 里没有超过 30d soft-deleted 的 conversation → 不删任何东西。"""
    engine, conn = fake_engine
    # 第 1 轮:SELECT id 返空 → while break
    conn.execute.return_value.fetchall.return_value = []

    with patch("lumen_services.chat_retention.engine", engine):
        from lumen_services.chat_retention import purge_old_chat_conversations
        result = purge_old_chat_conversations(days_hard=30)

    assert result == {
        "deleted_conversations": 0,
        "deleted_messages": 0,
        "nulled_audit_log_refs": 0,
        "nulled_llm_call_log_refs": 0,
        "nulled_embedding_call_log_refs": 0,
    }


def test_purge_old_chat_conversations_deletes_one_batch(fake_engine):
    """DB 有 2 个超过 30d soft-deleted 的 conversation + 5 个关联 messages + 3 个 audit_logs。

    验证:
    - audit_logs.resource_id 被 NULL 化(命中 str(conv_id))
    - llm_call_logs.conversation_id 被 NULL 化
    - embedding_call_logs.conversation_id 被 NULL 化
    - messages 被 DELETE
    - conversations 被 DELETE
    """
    engine, conn = fake_engine

    # 按调用顺序配置 side_effect:
    #   1. SELECT id FROM conversations ... → 返 2 个 id
    #   2. UPDATE audit_logs → rowcount=3
    #   3. UPDATE llm_call_logs → rowcount=4
    #   4. UPDATE embedding_call_logs → rowcount=2
    #   5. DELETE messages → rowcount=5
    #   6. DELETE conversations → rowcount=2
    #   7. 下一轮 SELECT id → 返空,跳出
    select_calls = iter([
        _select_ids_result([10, 11]),  # 第 1 批
        [],                              # 第 2 批 → 跳出
    ])
    update_counts = iter([3, 4, 2])  # audit, llm, emb
    delete_counts = iter([5, 2])  # messages, conversations

    def fake_execute(sql, params=None):
        text = str(sql).lower()
        result = MagicMock()
        if "select id from conversations" in text:
            result.fetchall.return_value = next(select_calls)
        elif "update audit_logs" in text:
            result.rowcount = next(update_counts)
        elif "update llm_call_logs" in text:
            result.rowcount = next(update_counts)
        elif "update embedding_call_logs" in text:
            result.rowcount = next(update_counts)
        elif "delete from messages" in text:
            result.rowcount = next(delete_counts)
        elif "delete from conversations" in text:
            result.rowcount = next(delete_counts)
        else:
            result.rowcount = 0
        return result

    conn.execute.side_effect = fake_execute

    with patch("lumen_services.chat_retention.engine", engine):
        from lumen_services.chat_retention import purge_old_chat_conversations
        result = purge_old_chat_conversations(days_hard=30, batch_size=500)

    assert result == {
        "deleted_conversations": 2,
        "deleted_messages": 5,
        "nulled_audit_log_refs": 3,
        "nulled_llm_call_log_refs": 4,
        "nulled_embedding_call_log_refs": 2,
    }


def _make_rowcount_aware_executor(select_iter):
    """返回 fake_execute,UPDATE/DELETE 返 ``len(当前 batch conv_ids)`` rowcount。

    真实 SQLAlchemy ``conn.execute().rowcount`` 返受影响行数,跟当前 batch 的
    conv_ids 数量一致(全 batch 内 IN (...) 命中)。mock 必须反映这点,
    否则 result["deleted_conversations"] 永远是 mock 写的固定数字。
    """
    state = {"current_batch": []}

    def fake_execute(sql, params=None):
        text = str(sql).lower()
        result = MagicMock()
        if "select id from conversations" in text:
            ids = next(select_iter)
            result.fetchall.return_value = _select_ids_result(ids)
            state["current_batch"] = ids
        elif "update" in text or "delete" in text:
            result.rowcount = len(state["current_batch"])
        else:
            result.rowcount = 0
        return result

    return fake_execute


# ---- SQL 注入 / safety ----


def test_purge_uses_parameterized_cutoff():
    """cutoff 走 SQLAlchemy :cutoff 参数化,不会字符串拼接到 SQL。"""
    engine = MagicMock()
    conn = MagicMock()
    engine.begin.return_value.__enter__.return_value = conn
    engine.begin.return_value.__exit__.return_value = False
    conn.execute.return_value.fetchall.return_value = []
    conn.execute.return_value.rowcount = 0

    with patch("lumen_services.chat_retention.engine", engine):
        from lumen_services.chat_retention import purge_old_chat_conversations
        purge_old_chat_conversations(days_hard=30)

    # 第一次 conn.execute 是 SELECT id,应该带 :cutoff + :n 参数。
    # SQLAlchemy text() + dict 参数 — dict 是第二个 positional arg(.args[1])。
    first_call = conn.execute.call_args_list[0]
    sql_text = str(first_call.args[0])
    assert ":cutoff" in sql_text
    assert ":n" in sql_text
    params = first_call.args[1]
    assert "cutoff" in params
    assert "n" in params


def test_purge_audit_sql_filters_only_conversation_resource_type(fake_engine):
    """audit_logs NULL-out 只命中 resource_type='conversation' 行,不污染其他 resource。"""
    engine, conn = fake_engine

    select_calls = iter([
        _select_ids_result([42]),
        [],
    ])

    def fake_execute(sql, params=None):
        text = str(sql).lower()
        result = MagicMock()
        if "select id from conversations" in text:
            result.fetchall.return_value = next(select_calls)
        elif "update audit_logs" in text:
            # 验证 SQL 里有 resource_type = 'conversation' 过滤
            assert "resource_type = 'conversation'" in text
            assert "resource_id in" in text
            result.rowcount = 1
        elif "delete" in text:
            result.rowcount = 1
        else:
            result.rowcount = 0
        return result

    conn.execute.side_effect = fake_execute

    with patch("lumen_services.chat_retention.engine", engine):
        from lumen_services.chat_retention import purge_old_chat_conversations
        result = purge_old_chat_conversations(days_hard=30)

    assert result["nulled_audit_log_refs"] == 1


# ---- batching / loop 边界 ----


def test_purge_loops_until_no_more_old_convs(fake_engine):
    """连续 3 批:第 1 批 500 (full),第 2 批 500 (full),第 3 批 200 (partial) → break。"""
    engine, conn = fake_engine

    full_batch = list(range(1, 501))  # 500 个
    partial_batch = list(range(501, 701))  # 200 个
    select_iter = iter([
        full_batch,
        full_batch,
        partial_batch,
        [],
    ])
    conn.execute.side_effect = _make_rowcount_aware_executor(select_iter)

    with patch("lumen_services.chat_retention.engine", engine):
        from lumen_services.chat_retention import purge_old_chat_conversations
        result = purge_old_chat_conversations(days_hard=30, batch_size=500)

    # 3 批 × (500+500+200) = 1200 convs;messages 也是 1200(每 conv 1 message 简化)
    assert result["deleted_conversations"] == 1200
    assert result["deleted_messages"] == 1200
    assert result["nulled_audit_log_refs"] == 1200
    assert result["nulled_llm_call_log_refs"] == 1200
    assert result["nulled_embedding_call_log_refs"] == 1200


def test_purge_short_batch_stops_loop(fake_engine):
    """partial batch (< batch_size) → break,不再发 SELECT。"""
    engine, conn = fake_engine
    select_iter = iter([
        [1, 2, 3],  # 3 < batch_size=10 → partial
    ])
    conn.execute.side_effect = _make_rowcount_aware_executor(select_iter)

    with patch("lumen_services.chat_retention.engine", engine):
        from lumen_services.chat_retention import purge_old_chat_conversations
        result = purge_old_chat_conversations(days_hard=30, batch_size=10)

    # SELECT 应该只调用 1 次
    select_count = sum(
        1 for c in conn.execute.call_args_list
        if "select id from conversations" in str(c.args[0]).lower()
    )
    assert select_count == 1
    assert result["deleted_conversations"] == 3


# ---- 异常路径 ----


def test_purge_raises_on_non_positive_days_hard(fake_engine):
    """days_hard <= 0 应该抛 ValueError,不碰 DB。"""
    engine, _ = fake_engine
    with patch("lumen_services.chat_retention.engine", engine):
        from lumen_services.chat_retention import purge_old_chat_conversations
        with pytest.raises(ValueError):
            purge_old_chat_conversations(days_hard=0)
        with pytest.raises(ValueError):
            purge_old_chat_conversations(days_hard=-1)


def test_purge_propagates_db_exceptions(fake_engine):
    """DB 抛错时不 swallow,让上层 scheduler log。"""
    engine, conn = fake_engine
    conn.execute.side_effect = RuntimeError("simulated DB error")

    with patch("lumen_services.chat_retention.engine", engine):
        from lumen_services.chat_retention import purge_old_chat_conversations
        with pytest.raises(RuntimeError, match="simulated DB error"):
            purge_old_chat_conversations(days_hard=30)


# ---- dry_run ----


def test_dry_run_count_returns_zero_when_no_old_convs(fake_engine):
    """dry_run_count 不动数据,只 SELECT COUNT。"""
    engine, conn = fake_engine
    conn.execute.return_value.scalar.return_value = 0

    with patch("lumen_services.chat_retention.engine", engine):
        from lumen_services.chat_retention import dry_run_count
        result = dry_run_count(days_hard=30)

    assert result == {"would_hard_delete_conversations": 0}


def test_dry_run_count_returns_count(fake_engine):
    engine, conn = fake_engine
    conn.execute.return_value.scalar.return_value = 17

    with patch("lumen_services.chat_retention.engine", engine):
        from lumen_services.chat_retention import dry_run_count
        result = dry_run_count(days_hard=30)

    assert result == {"would_hard_delete_conversations": 17}


def test_dry_run_count_raises_on_non_positive_days_hard(fake_engine):
    engine, _ = fake_engine
    with patch("lumen_services.chat_retention.engine", engine):
        from lumen_services.chat_retention import dry_run_count
        with pytest.raises(ValueError):
            dry_run_count(days_hard=0)


# ---- scheduler 注册 ----


def test_register_chat_retention_jobs_registers_with_apscheduler():
    """scheduler.add_job 应该被调用 1 次,job_id 固定 + replace_existing=True。"""
    from lumen_services.chat_retention_scheduler import (
        JOB_ID_CHAT_RETENTION,
        register_chat_retention_jobs,
    )

    scheduler = MagicMock()
    register_chat_retention_jobs(scheduler=scheduler)

    scheduler.add_job.assert_called_once()
    call_kwargs = scheduler.add_job.call_args.kwargs
    assert call_kwargs["id"] == JOB_ID_CHAT_RETENTION
    assert call_kwargs["replace_existing"] is True
    assert call_kwargs["max_instances"] == 1
    assert call_kwargs["coalesce"] is True


def test_register_chat_retention_jobs_uses_shared_singleton():
    """scheduler=None 时复用 workflow_scheduler.get_scheduler() 单例。"""
    from lumen_services.chat_retention_scheduler import register_chat_retention_jobs

    fake_sched = MagicMock()
    with patch(
        "lumen_services.chat_retention_scheduler.get_scheduler",
        return_value=fake_sched,
    ):
        register_chat_retention_jobs()

    fake_sched.add_job.assert_called_once()


def test_register_chat_retention_jobs_is_idempotent():
    """调两次不报错(replace_existing=True 让 APScheduler 内部替换)。"""
    from lumen_services.chat_retention_scheduler import register_chat_retention_jobs

    scheduler = MagicMock()
    register_chat_retention_jobs(scheduler=scheduler)
    register_chat_retention_jobs(scheduler=scheduler)

    # 两次 add_job 调用(APScheduler 内部走 replace_existing 不抛)
    assert scheduler.add_job.call_count == 2


# ---- module import smoke ----


def test_chat_retention_module_imports_clean():
    """import 不抛 ImportError。"""
    importlib.import_module("lumen_services.chat_retention")
    importlib.import_module("lumen_services.chat_retention_scheduler")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])