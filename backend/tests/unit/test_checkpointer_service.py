# backend/tests/unit/test_checkpointer_service.py
import pytest
from unittest.mock import patch, MagicMock
from lumen_core.checkpointer import CheckpointerService


@pytest.fixture(autouse=True)
def _reset_singleton():
    """每个测试前清空 _saver,避免前一个测试缓存的 mock 泄漏到下一个。"""
    CheckpointerService._saver = None
    yield
    CheckpointerService._saver = None


def test_get_returns_singleton():
    """多次调用 get() 返回同一个 PostgresSaver 实例。"""
    with patch("lumen_core.checkpointer.PostgresSaver") as MockSaver:
        MockSaver.from_conn_string.return_value = MagicMock()
        s1 = CheckpointerService.get()
        s2 = CheckpointerService.get()
        assert s1 is s2
        MockSaver.from_conn_string.assert_called_once()


def test_health_returns_true_when_pg_reachable():
    """pg_reachable=True → health=True。"""
    with patch("lumen_core.checkpointer.PostgresSaver") as MockSaver:
        mock = MagicMock()
        mock.get_next_version.return_value = "v1"  # 不抛异常 = reachable
        MockSaver.from_conn_string.return_value = mock
        assert CheckpointerService.health() is True


def test_health_returns_false_when_pg_unreachable():
    """pg_reachable=False → health=False,不抛。"""
    with patch("lumen_core.checkpointer.PostgresSaver") as MockSaver:
        mock = MagicMock()
        mock.get_next_version.side_effect = Exception("connection refused")
        MockSaver.from_conn_string.return_value = mock
        assert CheckpointerService.health() is False

