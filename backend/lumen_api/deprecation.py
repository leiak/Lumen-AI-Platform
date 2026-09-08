"""Endpoint deprecation signals — RFC 8594 style ``Deprecation`` /
``Sunset`` / ``Link`` headers.

2.0 spec §7 (Compatibility window) declares that during the
2.0 → 2.1 compatibility period the older endpoints ship a
``Deprecation: true`` response header so operators / API consumers can
flag them in dashboards before 2.1 removes them outright. From 2.1
(2026-09-08 ship) onwards the header set is the full RFC 8594 trio:

  - ``Deprecation: true``        — boolean, RFC 8594 §2.1
  - ``Sunset: <IMF-fixdate>``    — RFC 8594 §2.2 / RFC 7231 IMF-fixdate
                                   format (e.g. ``Sun, 31 Jan 2027
                                   00:00:00 GMT``)
  - ``Link: <new-path>; rel="successor-version"``
                                 — RFC 8594 §3 — points clients at the
                                   replacement endpoint so they can
                                   migrate before the sunset date hits

Plus our extension ``X-Lumen-Deprecation-Reason`` for human-readable
explanation (browsers display the *why* without grepping the source).

This module is intentionally small — a registry of deprecated paths
plus a FastAPI dependency that injects the headers into the response.
Per-endpoint opt-in keeps the surface easy to audit (``grep -n
DEPRECATED`` lists everything that flips the bit).

Why a dependency and not middleware
-----------------------------------
Middleware would have to scan the request path against the registry on
every call. A per-endpoint dependency makes the deprecation visible in
the route definition (``dependencies=[Depends(mark_deprecated(...))]``),
so a code reviewer can spot it without reading the registry.

Sunset calendar
---------------
The ``DEPRECATED_ENDPOINTS`` registry is the single source of truth for
the sunset calendar. Five endpoints are tracked:

  - ``/resume`` — M30d ship, 2.0 compatibility window (already wired)
  - ``/chat/legacy/complete``, ``/v0/dashboard/summary``,
    ``/api/v1/wx-publisher/publish-legacy``,
    ``/api/v1/storage/local-legacy/{key}``,
    ``/api/v1/image-generation/legacy``
    — pre-registered in 2.1 (2026-09-08), to be wired + flipped to
      ``410 Gone`` at the 2027-01-31 Sunset fire (Phase 6 A.3). The
      registry is the announcement channel today; the
      ``Link: <new-path>; rel="successor-version"`` header tells API
      consumers where to migrate before that date.
"""
from __future__ import annotations

from datetime import datetime, timezone
from email.utils import format_datetime
from typing import Dict, Optional

from fastapi import Response


# 2.0 spec §3.1 兼容期终点 → 所有旧 endpoint 在该日期切 410 Gone。
SUNSET_DATE = "2027-01-31"


def _to_imf_fixdate(date_str: str) -> str:
    """``YYYY-MM-DD`` → RFC 7231 IMF-fixdate (RFC 8594 §2.2 要求格式)。

    例子:``"2027-01-31"`` → ``"Sun, 31 Jan 2027 00:00:00 GMT"``。
    时间统一取 UTC 0:00,与公告的"Sunset fire @ 2027-01-31 0:00 UTC"
    口径一致。
    """
    dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    # email.utils.format_datetime 输出形如 ``Sun, 31 Jan 2027 00:00:00 GMT``
    # —— RFC 7231 IMF-fixdate,符合 RFC 8594 §2.2 强制要求。
    return format_datetime(dt, usegmt=True)


