"""2.1 C.2:httpx / boto3 proxy bypass env-aware 决策表测试。

测试矩阵:
- 默认 dev (无 HTTPS_PROXY env) → bypass,返 ``{"proxy": None, "trust_env": False}``
- 设了 HTTPS_PROXY → 不 bypass,返 ``{}``
- 设了 HTTP_PROXY → 不 bypass,返 ``{}``
- LUMEN_FORCE_PROXY_BYPASS=1 (env 也设了) → 强制 bypass
- 大小写不敏感 env var(HTTPS_PROXY vs https_proxy)
- 真值字符串集合 ``true/1/yes/on`` 都生效

镜像结构:httpx_bypass + boto3_bypass 两个 helper 各跑一遍。
"""
from __future__ import annotations

import importlib

import pytest


@pytest.fixture(autouse=True)
def _clean_proxy_env(monkeypatch):
    """每个 test 前清掉所有 proxy env var 和 LUMEN_FORCE_PROXY_BYPASS。"""
    for var in (
        "HTTPS_PROXY", "HTTP_PROXY",
        "https_proxy", "http_proxy",
        "LUMEN_FORCE_PROXY_BYPASS",
        "S3_BYPASS_PROXY",
    ):
        monkeypatch.delenv(var, raising=False)
    yield


def _reload_modules():
    """env 变了之后 reload 模块让 module-level code 重新读 env。"""
    import lumen_core.httpx_bypass
    import lumen_core.boto3_bypass
    importlib.reload(lumen_core.httpx_bypass)
    importlib.reload(lumen_core.boto3_bypass)


# ---- httpx_bypass ----


def test_httpx_bypass_default_no_env_bypasses_registry(monkeypatch):
    """无任何 proxy env:dev 默认,bypass Windows registry。"""
    _reload_modules()
    from lumen_core.httpx_bypass import bypass_proxy_client_kwargs

    result = bypass_proxy_client_kwargs()
    assert result == {"proxy": None, "trust_env": False}


def test_httpx_bypass_https_proxy_env_trusts_env(monkeypatch):
    """设 HTTPS_PROXY → 不 bypass,httpx 自己读 env 走代理。"""
    monkeypatch.setenv("HTTPS_PROXY", "http://corp-proxy:3128")
    _reload_modules()
    from lumen_core.httpx_bypass import bypass_proxy_client_kwargs

    result = bypass_proxy_client_kwargs()
    # 不 bypass,httpx 自己读 env
    assert result == {}


def test_httpx_bypass_http_proxy_env_trusts_env(monkeypatch):
    """HTTP_PROXY 也行(无 s)。"""
    monkeypatch.setenv("HTTP_PROXY", "http://corp-proxy:3128")
    _reload_modules()
    from lumen_core.httpx_bypass import bypass_proxy_client_kwargs

    result = bypass_proxy_client_kwargs()
    assert result == {}


def test_httpx_bypass_lowercase_env_var_works(monkeypatch):
    """curl-style lowercase https_proxy 也得识别。"""
    monkeypatch.setenv("https_proxy", "http://corp-proxy:3128")
    _reload_modules()
    from lumen_core.httpx_bypass import bypass_proxy_client_kwargs

    result = bypass_proxy_client_kwargs()
    assert result == {}


def test_httpx_bypass_force_override_bypasses_even_with_env(monkeypatch):
    """LUMEN_FORCE_PROXY_BYPASS=1 + HTTPS_PROXY 共存 → 强制 bypass。"""
    monkeypatch.setenv("HTTPS_PROXY", "http://corp-proxy:3128")
    monkeypatch.setenv("LUMEN_FORCE_PROXY_BYPASS", "1")
    _reload_modules()
    from lumen_core.httpx_bypass import bypass_proxy_client_kwargs

    result = bypass_proxy_client_kwargs()
    assert result == {"proxy": None, "trust_env": False}


def test_httpx_bypass_force_override_truthy_values(monkeypatch):
    """``LUMEN_FORCE_PROXY_BYPASS`` 真值集合 ``true/yes/on/1`` 都生效。"""
    for val in ("1", "true", "yes", "on"):
        monkeypatch.setenv("LUMEN_FORCE_PROXY_BYPASS", val)
        monkeypatch.setenv("HTTPS_PROXY", "http://x:3128")
        _reload_modules()
        from lumen_core.httpx_bypass import bypass_proxy_client_kwargs

        result = bypass_proxy_client_kwargs()
        assert result == {"proxy": None, "trust_env": False}, f"val={val} should bypass"
        monkeypatch.delenv("LUMEN_FORCE_PROXY_BYPASS")
        monkeypatch.delenv("HTTPS_PROXY")


