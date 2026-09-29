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
    """多次调用 get() 返回同一个 PostgresSaver 实例。

    pool + saver 都只在第一次调用时建,后续直接复用单例(避免反复建连接池)。
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


def test_health_returns_true_when_pg_reachable():
    """pg_reachable=True → health=True。"""
    with patch("lumen_core.checkpointer.PostgresSaver") as MockSaver, \
         patch("lumen_core.checkpointer.ConnectionPool") as MockPool:
        MockPool.return_value = MagicMock()
        mock_saver = MagicMock()
        mock_saver.get_next_version.return_value = "v1"  # 不抛异常 = reachable
        MockSaver.return_value = mock_saver
        assert CheckpointerService.health() is True


def test_health_returns_false_when_pg_unreachable():
    """pg_reachable=False → health=False,不抛。"""
    with patch("lumen_core.checkpointer.PostgresSaver") as MockSaver, \
         patch("lumen_core.checkpointer.ConnectionPool") as MockPool:
        MockPool.return_value = MagicMock()
        mock_saver = MagicMock()
        mock_saver.get_next_version.side_effect = Exception("connection refused")
        MockSaver.return_value = mock_saver
        assert CheckpointerService.health() is False


def test_get_works_against_real_pg():
    """端到端:CheckpointerService.get() 真连 PG 容器,返 PostgresSaver 实例。

    PG 容器 lumen-platform-postgres 在 dev 环境常驻,
    pytest 默认 .env 加载 POSTGRES_URL=postgresql://lumen:lumenpw@localhost:15432/lumen_checkpoints。

    如果 PG 没起 / URL 不指向 localhost,skip 这个 test。
    """
    url = settings.POSTGRES_URL or ""
    if not url or "localhost" not in url:
        pytest.skip("POSTGRES_URL not pointing to dev PG — skip integration")
    try:
        saver = CheckpointerService.get()
        assert saver is not None
        # 进一步验证:可以 setup() 建 LangGraph 表(idempotent)
        saver.setup()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"PG not reachable in this env: {exc}")
    finally:
        # 显式关 pool 释放连接,避免泄漏到后续 test
        CheckpointerService.close()
