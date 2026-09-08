"""M30d 2.0 spec A9.2 (2026-09-07) + 2.1 A.1 (2026-09-08): Deprecation / Sunset
/ Link header tests.

Verifies that:

- ``mark_deprecated`` (per-endpoint dependency) sets ``Deprecation: true``
  (RFC 8594 §2.1), ``Sunset: <IMF-fixdate>`` (RFC 8594 §2.2) and
  ``Link: <successor>; rel="successor-version"`` (RFC 8594 §3) on the
  response when the endpoint path is registered.
- ``DeprecationHeadersMiddleware`` (primary delivery channel) injects
  the same header set on every response — including HTTPException paths
  (401/403/404) where the dependency's ``response: Response`` injection
  is dropped by FastAPI.
- Raises ``KeyError`` for paths not in the registry — prevents typos
  from silently shipping without the header.
- Works as a FastAPI dependency via ``response: Response`` injection.
- Honours an explicit ``sunset_date=`` override when migrating to a new
  sunset window.

2.1 A.1: the registry now carries 6 paths (``/resume`` is the only
handler wired today; the other 5 are pre-registered for Phase 6 A.3 to
flip to 410 Gone on 2027-01-31). These tests assert the registry
content + the header format independently of whether a router actually
attaches the dep — the announcement calendar is the contract, the
middleware is the delivery channel.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import pytest
from fastapi import Depends, FastAPI, HTTPException, Response
from fastapi.testclient import TestClient

from lumen_api.deprecation import (
    DEPRECATED_ENDPOINTS,
    SUNSET_DATE,
    DeprecationHeadersMiddleware,
    mark_deprecated,
)


# RFC 7231 IMF-fixdate example: ``Sun, 31 Jan 2027 00:00:00 GMT``.
# RFC 8594 §2.2 mandates this exact format for the Sunset header.
IMF_FIXDATE_RE = re.compile(
    r"^(Mon|Tue|Wed|Thu|Fri|Sat|Sun), "
    r"\d{2} (Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) \d{4} "
    r"\d{2}:\d{2}:\d{2} GMT$"
)


# ---------------------------------------------------------------------------
# Registry content
# ---------------------------------------------------------------------------


def test_registry_contains_resume():
    """/resume MUST be in the registry — it's the only 2.0 sunset."""
    assert (
        "/workflows/{workflow_id}/runs/{run_id}/resume"
        in DEPRECATED_ENDPOINTS
    )


def test_registry_does_not_contain_continue():
    """Sanity: /continue is the modern replacement and is NOT deprecated."""
    assert (
        "/workflows/{workflow_id}/runs/{run_id}/continue"
        not in DEPRECATED_ENDPOINTS
    )


@pytest.mark.parametrize(
    "path",
    [
        "/workflows/{workflow_id}/runs/{run_id}/resume",
        "/chat/legacy/complete",
        "/v0/dashboard/summary",
        "/api/v1/wx-publisher/publish-legacy",
        "/api/v1/storage/local-legacy/{key}",
        "/api/v1/image-generation/legacy",
    ],
)
def test_registry_contains_all_announced_sunset_endpoints(path):
    """2.1 A.1: 5+1 deprecated endpoints in the sunset calendar.

    The 5 Phase-6-A.3 endpoints are pre-registered (announcement
    channel) — they don't have handlers yet, but they're on the public
    Sunset calendar so operators can plan migration.
    """
    assert path in DEPRECATED_ENDPOINTS
    entry = DEPRECATED_ENDPOINTS[path]
    # Each entry must carry the three contract fields.
    assert "reason" in entry and entry["reason"], f"{path} missing reason"
    assert (
        entry["sunset_date"] == SUNSET_DATE
    ), f"{path} sunset_date must equal {SUNSET_DATE}"


def test_sunset_date_is_2027_01_31():
    """Sunset fire date is 2.0 spec §3.1 hard constraint — 5 months
    after 2.1 plan start (2026-09-07), giving API consumers a window
    to migrate."""
    assert SUNSET_DATE == "2027-01-31"


# ---------------------------------------------------------------------------
# Header emission
# ---------------------------------------------------------------------------


def test_mark_deprecated_sets_full_header_trio():
    """/resume emits Deprecation + Sunset + Link + X-Lumen-Deprecation-Reason."""
    dep = mark_deprecated(
        "/workflows/{workflow_id}/runs/{run_id}/resume"
    )
    response = Response()
    dep(response)

    # RFC 8594 §2.1 — boolean Deprecation.
    assert response.headers["Deprecation"] == "true"

    # RFC 8594 §2.2 — Sunset in RFC 7231 IMF-fixdate.
    sunset = response.headers["Sunset"]
    assert IMF_FIXDATE_RE.match(sunset), (
        f"Sunset header must be IMF-fixdate, got {sunset!r}"
    )
    # The actual date must parse to 2027-01-31 00:00:00 UTC.
    parsed = parsedate_to_datetime(sunset)
    assert parsed == datetime(2027, 1, 31, 0, 0, 0, tzinfo=timezone.utc)

    # RFC 8594 §3 — Link header with rel=successor-version.
    link = response.headers["Link"]
    assert "/continue" in link
    assert 'rel="successor-version"' in link
    # Successor path is wrapped in angle brackets per RFC 8288.
    assert "</workflows/{workflow_id}/runs/{run_id}/continue>" in link

    # Lumen extension — human-readable reason.
    reason = response.headers["X-Lumen-Deprecation-Reason"]
    assert "continue" in reason.lower()


