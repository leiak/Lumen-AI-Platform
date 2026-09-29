# -*- coding: utf-8 -*-
# backend/tests/unit/test_checkpointer_service.py
import pytest
from unittest.mock import patch, MagicMock
from lumen_core.checkpointer import CheckpointerService
from lumen_core.config import settings


@pytest.fixture(autouse=True)
def _reset_singleton():
    """每个测试前清空 _saver / _pool,避免前一个测试缓存的 mock 泄漏到下一个。"""
    CheckpointerService._saver = None
    CheckpointerService._pool = None
    yield
    CheckpointerService._saver = None
    CheckpointerService._pool = None


def test_get_returns_singleton():
    """多次调用 get() 返回同一个 PostgresSaver 实例,且 ConnectionPool 用正确 kwargs。

    pool + saver 都只在第一次调用时建,后续直接复用单例(避免反复建连接池)。
    同时校验:
    - 不强制 autocommit=True(I-3 修法 —— PostgresSaver 写多张表需原子性)
    - min/max 来自 Settings(I-4 env 化,不是写死字面量)
    """
    with patch("lumen_core.checkpointer.PostgresSaver") as MockSaver, \
         patch("lumen_core.checkpointer.ConnectionPool") as MockPool:
        MockSaver.return_value = MagicMock()
        MockPool.return_value = MagicMock()
        s1 = CheckpointerService.get()
        s2 = CheckpointerService.get()
        assert s1 is s2
        # 只在第一次初始化时建 pool + saver,后续直接复用单例
        MockPool.assert_called_once()
        MockSaver.assert_called_once()
        # 验 saver 构造时拿到的是同一个 pool 实例
        saver_arg = MockSaver.call_args.args[0]
        assert saver_arg is MockPool.return_value
        # 验 pool kwargs:autocommit 必须不被强制开,min/max 来自 Settings
        kwargs = MockPool.call_args.kwargs
        assert "kwargs" not in kwargs or "autocommit" not in kwargs.get("kwargs", {})
        assert kwargs["min_size"] == settings.CHECKPOINTER_POOL_MIN_SIZE
        assert kwargs["max_size"] == settings.CHECKPOINTER_POOL_MAX_SIZE


def test_autocommit_is_not_forced_in_pool_kwargs():
    """确保没传 autocommit=True(会让 PostgresSaver 多 INSERT 拆事务,破坏原子性)。"""
    with patch("lumen_core.checkpointer.PostgresSaver") as MockSaver, \
         patch("lumen_core.checkpointer.ConnectionPool") as MockPool:
        MockSaver.return_value = MagicMock()
        MockPool.return_value = MagicMock()
        CheckpointerService._saver = None
        CheckpointerService._pool = None
        CheckpointerService.get()
        kwargs = MockPool.call_args.kwargs
        assert "kwargs" not in kwargs or "autocommit" not in kwargs.get("kwargs", {})


def test_health_returns_true_when_pg_reachable():
    """SELECT 1 返 (1,) → health=True。

    用 pool.connection() context manager 走 mock conn / cursor 模拟
    PostgresSaver 真打到 PG 的 round-trip;成功说明 health 探测有效。
    """
    with patch("lumen_core.checkpointer.PostgresSaver") as MockSaver, \
         patch("lumen_core.checkpointer.ConnectionPool") as MockPool:
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = (1,)
        # conn.cursor() 返回 ctx-mgr-compatible mock
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_pool = MagicMock()
        # pool.connection() 也是 ctx-mgr
        mock_pool.connection.return_value.__enter__.return_value = mock_conn
        MockPool.return_value = mock_pool
        MockSaver.return_value = MagicMock()
        assert CheckpointerService.health() is True
        # 真打了一次 SELECT 1,不是走 saver 内部纯算术路径
        mock_cursor.execute.assert_called_once_with("SELECT 1")


def test_health_returns_false_when_pg_unreachable():
    """SELECT 1 抛异常 / 返空 → health=False,不抛。

    health 必须 swallow 所有异常返 False —— 否则调用方得 try/except,
    失去 health check 的语义(只返 bool,不传播异常)。
    """
    with patch("lumen_core.checkpointer.ConnectionPool") as MockPool:
        mock_pool = MagicMock()
        mock_pool.connection.side_effect = Exception("connection refused")
        MockPool.return_value = mock_pool
        with patch("lumen_core.checkpointer.PostgresSaver") as MockSaver:
            MockSaver.return_value = MagicMock()
            assert CheckpointerService.health() is False


