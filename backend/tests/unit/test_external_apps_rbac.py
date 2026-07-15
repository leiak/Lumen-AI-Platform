"""RBAC: only users with the ``external_apps:manage`` permission can CRUD
external apps. Viewers (read-only) are restricted to GET. Cross-tenant
attempts return 404.

MVP: ``is_superuser`` is the gate. Once the RBAC table ships
(see Role/Permission models in app/models/role.py), the gate will
become a check for ``external_apps:manage`` permission. This test
locks down the CURRENT contract so a future migration doesn't
silently grant access to non-admins.
"""
import secrets
import pytest
from datetime import datetime
from fastapi.testclient import TestClient

from lumen_core.database import SessionLocal
from lumen_core.security import get_password_hash
from lumen_main import app
from lumen_models.tenant import Tenant
from lumen_models.user import User
from lumen_services.auth_service import create_access_token


# Same MDL-defense fixture as Tasks 10-16. See MEMORY.md "TestClient + MDL deadlock".
@pytest.fixture(autouse=True)
def _dispose_engine_after_test():
    yield
    from lumen_core.database import engine
    import gc
    gc.collect()
    engine.dispose()


def _make_user(db, *, tenant_id, username, is_superuser=False):
    """Returns (id, username) tuple to avoid DetachedInstanceError.

    User.email is nullable=False (see app/models/user.py:10) — must set it.
    """
    u = User(
        username=username,
        email=f"{username}@example.com",  # required, unique
        hashed_password=get_password_hash("x"),
        tenant_id=tenant_id, is_active=True, is_superuser=is_superuser,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return (u.id, u.username)


def _auth(uid: int, username: str):
    return {"Authorization": f"Bearer {create_access_token(data={'sub': username, 'user_id': uid})}"}


def test_non_admin_cannot_create():
    db = SessionLocal()
    try:
        # Tenant.status is Boolean (default True) — no status="active" arg
        t = Tenant(name=f"t-na-{secrets.token_hex(2)}",
                   code=f"tna-{datetime.utcnow().timestamp()}-{secrets.token_hex(2)}",
                   max_users=5)
        db.add(t)
        db.commit()
        db.refresh(t)
        uid, uname = _make_user(db, tenant_id=t.id, username=f"viewer-{secrets.token_hex(2)}",
                                is_superuser=False)
    finally:
        db.close()
    client = TestClient(app)
    r = client.post(
        "/api/v1/external-apps",
        json={"name": "x", "allowed_origins": []},
        headers=_auth(uid, uname),
    )
    assert r.status_code == 403


def test_admin_can_create_and_list():
    db = SessionLocal()
    try:
        t = Tenant(name=f"t-ad-{secrets.token_hex(2)}",
                   code=f"tad-{datetime.utcnow().timestamp()}-{secrets.token_hex(2)}",
                   max_users=5)
        db.add(t)
        db.commit()
        db.refresh(t)
        uid, uname = _make_user(db, tenant_id=t.id, username=f"admin-{secrets.token_hex(2)}",
                                is_superuser=True)
    finally:
        db.close()
    headers = _auth(uid, uname)
    client = TestClient(app)
    r = client.post("/api/v1/external-apps",
                    json={"name": "ok", "allowed_origins": ["https://a.com"]},
                    headers=headers)
    assert r.status_code == 200
    r2 = client.get("/api/v1/external-apps", headers=headers)
    assert r2.status_code == 200
    assert any(i["name"] == "ok" for i in r2.json()["data"])
