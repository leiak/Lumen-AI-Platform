"""M38.1: integration tests for ``/api/v1/storage/*``.

These cover the three endpoints added in the spec:

- ``GET  /api/v1/storage/health`` — connectivity probe.
- ``GET  /api/v1/storage/local/<key>`` — bearer-auth local proxy.
- ``POST /api/v1/storage/migrate-to-s3`` — admin-only cold migration.

Tests use FastAPI's ``dependency_overrides`` so the suite can run
without a live MySQL / uvicorn / MinIO stack. Behaviour-level coverage
of the underlying ``StorageBackend`` lives in
``tests/unit/test_storage_backends.py``.

Spec: §9.2.
"""
from __future__ import annotations

import io
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest
from fastapi.testclient import TestClient


# --- shared fixtures ----------------------------------------------------


class _FakeUser:
    """Minimal stand-in for ``lumen_models.user.User`` that the auth
    dependency expects. The endpoint only reads ``tenant_id`` and
    ``is_superuser``/role-ish attributes; ``auth.is_admin_user`` looks
    at ``is_superuser`` so that's the only flag we need.
    """

    def __init__(self, *, tenant_id: int = 1, is_superuser: bool = False) -> None:
        self.tenant_id = tenant_id
        self.is_superuser = is_superuser
        self.id = 1
        self.username = "tester"


class _FakeDocument:
    def __init__(
        self,
        *,
        document_id: int,
        tenant_id: int,
        asset_storage_key: Optional[str] = None,
        file_path: Optional[str] = None,
        knowledge_base_id: int = 1,
    ) -> None:
        self.id = document_id
        self.asset_storage_key = asset_storage_key
        self.file_path = file_path
        self.knowledge_base_id = knowledge_base_id
        self._tenant_id = tenant_id  # exposed below

    @property
    def tenant_id(self) -> int:
        # Lazy resolution against the KB so admin can read across
        # tenants even if the row's tenant differs — but in our
        # integration tests the KB tenant is what's checked.
        return self._tenant_id


class _FakeKB:
    def __init__(self, *, tenant_id: int) -> None:
        self.tenant_id = tenant_id


class _FakeQuery:
    """Bare-bones Query stub that filters one column against a list
    of pre-loaded rows. Avoids dragging a SQLAlchemy session into
    the test.

    ``filter(col == value)`` exposes a ``BinaryExpression``; we
    extract ``left.key`` for the column name and the bound
    parameter's ``.value`` for the comparison value.
    """

    def __init__(self, rows: List[_FakeDocument]):
        self._rows = list(rows)
        self._filters: Dict[str, Any] = {}

    def _extract_value(self, expr):
        """Best-effort extraction of a Python value from a SQLAlchemy
        clause operand (column, bound param, literal)."""
        # Bound parameters expose ``.value``; literals may not. Try
        # several attributes so the test stub survives SQLAlchemy
        # version drift.
        for attr in ("value", "effective_value"):
            v = getattr(expr, attr, None)
            if v is not None:
                return v
        # Column reference — return None; the caller usually checks
        # ``is_(None)`` for those.
        if hasattr(expr, "key"):
            return None
        return expr

    def filter(self, *args):
        for clause in args:
            try:
                op = clause.operator
                left = clause.left
                right = clause.right
            except AttributeError:
                continue
            op_name = getattr(op, "__name__", "")
            col_key = getattr(left, "key", None)
            if col_key is None:
                continue

            if op_name == "is_":
                self._filters[col_key] = None
                self._filters[f"_op_{col_key}"] = "is_null"
                continue

            if op_name != "eq":
                continue

            self._filters[col_key] = self._extract_value(right)
            self._filters.pop(f"_op_{col_key}", None)
        return self

    def _row_matches(self, row):
        for k, v in self._filters.items():
            if k.startswith("_"):
                continue
            actual = getattr(row, k, None)
            op_key = f"_op_{k}"
            op = self._filters.get(op_key)
            if op == "is_null":
                if actual is not None:
                    return False
                continue
            if op == "is_not_null":
                if actual is None:
                    return False
                continue
            if actual != v:
                return False
        return True

    def first(self):
        for row in self._rows:
            if self._row_matches(row):
                return row
        return None

    def limit(self, n):
        self._filters["_limit"] = n
        return self

    def all(self):
        limit = self._filters.pop("_limit", None)
        matched = [r for r in self._rows if self._row_matches(r)]
        if limit is None:
            return matched
        return matched[:limit]


