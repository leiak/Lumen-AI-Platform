"""Admin CRUD for /api/v1/external-apps — list / create / get / patch / delete / regenerate / usage.

Covers happy path + multi-tenant isolation (404, not 403) + reference
protection on delete (409 if there are active conversations).
"""
import secrets
import pytest
from datetime import datetime
from fastapi.testclient import TestClient

from lumen_core.database import SessionLocal
from lumen_main import app
from lumen_models.chat import Conversation
from lumen_models.external_app import ExternalApp
from lumen_models.tenant import Tenant
from lumen_models.user import User
from lumen_core.security import get_password_hash
from lumen_services.auth_service import create_access_token


# Same MDL-defense fixture as Tasks 10-15. See MEMORY.md "TestClient + MDL deadlock".
@pytest.fixture(autouse=True)
def _dispose_engine_after_test():
    yield
    from lumen_core.database import engine
    import gc
    gc.collect()
    engine.dispose()


def _make_admin_user(db, *, tenant_id, username):
    """Create a user with is_superuser=True so _require_admin passes.

    Plan's _make_user_with_role forgot to set is_superuser, which would
    cause every test to 403. The MVP _require_admin in this file checks
    is_superuser (not RBAC table), so superuser is sufficient.

    Returns (id, username) — we can't return the User object because the
    caller closes the session before reading attributes (DetachedInstance).
    """
    # User.email is nullable=False in the ORM; the plan's helper forgot it.
    u = User(
        username=username,
        email=f"{username}@example.com",
        hashed_password=get_password_hash("x"),
        tenant_id=tenant_id, is_active=True, is_superuser=True,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return (u.id, u.username)


def _auth(uid_username):
    uid, username = uid_username
    return {"Authorization": f"Bearer {create_access_token(data={'sub': username, 'user_id': uid})}"}


def test_list_returns_only_own_tenant():
    db = SessionLocal()
    try:
        t1 = Tenant(name=f"t1-{secrets.token_hex(2)}", code=f"t1-{datetime.utcnow().timestamp()}-{secrets.token_hex(2)}", max_users=5)
        t2 = Tenant(name=f"t2-{secrets.token_hex(2)}", code=f"t2-{datetime.utcnow().timestamp()}-{secrets.token_hex(2)}", max_users=5)
        db.add_all([t1, t2])
        db.commit()
        for t in (t1, t2):
            db.refresh(t)
        u = _make_admin_user(db, tenant_id=t1.id, username=f"u-list-{secrets.token_hex(2)}")
        a1 = ExternalApp(tenant_id=t1.id, name="a1", app_key=f"lc_pub_list_{secrets.token_hex(4)}",
                         app_secret_hash="x", allowed_origins=[])
        a2 = ExternalApp(tenant_id=t2.id, name="a2", app_key=f"lc_pub_list_{secrets.token_hex(4)}",
                         app_secret_hash="x", allowed_origins=[])
        db.add_all([a1, a2])
        db.commit()
    finally:
        db.close()
    client = TestClient(app)
    r = client.get("/api/v1/external-apps", headers=_auth(u))
    assert r.status_code == 200
    items = r.json()["data"]
    names = [i["name"] for i in items]
    assert "a1" in names
    assert "a2" not in names  # cross-tenant filtered


def test_create_returns_plain_secret_once():
    db = SessionLocal()
    try:
        t = Tenant(name=f"t-c-{secrets.token_hex(2)}", code=f"t-c-{datetime.utcnow().timestamp()}-{secrets.token_hex(2)}", max_users=5)
        db.add(t)
        db.commit()
        db.refresh(t)
        u = _make_admin_user(db, tenant_id=t.id, username=f"u-c-{secrets.token_hex(2)}")
    finally:
        db.close()
    client = TestClient(app)
    r = client.post("/api/v1/external-apps", json={
        "name": "new app",
        "allowed_origins": ["https://shop.example.com"],
        "allowed_agent_ids": [],
    }, headers=_auth(u))
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["app_key"].startswith("lc_pub_")
    assert data["app_secret_plain"].startswith("sk_")


def test_get_cross_tenant_404():
    db = SessionLocal()
    try:
        t1 = Tenant(name=f"t-g1-{secrets.token_hex(2)}", code=f"tg1-{datetime.utcnow().timestamp()}-{secrets.token_hex(2)}", max_users=5)
        t2 = Tenant(name=f"t-g2-{secrets.token_hex(2)}", code=f"tg2-{datetime.utcnow().timestamp()}-{secrets.token_hex(2)}", max_users=5)
        db.add_all([t1, t2])
        db.commit()
        for t in (t1, t2):
            db.refresh(t)
        u = _make_admin_user(db, tenant_id=t1.id, username=f"u-g1-{secrets.token_hex(2)}")
        other = ExternalApp(tenant_id=t2.id, name="o", app_key=f"lc_pub_g_{secrets.token_hex(4)}",
                            app_secret_hash="x", allowed_origins=[])
        db.add(other)
        db.commit()
        db.refresh(other)
        other_id = other.id
    finally:
        db.close()
    client = TestClient(app)
    r = client.get(f"/api/v1/external-apps/{other_id}", headers=_auth(u))
    assert r.status_code == 404  # NOT 403 — anti-enumeration


def test_delete_with_active_conversations_409():
    db = SessionLocal()
    try:
        t = Tenant(name=f"t-d-{secrets.token_hex(2)}", code=f"td-{datetime.utcnow().timestamp()}-{secrets.token_hex(2)}", max_users=5)
        db.add(t)
        db.commit()
        db.refresh(t)
        u = _make_admin_user(db, tenant_id=t.id, username=f"u-d-{secrets.token_hex(2)}")
        a = ExternalApp(tenant_id=t.id, name="del", app_key=f"lc_pub_d_{secrets.token_hex(4)}",
                        app_secret_hash="x", allowed_origins=[])
        db.add(a)
        db.commit()
        db.refresh(a)
        # Create a conv tied to this app (external_visitor_id can be None for
        # the reference-protection test — only the FK on external_app_id matters)
        c = Conversation(title="x", tenant_id=t.id, user_id=None,
                         external_app_id=a.id, external_visitor_id=None)
        db.add(c)
        db.commit()
        db.refresh(c)
        a_id = a.id
    finally:
        db.close()
    client = TestClient(app)
    r = client.delete(f"/api/v1/external-apps/{a_id}", headers=_auth(u))
    assert r.status_code == 409


def test_regenerate_secret_returns_new_plain():
    db = SessionLocal()
    try:
        t = Tenant(name=f"t-r-{secrets.token_hex(2)}", code=f"tr-{datetime.utcnow().timestamp()}-{secrets.token_hex(2)}", max_users=5)
        db.add(t)
        db.commit()
        db.refresh(t)
        u = _make_admin_user(db, tenant_id=t.id, username=f"u-r-{secrets.token_hex(2)}")
        a = ExternalApp(tenant_id=t.id, name="r", app_key=f"lc_pub_r_{secrets.token_hex(4)}",
                        app_secret_hash="x", allowed_origins=[])
        db.add(a)
        db.commit()
        db.refresh(a)
        a_id = a.id
    finally:
        db.close()
    client = TestClient(app)
    r = client.post(f"/api/v1/external-apps/{a_id}/regenerate-secret", headers=_auth(u))
    assert r.status_code == 200
    assert r.json()["data"]["app_secret_plain"].startswith("sk_")


def test_usage_endpoint_returns_counters():
    db = SessionLocal()
    try:
        t = Tenant(name=f"t-u-{secrets.token_hex(2)}", code=f"tu-{datetime.utcnow().timestamp()}-{secrets.token_hex(2)}", max_users=5)
        db.add(t)
        db.commit()
        db.refresh(t)
        u = _make_admin_user(db, tenant_id=t.id, username=f"u-u-{secrets.token_hex(2)}")
        a = ExternalApp(tenant_id=t.id, name="u", app_key=f"lc_pub_u_{secrets.token_hex(4)}",
                        app_secret_hash="x", allowed_origins=[])
        db.add(a)
        db.commit()
        db.refresh(a)
        a_id = a.id
    finally:
        db.close()
    client = TestClient(app)
    r = client.get(f"/api/v1/external-apps/{a_id}/usage", headers=_auth(u))
    assert r.status_code == 200
    data = r.json()["data"]
    assert "total_conversations" in data
    assert "active_visitors_7d" in data
