"""Tests for individual skill executors (M16)."""
import pytest
from lumen_models.skill_marketplace import SkillMarketplace


def _make_skill(type: str, type_config: dict, content: str = None) -> SkillMarketplace:
    from lumen_core.database import SessionLocal
    import uuid
    db = SessionLocal()
    s = SkillMarketplace(
        name=f"test-{type}-{uuid.uuid4().hex[:6]}",
        category="code",
        content=content,
        type=type,
        type_config=type_config,
        is_verified=1,
    )
    db.add(s); db.commit(); db.refresh(s)
    db.close()
    return s


def test_prompt_executor_returns_content():
    from lumen_services.skill_executors.prompt import PromptExecutor
    s = _make_skill("prompt", type_config=None, content="You are helpful")
    exe = PromptExecutor()
    assert exe.to_system_prompt(s) == "You are helpful"
    assert exe.to_langchain_tool(s, tenant_id=1) is None


def test_script_executor_returns_langchain_tool():
    from lumen_services.skill_executors.script import ScriptExecutor
    s = _make_skill("script", type_config={
        "code": "def main(x): return x",
        "runtime": "python-3.11",
        "timeout": 10,
    })
    exe = ScriptExecutor()
    assert exe.to_system_prompt(s) is None
    tool = exe.to_langchain_tool(s, tenant_id=1)
    assert tool is not None
    assert tool.name == f"skill_{s.id}_script"
    assert "test-" in tool.description or "code" in tool.description


def test_script_executor_tool_runs_sandbox(monkeypatch):
    """to_langchain_tool().run() should call ScriptSandbox."""
    from lumen_services.skill_executors.script import ScriptExecutor
    from lumen_core.sandbox.script_sandbox import ScriptSandbox

    s = _make_skill("script", type_config={
        "code": "def main(x): return x * 3",
        "timeout": 5,
    })
    exe = ScriptExecutor()
    tool = exe.to_langchain_tool(s, tenant_id=1)
    result = tool.run({"x": 7})
    assert result == 21


def test_http_executor_returns_langchain_tool():
    from lumen_services.skill_executors.http import HttpExecutor
    s = _make_skill("http", type_config={
        "url": "https://api.example.com/v1",
        "method": "GET",
        "timeout": 5,
    })
    exe = HttpExecutor()
    assert exe.to_system_prompt(s) is None
    tool = exe.to_langchain_tool(s, tenant_id=1)
    assert tool is not None
    assert tool.name == f"skill_{s.id}_http"


def test_http_executor_tool_runs_caller(monkeypatch):
    """to_langchain_tool().run() should call HttpCaller."""
    from lumen_services.skill_executors.http import HttpExecutor
    import httpx
    from lumen_core.skill_errors import SkillSecurityError

    s = _make_skill("http", type_config={
        "url": "https://api.good.com/v1",
        "method": "GET",
        "timeout": 5,
    })
    class FakeResp:
        status_code = 200
        text = '{"temp": 25}'

    def _fake_request(self, request, **kwargs):
        return FakeResp()

    # HttpCaller uses httpx.Client(...) which calls Client.send — patch the
    # transport-level request hook so the actual DNS lookup never happens.
    monkeypatch.setattr(httpx.Client, "send", _fake_request)
    # Bypass SSRF DNS resolution in the test (host is fictional).
    from lumen_core.sandbox import http_caller
    monkeypatch.setattr(http_caller, "_resolve_host_to_ip", lambda host: "203.0.113.1")
    exe = HttpExecutor()
    tool = exe.to_langchain_tool(s, tenant_id=1)

    # HttpCaller will fetch allowed_domains from system_configs; for this test
    # we pass them via the skill config
    # (Real impl: HttpExecutor reads system_configs at call time)
    # For the test, mock _resolve_allowed_domains to return our test list
    from lumen_services.skill_executors.http import _resolve_allowed_domains
    monkeypatch.setattr(
        "lumen_services.skill_executors.http._resolve_allowed_domains",
        lambda: ["*.good.com"],
    )
    result = tool.run({})
    assert result == '{"temp": 25}'


# === M17 executor tests ===