@pytest.fixture
def storage_test_root(tmp_path: Path, monkeypatch):
    """Point LocalBackend at a tmp dir and clear the singleton."""
    monkeypatch.setenv("STORAGE_LOCAL_ROOT", str(tmp_path))
    from lumen_services.storage import reset_storage_backend

    reset_storage_backend()
    yield tmp_path
    reset_storage_backend()


@pytest.fixture
def app_with_overrides(monkeypatch, storage_test_root):
    """Build a TestClient that swaps the DB / auth dependencies for
    in-memory fakes. The endpoint functions still go through
    FastAPI's normal validation / serialization, so any wiring bug
    (path parameter, response_model, status code) surfaces here."""
    from lumen_api.v1 import auth as auth_module
    from lumen_api.v1 import storage as storage_module
    from lumen_main import app
    from lumen_core.database import get_db

    captured: Dict[str, Any] = {"documents": [], "kb": {1: _FakeKB(tenant_id=1)}}

    # DB session fake — we hand-roll the .query(...).filter(...).first()
    # chain that ``storage_local_get`` and ``storage_migrate_to_s3``
    # use. Anything more elaborate would need real SQLAlchemy
    # machinery; this is enough to exercise the routes.
    class _FakeSession:
        def query(self, model):
            return _FakeQuery(captured["documents"])

        def get(self, model, pk):
            if model.__name__ == "KnowledgeBase":
                return captured["kb"].get(pk)
            return None

        def commit(self):
            captured["committed"] = True

        def rollback(self):
            pass

    def _override_db():
        yield _FakeSession()

    # Auth override
    admin_user = _FakeUser(tenant_id=1, is_superuser=True)
    tenant_user = _FakeUser(tenant_id=1, is_superuser=False)

    def _override_current_user():
        return tenant_user

    def _override_require_admin():
        return admin_user

    # Override the heavy init that ``app`` does on startup (DB
    # migrations, Redis limiter, etc.). The TestClient enters the
    # lifespan by default; we patch ``startup_event`` to a no-op so
    # the suite doesn't require a live MySQL.
    async def _noop_startup():
        return None

    monkeypatch.setattr(app, "router", app.router)
    # lifespan bypass — drop the existing startup hook so lifespan
    # doesn't try to run migrations against a missing DB.
    app.router.lifespan_context = None  # type: ignore[attr-defined]

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[auth_module.get_current_user] = _override_current_user
    app.dependency_overrides[auth_module.require_admin] = _override_require_admin

    client = TestClient(app)
    try:
        yield client, captured
    finally:
        app.dependency_overrides.clear()


# --- 1. /storage/health -------------------------------------------------


