"""DynamicCORS middleware: static origins + DB-driven (external_apps.
allowed_origins) with 60s in-memory cache. Replaces the hardcoded
``CORSMiddleware`` in main.py.

Cache invalidation:
- TTL expires (60s default)
- ``cache.invalidate()`` called explicitly (admin edit triggers it)

The cache is a module-level singleton so both the middleware and admin
code see the same instance.
"""
from __future__ import annotations

import time
from sqlalchemy import select
from starlette.types import ASGIApp, Receive, Scope, Send
from starlette.responses import Response

from lumen_core.database import SessionLocal
from lumen_models.external_app import ExternalApp


class _CORSCache:
    """In-memory cache of allowed origins. Singleton — one instance per process."""

    def __init__(self) -> None:
        self._allowed: set[str] = set()
        self._expires_at: float = 0.0

    def get_or_refresh(self, ttl: int) -> set[str]:
        now = time.monotonic()
        if now > self._expires_at:
            self._refresh(ttl)
        return self._allowed

    def _refresh(self, ttl: int) -> None:
        db = SessionLocal()
        try:
            rows = db.scalars(select(ExternalApp).where(
                ExternalApp.is_active == True  # noqa: E712
            )).all()
            origins: set[str] = set()
            for r in rows:
                for o in (r.allowed_origins or []):
                    if o:
                        origins.add(o.lower())
        finally:
            db.close()
        self._allowed = origins
        self._expires_at = time.monotonic() + ttl

    def invalidate(self) -> None:
        self._expires_at = 0.0


_cache = _CORSCache()


def get_cors_cache() -> _CORSCache:
    """Return the process-wide CORS cache singleton.

    Both the middleware and admin code (e.g. POST/PUT/DELETE
    /external-apps/*) call this to ensure they share the same instance
    — admin edits can call ``cache.invalidate()`` to flush the cache
    immediately instead of waiting for the TTL.
    """
    return _cache


class DynamicCORSMiddleware:
    """ASGI middleware that echoes ACAO headers for allowed origins only.

    Allowed origin = ``origin in static_origins`` OR
    ``origin in cache.get_or_refresh(ttl)``.

    Handles both preflight (OPTIONS + Access-Control-Request-Method) and
    actual responses (set the ACAO header on the way out via send wrapper).
    """

    def __init__(
        self, app: ASGIApp,
        static_origins: list[str],
        cache_ttl_seconds: int = 60,
    ) -> None:
        self.app = app
        self.static_origins = {o.lower() for o in static_origins}
        self.ttl = cache_ttl_seconds

    def _is_allowed(self, origin: str) -> bool:
        o = origin.strip().lower()
        if o in self.static_origins:
            return True
        return o in get_cors_cache().get_or_refresh(self.ttl)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict((k.decode().lower(), v.decode()) for k, v in scope.get("headers", []))
        origin = headers.get("origin", "")
        method = scope.get("method", "GET").upper()

        if origin and self._is_allowed(origin):
            # Preflight — M-FIX-2026-06-25:
            # 1. 处理 *所有* OPTIONS (含没有 Access-Control-Request-Method 的 server probe),
            #    避免 app 收到没 ACAO 的 405/404 让浏览器误报 CORS。
            # 2. 显式加 Vary: Origin 防止 CDN/代理缓存跨域响应。
            if method == "OPTIONS":
                response = Response(
                    status_code=200,
                    headers={
                        "Access-Control-Allow-Origin": origin,
                        "Access-Control-Allow-Methods": "GET, POST, PUT, PATCH, DELETE, OPTIONS",
                        "Access-Control-Allow-Headers": "Authorization, Content-Type, X-Requested-With",
                        "Access-Control-Max-Age": "600",
                        "Vary": "Origin",
                    },
                )
                await response(scope, receive, send)
                return
            # Actual request — inject ACAO on the way out
            # M-FIX-2026-06-25: try/finally 确保 app 抛异常时也返 ACAO 头,
            # 避免浏览器看到 500 无 ACAO 误报 CORS。
            response_started = False

            async def send_wrapper(message):
                nonlocal response_started
                if message["type"] == "http.response.start":
                    response_started = True
                    hdrs = list(message.get("headers", []))
                    # 移除已有 ACAO (避免重复) 再追加
                    hdrs = [(k, v) for k, v in hdrs if k.lower() != b"access-control-allow-origin"]
                    hdrs.append((b"access-control-allow-origin", origin.encode()))
                    # 补 Vary: Origin 防缓存
                    hdrs.append((b"vary", b"Origin"))
                    message["headers"] = hdrs
                await send(message)

            try:
                await self.app(scope, receive, send_wrapper)
            except Exception:
                # app 抛异常且没发任何响应 → 我们合成一个 500 + ACAO
                if not response_started:
                    await send({
                        "type": "http.response.start",
                        "status": 500,
                        "headers": [
                            (b"access-control-allow-origin", origin.encode()),
                            (b"content-type", b"application/json"),
                            (b"vary", b"Origin"),
                        ],
                    })
                    await send({
                        "type": "http.response.body",
                        "body": b'{"detail":"Internal Server Error (CORS-fallback)"}',
                    })
            return

        await self.app(scope, receive, send)
