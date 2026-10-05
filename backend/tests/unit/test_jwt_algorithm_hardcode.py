"""JWT algorithm hard-coded to HS256 (nitpick 2026-10-04 C4).

Locks three invariants for the JWT-decoder hardening:

  1. ``lumen_core.security`` uses ``_JWT_ALGORITHM = "HS256"`` for
     both encode (in ``create_access_token``) and decode
     (in ``decode_access_token``). ``settings.ALGORITHM`` is gone.
  2. The external-auth JWT (signed with ``EXTERNAL_JWT_SECRET``) is
     ALSO pinned to HS256 in ``lumen_services.external_auth_service``,
     not just the user-auth path.
  3. Tokens crafted with ``alg=none`` (the canonical alg-confusion
     attack vector) are refused by ``decode_access_token`` /
     ``decode_external_token`` — returns ``None``, not a forged
     payload.

Why this matters: ``python-jose`` does refuse ``alg=none`` tokens
out of the box, but the audit-friendly defence is that the
``algorithms=`` whitelist is a literal — ``["HS256"]`` — so a future
config knob like ``settings.ALGORITHM = "none"`` cannot weaken it
even if someone re-adds the field by mistake.
"""
import pytest


def test_user_jwt_round_trip_works():
    """``create_access_token`` + ``decode_access_token`` still works."""
    from lumen_core.security import create_access_token, decode_access_token
    from lumen_core.tenant import TenantContext

    TenantContext.set_tenant_id(1)
    try:
        token = create_access_token({"sub": "alice"})
        payload = decode_access_token(token)
        assert payload is not None
        assert payload.get("sub") == "alice"
    finally:
        TenantContext.set_tenant_id(None)


def test_external_jwt_round_trip_works():
    """External-auth encode + decode still round-trip on HS256."""
    from lumen_services.external_auth_service import (
        create_external_token,
        decode_external_token,
    )

    token = create_external_token({"user_id": 99, "sub": "widget"})
    payload = decode_external_token(token)
    assert payload is not None
    assert payload.get("user_id") == 99
    assert payload.get("sub") == "widget"


def test_security_module_uses_hardcoded_hs256():
    """``_JWT_ALGORITHM`` constant is exposed for tests + future audits."""
    from lumen_core import security

    assert security._JWT_ALGORITHM == "HS256"


def test_settings_has_no_algorithm_field():
    """``Settings.ALGORITHM`` no longer exists — it was the original P0."""
    from lumen_core.config import Settings

    assert "ALGORITHM" not in Settings.model_fields


def test_settings_extra_ignore_allows_legacy_env_var():
    """``.env`` 残留 ``ALGORITHM=xxx`` 不应阻止 Settings 构造。

    We can't easily set env vars in-process for this assertion
    without leaking state across tests, so instead we just verify
    that ``Config.extra == "ignore"`` is set on the Settings class.
    """
    from lumen_core.config import Settings

    cfg = Settings.model_config
    assert cfg.get("extra") == "ignore"


def test_user_jwt_decode_rejects_alg_none_token():
    """A hand-crafted ``alg=none`` token must NOT decode as valid."""
    import base64
    import json

    from lumen_core.security import decode_access_token

    # Build a minimal "unsigned" JWT: header.payload.<empty signature>
    header = base64.urlsafe_b64encode(
        json.dumps({"alg": "none", "typ": "JWT"}).encode()
    ).rstrip(b"=").decode()
    payload = base64.urlsafe_b64encode(
        json.dumps({"sub": "attacker", "tenant_id": 999}).encode()
    ).rstrip(b"=").decode()
    none_token = f"{header}.{payload}."

    # decode_access_token 必须拒绝 — 不能返回 dict 让 caller 误以为真
    assert decode_access_token(none_token) is None


def test_external_jwt_decode_rejects_alg_none_token():
    """External-auth decoder is equally strict on alg=none."""
    import base64
    import json

    from lumen_services.external_auth_service import decode_external_token

    header = base64.urlsafe_b64encode(
        json.dumps({"alg": "none", "typ": "JWT"}).encode()
    ).rstrip(b"=").decode()
    payload = base64.urlsafe_b64encode(
        json.dumps({"iss": "external-app", "sub": "attacker"}).encode()
    ).rstrip(b"=").decode()
    none_token = f"{header}.{payload}."

    assert decode_external_token(none_token) is None


def test_user_jwt_decode_rejects_wrong_signature():
    """Tampered signature returns None (signature still enforced)."""
    from lumen_core.security import create_access_token, decode_access_token
    from lumen_core.tenant import TenantContext

    TenantContext.set_tenant_id(1)
    try:
        token = create_access_token({"sub": "alice"})
        # 翻最后一字符的 base64:让 signature 错
        head, body, sig = token.split(".")
        tampered = f"{head}.{body}.{sig[:-2]}AA"
        assert decode_access_token(tampered) is None
    finally:
        TenantContext.set_tenant_id(None)


def test_external_jwt_decode_rejects_wrong_signature():
    from lumen_services.external_auth_service import (
        create_external_token,
        decode_external_token,
    )

    token = create_external_token({"sub": "x"})
    head, body, sig = token.split(".")
    tampered = f"{head}.{body}.{sig[:-2]}AA"
    assert decode_external_token(tampered) is None