def test_mark_deprecated_legacy_endpoint_emits_link():
    """Pre-registered Phase 6 endpoints emit the same header trio.

    Even though they don't have handlers yet, the registry entries are
    wired correctly — Phase 6 just attaches ``Depends(mark_deprecated(...))``
    to the new handler and the headers light up.
    """
    dep = mark_deprecated("/chat/legacy/complete")
    response = Response()
    dep(response)
    assert response.headers["Deprecation"] == "true"
    assert IMF_FIXDATE_RE.match(response.headers["Sunset"])
    # /chat/legacy/complete → /chat/messages
    assert "/chat/messages" in response.headers["Link"]
    assert 'rel="successor-version"' in response.headers["Link"]


def test_mark_deprecated_unknown_path_raises_keyerror():
    """A typo in the endpoint path must fail fast, not silently pass."""
    with pytest.raises(KeyError) as exc_info:
        mark_deprecated("/workflows/{workflow_id}/runs/{run_id}/resum")  # typo
    assert "not registered" in str(exc_info.value)


def test_mark_deprecated_idempotent_set_headers():
    """Calling the dep twice is safe — same values, no duplicate keys."""
    dep = mark_deprecated(
        "/workflows/{workflow_id}/runs/{run_id}/resume"
    )
    response = Response()
    dep(response)
    dep(response)
    assert response.headers.get("Deprecation") == "true"
    assert response.headers.get("Sunset") is not None
    assert response.headers.get("Link") is not None


def test_mark_deprecated_sunset_date_override():
    """sunset_date= override lets ops pull-forward without editing the
    registry entry (e.g. emergency CVE pull)."""
    dep = mark_deprecated(
        "/workflows/{workflow_id}/runs/{run_id}/resume",
        sunset_date="2026-12-01",
    )
    response = Response()
    dep(response)
    sunset = response.headers["Sunset"]
    parsed = parsedate_to_datetime(sunset)
    assert parsed == datetime(2026, 12, 1, 0, 0, 0, tzinfo=timezone.utc)


def test_mark_deprecated_no_successor_omits_link():
    """If a registry entry has no successor, the Link header is omitted
    (some endpoints have no direct replacement — clients must adopt a
    new flow, not just a new path)."""
    # All 5 current entries happen to have successors, so we
    # synthesize an entry without one via monkeypatch.
    from lumen_api import deprecation as dep_module

    original = dep_module.DEPRECATED_ENDPOINTS.copy()
    dep_module.DEPRECATED_ENDPOINTS["/test/no-successor"] = {
        "reason": "test reason",
        "sunset_date": SUNSET_DATE,
        # no successor key
    }
    try:
        dep = dep_module.mark_deprecated("/test/no-successor")
        response = Response()
        dep(response)
        assert response.headers["Deprecation"] == "true"
        assert response.headers["Sunset"] is not None
        # Link header is omitted when no successor.
        assert "Link" not in response.headers
    finally:
        dep_module.DEPRECATED_ENDPOINTS.clear()
        dep_module.DEPRECATED_ENDPOINTS.update(original)


# ---------------------------------------------------------------------------
# Middleware delivery channel
# ---------------------------------------------------------------------------
#
# 2.1 A.1 (2026-09-08): the middleware is the primary delivery channel
# because FastAPI drops ``response: Response`` injection when the path
# function raises HTTPException. The migration window is most valuable
# exactly when the request can't succeed (401/403/404) — those are the
# calls where the consumer needs the warning most.


def _make_test_app() -> FastAPI:
    """Build a minimal FastAPI app with the deprecation middleware."""
    app = FastAPI()
    app.add_middleware(DeprecationHeadersMiddleware)

    @app.get("/legacy/ok")
    async def legacy_ok():
        return {"ok": True}

    @app.get("/legacy/error")
    async def legacy_error():
        raise HTTPException(status_code=404, detail="not found")

    @app.get("/legacy/forbidden")
    async def legacy_forbidden():
        raise HTTPException(status_code=403, detail="forbidden")

    @app.get("/modern/ok")
    async def modern_ok():
        return {"ok": True}

    @app.get(
        "/workflows/{workflow_id}/runs/{run_id}/resume",
        dependencies=[Depends(mark_deprecated(
            "/workflows/{workflow_id}/runs/{run_id}/resume"
        ))],
    )
    async def wf_resume(workflow_id: int, run_id: int):
        raise HTTPException(status_code=404, detail="not found")

    return app