def test_knowledge_retrieval_executor_returns_tool():
    from lumen_services.skill_executors.knowledge_retrieval import KnowledgeRetrievalExecutor
    s = _make_skill("knowledge_retrieval", type_config={
        "kb_id": 1, "top_k": 3, "score_threshold": 0.7,
        "query_template": "{{user_query}}",
    })
    exe = KnowledgeRetrievalExecutor()
    assert exe.to_system_prompt(s) is None
    tool = exe.to_langchain_tool(s, tenant_id=1)
    assert tool is not None
    assert tool.name == f"skill_{s.id}_kb"
    fields = tool.args_schema.model_fields
    assert "user_query" in fields


def test_knowledge_retrieval_executor_no_template_uses_default_query():
    from lumen_services.skill_executors.knowledge_retrieval import KnowledgeRetrievalExecutor
    s = _make_skill("knowledge_retrieval", type_config={
        "kb_id": 1, "top_k": 5, "score_threshold": 0.5,
        "query_template": "static query string",  # no placeholders
    })
    exe = KnowledgeRetrievalExecutor()
    tool = exe.to_langchain_tool(s, tenant_id=1)
    assert tool is not None
    fields = tool.args_schema.model_fields
    assert "query" in fields


def test_tool_executor_returns_tool():
    from lumen_services.skill_executors.tool import ToolExecutor
    s = _make_skill("tool", type_config={
        "mcp_server": "demo-mcp",
        "tool_name": "list_workflows",
        "param_schema": {
            "type": "object",
            "properties": {"x": {"type": "string", "description": "some param"}},
        },
    })
    exe = ToolExecutor()
    assert exe.to_system_prompt(s) is None
    tool = exe.to_langchain_tool(s, tenant_id=1)
    assert tool is not None
    assert tool.name == f"skill_{s.id}_mcp"


def test_tool_executor_no_param_schema_empty_input():
    from lumen_services.skill_executors.tool import ToolExecutor
    s = _make_skill("tool", type_config={
        "mcp_server": "demo-mcp",
        "tool_name": "ping",
    })
    exe = ToolExecutor()
    tool = exe.to_langchain_tool(s, tenant_id=1)
    assert tool is not None
    # LangChain 1.0 StructuredTool drops the input dict when the
    # args_schema has zero fields (treated as 'no args'). The 4 skill
    # executors ship a single Optional[Dict] placeholder field named
    # 'data' so get_fields() is non-empty and the payload lands
    # in **kwargs. The placeholder is itself unused — see
    # ScriptExecutor._empty_input_model docstring for the full
    # rationale.
    assert set(tool.args_schema.model_fields) == {"data"}


# === M34 HTTP executor tests for 3 new marketplace seeds ===
#
# Each test:
#  1. Builds a SkillMarketplace row with the seed's type_config.
#  2. Monkey-patches ``_resolve_host_to_ip`` so the SSRF guard never
#     hits the real DNS / network — the test stays hermetic.
#  3. Monkey-patches ``_resolve_allowed_domains`` to whitelist the
#     skill's domain (mirrors what the SystemConfig row would do in
#     production).
#  4. Wires ``httpx.Client.send`` via monkey-patch so the executor's
#     ``httpx.Client(...) → client.get(...) → send(...)`` chain is
#     intercepted; no real DNS / TCP / HTTP.
#  5. Drives ``tool.run({...})`` and asserts the body comes back
#     verbatim (or as wrapped in the executor's error branch when
#     the response is 4xx/5xx).

WEATHER_URL = "https://api.open-meteo.com/v1/forecast"
FOREX_URL = "https://api.frankfurter.app/latest"
SHORT_URL_API = "https://is.gd/create.php"

_WEATHER_BODY = (
    '{"latitude":39.9,"longitude":116.4,"current_weather":'
    '{"temperature":18.6,"windspeed":7.5,"weathercode":3}}'
)
_FOREX_BODY = (
    '{"amount":100.0,"base":"USD","date":"2026-06-29","rates":{"CNY":7.18}}'
)
_SHORT_URL_BODY = '{"shorturl":"https://is.gd/AbCdE","status_code":1}'


def _patch_http_for_test(monkeypatch, *, allowed_domain: str, body: str,
                         status_code: int = 200):
    """Common mocking for HTTP seeds. Bypasses DNS + allowlist + network."""
    import httpx
    from lumen_core.sandbox import http_caller
    from lumen_services.skill_executors import http as http_exec

    # (1) SSRF pre-check: fake-resolve to a harmless public IP.
    monkeypatch.setattr(http_caller, "_resolve_host_to_ip",
                        lambda host: "203.0.113.1")  # RFC 5737 TEST-NET-3

    # (2) Allowlist provider — return the test domain.
    monkeypatch.setattr(http_exec, "_resolve_allowed_domains",
                        lambda: [allowed_domain])

    # (3) Mock the transport: replace httpx.Client.send at class
    # level so every new httpx.Client inside HttpCaller.execute()
    # gets a deterministic response.
    def _fake_send(self, request, **kw):
        return httpx.Response(status_code, content=body.encode("utf-8"))
    monkeypatch.setattr(httpx.Client, "send", _fake_send)