# 路径 → 描述 dict。key = endpoint 路径(包含前缀);value 字段:
#   reason   — 人类可读的弃用原因(写入 X-Lumen-Deprecation-Reason header)
#   sunset_date — ``YYYY-MM-DD`` 形式,Sunset fire 日期(2027-01-31)
#   successor   — 替代 endpoint 路径(RFC 8594 §3 Link header 用,
#                 可选 — 部分 endpoint 没有直接替代)
#
# 注册一条 entry 就意味着两条承诺:
#   1. 任何挂着 ``mark_deprecated(<path>)`` 的 endpoint 都自动 emit
#      Deprecation / Sunset / Link 三件套 header。
#   2. 2027-01-31 当天 Phase 6 A.3 会把 endpoint 改成 ``410 Gone`` 并
#      删除 entry —— 这是 shipping contract 的硬约束。
DEPRECATED_ENDPOINTS: Dict[str, Dict[str, str]] = {
    # M30d 2.0 (2026-09-07): /resume ships with Deprecation: true during
    # the 2.0 compatibility window. Prefer /continue which skips
    # status=completed nodes (saves downstream LLM calls). /resume is
    # kept for clients that explicitly want "retry the whole DAG with
    # the same input_data" semantics.
    "/workflows/{workflow_id}/runs/{run_id}/resume": {
        "reason": (
            "Use POST /workflows/{workflow_id}/runs/{run_id}/continue "
            "instead. /resume re-runs the whole DAG; /continue skips "
            "status=completed nodes. Behaviour is identical only when "
            "the old run had zero completed nodes."
        ),
        "sunset_date": SUNSET_DATE,
        "successor": "/workflows/{workflow_id}/runs/{run_id}/continue",
    },
    # 2.1 (2026-09-08): pre-registered for Phase 6 A.3 Sunset fire
    # 2027-01-31. /chat/legacy/complete is the pre-2.0 single-turn
    # completion endpoint; replaced by /chat/messages streaming +
    # tool-calling in 2.0. No direct successor (clients should adopt
    # the streaming /messages flow), so the Link header is omitted.
    "/chat/legacy/complete": {
        "reason": (
            "Legacy single-turn /complete endpoint removed in 2.1. "
            "Use POST /chat/messages for streaming multi-turn "
            "conversations (see docs/modules/chat.md §3)."
        ),
        "sunset_date": SUNSET_DATE,
        "successor": "/chat/messages",
    },
    # 2.1: pre-2.0 dashboard summary; replaced by /v1/dashboard/summary
    # which adds workspace / multimodal / cost aggregations.
    "/v0/dashboard/summary": {
        "reason": (
            "Legacy v0 dashboard summary endpoint removed in 2.1. "
            "Use GET /v1/dashboard/summary for the current aggregation "
            "(includes workspace, multimodal KB, and LLM cost "
            "breakdowns added in 2.0)."
        ),
        "sunset_date": SUNSET_DATE,
        "successor": "/v1/dashboard/summary",
    },
    # 2.1: pre-2.0 wx-publisher publish endpoint; replaced by
    # /api/v1/wx-publisher/drafts/{id}/publish which adds image picker
    # + AI rewrite + draft versioning.
    "/api/v1/wx-publisher/publish-legacy": {
        "reason": (
            "Legacy publish endpoint removed in 2.1. Use POST "
            "/api/v1/wx-publisher/drafts/{id}/publish for the current "
            "flow (image picker + AI rewrite + draft versioning)."
        ),
        "sunset_date": SUNSET_DATE,
        "successor": "/api/v1/wx-publisher/drafts/{id}/publish",
    },
    # 2.1: pre-M38.1 raw local storage proxy; replaced by the
    # storage-backend-agnostic /api/v1/storage/{key:path} endpoint
    # which routes through the active backend (local or S3/MinIO).
    "/api/v1/storage/local-legacy/{key}": {
        "reason": (
            "Legacy local-only storage proxy removed in 2.1. Use GET "
            "/api/v1/storage/{key:path} which dispatches to the active "
            "STORAGE_BACKEND (local / S3 / MinIO)."
        ),
        "sunset_date": SUNSET_DATE,
        "successor": "/api/v1/storage/{key}",
    },
    # 2.1: pre-2.0 image-generation single-shot endpoint; replaced by
    # the v2 /image-generation/generate flow with multimodal support
    # + stock-asset picker + per-image cost tracking.
    "/api/v1/image-generation/legacy": {
        "reason": (
            "Legacy image-generation endpoint removed in 2.1. Use "
            "POST /api/v1/image-generation/generate for the v2 flow "
            "(multimodal model + stock picker + cost tracking)."
        ),
        "sunset_date": SUNSET_DATE,
        "successor": "/api/v1/image-generation/generate",
    },
}


def mark_deprecated(endpoint_path: str, sunset_date: Optional[str] = None):
    """Return a FastAPI dependency that sets the full RFC 8594 trio of
    deprecation headers (``Deprecation`` / ``Sunset`` / ``Link``) plus
    the Lumen extension ``X-Lumen-Deprecation-Reason``.

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
        sunset_date: optional ``YYYY-MM-DD`` override. When ``None``
            (default), uses the entry's ``sunset_date`` field from the
            registry. Pass a different date only when migrating to a
            new sunset window without editing the registry entry (e.g.
            emergency pull-forward).

    Returns:
        A FastAPI dependency callable that mutates ``response.headers``.
    """
    if endpoint_path not in DEPRECATED_ENDPOINTS:
        # Fail fast at import / dep-resolution time rather than silently
        # shipping a non-deprecated endpoint. Matches the spec's "every
        # 2.0 → 2.1 sunset is announced via Deprecation header" rule.
        raise KeyError(
            f"Endpoint {endpoint_path!r} is not registered as deprecated. "
            f"Add it to lumen_api.deprecation.DEPRECATED_ENDPOINTS first."
        )
    entry = DEPRECATED_ENDPOINTS[endpoint_path]
    reason = entry["reason"]
    effective_sunset_date = sunset_date or entry["sunset_date"]
    sunset_fixdate = _to_imf_fixdate(effective_sunset_date)
    successor = entry.get("successor")

    def _set_deprecation_headers(response: Response) -> None:
        # RFC 8594 §2.1: boolean Deprecation header.
        response.headers["Deprecation"] = "true"
        # RFC 8594 §2.2: Sunset header MUST be RFC 7231 IMF-fixdate.
        # 客户端(API 网关 / 监控)能直接 parse 不用 custom logic。
        response.headers["Sunset"] = sunset_fixdate
        # RFC 8594 §3: Link header rel=successor-version —— 客户端在
        # Sunset fire 之前有 5 个月窗口迁移,这个 header 是 machine-
        # readable 的迁移指引(浏览器 / SDK 可自动 rewrite)。
        if successor:
            # Link 值用尖括号包 URL,rel 属性引号,逗号分隔参数。
            # 例子: ``</api/v1/chat/messages>; rel="successor-version"``
            response.headers["Link"] = (
                f'<{successor}>; rel="successor-version"'
            )
        # Lumen 扩展:人类可读原因,浏览器 devtools 直接看到。
        response.headers["X-Lumen-Deprecation-Reason"] = reason

    return _set_deprecation_headers