def test_httpx_bypass_force_override_unset_string_treated_as_false(monkeypatch):
    """``LUMEN_FORCE_PROXY_BYPASS=''`` (空字符串) → 不强制。"""
    monkeypatch.setenv("LUMEN_FORCE_PROXY_BYPASS", "")
    monkeypatch.setenv("HTTPS_PROXY", "http://x:3128")
    _reload_modules()
    from lumen_core.httpx_bypass import bypass_proxy_client_kwargs

    # env 有 HTTPS_PROXY → 不 bypass
    result = bypass_proxy_client_kwargs()
    assert result == {}


# ---- boto3_bypass ----


def test_boto3_bypass_default_no_env_bypasses(monkeypatch):
    """boto3 默认行为镜像 httpx:无 env → bypass。"""
    _reload_modules()
    from lumen_core.boto3_bypass import boto3_bypass_proxy_kwargs

    result = boto3_bypass_proxy_kwargs()
    assert result == {"proxies": {}}


def test_boto3_bypass_https_proxy_env_returns_empty_dict(monkeypatch):
    """HTTPS_PROXY 设了 → 返 ``{}``(botocore 自己读 env)。"""
    monkeypatch.setenv("HTTPS_PROXY", "http://corp-proxy:3128")
    _reload_modules()
    from lumen_core.boto3_bypass import boto3_bypass_proxy_kwargs

    result = boto3_bypass_proxy_kwargs()
    assert result == {}


def test_boto3_bypass_force_override_bypasses_even_with_env(monkeypatch):
    """LUMEN_FORCE_PROXY_BYPASS=1 强制 bypass,无视 env。"""
    monkeypatch.setenv("HTTPS_PROXY", "http://corp-proxy:3128")
    monkeypatch.setenv("LUMEN_FORCE_PROXY_BYPASS", "1")
    _reload_modules()
    from lumen_core.boto3_bypass import boto3_bypass_proxy_kwargs

    result = boto3_bypass_proxy_kwargs()
    assert result == {"proxies": {}}


# ---- S3Backend._bypass_proxy_kwargs 集成 ----


def test_s3_backend_bypass_default_uses_shared_helper(monkeypatch):
    """S3Backend._bypass_proxy_kwargs 默认走 boto3_bypass helper(env-aware)。"""
    _reload_modules()
    from lumen_services.storage.s3_backend import S3Backend

    result = S3Backend._bypass_proxy_kwargs()
    # 默认无 env → bypass,返 ``{"proxies": {}}``
    assert result == {"proxies": {}}


def test_s3_backend_bypass_false_returns_auto(monkeypatch):
    """``S3_BYPASS_PROXY=false`` → 返 ``"auto"`` sentinel,BotoConfig 不传 proxies。"""
    monkeypatch.setenv("S3_BYPASS_PROXY", "false")
    _reload_modules()
    from lumen_services.storage.s3_backend import S3Backend

    result = S3Backend._bypass_proxy_kwargs()
    assert result == "auto"


def test_s3_backend_bypass_https_proxy_returns_empty_dict(monkeypatch):
    """``HTTPS_PROXY`` 设了但 ``S3_BYPASS_PROXY`` 默认 → 走 boto3 helper 返 ``{}``。"""
    monkeypatch.setenv("HTTPS_PROXY", "http://corp-proxy:3128")
    _reload_modules()
    from lumen_services.storage.s3_backend import S3Backend

    result = S3Backend._bypass_proxy_kwargs()
    # env 有 HTTPS_PROXY → bypass helper 返 ``{}``
    assert result == {}


def test_s3_backend_bypass_false_with_https_proxy_returns_auto(monkeypatch):
    """``S3_BYPASS_PROXY=false`` 显式 opt-out,即使没设 env 也返 auto。"""
    monkeypatch.setenv("S3_BYPASS_PROXY", "false")
    _reload_modules()
    from lumen_services.storage.s3_backend import S3Backend

    result = S3Backend._bypass_proxy_kwargs()
    assert result == "auto"


# ---- module import smoke ----


def test_proxy_bypass_modules_import_clean():
    """模块导入不抛。"""
    importlib.import_module("lumen_core.httpx_bypass")
    importlib.import_module("lumen_core.boto3_bypass")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])