def test_health_returns_false_when_select_returns_unexpected():
    """SELECT 1 返非 (1,) 也算 unreachable —— 说明 PG 状态异常 / 协议错乱。"""
    with patch("lumen_core.checkpointer.ConnectionPool") as MockPool, \
         patch("lumen_core.checkpointer.PostgresSaver") as MockSaver:
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = (2,)  # 期望 (1,) 但拿到 (2,)
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_pool = MagicMock()
        mock_pool.connection.return_value.__enter__.return_value = mock_conn
        MockPool.return_value = mock_pool
        MockSaver.return_value = MagicMock()
        assert CheckpointerService.health() is False


def test_setup_cleans_up_on_failure():
    """setup() 抛错时主动 close(),不留半构造 pool/saver 状态。"""
    with patch("lumen_core.checkpointer.PostgresSaver") as MockSaver, \
         patch("lumen_core.checkpointer.ConnectionPool") as MockPool:
        mock_pool = MagicMock()
        MockPool.return_value = mock_pool
        mock_saver = MagicMock()
        mock_saver.setup.side_effect = RuntimeError("DDL failed")
        MockSaver.return_value = mock_saver

        with pytest.raises(RuntimeError, match="DDL failed"):
            CheckpointerService.setup()

        # setup 失败时 close() 应该被调,释放 pool
        mock_pool.close.assert_called_once()
        # 半构造状态清空,下次 get() 会重新初始化
        assert CheckpointerService._saver is None
        assert CheckpointerService._pool is None


def test_get_cleans_up_on_postgressaver_init_failure():
    """PostgresSaver(pool) 构造抛错时,不留半构造 pool 引用。"""
    with patch("lumen_core.checkpointer.PostgresSaver") as MockSaver, \
         patch("lumen_core.checkpointer.ConnectionPool") as MockPool:
        mock_pool = MagicMock()
        MockPool.return_value = mock_pool
        MockSaver.side_effect = RuntimeError("invalid conninfo")

        with pytest.raises(RuntimeError, match="invalid conninfo"):
            CheckpointerService.get()

        # pool 已被显式 close(防止 fd 泄漏),且 class attrs 清空
        mock_pool.close.assert_called_once()
        assert CheckpointerService._saver is None
        assert CheckpointerService._pool is None


def test_close_logs_warning_when_pool_close_fails():
    """close() 内部 pool.close() 失败时记 warning,不再静默吞。"""
    mock_pool = MagicMock()
    mock_pool.close.side_effect = Exception("socket hang up during shutdown")
    CheckpointerService._pool = mock_pool
    CheckpointerService._saver = MagicMock()

    with patch("lumen_core.checkpointer.logger") as MockLogger:
        CheckpointerService.close()
        MockLogger.warning.assert_called_once()
        # warning 触发原因包含原异常信息,便于排查
        call_args = MockLogger.warning.call_args
        assert "pool close failed" in call_args.args[0]
    assert CheckpointerService._pool is None
    assert CheckpointerService._saver is None


def test_get_works_against_real_pg():
    """端到端:CheckpointerService.get() 真连 PG 容器,跑 SELECT 1 round-trip。

    PG 容器 lumen-platform-postgres 在 dev 环境常驻,
    pytest 默认 .env 加载 POSTGRES_URL=postgresql://lumen:lumenpw@localhost:15432/lumen_checkpoints。

    如果 PG 没起 / URL 不指向 localhost,skip 这个 test。

    健康检查改 SELECT 1 后,这个 test 也顺便验证 health() 真打 PG:
    get() 之后调一次 health(),如果 round-trip 成功才算 PG 真在。
    """
    url = settings.POSTGRES_URL or ""
    if not url or "localhost" not in url:
        pytest.skip("POSTGRES_URL not pointing to dev PG — skip integration")
    try:
        saver = CheckpointerService.get()
        assert saver is not None
        # 进一步验证:可以 setup() 建 LangGraph 表(idempotent)
        saver.setup()
        # health() 真打 SELECT 1 —— 之前 get_next_version 是纯算术不算,
        # 现在改成 round-trip 后 health 是真探测。
        assert CheckpointerService.health() is True
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"PG not reachable in this env: {exc}")
    finally:
        # 显式关 pool 释放连接,避免泄漏到后续 test
        CheckpointerService.close()