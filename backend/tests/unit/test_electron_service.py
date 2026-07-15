"""
ElectronService.broadcast_event_async 单元测试
"""
import pytest
import asyncio
import sys
import os
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))


class TestBroadcastEventAsync:
    @pytest.fixture
    def service(self):
        from lumen_services.electron_service import ElectronService
        return ElectronService()

    @pytest.mark.asyncio
    async def test_broadcast_to_multiple_connections(self, service):
        """应该向所有活跃连接发送 broadcast 消息"""
        conn1 = MagicMock()
        conn1.connection_id = "c1"
        conn1.websocket = AsyncMock()
        conn2 = MagicMock()
        conn2.connection_id = "c2"
        conn2.websocket = AsyncMock()
        service.connections = {"c1": conn1, "c2": conn2}

        await service.broadcast_event_async(
            "workflow_run_completed",
            {"run_id": 1, "workflow_name": "test", "status": "completed", "duration_ms": 100, "tenant_id": 1},
        )

        assert conn1.websocket.send_json.await_count == 1
        assert conn2.websocket.send_json.await_count == 1
        sent = conn1.websocket.send_json.call_args[0][0]
        assert sent["type"] == "broadcast"
        assert sent["event"] == "workflow_run_completed"
        assert sent["payload"]["run_id"] == 1

    @pytest.mark.asyncio
    async def test_broadcast_with_no_connections(self, service):
        """没有连接时静默成功"""
        service.connections = {}
        # 不应该抛错
        await service.broadcast_event_async("test_event", {})

    @pytest.mark.asyncio
    async def test_dead_connection_removed(self, service):
        """发送失败的连接应该从 connections 移除"""
        dead = MagicMock()
        dead.connection_id = "dead"
        dead.websocket = AsyncMock()
        dead.websocket.send_json.side_effect = Exception("connection closed")
        alive = MagicMock()
        alive.connection_id = "alive"
        alive.websocket = AsyncMock()
        service.connections = {"dead": dead, "alive": alive}

        await service.broadcast_event_async("test", {"foo": "bar"})

        assert "dead" not in service.connections
        assert "alive" in service.connections
        assert alive.websocket.send_json.await_count == 1
