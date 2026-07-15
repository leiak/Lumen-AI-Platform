"""Tests for HttpCaller (M16 http skill type)."""
import os
import pytest


def _mock_dns(monkeypatch):
    """Bypass real DNS so offline test env can exercise non-loopback hosts.

    Maps any host to 93.184.216.34 (public, unicast, not in any forbidden CIDR).
    """
    import lumen_core.sandbox.http_caller as mod

    def fake_resolve(host: str) -> str:
        return "93.184.216.34"

    monkeypatch.setattr(mod, "_resolve_host_to_ip", fake_resolve)


def test_blocks_localhost(monkeypatch):
    """127.0.0.1 must be rejected (SSRF)."""
    from lumen_core.sandbox.http_caller import HttpCaller
    from lumen_core.skill_errors import SkillSecurityError
    from lumen_schemas.skill import HttpTypeConfig

    cfg = HttpTypeConfig(url="http://127.0.0.1:9999/foo", method="GET")
    with pytest.raises(SkillSecurityError, match="internal"):
        HttpCaller.execute(cfg, {}, allowed_domains=[])


def test_blocks_private_cidr(monkeypatch):
    """10.0.0.0/8 must be rejected (SSRF)."""
    from lumen_core.sandbox.http_caller import HttpCaller
    from lumen_core.skill_errors import SkillSecurityError
    from lumen_schemas.skill import HttpTypeConfig

    cfg = HttpTypeConfig(url="http://10.0.0.5/admin", method="GET")
    with pytest.raises(SkillSecurityError, match="internal"):
        HttpCaller.execute(cfg, {}, allowed_domains=[])


def test_blocks_non_allowlisted_domain(monkeypatch):
    """URL host not in allowlist is rejected."""
    from lumen_core.sandbox.http_caller import HttpCaller
    from lumen_core.skill_errors import SkillSecurityError
    from lumen_schemas.skill import HttpTypeConfig

    cfg = HttpTypeConfig(url="https://malicious.com/steal", method="GET")
    with pytest.raises(SkillSecurityError, match="allowlist"):
        HttpCaller.execute(cfg, {}, allowed_domains=["*.good.com"])


def test_allows_allowlisted_domain(monkeypatch):
    """A host matching the glob allowlist is accepted (we don't actually hit it)."""
    from lumen_core.sandbox.http_caller import HttpCaller
    from lumen_schemas.skill import HttpTypeConfig
    import httpx

    cfg = HttpTypeConfig(url="https://api.good.com/v1", method="GET")
    _mock_dns(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text='{"ok": true}')

    import lumen_core.sandbox.http_caller as mod
    orig = mod.httpx.Client
    transport = httpx.MockTransport(handler)
    mod.httpx.Client = lambda **kw: orig(transport=transport, **kw)
    try:
        result = HttpCaller.execute(cfg, {}, allowed_domains=["*.good.com"])
    finally:
        mod.httpx.Client = orig
    assert result == '{"ok": true}'


def test_resolves_env_credential(monkeypatch):
    """${ENV_VAR} is replaced from os.environ at call time."""
    from lumen_core.sandbox.http_caller import HttpCaller
    from lumen_schemas.skill import HttpTypeConfig, HttpAuth
    import httpx

    monkeypatch.setenv("MY_TEST_KEY", "secret-abc")
    cfg = HttpTypeConfig(
        url="https://api.example.com/v1",
        method="GET",
        auth=HttpAuth(type="bearer", credential_ref="${MY_TEST_KEY}"),
    )
    _mock_dns(monkeypatch)
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["headers"] = dict(request.headers)
        return httpx.Response(200, text="ok")

    import lumen_core.sandbox.http_caller as mod
    orig = mod.httpx.Client
    transport = httpx.MockTransport(handler)
    mod.httpx.Client = lambda **kw: orig(transport=transport, **kw)
    try:
        HttpCaller.execute(cfg, {}, allowed_domains=["*.example.com"])
    finally:
        mod.httpx.Client = orig
    assert captured["headers"]["authorization"] == "Bearer secret-abc"


def test_missing_env_raises(monkeypatch):
    """credential_ref pointing to undefined env var raises."""
    from lumen_core.sandbox.http_caller import HttpCaller
    from lumen_core.skill_errors import SkillSecurityError
    from lumen_schemas.skill import HttpTypeConfig, HttpAuth

    _mock_dns(monkeypatch)
    monkeypatch.delenv("NONEXISTENT_KEY_XYZ", raising=False)
    cfg = HttpTypeConfig(
        url="https://api.example.com/v1",
        auth=HttpAuth(type="bearer", credential_ref="${NONEXISTENT_KEY_XYZ}"),
    )
    with pytest.raises(SkillSecurityError, match="not set"):
        HttpCaller.execute(cfg, {}, allowed_domains=["*.example.com"])


def test_happy_post_with_body_template(monkeypatch):
    """POST with body_template substitutes {{arg}} placeholders."""
    from lumen_core.sandbox.http_caller import HttpCaller
    from lumen_schemas.skill import HttpTypeConfig
    import httpx

    cfg = HttpTypeConfig(
        url="https://api.example.com/v1",
        method="POST",
        body_template='{"city": "{{city}}"}',
    )
    _mock_dns(monkeypatch)
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json as _json
        captured["json"] = _json.loads(request.content)
        return httpx.Response(200, text='{"ok": true}')

    import lumen_core.sandbox.http_caller as mod
    orig = mod.httpx.Client
    transport = httpx.MockTransport(handler)
    mod.httpx.Client = lambda **kw: orig(transport=transport, **kw)
    try:
        HttpCaller.execute(cfg, {"city": "Beijing"}, allowed_domains=["*.example.com"])
    finally:
        mod.httpx.Client = orig
    assert captured["json"] == {"city": "Beijing"}
