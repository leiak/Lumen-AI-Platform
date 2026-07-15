"""External (widget) auth helpers: Origin matching, JWT issue/decode,
visitor UPSERT, and in-process rate limiting.

See ``docs/superpowers/specs/2026-06-08-external-chat-widget-design.md`` § 5
for the contract; this module is the service-layer implementation.

Used by ``/api/v1/external/...`` routes and the boot-time guard in
``app.main`` (which checks the EXTERNAL_JWT_SECRET default).
"""
from __future__ import annotations

import re
import threading
import time
from collections import deque
from datetime import datetime
from typing import Optional

from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from lumen_core.config import settings
from lumen_models.external_app import ExternalVisitor


# ---------------------------------------------------------------------------
# Origin matching
# ---------------------------------------------------------------------------

def match_origin(origin: str, allowed: Optional[list[str]]) -> bool:
    """Return True iff ``origin`` matches one of the patterns in ``allowed``.

    Patterns are exact (``https://shop.example.com``) or single-level
    wildcard prefix (``https://*.example.com`` — matches exactly one
    subdomain level, not the bare domain or a deeper sub-sub-domain).
    Case-insensitive on the host; scheme must match exactly.

    Security properties (validated by ``tests/unit/test_external_auth_service.py``):
      - empty ``allowed`` (or ``None``) rejects every origin
      - ``https://*.example.com`` does NOT match ``example.com`` (the
        wildcard requires at least one label)
      - ``https://*.example.com`` does NOT match ``example.com.attacker.com``
        (suffix attack prevention)
      - scheme-less patterns are rejected (defense against
        ``shop.example.com`` accidentally being treated as a wildcard)
    """
    if not origin or not allowed:
        return False
    o = origin.strip().lower()
    for pat in allowed:
        if not pat:
            continue
        p = pat.strip().lower()
        if "*" in p:
            # Build regex from pattern: escape dots, replace * with
            # ``[^.]+`` (one-or-more non-dot chars — single level).
            # Python's ``re.escape`` (3.7+) escapes ``*`` to ``\*``;
            # we replace the literal two-char sequence back to the
            # single-level-subdomain regex.
            regex = "^" + re.escape(p).replace(r"\*", "[^.]+") + "$"
            if re.match(regex, o):
                return True
        else:
            if o == p:
                return True
    return False


# ---------------------------------------------------------------------------
# JWT
# ---------------------------------------------------------------------------

def create_external_token(payload: dict, *, ttl_seconds: Optional[int] = None) -> str:
    """Sign a short-lived JWT for the external widget.

    ``iss`` is stamped as ``external-app`` so the decoder can
    sanity-check the source even before signature verification.
    ``exp`` is stamped as ``now + ttl_seconds`` (default
    ``settings.EXTERNAL_TOKEN_TTL_SECONDS``).
    """
    body = dict(payload)
    body["iss"] = "external-app"
    body["exp"] = int(time.time()) + (ttl_seconds if ttl_seconds is not None else settings.EXTERNAL_TOKEN_TTL_SECONDS)
    return jwt.encode(body, settings.EXTERNAL_JWT_SECRET, algorithm=settings.ALGORITHM)


def decode_external_token(token: str) -> Optional[dict]:
    """Return the decoded payload or ``None`` on any JWT failure.

    Returns ``None`` for: bad signature, expired token, malformed token.
    The caller should treat ``None`` as "unauthorized" — never trust the
    payload without checking this return value first.
    """
    try:
        return jwt.decode(
            token, settings.EXTERNAL_JWT_SECRET, algorithms=[settings.ALGORITHM]
        )
    except JWTError:
        return None


# ---------------------------------------------------------------------------
# Visitor UPSERT
# ---------------------------------------------------------------------------

def upsert_visitor(db: Session, app_id: int, visitor_uuid: str) -> ExternalVisitor:
    """Get-or-create a visitor row and bump ``last_seen_at``.

    Uses ``SELECT ... FOR UPDATE`` inside an existing transaction so
    concurrent calls for the same (app_id, visitor_uuid) don't
    both create rows (the unique constraint would then raise on
    commit). Callers that don't already have a transaction should
    open one before calling.

    Returns the (now-existing) row. Caller is responsible for
    committing the surrounding transaction.
    """
    now = datetime.utcnow()
    row = db.scalar(
        select(ExternalVisitor)
        .where(ExternalVisitor.app_id == app_id, ExternalVisitor.visitor_id == visitor_uuid)
        .with_for_update()
    )
    if row:
        row.last_seen_at = now
    else:
        row = ExternalVisitor(
            app_id=app_id,
            visitor_id=visitor_uuid,
            first_seen_at=now,
            last_seen_at=now,
        )
        db.add(row)
        db.flush()  # assign id
    return row


# ---------------------------------------------------------------------------
# Rate limiting (in-process, sliding window 60s)
# ---------------------------------------------------------------------------
#
# NOTE: state is held in module-level ``_buckets`` and protected by
# ``_lock``. This is fine for a single uvicorn worker. When we move
# to multi-worker (gunicorn with -w N or multiple k8s pods), the
# effective limit becomes ``limit_per_min * N`` because each worker
# has its own bucket — the spec § 9 calls out Redis as the upgrade
# path. For now the in-process implementation keeps the dependency
# surface small and avoids a Redis round-trip on the hot path.

_lock = threading.Lock()
_buckets: dict[tuple[int, str], deque[float]] = {}


def check_rate_limit(*, app_id: int, endpoint_class: str, limit_per_min: int) -> bool:
    """Return True if the request is allowed, False if rate-limited.

    Sliding window over the last 60s. In-process only — see spec § 9
    for the Redis upgrade path. Each (app_id, endpoint_class) pair
    has its own bucket.
    """
    now = time.monotonic()
    cutoff = now - 60.0
    key = (app_id, endpoint_class)
    with _lock:
        bucket = _buckets.setdefault(key, deque())
        # Drop entries older than 60s
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        if len(bucket) >= limit_per_min:
            return False
        bucket.append(now)
        return True