@pytest.fixture
def deprecation_app():
    """Register test routes + middleware for the duration of a test.

    We use synthetic paths (/legacy/*) since adding real Phase 6
    endpoints to the registry just for tests would conflict with the
    sunset-calendar contract. The test patches the registry to point
    at the synthetic paths, runs the middleware, then restores.
    """
    from lumen_api import deprecation as dep_module

    original = {
        path: dict(entry) for path, entry in dep_module.DEPRECATED_ENDPOINTS.items()
    }
    # Re-key synthetic paths to test entries.
    dep_module.DEPRECATED_ENDPOINTS.clear()
    dep_module.DEPRECATED_ENDPOINTS.update({
        "/legacy/ok": {
            "reason": "test legacy ok reason",
            "sunset_date": SUNSET_DATE,
            "successor": "/modern/ok",
        },
        "/legacy/error": {
            "reason": "test legacy error reason",
            "sunset_date": SUNSET_DATE,
            "successor": "/modern/ok",
        },
        "/legacy/forbidden": {
            "reason": "test legacy forbidden reason",
            "sunset_date": SUNSET_DATE,
            "successor": "/modern/ok",
        },
        # Resume route — used by test_wf_resume_compat_double_emission.
        "/workflows/{workflow_id}/runs/{run_id}/resume": original[
            "/workflows/{workflow_id}/runs/{run_id}/resume"
        ],
    })
    # Recompile the cached patterns after registry mutation.
    import re as _re
    dep_module._COMPILED_DEPRECATED = tuple(
        (dep_module._compile_pattern(path), entry)
        for path, entry in dep_module.DEPRECATED_ENDPOINTS.items()
    )
    try:
        yield _make_test_app()
    finally:
        dep_module.DEPRECATED_ENDPOINTS.clear()
        dep_module.DEPRECATED_ENDPOINTS.update(original)
        dep_module._COMPILED_DEPRECATED = tuple(
            (dep_module._compile_pattern(path), entry)
            for path, entry in dep_module.DEPRECATED_ENDPOINTS.items()
        )


def test_middleware_injects_headers_on_ok_response(deprecation_app):
    """Middleware runs on the happy path too — every response gets
    the Sunset trio."""
    client = TestClient(deprecation_app)
    r = client.get("/legacy/ok")
    assert r.status_code == 200
    assert r.headers["Deprecation"] == "true"
    assert "Sun, 31 Jan 2027" in r.headers["Sunset"]
    assert "/modern/ok" in r.headers["Link"]
    assert 'rel="successor-version"' in r.headers["Link"]
    assert "test legacy ok reason" in r.headers["X-Lumen-Deprecation-Reason"]


def test_middleware_injects_headers_on_httpexception(deprecation_app):
    """HTTPException 404: the dependency's response injection is
    discarded, but the middleware injects headers on the final
    HTTPException response. This is the core 2.1 A.1 motivation."""
    client = TestClient(deprecation_app)
    r = client.get("/legacy/error")
    assert r.status_code == 404
    assert r.headers["Deprecation"] == "true"
    assert "2027" in r.headers["Sunset"]
    assert "/modern/ok" in r.headers["Link"]
    assert "test legacy error reason" in r.headers["X-Lumen-Deprecation-Reason"]


def test_middleware_injects_headers_on_403(deprecation_app):
    """HTTPException 403: same as 404 — middleware still injects."""
    client = TestClient(deprecation_app)
    r = client.get("/legacy/forbidden")
    assert r.status_code == 403
    assert r.headers["Deprecation"] == "true"
    assert "2027" in r.headers["Sunset"]


def test_middleware_skips_non_deprecated_paths(deprecation_app):
    """Modern (non-deprecated) endpoints get no deprecation headers."""
    client = TestClient(deprecation_app)
    r = client.get("/modern/ok")
    assert r.status_code == 200
    assert "Deprecation" not in r.headers
    assert "Sunset" not in r.headers
    assert "Link" not in r.headers
    assert "X-Lumen-Deprecation-Reason" not in r.headers


def test_middleware_pattern_matches_path_params(deprecation_app):
    """Path-param placeholders in registry entries are matched as
    ``[^/]+`` so /workflows/123/runs/456/resume hits the
    ``/workflows/{workflow_id}/runs/{run_id}/resume`` entry."""
    client = TestClient(deprecation_app)
    r = client.get("/workflows/42/runs/7/resume")
    assert r.status_code == 404  # handler raises
    assert r.headers["Deprecation"] == "true"
    assert "/continue" in r.headers["Link"]


def test_wf_resume_dependency_plus_middleware_compatible(deprecation_app):
    """Both delivery channels (dep + middleware) write the same headers
    idempotently. This is the real /resume endpoint pattern: handler
    carries the dep (visibility) + middleware catches HTTPException."""
    client = TestClient(deprecation_app)
    r = client.get("/workflows/99/runs/1/resume")
    assert r.status_code == 404
    # Headers present exactly once (no duplicate values).
    assert r.headers.get_list("Deprecation") == ["true"]
    assert len(r.headers.get_list("Sunset")) == 1
    assert len(r.headers.get_list("Link")) == 1
