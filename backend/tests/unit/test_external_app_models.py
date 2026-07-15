"""Tests for ExternalApp + ExternalVisitor ORM models.

Covers:
  - table creation (relies on Base.metadata.create_all)
  - unique constraint on app_key
  - unique constraint on (app_id, visitor_id) for ExternalVisitor
  - cascade behavior
"""
import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from lumen_core.database import SessionLocal, create_tables
from lumen_models.external_app import ExternalApp, ExternalVisitor

# Idempotent: only creates missing tables. Safe to call on every test
# run — Task 3 will replace this with the real migration. The dev DB
# already has tenants/users; the new tables are created here so this
# test file is self-contained (no FastAPI startup required).
create_tables()


@pytest.fixture
def db():
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


# Hardcoded app_keys used by every test in this module. The autouse
# fixture below deletes them (and the visitor rows they own) after
# each test so the suite is idempotent — without this, a second run
# on the dev DB hits "Duplicate entry 'lc_pub_abc123' for key
# 'external_apps.app_key'" before the first assertion.
_TEST_APP_KEYS = (
    "lc_pub_abc123",
    "lc_pub_same",
    "lc_pub_uv",
    "lc_pub_a1",
    "lc_pub_a2",
)


@pytest.fixture(autouse=True)
def _cleanup_external_app_rows():
    yield
    s = SessionLocal()
    try:
        apps = (
            s.query(ExternalApp)
            .filter(ExternalApp.app_key.in_(_TEST_APP_KEYS))
            .all()
        )
        if apps:
            app_ids = [a.id for a in apps]
            s.query(ExternalVisitor).filter(
                ExternalVisitor.app_id.in_(app_ids)
            ).delete(synchronize_session=False)
            for a in apps:
                s.delete(a)
            s.commit()
    except Exception:
        s.rollback()
    finally:
        s.close()


def _make_tenant(db: Session):
    from lumen_models.tenant import Tenant
    t = Tenant(name="t", code=f"t-{id(db)}", status=True, max_users=10)
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


def _make_user(db: Session, tenant_id: int):
    from lumen_models.user import User
    from lumen_core.security import get_password_hash
    u = User(
        username=f"u-{id(db)}",
        email=f"u-{id(db)}@test.local",
        hashed_password=get_password_hash("x"),
        tenant_id=tenant_id,
        is_active=True,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def test_create_external_app_minimum(db):
    t = _make_tenant(db)
    u = _make_user(db, t.id)
    app = ExternalApp(
        tenant_id=t.id,
        name="shop widget",
        app_key="lc_pub_abc123",
        app_secret_hash="x" * 60,
        allowed_origins=["https://shop.example.com"],
        created_by=u.id,
    )
    db.add(app)
    db.commit()
    db.refresh(app)
    assert app.id is not None
    assert app.is_active is True
    assert app.rate_limit_per_min == 60
    assert app.allowed_agent_ids == []
    assert app.allowed_team_ids == []


def test_app_key_uniqueness(db):
    t = _make_tenant(db)
    a1 = ExternalApp(tenant_id=t.id, name="a", app_key="lc_pub_same",
                    app_secret_hash="x", allowed_origins=[])
    db.add(a1)
    db.commit()
    a2 = ExternalApp(tenant_id=t.id, name="b", app_key="lc_pub_same",
                    app_secret_hash="y", allowed_origins=[])
    db.add(a2)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_visitor_unique_per_app(db):
    t = _make_tenant(db)
    app = ExternalApp(tenant_id=t.id, name="a", app_key="lc_pub_uv",
                      app_secret_hash="x", allowed_origins=[])
    db.add(app)
    db.commit()
    db.refresh(app)
    v1 = ExternalVisitor(app_id=app.id, visitor_id="vid-1")
    db.add(v1)
    db.commit()
    v2 = ExternalVisitor(app_id=app.id, visitor_id="vid-1")  # same visitor_id
    db.add(v2)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_visitor_can_repeat_across_apps(db):
    t = _make_tenant(db)
    a1 = ExternalApp(tenant_id=t.id, name="a1", app_key="lc_pub_a1",
                     app_secret_hash="x", allowed_origins=[])
    a2 = ExternalApp(tenant_id=t.id, name="a2", app_key="lc_pub_a2",
                     app_secret_hash="x", allowed_origins=[])
    db.add_all([a1, a2])
    db.commit()
    v1 = ExternalVisitor(app_id=a1.id, visitor_id="shared")
    v2 = ExternalVisitor(app_id=a2.id, visitor_id="shared")
    db.add_all([v1, v2])
    db.commit()  # OK — different apps, same visitor_id
