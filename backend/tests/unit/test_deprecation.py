"""M30d 2.0 spec A9.2 (2026-09-07): Deprecation header tests.

Verifies that ``mark_deprecated``:

- Sets ``Deprecation: true`` and ``X-Lumen-Deprecation-Reason`` on the
  response when the endpoint path is registered.
- Raises ``KeyError`` for paths not in the registry — prevents typos
  from silently shipping without the header.
- Works as a FastAPI dependency via ``response: Response`` injection.

These tests don't spin up a full FastAPI app; the dependency body is a
plain function that mutates ``response.headers``, which is what the
real handler receives from FastAPI's dependency injection.
"""
from __future__ import annotations

import pytest
from fastapi import Response

from lumen_api.deprecation import DEPRECATED_ENDPOINTS, mark_deprecated


def test_registry_contains_resume():
    """/resume MUST be in the registry — it's the only 2.0 sunset."""
    assert (
        "/workflows/{workflow_id}/runs/{run_id}/resume" in DEPRECATED_ENDPOINTS
    )


def test_registry_contains_continue():
    """Sanity: /continue is the modern replacement and is NOT deprecated."""
    assert (
        "/workflows/{workflow_id}/runs/{run_id}/continue"
        not in DEPRECATED_ENDPOINTS
    )


def test_mark_deprecated_sets_headers():
    dep = mark_deprecated(
        "/workflows/{workflow_id}/runs/{run_id}/resume"
    )
    response = Response()
    dep(response)
    assert response.headers["Deprecation"] == "true"
    assert "continue" in response.headers["X-Lumen-Deprecation-Reason"].lower()


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
    # ``headers`` is a multidict-like; verify value is still "true".
    assert response.headers.get("Deprecation") == "true"
