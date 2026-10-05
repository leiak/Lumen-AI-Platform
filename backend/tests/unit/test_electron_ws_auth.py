"""Auth guards on /electron/* HTTP routes (nitpick 2026-10-04 C3).

Until M39 these 4 routes were open to anyone on the internal network
(no ``Depends(get_current_user)``). ``/connections`` exposed owning
user_id / tenant_id for every live Electron client; ``/broadcast``
fell through to fan-out-to-all without any caller authentication.

This test locks the new auth model:

  - ``/electron/status``     — admin-only (count of active conns is recon)
  - ``/electron/connections``— admin-only (user/tenant enumeration)
  - ``/electron/broadcast``  — admin-only (legacy secret fallback kept)
  - ``/electron/health``     — any authenticated user (dashboard polls)

Each test covers the negative path (anonymous / non-admin) AND the
positive path (admin passes). For ``/broadcast`` we also lock the
legacy "wrong secret drops target_user_id" semantics so future
hardening doesn't accidentally re-widen the route.
"""
import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from fastapi.testclient import TestClient


# ---------- fixtures ---------- #


@pytest.fixture
def admin_user():
    u = MagicMock()
    u.id = 1
    u.username = "test_admin"
    u.is_superuser = True
    u.is_active = True
    u.tenant_id = 1
    return u


@pytest.fixture
def regular_user():
    u = MagicMock()
    u.id = 2
    u.username = "test_user"
    u.is_superuser = False
    u.is_active = True
    u.tenant_id = 1
    return u


@pytest.fixture
def app_with_admin(admin_user):
    """App with ``require_admin`` / ``get_current_user`` overridden.

    Per-test the caller chooses which synthetic user is wired up via
    ``wire_*`` fixtures below.
    """
    from lumen_main import app
    from lumen_api.v1.auth import require_admin, get_current_user

    app.dependency_overrides[require_admin] = lambda: admin_user
    app.dependency_overrides[get_current_user] = lambda: admin_user
    try:
        yield app
    finally:
        app.dependency_overrides.pop(require_admin, None)
        app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture
def app_with_regular(regular_user):
    from lumen_main import app
    from lumen_api.v1.auth import require_admin, get_current_user

    # Regular user authenticates as ``get_current_user`` but FAILS
    # ``require_admin``. This is the realistic "logged-in but not
    # superuser" scenario the guards must distinguish.
    app.dependency_overrides[require_admin] = lambda: (_ for _ in ()).throw(
        __import__("fastapi").HTTPException(
            status_code=403, detail="仅管理员可访问"
        )
    )
    app.dependency_overrides[get_current_user] = lambda: regular_user
    try:
        yield app
    finally:
        app.dependency_overrides.pop(require_admin, None)
        app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture
def client(app_with_admin):
    return TestClient(app_with_admin)


@pytest.fixture
def regular_client(app_with_regular):
    return TestClient(app_with_regular)


# ---------- /electron/status ---------- #


class TestStatusEndpoint:
    def test_anonymous_caller_rejected(self):
        """Without an auth override, ``Depends(require_admin)`` raises 401/403."""
        from lumen_main import app
        from lumen_api.v1.auth import require_admin

        # Pull the existing override (if any) to ensure a clean slate.
        app.dependency_overrides.pop(require_admin, None)
        app.dependency_overrides.pop(__import__("lumen_api.v1.auth", fromlist=["get_current_user"]).get_current_user, None)

        r = TestClient(app).get("/api/v1/electron/status")
        # FastAPI security scheme returns 401 for missing token,
        # 403 for insufficient privileges. Either is acceptable
        # for the anonymous / status path.
        assert r.status_code in (401, 403), (
            f"anonymous must NOT reach /electron/status; got {r.status_code} {r.text}"
        )

    def test_regular_user_rejected_with_403(self, regular_client):
        r = regular_client.get("/api/v1/electron/status")
        assert r.status_code == 403
        assert "仅管理员可访问" in r.text

    def test_admin_passes(self, client):
        with patch(
            "lumen_services.electron_service.electron_service.handle_message",
            new=AsyncMock(return_value={"success": True, "data": {"connections": 0}}),
        ):
            r = client.get("/api/v1/electron/status")
        assert r.status_code == 200


# ---------- /electron/connections ---------- #


class TestConnectionsEndpoint:
    def test_anonymous_caller_rejected(self):
        from lumen_main import app
        from lumen_api.v1.auth import require_admin

        app.dependency_overrides.pop(require_admin, None)
        r = TestClient(app).get("/api/v1/electron/connections")
        assert r.status_code in (401, 403)

    def test_regular_user_rejected_with_403(self, regular_client):
        r = regular_client.get("/api/v1/electron/connections")
        assert r.status_code == 403

    def test_admin_passes(self, client):
        r = client.get("/api/v1/electron/connections")
        assert r.status_code == 200
        body = r.json()
        assert "connections" in body
        assert "count" in body


