"""/broadcast route honors target_user_id when X-Internal-Broadcast is correct"""
import pytest
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from lumen_main import app
    return TestClient(app)


def _set_secret(monkeypatch, value):
    from lumen_core import config
    monkeypatch.setattr(config.settings, "BROADCAST_INTERNAL_SECRET", value)


def test_broadcast_with_correct_secret_passes_target_user(monkeypatch, client):
    _set_secret(monkeypatch, "s3cr3t")
    with patch(
        "lumen_services.electron_service.electron_service.broadcast_event_async",
        new=AsyncMock(return_value=1),
    ) as mock_bcast:
        r = client.post(
            "/api/v1/electron/broadcast",
            headers={"X-Internal-Broadcast": "s3cr3t"},
            json={
                "type": "broadcast",
                "event": "notification_created",
                "payload": {"id": 1},
                "target_user_id": 42,
            },
        )
    assert r.status_code == 200
    mock_bcast.assert_awaited_once()
    kwargs = mock_bcast.await_args.kwargs
    assert kwargs.get("target_user_id") == 42


def test_broadcast_with_wrong_secret_drops_target_user(monkeypatch, client):
    _set_secret(monkeypatch, "s3cr3t")
    with patch(
        "lumen_services.electron_service.electron_service.broadcast_event_async",
        new=AsyncMock(return_value=1),
    ) as mock_bcast:
        r = client.post(
            "/api/v1/electron/broadcast",
            headers={"X-Internal-Broadcast": "wrong"},
            json={
                "type": "broadcast",
                "event": "notification_created",
                "payload": {"id": 1},
                "target_user_id": 42,
            },
        )
    assert r.status_code == 200
    kwargs = mock_bcast.await_args.kwargs
    assert kwargs.get("target_user_id") is None


def test_broadcast_without_target_user_does_not_require_secret(client):
    """Electron path: no target_user_id, no secret — still works."""
    with patch(
        "lumen_services.electron_service.electron_service.broadcast_event_async",
        new=AsyncMock(return_value=1),
    ) as mock_bcast:
        r = client.post(
            "/api/v1/electron/broadcast",
            json={
                "type": "broadcast",
                "event": "chat_message_received",
                "payload": {"x": 1},
            },
        )
    assert r.status_code == 200
    assert mock_bcast.await_args.kwargs.get("target_user_id") is None


def test_broadcast_with_string_target_user_id_drops_to_none(monkeypatch, client):
    """A JSON string target_user_id must NOT bypass the filter — it would
    compare unequal to int conn.user_id and silently send to zero clients."""
    _set_secret(monkeypatch, "s3cr3t")
    with patch(
        "lumen_services.electron_service.electron_service.broadcast_event_async",
        new=AsyncMock(return_value=1),
    ) as mock_bcast:
        r = client.post(
            "/api/v1/electron/broadcast",
            headers={"X-Internal-Broadcast": "s3cr3t"},
            json={
                "type": "broadcast",
                "event": "notification_created",
                "payload": {"id": 1},
                "target_user_id": "42",   # string, not int
            },
        )
    assert r.status_code == 200
    assert mock_bcast.await_args.kwargs.get("target_user_id") is None


def test_broadcast_with_invalid_json_returns_422(client):
    r = client.post(
        "/api/v1/electron/broadcast",
        content=b"not json {{{",
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 422


def test_broadcast_uses_event_type_kwarg_m30_regression(client):
    """M30 regression: M27-era route handler called
    ``broadcast_event_async(event=event, payload=..., target_user_id=...)``
    with ``event=`` as the kwarg, but the service's signature is
    ``event_type=``. The mismatch raised TypeError → 500 on every
    chat. This test asserts the route uses the correct kwarg so a
    future rename of the service's parameter would fail loudly
    here instead of in production.
    """
    with patch(
        "lumen_services.electron_service.electron_service.broadcast_event_async",
        new=AsyncMock(return_value=1),
    ) as mock_bcast:
        r = client.post(
            "/api/v1/electron/broadcast",
            json={
                "type": "broadcast",
                "event": "chat_message_received",
                "payload": {"conv_id": 99, "preview": "hi"},
            },
        )
    assert r.status_code == 200
    # Both the kwarg NAME and value must match the real service.
    kwargs = mock_bcast.await_args.kwargs
    assert "event_type" in kwargs, (
        f"broadcast_event_async must be called with event_type=... kwarg, "
        f"got kwargs={list(kwargs.keys())}"
    )
    assert kwargs["event_type"] == "chat_message_received"
    # The buggy `event=` must NOT be in kwargs (catches the
    # future refactor that re-introduces the keyword mismatch).
    assert "event" not in kwargs, (
        f"`event=` kwarg is invalid; use event_type=. Got {kwargs}"
    )
    assert kwargs["payload"] == {"conv_id": 99, "preview": "hi"}
