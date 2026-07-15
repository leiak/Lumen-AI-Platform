"""Regression: internal chat must still work after ``conversations.user_id``
is made nullable.

We lock down the happy path of the 3 critical internal-chat operations
with non-null user_ids, so that if a future change drops the ``user_id``
filter or assumes user_id IS NOT NULL, these tests fail loudly.

Background: see ``docs/superpowers/specs/2026-06-08-external-chat-widget-design.md``
section 4.3 — the EXTERNAL chat flow uses ``user_id IS NULL`` and
populates ``external_app_id`` + ``external_visitor_id`` instead. The
service layer (added in later tasks) enforces the mutual-exclusion; this
test file only verifies that the internal flow (user_id IS NOT NULL)
still works end-to-end through the HTTP layer.

Note on session lifecycle (2026-06-08): the autouse
``_dispose_engine_after_test`` fixture calls ``gc.collect()`` and then
``engine.dispose()`` after each test in this file. The autouse
``get_db`` FastAPI dependency calls ``db.close()`` in its ``finally``
block, which returns the connection to the pool — but in a
long-running pytest process the underlying DBAPI connection's
transaction state (and any InnoDB metadata lock it holds) can survive
the close because the ``Session`` object is still alive in a
generator-local frame that hasn't been garbage-collected yet. When
the next test in the suite (``test_database_migrations.py::
test_ensure_conversations_user_id_nullable_is_idempotent``) issues a
``MODIFY COLUMN`` on ``conversations``, the orphaned connection
blocks the DDL — observable as the full ``pytest tests/unit/`` suite
"hanging" at ~20%. Regression guard: see
``docs/troubleshooting/2026-06-08-external-chat-mdl-deadlock.md``.

The fix has two halves: ``gc.collect()`` forces the unreferenced
``Session`` objects to finalize (which returns their connections to
the pool), and then ``engine.dispose()`` closes all checked-in
connections. The order matters — disposing without first collecting
would skip the connections that are still held by live ``Session``
references.

We do NOT use ``TestClient`` as a context manager here: doing so would
trigger FastAPI's async ``shutdown`` event handler, which closes the
event loop — subsequent tests in the same file then fail with
``RuntimeError: Event loop is closed``. The peer test files
(``test_chat_api_delete.py``, ``test_chat_conversation_agent.py``) use
the same plain ``TestClient(app)`` pattern; the dispose fixture is
the minimal delta that fixes the hang without changing that.
"""
import pytest
import uuid
from fastapi.testclient import TestClient
from lumen_core.database import SessionLocal


@pytest.fixture
def client():
    from lumen_main import app
    return TestClient(app)


@pytest.fixture(autouse=True)
def _dispose_engine_after_test():
    """Force-close all pooled connections after each test.

    See module docstring for the full diagnosis. This is heavy-handed
    but proven to work; it only affects this test file (autouse scope
    is the file), so it doesn't slow the broader suite.

    The ``gc.collect()`` is critical: prior tests in the suite (e.g.
    ``test_chat_conversation_agent.py``) sometimes leave SQLAlchemy
    ``Session`` objects in a generator-local frame that hasn't been
    garbage-collected yet — their underlying DBAPI connection stays
    checked out from the pool, holding the InnoDB metadata lock on
    ``conversations`` until the next ``innodb_lock_wait_timeout`` (50s)
    expires. ``engine.dispose()`` only closes connections that are
    currently checked IN; ``gc.collect()`` forces the unreferenced
    ``Session`` objects to finalize (``Session.close()`` returns the
    connection to the pool), and then ``engine.dispose()`` closes them.
    """
    yield
    from lumen_core.database import engine
    import gc
    gc.collect()
    engine.dispose()


@pytest.fixture
def auth_header(tmp_user):
    # auth_service re-exports create_access_token via `from lumen_core.security
    # import ... create_access_token` at module top, so this import works
    # the same way the other chat tests do (see test_chat_api_delete.py).
    from lumen_services.auth_service import create_access_token
    token = create_access_token(
        data={"sub": tmp_user.username, "user_id": tmp_user.id}
    )
    return {"Authorization": f"Bearer {token}"}


def test_list_conversations_user_scoped(client, auth_header, tmp_user):
    """A conversation owned by tmp_user must appear in GET /chat/conversations.

    Locks down: the list endpoint still filters by ``user_id ==
    current_user.id`` (the plan's schema change makes the column
    nullable, but the query must NOT silently match external rows where
    user_id IS NULL).
    """
    db = SessionLocal()
    try:
        from lumen_models.chat import Conversation
        own = Conversation(title="own", user_id=tmp_user.id, tenant_id=tmp_user.tenant_id)
        db.add(own)
        db.commit()
        own_id = own.id
    finally:
        db.close()

    r = client.get("/api/v1/chat/conversations", headers=auth_header)
    assert r.status_code == 200
    body = r.json()
    assert body["code"] == 200
    ids = {c["id"] for c in body["data"]}
    assert own_id in ids


def test_create_conversation_persists_user_id(client, auth_header, tmp_user):
    """POST /chat/conversations must still wire user_id for internal users.

    Locks down: the create endpoint explicitly sets ``user_id =
    current_user.id`` — it does NOT skip that field just because the
    column is now nullable. Without this regression, an internal user
    could end up with a Conversation that has ``user_id IS NULL``,
    which would then be filtered out by the list endpoint (no leakage
    but data corruption).
    """
    r = client.post(
        "/api/v1/chat/conversations",
        json={"title": "nullable-regression"},
        headers=auth_header,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["code"] == 200
    conv_id = body["data"]["id"]

    db = SessionLocal()
    try:
        from lumen_models.chat import Conversation
        conv = db.get(Conversation, conv_id)
        assert conv is not None
        assert conv.user_id == tmp_user.id  # internal flow still wires user_id
        # Both external_*_id columns must be NULL on an internal conv —
        # the service layer (added in later tasks) will enforce the
        # mutual-exclusion invariant; we just lock down the current
        # behavior here.
        assert conv.external_app_id is None
        assert conv.external_visitor_id is None
    finally:
        db.close()


def test_get_messages_user_scoped_404_for_other_user(client, auth_header, tmp_user):
    """GET /chat/conversations/{id}/messages must 404 on cross-user access.

    Locks down: the user-scope filter on the read path is still in
    place. If a future refactor drops the ``user_id == current_user.id``
    clause (e.g. because the column is now nullable and the developer
    forgot to update the WHERE), this test fails.
    """
    db = SessionLocal()
    try:
        from lumen_models.chat import Conversation
        from lumen_models.user import User
        from lumen_core.security import get_password_hash
        suffix = uuid.uuid4().hex[:8]
        other = User(
            username=f"other_{suffix}",
            email=f"other_{suffix}@test.local",
            hashed_password=get_password_hash("x"),
            tenant_id=tmp_user.tenant_id,
            is_active=True,
        )
        db.add(other)
        db.commit()
        db.refresh(other)
        other_conv = Conversation(
            title="other-user-conv", user_id=other.id, tenant_id=tmp_user.tenant_id
        )
        db.add(other_conv)
        db.commit()
        other_conv_id = other_conv.id
    finally:
        db.close()

    r = client.get(
        f"/api/v1/chat/conversations/{other_conv_id}/messages",
        headers=auth_header,
    )
    assert r.status_code == 404  # NOT 200 — must not leak across users