# ---------- /electron/broadcast ---------- #


class TestBroadcastEndpoint:
    def test_anonymous_caller_rejected(self):
        from lumen_main import app
        from lumen_api.v1.auth import require_admin

        app.dependency_overrides.pop(require_admin, None)
        r = TestClient(app).post(
            "/api/v1/electron/broadcast",
            json={"type": "broadcast", "event": "x", "payload": {}},
        )
        assert r.status_code in (401, 403)

    def test_regular_user_rejected_with_403(self, regular_client):
        r = regular_client.post(
            "/api/v1/electron/broadcast",
            json={"type": "broadcast", "event": "x", "payload": {}},
        )
        assert r.status_code == 403

    def test_admin_no_target_no_secret_fans_out(self, client):
        """Legacy compat: admin + no target_user_id + no secret → 200."""
        with patch(
            "lumen_services.electron_service.electron_service.broadcast_event_async",
            new=AsyncMock(return_value=1),
        ) as m:
            r = client.post(
                "/api/v1/electron/broadcast",
                json={
                    "type": "broadcast",
                    "event": "chat_message_received",
                    "payload": {"x": 1},
                },
            )
        assert r.status_code == 200
        assert m.await_args.kwargs.get("target_user_id") is None

    def test_admin_with_target_no_secret_drops_to_fanout(self, monkeypatch, client):
        """Admin + target_user_id + missing secret → silently fan-out (legacy compat)."""
        from lumen_core import config

        monkeypatch.setattr(config.settings, "BROADCAST_INTERNAL_SECRET", "real-secret")
        with patch(
            "lumen_services.electron_service.electron_service.broadcast_event_async",
            new=AsyncMock(return_value=1),
        ) as m:
            r = client.post(
                "/api/v1/electron/broadcast",
                json={
                    "type": "broadcast",
                    "event": "x",
                    "payload": {},
                    "target_user_id": 42,
                },
            )
        assert r.status_code == 200
        assert m.await_args.kwargs.get("target_user_id") is None

    def test_admin_with_target_and_wrong_secret_drops_to_fanout(self, monkeypatch, client):
        from lumen_core import config

        monkeypatch.setattr(config.settings, "BROADCAST_INTERNAL_SECRET", "real-secret")
        with patch(
            "lumen_services.electron_service.electron_service.broadcast_event_async",
            new=AsyncMock(return_value=1),
        ) as m:
            r = client.post(
                "/api/v1/electron/broadcast",
                headers={"X-Internal-Broadcast": "wrong"},
                json={
                    "type": "broadcast",
                    "event": "x",
                    "payload": {},
                    "target_user_id": 42,
                },
            )
        assert r.status_code == 200
        assert m.await_args.kwargs.get("target_user_id") is None

    def test_admin_with_correct_secret_passes_target_user(self, monkeypatch, client):
        from lumen_core import config

        monkeypatch.setattr(config.settings, "BROADCAST_INTERNAL_SECRET", "real-secret")
        with patch(
            "lumen_services.electron_service.electron_service.broadcast_event_async",
            new=AsyncMock(return_value=1),
        ) as m:
            r = client.post(
                "/api/v1/electron/broadcast",
                headers={"X-Internal-Broadcast": "real-secret"},
                json={
                    "type": "broadcast",
                    "event": "x",
                    "payload": {},
                    "target_user_id": 42,
                },
            )
        assert r.status_code == 200
        assert m.await_args.kwargs.get("target_user_id") == 42


# ---------- /electron/health ---------- #


class TestHealthEndpoint:
    def test_anonymous_caller_rejected(self):
        """``/electron/health`` requires at least a valid user token (any role)."""
        from lumen_main import app
        from lumen_api.v1.auth import get_current_user

        app.dependency_overrides.pop(get_current_user, None)
        r = TestClient(app).get("/api/v1/electron/health")
        # No token → 401 (FastAPI security scheme rejects)
        assert r.status_code == 401

    def test_regular_user_passes(self, regular_client):
        with patch(
            "lumen_services.electron_service.electron_service.handle_message",
            new=AsyncMock(return_value={"success": True, "data": {"healthy": True}}),
        ):
            r = regular_client.get("/api/v1/electron/health")
        assert r.status_code == 200
        body = r.json()
        assert body.get("healthy") is True

    def test_admin_passes(self, client):
        with patch(
            "lumen_services.electron_service.electron_service.handle_message",
            new=AsyncMock(return_value={"success": True, "data": {"healthy": True}}),
        ):
            r = client.get("/api/v1/electron/health")
        assert r.status_code == 200