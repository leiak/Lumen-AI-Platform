"""/api/v1/ws/web authentication & lifecycle tests"""
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from fastapi import WebSocketDisconnect


@pytest.fixture
def client():
    from lumen_main import app
    return TestClient(app)


def test_ws_web_no_token_closes_4401(client):
    """Missing token → server closes with code 4401."""
    from starlette.websockets import WebSocket
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/api/v1/ws/web") as ws:
            ws.receive_json()
    assert exc.value.code == 4401


def test_ws_web_bad_token_closes_4401(client):
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(
            "/api/v1/ws/web?token=not-a-jwt"
        ) as ws:
            ws.receive_json()
    assert exc.value.code == 4401


def test_ws_web_valid_token_accepts(client, tmp_user):
    """Valid token → server accepts and sends connection_acknowledged.
    On context manager exit the connection should be unregistered."""
    from lumen_core.security import create_access_token
    from lumen_services import electron_service
    token = create_access_token(
        data={"sub": tmp_user.username, "user_id": tmp_user.id}
    )
    # Snapshot connection count before — the route registers into the
    # real singleton, not a mock.
    before = len(electron_service.electron_service.connections)
    with client.websocket_connect(
        f"/api/v1/ws/web?token={token}"
    ) as ws:
        ack = ws.receive_json()
        assert ack["type"] == "connection_acknowledged"
        assert ack["user_id"] == tmp_user.id
        assert ack["tenant_id"] == tmp_user.tenant_id
        # While the WS is open, a new connection should be registered.
        assert len(electron_service.electron_service.connections) == before + 1
    # After exit, the connection is unregistered → back to baseline.
    assert len(electron_service.electron_service.connections) == before