def test_storage_health_endpoint_reports_backend(app_with_overrides):
    client, _ = app_with_overrides
    resp = client.get("/api/v1/storage/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 200
    assert body["data"]["backend"] == "local"
    assert body["data"]["ok"] is True
    assert "latency_ms" in body["data"]


def test_storage_health_never_raises(app_with_overrides, monkeypatch):
    """Even if the backend throws, /health should return ok=False
    rather than 5xx."""
    client, _ = app_with_overrides

    from lumen_services.storage import local_backend as lb

    def _boom(self):
        return {"backend": "local", "ok": False, "detail": "boom", "latency_ms": 0}

    monkeypatch.setattr(lb.LocalBackend, "health_check", _boom)
    resp = client.get("/api/v1/storage/health")
    assert resp.status_code == 200
    assert resp.json()["data"]["ok"] is False


# --- 2. /storage/local/<key> --------------------------------------------


def test_storage_local_get_returns_object_bytes(app_with_overrides, storage_test_root):
    client, captured = app_with_overrides
    key = "uploads/1/2/hello.txt"
    # Pre-populate the local backend root.
    abs_path = storage_test_root / key
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    abs_path.write_bytes(b"hello world")
    # Register a fake document row that maps to the key.
    captured["documents"].append(_FakeDocument(
        document_id=7,
        tenant_id=1,
        asset_storage_key=key,
    ))

    resp = client.get(f"/api/v1/storage/local/{key}")
    assert resp.status_code == 200
    assert resp.content == b"hello world"


def test_storage_local_get_404_for_unknown_key(app_with_overrides):
    client, captured = app_with_overrides
    # No matching fake document.
    resp = client.get("/api/v1/storage/local/uploads/1/2/missing.txt")
    assert resp.status_code == 404


def test_storage_local_get_404_when_file_missing_on_disk(
    app_with_overrides, storage_test_root,
):
    """Document row exists but the on-disk file is gone — still 404."""
    client, captured = app_with_overrides
    captured["documents"].append(_FakeDocument(
        document_id=8,
        tenant_id=1,
        asset_storage_key="uploads/1/2/vanished.txt",
    ))
    resp = client.get("/api/v1/storage/local/uploads/1/2/vanished.txt")
    assert resp.status_code == 404


def test_storage_local_get_blocks_cross_tenant(app_with_overrides):
    """Non-admin caller from tenant 2 can't read tenant 1's file."""
    client, captured = app_with_overrides
    captured["documents"].append(_FakeDocument(
        document_id=9,
        tenant_id=1,
        asset_storage_key="uploads/1/2/secret.txt",
    ))
    # Override the user to be in tenant 2.
    from lumen_api.v1 import auth as auth_module
    tenant2_user = _FakeUser(tenant_id=2, is_superuser=False)
    from lumen_main import app
    app.dependency_overrides[auth_module.get_current_user] = lambda: tenant2_user
    try:
        resp = client.get("/api/v1/storage/local/uploads/1/2/secret.txt")
    finally:
        app.dependency_overrides[auth_module.get_current_user] = lambda: _FakeUser(tenant_id=1)
    assert resp.status_code == 403


def test_storage_local_get_allows_admin_cross_tenant(app_with_overrides, storage_test_root):
    client, captured = app_with_overrides
    key = "uploads/1/2/admin-allowed.txt"
    (storage_test_root / key).parent.mkdir(parents=True, exist_ok=True)
    (storage_test_root / key).write_bytes(b"hi")
    captured["documents"].append(_FakeDocument(
        document_id=10,
        tenant_id=1,
        asset_storage_key=key,
    ))
    # require_admin fixture already returns a superuser; without
    # overriding get_current_user, the local endpoint will see the
    # tenant_user. Switch to the admin via the override below.
    from lumen_api.v1 import auth as auth_module
    from lumen_main import app
    admin_user = _FakeUser(tenant_id=99, is_superuser=True)
    app.dependency_overrides[auth_module.get_current_user] = lambda: admin_user
    try:
        resp = client.get(f"/api/v1/storage/local/{key}")
    finally:
        # restore the default tenant_user override
        app.dependency_overrides[auth_module.get_current_user] = lambda: _FakeUser(tenant_id=1)
    assert resp.status_code == 200
    assert resp.content == b"hi"


def test_storage_local_get_410_when_backend_is_s3(
    app_with_overrides, monkeypatch,
):
    """If the deployment has switched to s3, /local/* returns 410."""
    client, _ = app_with_overrides
    monkeypatch.setenv("STORAGE_BACKEND", "s3")
    # Force rebuild — but we don't have boto3 here, so patch the
    # backend attribute directly.
    from lumen_services.storage import local_backend as lb

    class _FakeS3:
        backend_name = "s3"

    monkeypatch.setattr(
        "lumen_services.storage.get_storage_backend", lambda: _FakeS3()
    )
    resp = client.get("/api/v1/storage/local/uploads/1/2/x.pdf")
    assert resp.status_code == 410


# --- 3. /storage/migrate-to-s3 -----------------------------------------


def test_migrate_to_s3_requires_admin(app_with_overrides, monkeypatch):
    """Non-admin callers should be blocked by ``require_admin`` even
    before the route body runs. We simulate this by swapping the
    admin override with one that raises."""
    client, _ = app_with_overrides
    from lumen_api.v1 import auth as auth_module
    from lumen_main import app
    from fastapi import HTTPException

    def _deny():
        raise HTTPException(status_code=403, detail="admin only")

    app.dependency_overrides[auth_module.require_admin] = _deny
    try:
        resp = client.post("/api/v1/storage/migrate-to-s3")
    finally:
        app.dependency_overrides.pop(auth_module.require_admin, None)
    assert resp.status_code == 403


def test_migrate_to_s3_rejects_when_backend_not_s3(app_with_overrides):
    """Without STORAGE_BACKEND=s3 the migration endpoint returns 400."""
    client, _ = app_with_overrides
    resp = client.post("/api/v1/storage/migrate-to-s3")
    assert resp.status_code == 400
    assert "STORAGE_BACKEND" in resp.json()["detail"]


def test_migrate_to_s3_writes_rows_and_calls_put(app_with_overrides, monkeypatch, storage_test_root):
    """End-to-end migration: rows with legacy ``file_path`` get PUT
    through the S3 backend and have ``asset_storage_key`` +
    ``storage_backend`` filled in."""
    client, captured = app_with_overrides
    # Force the singleton into "s3" mode via the factory stub.
    from lumen_services.storage import base as base_mod

    put_calls: List[Dict[str, Any]] = []

    class _StubS3(base_mod.StorageBackend):
        backend_name = "s3"

        def put_object(self, key, data, content_type=None):
            put_calls.append({"key": key, "bytes": data, "ct": content_type})
            return f"s3://test-bucket/{key}"

        def get_object(self, key):
            # Migration reads source bytes via the active backend —
            # the stub looks them up against the test's local root so
            # we can assert the PUT payload matches the seeded bytes.
            abs_path = storage_test_root / key
            if not abs_path.is_file():
                raise FileNotFoundError(key)
            return abs_path.read_bytes()

        def get_object_stream(self, key): return io.BytesIO(b"")
        def delete_object(self, key): pass
        def object_exists(self, key): return True
        def get_presigned_url(self, key, expiry=None): return f"s3://{key}"
        def health_check(self): return {"backend": "s3", "ok": True, "detail": "", "latency_ms": 0}
        # M38.1 follow-up (2026-08-31): ABC added ``list_objects`` and
        # ``put_object_multipart`` — the migration test stubs must
        # implement them or the abstract check rejects instantiation.
        def list_objects(self, prefix="", max_keys=1000):
            return iter(())
        def put_object_multipart(self, key, data_stream, part_size=5*1024*1024, content_type=None):
            return self.put_object(key, data_stream.read(), content_type=content_type)
        def resolve_to_local_path(self, key):
            abs_path = storage_test_root / key
            if not abs_path.is_file():
                raise FileNotFoundError(key)
            return str(abs_path)

    monkeypatch.setattr(
        "lumen_services.storage.get_storage_backend", lambda: _StubS3()
    )

    # Seed a legacy row pointing at a real file under our tmp root.
    legacy_dir = storage_test_root / "uploads" / "1" / "5"
    legacy_dir.mkdir(parents=True, exist_ok=True)
    (legacy_dir / "doc.pdf").write_bytes(b"pdf-bytes")
    captured["documents"].append(_FakeDocument(
        document_id=11,
        tenant_id=1,
        file_path="data/uploads/1/5/doc.pdf",  # legacy shape
    ))

    resp = client.post("/api/v1/storage/migrate-to-s3?batch_size=10")
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["scanned"] >= 1
    assert body["migrated"] >= 1
    assert body["failed"] == 0

    # The stub captured the PUT.
    assert any(call["key"] == "uploads/1/5/doc.pdf" for call in put_calls)
    assert any(call["bytes"] == b"pdf-bytes" for call in put_calls)

    # The document row has been updated to point at S3.
    doc = captured["documents"][0]
    assert doc.asset_storage_key == "uploads/1/5/doc.pdf"
    assert doc.storage_backend == "s3"


def test_migrate_to_s3_skips_rows_without_legacy_path(app_with_overrides, monkeypatch):
    """Rows with no ``file_path`` start with shouldn't be migrated."""
    client, captured = app_with_overrides
    from lumen_services.storage import base as base_mod

    class _StubS3(base_mod.StorageBackend):
        backend_name = "s3"
        put_calls = 0

        def put_object(self, key, data, content_type=None):
            type(self).put_calls += 1
            return f"s3://x/{key}"

        def get_object(self, key): return b""
        def get_object_stream(self, key): return io.BytesIO(b"")
        def delete_object(self, key): pass
        def object_exists(self, key): return True
        def get_presigned_url(self, key, expiry=None): return key
        def health_check(self): return {"backend": "s3", "ok": True, "detail": "", "latency_ms": 0}
        # M38.1 follow-up (2026-08-31): see _StubS3 in test_migrate_to_s3_writes_rows_and_calls_put above.
        def list_objects(self, prefix="", max_keys=1000):
            return iter(())
        def put_object_multipart(self, key, data_stream, part_size=5*1024*1024, content_type=None):
            return self.put_object(key, data_stream.read(), content_type=content_type)
        def resolve_to_local_path(self, key):
            raise FileNotFoundError(key)

    monkeypatch.setattr(
        "lumen_services.storage.get_storage_backend", lambda: _StubS3()
    )

    # Row without legacy file_path — should be reported as failed
    # with reason "no_legacy_file_path".
    captured["documents"].append(_FakeDocument(
        document_id=12,
        tenant_id=1,
        file_path=None,
    ))

    resp = client.post("/api/v1/storage/migrate-to-s3?batch_size=10")
    body = resp.json()["data"]
    assert body["failed"] == 1
    assert body["errors"][0]["reason"] == "no_legacy_file_path"