"""Tests for ExternalAuthService helpers (pure functions + small DB ops).

Covers:
  - match_origin: exact, single-level wildcard, attack-via-suffix, case
    insensitivity, empty pattern list, scheme requirement
  - create_external_token / decode_external_token: roundtrip, expired
    tokens, wrong-secret signature rejection
  - check_rate_limit: under-threshold, over-threshold, per-app isolation
  - upsert_visitor: creates then updates the same (app, visitor_uuid)

Spec: ``docs/superpowers/specs/2026-06-08-external-chat-widget-design.md`` § 5.
"""
import uuid
from datetime import datetime
from unittest.mock import patch

import pytest

from lumen_core.database import SessionLocal
from lumen_services.external_auth_service import (
    match_origin,
    upsert_visitor,
    create_external_token,
    decode_external_token,
    check_rate_limit,
)


# ---------------------------------------------------------------------------
# match_origin
# ---------------------------------------------------------------------------


def test_match_origin_exact():
    assert match_origin("https://shop.example.com", ["https://shop.example.com"]) is True


def test_match_origin_wildcard_subdomain():
    assert match_origin("https://shop.example.com", ["https://*.example.com"]) is True
    # Multi-level subdomains must NOT match the single-level wildcard.
    assert match_origin("https://blog.shop.example.com", ["https://*.example.com"]) is False


def test_match_origin_root_not_match_subdomain_wildcard():
    """``https://*.example.com`` must NOT match the bare ``example.com``.

    The wildcard requires at least one subdomain label.
    """
    assert match_origin("https://example.com", ["https://*.example.com"]) is False


def test_match_origin_no_attack_via_suffix():
    """``https://*.example.com`` must NOT match ``https://example.com.attacker.com``.

    Classic origin-bypass attack: a malicious site registers a domain
    that ends in ``example.com`` to inherit the parent's allowlist.
    """
    assert match_origin("https://example.com.attacker.com", ["https://*.example.com"]) is False


def test_match_origin_case_insensitive():
    assert match_origin("https://SHOP.Example.com", ["https://shop.example.com"]) is True


def test_match_origin_empty_disallows_all():
    assert match_origin("https://anywhere.com", []) is False
    assert match_origin("https://anywhere.com", None) is False


def test_match_origin_protocol_required_in_pattern():
    # Origin is always https://... in browser context; pattern without scheme is invalid
    assert match_origin("https://shop.example.com", ["shop.example.com"]) is False


# ---------------------------------------------------------------------------
# JWT
# ---------------------------------------------------------------------------


def test_create_and_decode_external_token_roundtrip():
    payload = {
        "app_id": 1, "tenant_id": 2, "visitor_id": 3, "visitor_uuid": "vid-1",
        "allowed_agent_ids": [10], "allowed_team_ids": [],
        "scopes": ["chat:stream"],
    }
    token = create_external_token(payload, ttl_seconds=60)
    decoded = decode_external_token(token)
    assert decoded is not None
    assert decoded["app_id"] == 1
    assert decoded["iss"] == "external-app"
    assert decoded["allowed_agent_ids"] == [10]


def test_decode_external_token_expired_returns_none():
    payload = {"app_id": 1, "tenant_id": 1, "visitor_id": 1, "visitor_uuid": "v"}
    token = create_external_token(payload, ttl_seconds=-1)  # already expired
    assert decode_external_token(token) is None


def test_decode_external_token_wrong_secret_returns_none():
    payload = {"app_id": 1, "tenant_id": 1, "visitor_id": 1, "visitor_uuid": "v"}
    token = create_external_token(payload, ttl_seconds=60)
    # Patch the Settings instance attribute. pydantic-settings 2.5.x is
    # not frozen by default, so attribute assignment works at the
    # instance level and the service module sees the new value on the
    # next call (it accesses ``settings.EXTERNAL_JWT_SECRET`` at call
    # time, not at import time).
    with patch("lumen_core.config.settings.EXTERNAL_JWT_SECRET", "different-secret"):
        assert decode_external_token(token) is None


