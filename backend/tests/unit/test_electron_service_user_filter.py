"""target_user_id filtering on broadcast_event_async"""
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock


@pytest.fixture
def service():
    from lumen_services.electron_service import ElectronService
    return ElectronService()


def _conn(cid, user_id=None):
    c = MagicMock()
    c.connection_id = cid
    c.user_id = user_id
    c.websocket = AsyncMock()
    return c


@pytest.mark.asyncio
async def test_target_user_id_filters_to_one_user(service):
    """Only the target user's connections receive the event."""
    me_a = _conn("a", user_id=42)
    me_b = _conn("b", user_id=42)        # 同一用户多 tab
    other = _conn("c", user_id=99)
    electron = _conn("d", user_id=None)  # Electron 客户端
    service.connections = {"a": me_a, "b": me_b, "c": other, "d": electron}

    sent = await service.broadcast_event_async(
        "notification_created", {"id": 1}, target_user_id=42
    )

    assert sent == 2
    assert me_a.websocket.send_json.await_count == 1
    assert me_b.websocket.send_json.await_count == 1
    assert other.websocket.send_json.await_count == 0
    assert electron.websocket.send_json.await_count == 0


@pytest.mark.asyncio
async def test_no_target_user_id_broadcasts_to_all(service):
    """target_user_id=None keeps the historical fan-out-to-all behavior."""
    me = _conn("a", user_id=42)
    other = _conn("c", user_id=99)
    electron = _conn("d", user_id=None)
    service.connections = {"a": me, "c": other, "d": electron}

    sent = await service.broadcast_event_async("knowledge_parse_completed", {})

    assert sent == 3
    assert me.websocket.send_json.await_count == 1
    assert other.websocket.send_json.await_count == 1
    assert electron.websocket.send_json.await_count == 1


@pytest.mark.asyncio
async def test_target_user_id_with_no_matching_conn_returns_zero(service):
    service.connections = {"a": _conn("a", user_id=1)}
    sent = await service.broadcast_event_async(
        "x", {}, target_user_id=999
    )
    assert sent == 0
