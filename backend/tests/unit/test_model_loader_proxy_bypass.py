"""Tests for proxy-bypass injection in `app.services.model_loader`.

Workflow 1148 incident (2026-08-30): httpx with ``trust_env=True`` reads
``HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Internet Settings\\
ProxyServer`` and routed ChatOllama through ``127.0.0.1:10793``, which
returned 502 for localhost-bound requests (ollama on 11434). curl was
healthy so the dev environment looked fine, but the workflow agent
executor kept failing.

The fix is in ``_bypass_proxy_client_kwargs()``: ``proxy=None`` +
``trust_env=False``. This file pins the contract that BOTH branches
(ollama + openai_compat) inject that bypass; a regression that drops
it on either branch would resurrect the bug silently because the
underlying model still constructs successfully — only the network
call would fail.

Tests are pure unit (no DB, no network, no fixtures beyond the factory
itself) so they run with the full suite without dev DB dependency.
"""
from typing import Any


def _unwrap_inner(proxy: Any) -> Any:
    """Pull the real LangChain model out of the LoggingChatModel proxy."""
    # LoggingChatModel exposes the wrapped model via the private ``_inner``
    # attribute (mirrors how langchain itself accesses partner libraries).
    # If a future refactor drops the proxy, the test fails fast with a
    # clear AttributeError, not a confusing bypass mismatch.
    return proxy._inner


def test_bypass_helper_contains_required_keys():
    """The helper must return both proxy and trust_env keys.

    httpx ignores a partial dict silently — e.g. setting only
    ``trust_env=False`` still leaves the explicit ``proxy`` URL
    resolved from the registry. Both keys are required to make the
    registry proxy fully inert.
    """
    from lumen_services.model_loader import _bypass_proxy_client_kwargs

    kwargs = _bypass_proxy_client_kwargs()
    assert kwargs == {"proxy": None, "trust_env": False}, (
        f"bypass kwargs drifted: {kwargs!r}. Both proxy and trust_env must "
        f"be set to fully disable httpx env-based proxy resolution."
    )


def test_ollama_branch_injects_proxy_bypass():
    """The ollama branch must pass client_kwargs={\"proxy\": None,
    \"trust_env\": False} to ChatOllama. This is the path that
    workflow 1148's agent executor took, so a regression here is the
    bug we're guarding against.
    """
    from langchain_ollama import ChatOllama

    from lumen_services.model_loader import create_chat_model

    proxy = create_chat_model(
        model_type="ollama",
        model_name="qwen2.5:7b",
        base_url="http://localhost:11434",
        temperature=0.7,
        timeout=60,
    )
    inner = _unwrap_inner(proxy)
    assert isinstance(inner, ChatOllama), (
        f"ollama branch should produce ChatOllama, got {type(inner).__name__}"
    )
    # ChatOllama stores client_kwargs and passes them straight to
    # httpx.Client / httpx.AsyncClient at .invoke / .ainvoke time.
    assert inner.client_kwargs == {"proxy": None, "trust_env": False}, (
        f"ChatOllama.client_kwargs drifted: {inner.client_kwargs!r}. "
        f"httpx will fall back to Windows registry proxy and 502 again."
    )


def test_openai_compat_branch_injects_proxy_bypass():
    """The openai_compat branch must inject bypass into BOTH http_client
    (sync) and http_async_client (async). Missing one would leave the
    other half exposed to the registry proxy.

    We use a synthetic 'openai' provider (already in the catalog) and
    a fake base_url/api_key — the client objects are constructed
    without making any network call.

    Note: openai SDK's ``Client`` exposes ``trust_env`` directly but
    does NOT expose ``proxy`` (it's stored as internal ``_get_proxy_map``).
    ``trust_env=False`` is the canonical switch — with it set, httpx
    ignores both env vars and the Windows registry, so the proxy
    resolution path is fully short-circuited.
    """
    from langchain_openai import ChatOpenAI

    from lumen_services.model_loader import create_chat_model

    proxy = create_chat_model(
        model_type="openai",
        model_name="gpt-4o-mini",
        base_url="http://example.invalid/v1",
        api_key="sk-test-not-real",
        temperature=0.7,
        timeout=60,
    )
    inner = _unwrap_inner(proxy)
    assert isinstance(inner, ChatOpenAI), (
        f"openai branch should produce ChatOpenAI, got {type(inner).__name__}"
    )
    # Sync client: used by .invoke() and any internal openai SDK call.
    assert inner.http_client is not None, (
        "ChatOpenAI.http_client must be set explicitly — passing None "
        "would let the SDK auto-build one with trust_env=True."
    )
    assert inner.http_client.trust_env is False, (
        f"sync http_client.trust_env should be False, "
        f"got {inner.http_client.trust_env!r}"
    )
    # Async client: used by .ainvoke() and .astream().
    assert inner.http_async_client is not None, (
        "ChatOpenAI.http_async_client must be set explicitly — passing "
        "None would let the SDK auto-build one with trust_env=True."
    )
    assert inner.http_async_client.trust_env is False, (
        f"async http_async_client.trust_env should be False, "
        f"got {inner.http_async_client.trust_env!r}"
    )


def test_ollama_kwargs_survives_pydantic_validation():
    """ChatOllama stores client_kwargs in a pydantic Field. A bug
    where ``proxy=None`` got rejected by httpx's pydantic model would
    surface as a ValidationError at construction time — guard the
    construction path itself so future refactors don't silently
    introduce a regression.
    """
    from langchain_ollama import ChatOllama

    # Should NOT raise pydantic ValidationError. ``proxy`` is an
    # ``Optional[httpx.Proxy]`` field and ``None`` is the documented
    # "no proxy" sentinel — but a careless refactor that swaps in a
    # non-pydantic Client could break this.
    chat = ChatOllama(
        model="qwen2.5:7b",
        base_url="http://localhost:11434",
        timeout=60,
        client_kwargs={"proxy": None, "trust_env": False},
    )
    assert chat.client_kwargs["trust_env"] is False
    assert chat.client_kwargs["proxy"] is None