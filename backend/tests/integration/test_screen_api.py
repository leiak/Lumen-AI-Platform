"""Integration tests for the /api/v1/screen/* endpoints.

Approach: Option A (mock AggregateService).

The real AggregateService methods use MySQL-specific SQL (func.date_format,
func.json_unquote, func.json_extract, func.timestampdiff), which cannot run
on the in-memory SQLite engine used by these tests. We therefore patch the
service methods to return canned data and exercise only:
  - Pydantic Literal range validation (422 on invalid)
  - the SingleResponse envelope shape
  - the 5 endpoint paths all return 200 anonymously (no auth required since 2026-06-06)

Note: as of 2026-06-06 the screen endpoints are intentionally public (no
require_admin gate) so the operations dashboard at frontend-overview:11337
can render anonymously. The admin gate itself still exists in
app.api.v1.auth and is covered by tests/unit/test_require_admin.py.
"""
import os
import sys
from datetime import timedelta
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Allow importing app.* from this nested test directory.
BACKEND_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from lumen_main import app  # noqa: E402
from lumen_core.database import Base, get_db  # noqa: E402


# Canned data returned by the patched AggregateService methods. Keys mirror
# the real return contracts in app/services/aggregate_service.py.
_OVERVIEW = {
    "total_tenants": 1,
    "active_tenants": 1,
    "total_users": 2,
    "active_users": 1,
    "total_agents": 0,
    "total_kbs": 0,
    "total_workflows": 0,
    "total_documents": 0,
    "total_chunks": 0,
    "total_chat_messages": 0,
    "ai_calls": 0,
    "ai_errors": 0,
    "ai_error_rate": 0.0,
    "top_tenants": [],
    "data_source_note": "AI 调用统计基于 audit_logs 近似聚合",
}

_AI_CALLS = {
    "series": [
        {"ts": "2026-06-04 10:00:00", "calls": 5, "errors": 1, "avg_latency_ms": 120, "p95_latency_ms": None}
    ],
    "by_model": [
        {"model": "ollama", "calls": 5, "errors": 1, "avg_latency_ms": 120}
    ],
}

_KNOWLEDGE = {
    "total_kbs": 0,
    "total_documents": 0,
    "total_chunks": 0,
    "parse_success": 0,
    "parse_failed": 0,
    "embedding_failed": 0,
    "by_status": [],
}

_WORKFLOWS = {
    "total_workflows": 0,
    "total_runs": 0,
    "success": 0,
    "failed": 0,
    "cancelled": 0,
    "avg_duration_ms": 0,
    "by_node_type": [],
}

_TENANTS_USERS = {
    "tenant_growth": [{"ts": "2026-06-03T10:00:00Z", "count": 1}],
    "user_growth": [{"ts": "2026-06-03T10:00:00Z", "count": 2}],
    "top_active_tenants": [],
}


@pytest.fixture
def client_with_db():
    """SQLite in-memory DB with AggregateService mocked. No auth required."""
    # StaticPool + check_same_thread=False lets FastAPI's worker thread reuse
    # the same in-memory connection that the fixture created in the main thread.
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    # create_all needs Tenant and User registered with Base.metadata; we don't
    # actually need any rows since the screen endpoints no longer touch users,
    # but registering the models keeps the schema creation explicit.
    from lumen_models.tenant import Tenant  # noqa: F401
    from lumen_models.user import User  # noqa: F401
    # M32 cleanup (2026-06-17): ``app.models.wx_publisher`` uses MySQL-only
    # types (LONGTEXT / MEDIUMBLOB) that ``Base.metadata.create_all`` cannot
    # render on SQLite — the screen API tests don't touch wx_* tables at
    # all, so we exclude every wx_-prefixed table from the create_all call.
    tables = [
        t for t in Base.metadata.sorted_tables
        if not t.name.startswith("wx_")
    ]
    Base.metadata.create_all(bind=engine, tables=tables)
    SessionLocal = sessionmaker(bind=engine)

    def _override_get_db():
        s = SessionLocal()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = _override_get_db

    # Patch the AggregateService symbol that screen.py actually references.
    # The endpoint does `from lumen_services.aggregate_service import AggregateService`
    # at module load, so we must patch the bound name in screen.py's namespace.
    with patch("lumen_api.v1.screen.AggregateService") as MockSvc:
        instance = MagicMock()
        instance.overview.return_value = dict(_OVERVIEW)
        instance.ai_calls_series.return_value = dict(_AI_CALLS)
        instance.knowledge_summary.return_value = dict(_KNOWLEDGE)
        instance.workflow_summary.return_value = dict(_WORKFLOWS)
        instance.tenant_user_growth.return_value = dict(_TENANTS_USERS)
        MockSvc.return_value = instance
        # range_to_window is a static method on the real class. Pydantic's
        # Literal validation rejects invalid values before the endpoint body
        # runs, so the mock just needs to return *some* timedelta.
        MockSvc.range_to_window.return_value = timedelta(hours=24)

        # Use the no-context-manager form so FastAPI's startup_event /
        # shutdown_event are NOT fired. The workflow scheduler started in
        # startup_event has no associated event loop at TestClient teardown
        # and would otherwise raise "Event loop is closed" errors during
        # fixture teardown for every test. The screen endpoints do not
        # depend on the scheduler.
        c = TestClient(app)
        yield c

    app.dependency_overrides.clear()


def test_overview_no_auth_required(client_with_db):
    """Anonymous request must succeed (no Authorization header)."""
    c = client_with_db
    r = c.get("/api/v1/screen/overview?range=24h")
    assert r.status_code == 200
    body = r.json()
    assert body["code"] == 200
    data = body["data"]
    assert data["range"] == "24h"
    # values come from the mock, not the real DB
    assert data["total_tenants"] == 1
    assert data["ai_error_rate"] == 0.0
    assert "audit" in data["data_source_note"]


def test_overview_returns_data_unauthenticated(client_with_db):
    """Explicit empty headers also pass — guards against any future accidental
    re-introduction of an auth dependency."""
    c = client_with_db
    r = c.get("/api/v1/screen/overview?range=24h", headers={})
    assert r.status_code == 200
    assert r.json()["code"] == 200


def test_5_endpoints_return_200(client_with_db):
    c = client_with_db
    paths = (
        "/api/v1/screen/overview?range=24h",
        "/api/v1/screen/ai-calls?range=24h&granularity=hour",
        "/api/v1/screen/knowledge?range=24h",
        "/api/v1/screen/workflows?range=24h",
        "/api/v1/screen/tenants-users?range=24h",
    )
    for path in paths:
        r = c.get(path, headers={})
        assert r.status_code == 200, f"{path} -> {r.status_code} {r.text}"


def test_overview_invalid_range_returns_422(client_with_db):
    c = client_with_db
    r = c.get("/api/v1/screen/overview?range=99h")
    # Pydantic Literal validation failure -> 422
    assert r.status_code in (400, 422)
