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

How delivery works (two layers)
-------------------------------
We **don't** rely on a router-level ``Depends(mark_deprecated(...))``
alone because FastAPI discards response headers set via
``response: Response`` injection when the path handler raises
``HTTPException`` (e.g. 401/403/404 from auth or permission checks).
That's exactly when API consumers **most need** the Sunset warning —
their request can't even reach the handler. So:

  1. **Middleware** (``DeprecationHeadersMiddleware``) — scans every
     response (including HTTPException paths) and injects headers when
     the request path matches a registry entry. This is the primary
     delivery channel. Wired in ``lumen_main.py:app.add_middleware(...)``
     once at app boot.

  2. **Dependency** (``mark_deprecated(path)``) — kept for two reasons:
     (a) per-endpoint code visibility (``grep mark_deprecated`` lists
     deprecated endpoints in code review without cross-referencing the
     middleware); (b) handler-level override of the Sunset date (e.g.
     emergency pull-forward). Today only ``/resume`` is wired; the 5
     pre-registered entries get headers via middleware automatically.

Sunset calendar
---------------
The ``DEPRECATED_ENDPOINTS`` registry is the single source of truth for
the sunset calendar. Six paths are tracked:

  - ``/workflows/{id}/runs/{id}/resume`` — M30d 2.0 ship (handler wired)
  - ``/chat/legacy/complete``, ``/v0/dashboard/summary``,
    ``/api/v1/wx-publisher/publish-legacy``,
    ``/api/v1/storage/local-legacy/{key}``,
    ``/api/v1/image-generation/legacy`` — pre-registered in 2.1
    (2026-09-08), to be wired + flipped to ``410 Gone`` at the
    2027-01-31 Sunset fire (Phase 6 A.3). The registry is the
    announcement channel today; middleware lights up the headers
    automatically when those paths come online.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from email.utils import format_datetime
from typing import Dict, Iterable, Optional, Tuple

from fastapi import Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.types import ASGIApp


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


# 路径 → 描述 dict。key = endpoint 路径模板(包含前缀);value 字段:
#   reason   — 人类可读的弃用原因(写入 X-Lumen-Deprecation-Reason header)
#   sunset_date — ``YYYY-MM-DD`` 形式,Sunset fire 日期(2027-01-31)
#   successor   — 替代 endpoint 路径(RFC 8594 §3 Link header 用,
#                 可选 — 部分 endpoint 没有直接替代)
#
# 注册一条 entry 就意味着两条承诺:
#   1. middleware 自动给匹配 path 的所有 response(含 HTTPException)
#      发 Deprecation / Sunset / Link 三件套 header。
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
    # tool-calling in 2.0.
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


def _compile_pattern(path_template: str) -> re.Pattern:
    """把 ``{workflow_id}`` 之类 path-param 占位符编译成 regex。

    例:``"/workflows/{workflow_id}/runs/{run_id}/resume"`` →
    ``^/workflows/[^/]+/runs/[^/]+/resume$``。
    """
    # 先把 path-param 替成 sentinel(避免与 regex 特殊字符冲突),再替成
    # ``[^/]+``,最后重新组装。
    parts = re.split(r"(\{[^}]+\})", path_template)
    pattern = "".join(
        "[^/]+" if part.startswith("{") else re.escape(part)
        for part in parts
    )
    return re.compile(f"^{pattern}$")


# 预编译 regex patterns + entry —— middleware O(N) 但 N 很小(目前 6)。
_COMPILED_DEPRECATED: Tuple[Tuple[re.Pattern, Dict[str, str]], ...] = tuple(
    (_compile_pattern(path), entry)
    for path, entry in DEPRECATED_ENDPOINTS.items()
)


def _lookup_deprecated(request_path: str) -> Optional[Dict[str, str]]:
    """返回第一个匹配的 registry entry(理论上一个 path 只命中一个 entry)"""
    for pattern, entry in _COMPILED_DEPRECATED:
        if pattern.match(request_path):
            return entry
    return None


def _build_headers(
    entry: Dict[str, str], sunset_date: Optional[str] = None
) -> Dict[str, str]:
    """根据 registry entry 构造 RFC 8594 三件套 + 扩展 header。"""
    effective_sunset_date = sunset_date or entry["sunset_date"]
    headers: Dict[str, str] = {
        "Deprecation": "true",
        "Sunset": _to_imf_fixdate(effective_sunset_date),
    }
    successor = entry.get("successor")
    if successor:
        # RFC 8288: Link value 用尖括号包 URL,rel 属性引号。
        # 例: ``</api/v1/chat/messages>; rel="successor-version"``
        headers["Link"] = f'<{successor}>; rel="successor-version"'
    headers["X-Lumen-Deprecation-Reason"] = entry["reason"]
    return headers


