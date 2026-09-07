"""Endpoint deprecation signals — RFC 8594 style ``Deprecation`` header.

M30d 2.0 spec A9.2 / 2.0 spec §7 (Compatibility window) declares that
during the 2.0 compatibility period the older endpoints ship a
``Deprecation: true`` response header so operators / API consumers can
flag them in dashboards before 2.1 removes them outright.

This module is intentionally small — a registry of deprecated paths
plus a FastAPI dependency that injects the header into the response.
Per-endpoint opt-in keeps the surface easy to audit (``grep -n
DEPRECATED`` lists everything that flips the bit).

Why a dependency and not middleware
-----------------------------------
Middleware would have to scan the request path against the registry on
every call. A per-endpoint dependency makes the deprecation visible in
the route definition (``dependencies=[Depends(mark_deprecated(...))]``),
so a code reviewer can spot it without reading the registry. The
``/resume`` endpoint is the only one currently marked; new ones are
added by importing this module and adding the dep to the route.
"""
from __future__ import annotations

from typing import Dict

from fastapi import Response


# Path → human-readable deprecation reason. The key matches the
# endpoint path exactly (including the prefix). When 2.1 lands, the
# entry is removed and the endpoint either stays (deprecation header
# was the only signal) or gets deleted.
DEPRECATED_ENDPOINTS: Dict[str, str] = {
    # M30d 2.0 (2026-09-07): /resume ships with Deprecation: true during
    # the 2.0 compatibility window. Prefer /continue which skips
    # status=completed nodes (saves downstream LLM calls). /resume is
    # kept for clients that explicitly want "retry the whole DAG with
    # the same input_data" semantics.
    "/workflows/{workflow_id}/runs/{run_id}/resume": (
        "Use POST /workflows/{workflow_id}/runs/{run_id}/continue instead. "
        "/resume re-runs the whole DAG; /continue skips status=completed "
        "nodes. Behaviour is identical only when the old run had zero "
        "completed nodes."
    ),
}


def mark_deprecated(endpoint_path: str):
    """Return a FastAPI dependency that sets ``Deprecation: true`` + a
    ``Sunset`` header on the response.

    Usage in a router::

        from .deprecation import mark_deprecated

        @router.post(
            "/foo",
            dependencies=[Depends(mark_deprecated("/foo"))],
        )
        async def foo(...): ...

    Args:
        endpoint_path: the canonical path registered in
            :data:`DEPRECATED_ENDPOINTS`. Passed as a string literal so
            the registry stays the single source of truth — a typo here
            raises ``KeyError`` immediately at module import time
            (cheaper than waiting for the first request).
    """
    if endpoint_path not in DEPRECATED_ENDPOINTS:
        # Fail fast at import / dep-resolution time rather than silently
        # shipping a non-deprecated endpoint. Matches the spec's "every
        # 2.0 → 2.1 sunset is announced via Deprecation header" rule.
        raise KeyError(
            f"Endpoint {endpoint_path!r} is not registered as deprecated. "
            f"Add it to lumen_api.deprecation.DEPRECATED_ENDPOINTS first."
        )
    reason = DEPRECATED_ENDPOINTS[endpoint_path]

    def _set_deprecation_headers(response: Response) -> None:
        # RFC 8594: ``Deprecation: true`` is the boolean form. ``Sunset``
        # would carry the actual removal date once 2.1 ships — left out
        # today because the sunset date isn't pinned yet (tracked in
        # the 2.1 release spec). ``X-Lumen-Deprecation-Reason`` is our
        # extension so humans reading the response in a browser can see
        # *why* without grepping the source.
        response.headers["Deprecation"] = "true"
        response.headers["X-Lumen-Deprecation-Reason"] = reason

    return _set_deprecation_headers
