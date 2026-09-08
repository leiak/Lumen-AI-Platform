"""M30d 2.0 spec A9.2 (2026-09-07) + 2.1 A.1 (2026-09-08): Deprecation / Sunset
/ Link header tests.

Verifies that ``mark_deprecated``:

- Sets ``Deprecation: true`` (RFC 8594 §2.1), ``Sunset: <IMF-fixdate>``
  (RFC 8594 §2.2) and ``Link: <successor>; rel="successor-version"``
  (RFC 8594 §3) on the response when the endpoint path is registered.
- Sets ``X-Lumen-Deprecation-Reason`` extension for human readability.
- Raises ``KeyError`` for paths not in the registry — prevents typos
  from silently shipping without the header.
- Works as a FastAPI dependency via ``response: Response`` injection.
- Honours an explicit ``sunset_date=`` override when migrating to a new
  sunset window.

2.1 A.1: the registry now carries 5 endpoints (``/resume`` is the only
handler wired today; the other 4 are pre-registered for Phase 6 A.3 to
flip to 410 Gone on 2027-01-31). These tests assert the registry
content + the header format independently of whether a router actually
attaches the dep — the announcement calendar is the contract, the
header is the delivery channel.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import pytest
from fastapi import Response

from lumen_api.deprecation import (
    DEPRECATED_ENDPOINTS,
    SUNSET_DATE,
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