class DeprecationHeadersMiddleware(BaseHTTPMiddleware):
    """Inject RFC 8594 Sunset headers on responses to deprecated paths.

    Wired in ``lumen_main.py``. Runs on **every** response — including
    HTTPException responses (401/403/404 etc.) — so API consumers see
    the Sunset warning even when their request fails pre-handler (e.g.
    before auth/scope checks). That's intentional: the migration window
    is most valuable when the request itself can't succeed.

    Header emission is a single dict-merge on the response; cost is
    negligible (~µs per request). The middleware only does work when
    the path matches a registry entry (linear scan over ~6 patterns).

    Path matching
    -------------
    Registry entries are **router-relative** (e.g.
    ``/workflows/{workflow_id}/runs/{run_id}/resume``) — that's the
    form the ``mark_deprecated(path)`` dependency expects, matching
    the FastAPI router convention. But ``request.url.path`` carries the
    full mount-prefixed path (e.g.
    ``/api/v1/workflows/1/runs/1/resume``) because the v1 router is
    mounted under ``/api/v1``. We strip the known mount prefix
    (``/api/v1``) before lookup; if the path doesn't start with that
    prefix (e.g. dev-only routes), we try the path as-is. Registry
    entries without the prefix stay the single source of truth.
    """

    _MOUNT_PREFIX = "/api/v1"

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        response = await call_next(request)
        # 优先看带 prefix 的 path(实际请求 path);fallback 到 router-relative。
        # 双查找兼容:dev 环境直接挂 /workflows/... (无 /api/v1/) 也命中。
        full_path = request.url.path
        candidates = [full_path]
        if full_path.startswith(self._MOUNT_PREFIX + "/"):
            candidates.append(full_path[len(self._MOUNT_PREFIX):])
        elif full_path == self._MOUNT_PREFIX:
            candidates.append("/")
        for path in candidates:
            entry = _lookup_deprecated(path)
            if entry is not None:
                for header_name, header_value in _build_headers(entry).items():
                    response.headers[header_name] = header_value
                break
        return response


def mark_deprecated(endpoint_path: str, sunset_date: Optional[str] = None):
    """Return a FastAPI dependency that sets the full RFC 8594 trio of
    deprecation headers (``Deprecation`` / ``Sunset`` / ``Link``) plus
    the Lumen extension ``X-Lumen-Deprecation-Reason``.

    Note: in 2.1 (2026-09-08) the middleware is the primary delivery
    channel — this dependency is kept for **two reasons**:

    1. Per-endpoint code visibility (``grep mark_deprecated`` lists
       deprecated endpoints in code review, no need to cross-reference
       the middleware).
    2. When a handler wants to override the Sunset date (e.g. emergency
       pull-forward to an earlier date).

    **Caveat**: this dep's ``response: Response`` injection does NOT
    survive ``HTTPException`` raised inside the path function (FastAPI
    builds a fresh response). For HTTPException safety, the middleware
    is the backstop — both write the same headers idempotently.

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
            raises ``KeyError`` immediately at module import time.
        sunset_date: optional ``YYYY-MM-DD`` override. When ``None``
            (default), uses the entry's ``sunset_date`` field.

    Returns:
        A FastAPI dependency callable that mutates ``response.headers``.
    """
    if endpoint_path not in DEPRECATED_ENDPOINTS:
        # Fail fast at import / dep-resolution time rather than silently
        # shipping a non-deprecated endpoint.
        raise KeyError(
            f"Endpoint {endpoint_path!r} is not registered as deprecated. "
            f"Add it to lumen_api.deprecation.DEPRECATED_ENDPOINTS first."
        )

    def _set_deprecation_headers(response: Response) -> None:
        for header_name, header_value in _build_headers(
            DEPRECATED_ENDPOINTS[endpoint_path], sunset_date
        ).items():
            response.headers[header_name] = header_value

    return _set_deprecation_headers


def deprecation_known_endpoints() -> Iterable[Tuple[str, Dict[str, str]]]:
    """迭代器 helper,给 Swagger UI / OpenAPI 自定义字段用。"""
    return DEPRECATED_ENDPOINTS.items()
