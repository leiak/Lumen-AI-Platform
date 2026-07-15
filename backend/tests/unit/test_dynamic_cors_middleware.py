"""DynamicCORS middleware tests — covers static allow, DB-driven allow,
60s cache, and rejection."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from lumen_core.database import SessionLocal
from lumen_core.dynamic_cors import DynamicCORSMiddleware
from lumen_models.external_app import ExternalApp
from lumen_scripts.seed_external_app import seed_dev_external_app


# Same MDL-defense fixture as Tasks 10/11/12/13 — the cache _refresh()
# opens SessionLocal; leaked Sessions could hold MDL on conversations.
# See MEMORY.md "TestClient + MDL deadlock".
@pytest.fixture(autouse=True)
def _dispose_engine_after_test():
    yield
    from lumen_core.database import engine
    import gc
    gc.collect()
    engine.dispose()


@pytest.fixture
def app():
    seed_dev_external_app()
    a = FastAPI()
    a.add_middleware(
        DynamicCORSMiddleware,
        static_origins=["http://localhost:11334"],
        cache_ttl_seconds=2,  # short TTL for test_cache_invalidation
    )
    @a.get("/ping")
    def ping():
        return {"ok": True}
    return a


def test_static_origin_allowed(app):
    client = TestClient(app)
    r = client.options("/ping", headers={
        "Origin": "http://localhost:11334",
        "Access-Control-Request-Method": "GET",
    })
    assert r.status_code in (200, 204)
    assert r.headers.get("access-control-allow-origin") == "http://localhost:11334"


def test_preflight_advertises_put(app):
    """Regression: preflight must list PUT in Allow-Methods.

    Before 2026-06-09, the hardcoded Allow-Methods list was
    "GET, POST, PATCH, DELETE, OPTIONS" — PUT was missing, so the
    browser blocked PUT /workflows/{id} (and PUT
    /workflows/{id}/schedules/{schedule_id}) with::

        Method PUT is not allowed by Access-Control-Allow-Methods
        in preflight response.

    The designer save flow uses PUT (services/workflow.ts:115), so the
    workflow designer could not save. This test pins the contract:
    whatever methods the API actually serves must be advertised in
    preflight.
    """
    client = TestClient(app)
    r = client.options("/ping", headers={
        "Origin": "http://localhost:11334",
        "Access-Control-Request-Method": "PUT",
    })
    assert r.status_code in (200, 204)
    allowed = r.headers.get("access-control-allow-methods", "")
    # Comma-separated list — be lenient about whitespace
    methods = {m.strip().upper() for m in allowed.split(",") if m.strip()}
    assert "PUT" in methods, (
        f"preflight response missing PUT in Allow-Methods: {allowed!r}"
    )


def test_db_origin_allowed(app):
    # seed_dev_app allowed_origins includes http://localhost:11337
    client = TestClient(app)
    r = client.options("/ping", headers={
        "Origin": "http://localhost:11337",
        "Access-Control-Request-Method": "GET",
    })
    assert r.headers.get("access-control-allow-origin") == "http://localhost:11337"


def test_unknown_origin_rejected(app):
    client = TestClient(app)
    r = client.options("/ping", headers={
        "Origin": "https://evil.com",
        "Access-Control-Request-Method": "GET",
    })
    # Either missing ACAO header OR set to a value other than the evil origin
    assert r.headers.get("access-control-allow-origin") != "https://evil.com"


def test_cache_invalidation(app):
    from lumen_core.dynamic_cors import get_cors_cache
    cache = get_cors_cache()
    cache.invalidate()  # start fresh

    client = TestClient(app)
    r1 = client.options("/ping", headers={
        "Origin": "http://localhost:11337", "Access-Control-Request-Method": "GET"
    })
    assert r1.headers.get("access-control-allow-origin") == "http://localhost:11337"

    # Remove the dev app's allowed origin 11337 by mutating the DB row
    db = SessionLocal()
    try:
        ext_app = db.scalar(select(ExternalApp).where(
            ExternalApp.app_key == "lc_pub_dev_demo_only_replace_in_prod"
        ))
        ext_app.allowed_origins = ["https://other.com"]
        db.commit()
    finally:
        db.close()
    cache.invalidate()  # force re-read from DB

    r2 = client.options("/ping", headers={
        "Origin": "http://localhost:11337", "Access-Control-Request-Method": "GET"
    })
    # After cache invalidate + DB change, this origin should NOT be allowed
    assert r2.headers.get("access-control-allow-origin") != "http://localhost:11337"