def test_http_weather_seed_calls_mock_endpoint(monkeypatch):
    """天气查询 (Open-Meteo) — verify executor reaches URL + body."""
    from lumen_services.skill_executors.http import HttpExecutor
    s = _make_skill("http", type_config={
        "url": WEATHER_URL,
        "method": "GET",
        "headers": {"Accept": "application/json"},
        "timeout": 10,
    })
    _patch_http_for_test(
        monkeypatch,
        allowed_domain="api.open-meteo.com",
        body=_WEATHER_BODY,
    )
    exe = HttpExecutor()
    tool = exe.to_langchain_tool(s, tenant_id=1)
    result = tool.run({})  # GET — no body args
    # Executor returns resp.text unchanged for 2xx.
    assert "current_weather" in result, f"unexpected body: {result!r}"
    assert "18.6" in result, "missing temperature in mock body"
    assert s.type_config["url"] == WEATHER_URL


def test_http_forex_seed_calls_mock_endpoint(monkeypatch):
    """汇率换算 (frankfurter.app) — body is forwarded verbatim."""
    from lumen_services.skill_executors.http import HttpExecutor
    s = _make_skill("http", type_config={
        "url": FOREX_URL,
        "method": "GET",
        "headers": {"Accept": "application/json"},
        "timeout": 10,
    })
    _patch_http_for_test(
        monkeypatch,
        allowed_domain="api.frankfurter.app",
        body=_FOREX_BODY,
    )
    exe = HttpExecutor()
    tool = exe.to_langchain_tool(s, tenant_id=1)
    result = tool.run({})
    assert "CNY" in result
    assert '"base":"USD"' in result
    assert '"date":"2026-06-29"' in result


def test_http_short_url_seed_calls_mock_endpoint(monkeypatch):
    """短网址生成 (is.gd) — body is forwarded verbatim."""
    from lumen_services.skill_executors.http import HttpExecutor
    s = _make_skill("http", type_config={
        "url": SHORT_URL_API,
        "method": "GET",
        "headers": {"Accept": "application/json"},
        "timeout": 10,
    })
    _patch_http_for_test(
        monkeypatch,
        allowed_domain="is.gd",
        body=_SHORT_URL_BODY,
    )
    exe = HttpExecutor()
    tool = exe.to_langchain_tool(s, tenant_id=1)
    result = tool.run({})
    assert "shorturl" in result
    assert "is.gd/AbCdE" in result


def test_http_seed_blocks_non_allowlisted_domain(monkeypatch):
    """A host NOT in the allowlist → SkillSecurityError.

    Mirrors the production path: an admin deletes api.open-meteo.com
    from SystemConfig and the executor fail-closed blocks the call.
    The executor wraps the error in a string ("SecurityError: ...")
    so callers can show it directly to the LLM stream.
    """
    from lumen_services.skill_executors.http import HttpExecutor
    from lumen_services.skill_executors import http as http_exec
    from lumen_core.sandbox import http_caller

    s = _make_skill("http", type_config={
        "url": "https://evil.example.com/x",
        "method": "GET",
        "timeout": 5,
    })
    # Allowlist excludes the test target domain → should fail-closed.
    monkeypatch.setattr(http_exec, "_resolve_allowed_domains",
                        lambda: ["api.frankfurter.app"])
    # Bypass real DNS so the SSRF pre-check passes and the allowlist
    # gate is the only obstacle (otherwise we hit network errors
    # before the security gate fires).
    monkeypatch.setattr(http_caller, "_resolve_host_to_ip",
                        lambda host: "203.0.113.1")

    exe = HttpExecutor()
    tool = exe.to_langchain_tool(s, tenant_id=1)
    result = tool.run({})
    assert "SecurityError" in result, f"expected SecurityError, got: {result!r}"
    assert "not in allowlist" in result, (
        f"expected 'not in allowlist' message, got: {result!r}"
    )