# ---------------------------------------------------------------------------
# Rate limit
# ---------------------------------------------------------------------------


def test_check_rate_limit_allows_under_threshold():
    for _ in range(5):
        assert check_rate_limit(app_id=999, endpoint_class="chat", limit_per_min=10) is True


def test_check_rate_limit_blocks_over_threshold():
    for _ in range(10):
        check_rate_limit(app_id=998, endpoint_class="chat", limit_per_min=10)
    # 11th call within 60s exceeds limit
    assert check_rate_limit(app_id=998, endpoint_class="chat", limit_per_min=10) is False


def test_check_rate_limit_isolated_by_app_id():
    for _ in range(10):
        check_rate_limit(app_id=997, endpoint_class="chat", limit_per_min=10)
    # different app_id — independent bucket, still allowed
    assert check_rate_limit(app_id=996, endpoint_class="chat", limit_per_min=10) is True


# ---------------------------------------------------------------------------
# upsert_visitor
# ---------------------------------------------------------------------------


def test_upsert_visitor_creates_then_updates():
    db = SessionLocal()
    visitor = None
    app = None
    tenant = None
    try:
        from lumen_models.external_app import ExternalApp
        from lumen_models.tenant import Tenant
        # ``status`` is Boolean (not String) on Tenant — drop the
        # plan's ``status="active"`` argument and rely on the
        # column default. ``max_users`` is Integer with default 10.
        tenant = Tenant(
            name="t-uv",
            code=f"uv-{uuid.uuid4().hex[:12]}",
        )
        db.add(tenant)
        db.commit()
        db.refresh(tenant)
        app = ExternalApp(
            tenant_id=tenant.id,
            name="uv",
            app_key=f"lc_pub_uv_{uuid.uuid4().hex[:8]}",
            app_secret_hash="x",
            allowed_origins=[],
        )
        db.add(app)
        db.commit()
        db.refresh(app)

        v1 = upsert_visitor(db, app.id, "vid-xyz")
        db.commit()
        v2 = upsert_visitor(db, app.id, "vid-xyz")
        db.commit()

        assert v1.id == v2.id  # same row, not a new insert
        assert v2.last_seen_at >= v1.last_seen_at
        visitor = v2
    finally:
        # Clean up so re-runs don't accumulate orphan tenants/apps.
        try:
            if visitor is not None:
                db.delete(visitor)
                db.commit()
            if app is not None:
                # Also delete the visitor rows (if any) tied to this app
                from lumen_models.external_app import ExternalVisitor
                db.query(ExternalVisitor).filter(ExternalVisitor.app_id == app.id).delete()
                db.delete(app)
                db.commit()
            if tenant is not None:
                db.delete(tenant)
                db.commit()
        except Exception:
            db.rollback()
        finally:
            db.close()


# ---------------------------------------------------------------------------
# Rate limit sliding window (Task 15)
# ---------------------------------------------------------------------------


def test_check_rate_limit_sliding_window_drops_old_entries(monkeypatch):
    """After waiting > 60s, old entries are dropped and new requests allowed.

    We monkeypatch time.monotonic to simulate the wait without sleeping.
    """
    import time
    from lumen_services import external_auth_service as svc
    monkeypatch.setattr(svc.time, "monotonic", lambda: 1000.0)
    for _ in range(10):
        assert svc.check_rate_limit(app_id=995, endpoint_class="chat", limit_per_min=10) is True
    # Blocked at limit
    assert svc.check_rate_limit(app_id=995, endpoint_class="chat", limit_per_min=10) is False
    # Advance 61s
    monkeypatch.setattr(svc.time, "monotonic", lambda: 1061.0)
    # Now should be allowed again
    assert svc.check_rate_limit(app_id=995, endpoint_class="chat", limit_per_min=10) is True
