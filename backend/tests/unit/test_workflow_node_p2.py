"""P2 workflow node tests (CodeNode and subsequent P2 nodes)."""
import asyncio

import pytest

from lumen_core.workflow.variable_pool import VariablePool

# ===== CodeNode =====

from lumen_core.workflow.nodes.code import CodeNode, CodeNodeData


def _make_code_node(config: dict) -> CodeNode:
    pool = VariablePool()
    pool.add(["input", "user_query"], "USER_QUERY")
    return CodeNode(
        node_id="c1", config=config, pool=pool, db=None, tenant_id=1
    )


def test_code_node_basic_arithmetic():
    n = _make_code_node({"code": "RESULT = 1 + 1", "output_var": "RESULT"})
    r = asyncio.run(n._run())
    assert r.output_values["result"] == 2
    assert r.output_values["stdout"] == ""
    assert r.output_values["error"] is None


def test_code_node_inputs_mapping_resolves_pool():
    n = _make_code_node({
        "code": "RESULT = x.upper()",
        "inputs_mapping": {"x": "input.user_query"},
        "output_var": "RESULT",
    })
    r = asyncio.run(n._run())
    assert r.output_values["result"] == "USER_QUERY"


def test_code_node_print_captured_in_stdout():
    n = _make_code_node({
        "code": "print('hello')\nRESULT = 42",
        "output_var": "RESULT",
    })
    r = asyncio.run(n._run())
    assert r.output_values["stdout"] == "hello\n"
    assert r.output_values["result"] == 42


def test_code_node_import_blocked_raises_name_error():
    n = _make_code_node({"code": "import os\nRESULT = os.listdir()"})
    with pytest.raises(NameError):
        asyncio.run(n._run())


def test_code_node_open_blocked_raises_name_error():
    n = _make_code_node({"code": "open('/etc/passwd')\nRESULT = None"})
    with pytest.raises(NameError):
        asyncio.run(n._run())


def test_code_node_syntax_error_raises_value_error():
    n = _make_code_node({"code": "def broken(:\n  pass\nRESULT = None"})
    with pytest.raises(ValueError, match="compile error"):
        asyncio.run(n._run())


def test_code_node_result_not_set_returns_none():
    n = _make_code_node({"code": "x = 5"})
    r = asyncio.run(n._run())
    assert r.output_values["result"] is None
    assert r.output_values["error"] is None


def test_code_node_outputs_contains_three_vars():
    n = _make_code_node({"code": "RESULT = 1"})
    outs = n.outputs()
    names = {o.name for o in outs}
    assert names == {"stdout", "result", "error"}


def test_code_node_timeout_via_run_node_with_handling(monkeypatch):
    from lumen_core.workflow import executor_helpers
    pool = VariablePool()
    node = CodeNode(
        node_id="c1",
        config={"code": "RESULT = 1", "timeout": 0.05},
        pool=pool, db=None, tenant_id=1,
    )

    async def slow():
        import asyncio as _aio
        await _aio.sleep(1.0)
        return None

    monkeypatch.setattr(node, "_run", slow)
    with pytest.raises(Exception) as exc:
        asyncio.run(executor_helpers.run_node_with_handling(node))
    assert "timed out" in str(exc.value).lower() or "NodeRunError" in type(exc.value).__name__


def test_code_node_error_strategy_default_value(monkeypatch):
    from lumen_core.workflow import executor_helpers
    pool = VariablePool()
    node = CodeNode(
        node_id="c1",
        config={"code": "RESULT = 1", "error_strategy": "default_value", "default_value": {"answer": "fallback"}},
        pool=pool, db=None, tenant_id=1,
    )

    async def fail():
        raise RuntimeError("boom")
    monkeypatch.setattr(node, "_run", fail)
    r = asyncio.run(executor_helpers.run_node_with_handling(node))
    assert r.output_values == {"answer": "fallback"}
    assert "boom" in r.error


def test_code_node_inputs_mapping_nested_path_resolves():
    n = _make_code_node({
        "code": "RESULT = x",
        "inputs_mapping": {"x": "input.user_query"},
        "output_var": "RESULT",
    })
    r = asyncio.run(n._run())
    assert r.output_values["result"] == "USER_QUERY"


def test_code_node_concurrent_invocation_isolated():
    """10 个 CodeNode 并发跑,各自有自己的 pool,结果不串。"""
    import concurrent.futures

    def run_one(i):
        pool = VariablePool()
        node = CodeNode(
            node_id=f"c{i}",
            config={"code": f"RESULT = {i} * 2", "output_var": "RESULT"},
            pool=pool, db=None, tenant_id=1,
        )
        return asyncio.run(node._run()).output_values["result"]

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
        results = list(ex.map(run_one, range(10)))
    assert sorted(results) == [i * 2 for i in range(10)]


# ===== HTTPNode =====
# (Most HTTPNode tests are in test_workflow_node_p2_http_integration.py with a real
#  httpx mock server. Here we cover simple auth and body logic with monkeypatched httpx.)

from lumen_core.workflow.nodes.http import HTTPNode, HTTPNodeData
import lumen_core.workflow.nodes.http as http_mod


def _make_http_node(config: dict) -> HTTPNode:
    pool = VariablePool()
    return HTTPNode(node_id="h1", config=config, pool=pool, db=None, tenant_id=1)


def test_http_node_outputs_declaration():
    n = _make_http_node({"method": "GET", "url": "https://x.example"})
    outs = n.outputs()
    assert {o.name for o in outs} == {"status_code", "headers", "body", "error"}


def test_http_node_bearer_auth_adds_header(monkeypatch):
    captured = {}

    class _FakeResponse:
        status_code = 200
        headers = {"content-type": "application/json"}
        text = '{"ok": true}'

        def json(self):
            return {"ok": True}

    class _FakeClient:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def request(self, method, url, headers=None, **kw):
            captured["headers"] = headers
            return _FakeResponse()

    monkeypatch.setattr(http_mod.httpx, "AsyncClient", _FakeClient)
    n = _make_http_node({
        "method": "GET", "url": "https://x.example",
        "auth_type": "bearer", "auth_config": {"token": "abc"},
    })
    r = asyncio.run(n._run())
    assert captured["headers"]["Authorization"] == "Bearer abc"
    assert r.output_values["status_code"] == 200
    assert r.output_values["body"] == {"ok": True}


def test_http_node_basic_auth_base64(monkeypatch):
    import base64
    captured = {}

    class _FakeResponse:
        status_code = 200
        headers = {}
        text = "{}"
        def json(self): return {}

    class _FakeClient:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def request(self, method, url, headers=None, **kw):
            captured["headers"] = headers
            return _FakeResponse()

    monkeypatch.setattr(http_mod.httpx, "AsyncClient", _FakeClient)
    n = _make_http_node({
        "method": "GET", "url": "https://x.example",
        "auth_type": "basic", "auth_config": {"username": "u", "password": "p"},
    })
    asyncio.run(n._run())
    expected = "Basic " + base64.b64encode(b"u:p").decode()
    assert captured["headers"]["Authorization"] == expected


def test_http_node_api_key_auth_uses_custom_header(monkeypatch):
    captured = {}

    class _FakeResponse:
        status_code = 200
        headers = {}
        text = "{}"
        def json(self): return {}

    class _FakeClient:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def request(self, method, url, headers=None, **kw):
            captured["headers"] = headers
            return _FakeResponse()

    monkeypatch.setattr(http_mod.httpx, "AsyncClient", _FakeClient)
    n = _make_http_node({
        "method": "GET", "url": "https://x.example",
        "auth_type": "api_key",
        "auth_config": {"header_name": "X-API-Key", "api_key": "k123"},
    })
    asyncio.run(n._run())
    assert captured["headers"]["X-API-Key"] == "k123"


def test_http_node_custom_header_auth(monkeypatch):
    captured = {}

    class _FakeResponse:
        status_code = 200
        headers = {}
        text = "{}"
        def json(self): return {}

    class _FakeClient:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def request(self, method, url, headers=None, **kw):
            captured["headers"] = headers
            return _FakeResponse()

    monkeypatch.setattr(http_mod.httpx, "AsyncClient", _FakeClient)
    n = _make_http_node({
        "method": "GET", "url": "https://x.example",
        "auth_type": "custom_header",
        "auth_config": {"X-Foo": "bar", "X-Baz": "qux"},
    })
    asyncio.run(n._run())
    assert captured["headers"]["X-Foo"] == "bar"
    assert captured["headers"]["X-Baz"] == "qux"


def test_http_node_url_template_renders():
    pool = VariablePool()
    pool.add(["input", "user_id"], "42")
    n = HTTPNode(
        node_id="h1",
        config={"method": "GET", "url": "https://x.example/users/{{#input.user_id#}}"},
        pool=pool, db=None, tenant_id=1,
    )
    rendered = n._render_url()
    assert rendered == "https://x.example/users/42"


def test_http_node_body_json_serialized(monkeypatch):
    captured = {}

    class _FakeResponse:
        status_code = 201
        headers = {}
        text = ""
        def json(self): return {}

    class _FakeClient:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def request(self, method, url, headers=None, params=None,
                          content=None, json=None, data=None):
            captured["content"] = content
            captured["json"] = json
            captured["data"] = data
            return _FakeResponse()

    monkeypatch.setattr(http_mod.httpx, "AsyncClient", _FakeClient)
    n = _make_http_node({
        "method": "POST", "url": "https://x.example",
        "body_type": "json", "body": {"k": "v"},
    })
    asyncio.run(n._run())
    # body_type="json" with dict body → httpx receives json= (not content=)
    assert captured["json"] == {"k": "v"}
    assert captured["content"] is None
    assert captured["data"] is None


def test_http_node_non_json_response_returns_text(monkeypatch):
    class _FakeResponse:
        status_code = 200
        headers = {}
        text = "plain text"
        def json(self):
            raise ValueError("not json")

    class _FakeClient:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def request(self, **kw): return _FakeResponse()

    monkeypatch.setattr(http_mod.httpx, "AsyncClient", _FakeClient)
    n = _make_http_node({"method": "GET", "url": "https://x.example"})
    r = asyncio.run(n._run())
    assert r.output_values["body"] == "plain text"


def test_http_node_no_method_raises_value_error():
    # Pydantic default is "GET", so we need to explicitly pass empty string
    n = _make_http_node({"url": "https://x.example", "method": ""})
    with pytest.raises(ValueError):
        asyncio.run(n._run())


def test_http_node_no_url_raises_value_error():
    n = _make_http_node({"method": "GET"})
    with pytest.raises(ValueError):
        asyncio.run(n._run())


def test_http_node_verify_ssl_passed_to_client(monkeypatch):
    captured = {}

    class _FakeClient:
        def __init__(self, **kw):
            captured.update(kw)
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def request(self, **kw):
            class _R:
                status_code = 200
                headers = {}
                text = ""
                def json(self): return {}
            return _R()

    monkeypatch.setattr(http_mod.httpx, "AsyncClient", _FakeClient)
    n = _make_http_node({
        "method": "GET", "url": "https://x.example",
        "verify_ssl": False, "follow_redirects": False,
    })
    asyncio.run(n._run())
    assert captured["verify"] is False
    assert captured["follow_redirects"] is False


def test_http_node_query_params_rendered(monkeypatch):
    captured = {}

    class _FakeResponse:
        status_code = 200
        headers = {}
        text = "{}"
        def json(self): return {}

    class _FakeClient:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def request(self, method, url, headers=None, params=None, **kw):
            captured["params"] = params
            return _FakeResponse()

    monkeypatch.setattr(http_mod.httpx, "AsyncClient", _FakeClient)
    n = _make_http_node({
        "method": "GET", "url": "https://x.example",
        "query_params": {"q": "{{#input.q#}}"},
    })
    n.pool.add(["input", "q"], "hello")
    asyncio.run(n._run())
    assert captured["params"] == {"q": "hello"}


def test_http_node_body_form_dict_uses_data_kwarg(monkeypatch):
    """form body type with dict body should pass to httpx as data= (URL-encoded)."""
    captured = {}

    class _FakeResponse:
        status_code = 200
        headers = {}
        text = "{}"
        def json(self): return {}

    class _FakeClient:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def request(self, method, url, headers=None, params=None,
                          content=None, json=None, data=None):
            captured["data"] = data
            captured["content"] = content
            captured["json"] = json
            return _FakeResponse()

    monkeypatch.setattr(http_mod.httpx, "AsyncClient", _FakeClient)
    n = _make_http_node({
        "method": "POST", "url": "https://x.example",
        "body_type": "form", "body": {"key": "value"},
    })
    asyncio.run(n._run())
    assert captured["data"] == {"key": "value"}
    assert captured["content"] is None
    assert captured["json"] is None


def test_http_node_body_raw_string_template_rendered(monkeypatch):
    """raw body type with string body should pass to httpx as content= after template render."""
    captured = {}

    class _FakeResponse:
        status_code = 200
        headers = {}
        text = "{}"
        def json(self): return {}

    class _FakeClient:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def request(self, method, url, headers=None, params=None,
                          content=None, json=None, data=None):
            captured["content"] = content
            captured["json"] = json
            captured["data"] = data
            return _FakeResponse()

    monkeypatch.setattr(http_mod.httpx, "AsyncClient", _FakeClient)
    n = _make_http_node({
        "method": "POST", "url": "https://x.example",
        "body_type": "raw", "body": "hello {{#input.name#}}",
    })
    n.pool.add(["input", "name"], "world")
    asyncio.run(n._run())
    assert captured["content"] == "hello world"
    assert captured["json"] is None
    assert captured["data"] is None


# ===== ToolNode =====

from lumen_core.workflow.nodes.tool import ToolNode, ToolNodeData


class _FakeMCPTool:
    """测试替身:mock MCPTool ORM 行。"""
    def __init__(self, id, name, tenant_id=1, is_active=True):
        self.id = id
        self.name = name
        self.tenant_id = tenant_id
        self.is_active = is_active  # 抽象为 bool;fake filter 同时接受 is_active= 和 is_enabled=


class _FakeMCPService:
    """测试替身:mock MCPService.execute_tool。

    真实签名是 ``async def execute_tool(self, db, tenant_id, tool_name, input_data)``,
    返回 MCP 协议 ``result`` 形状 ``{"content": [...], "isError": bool}``。
    """
    def __init__(self, db):
        self.db = db
        self.calls = []

    async def execute_tool(self, db, tenant_id, tool_name, input_data):
        self.calls.append({
            "db": db, "tenant_id": tenant_id,
            "tool_name": tool_name, "input_data": input_data,
        })
        return {
            "content": [{"type": "text", "text": repr(input_data)}],
            "isError": False,
        }


class _ToolDB:
    """最小 db fake:支持 chainable query/filter/filter_by + first。

    filter_by 真实地根据 kwargs 判定是否命中,而不是无脑返回 self。
    """
    def __init__(self, tool):
        self._tool = tool
        self._matches = tool is not None
        self.mcp_service = None

    def query(self, *a, **kw):
        return self

    def filter(self, *a, **kw):
        return self

    def filter_by(self, **kw):
        if self._tool is None:
            self._matches = False
            return self
        # id 匹配
        if "id" in kw and kw["id"] != self._tool.id:
            self._matches = False
        # active 判定(同时支持 is_active=bool 与 is_enabled=1 两种 kwarg)
        if "is_active" in kw and bool(kw["is_active"]) != self._tool.is_active:
            self._matches = False
        if "is_enabled" in kw and bool(kw["is_enabled"]) != self._tool.is_active:
            self._matches = False
        return self

    def first(self):
        return self._tool if self._matches else None


def _make_tool_node(config: dict, tool: _FakeMCPTool | None = None) -> ToolNode:
    db = _ToolDB(tool)
    db.mcp_service = _FakeMCPService(db)
    pool = VariablePool()
    return ToolNode(node_id="t1", config=config, pool=pool, db=db, tenant_id=1)


def test_tool_node_outputs_declaration():
    n = _make_tool_node({"tool_id": 1})
    assert {o.name for o in n.outputs()} == {"result", "is_error", "error"}


def test_tool_node_executes_active_tool():
    tool = _FakeMCPTool(id=1, name="search", tenant_id=1)
    n = _make_tool_node({"tool_id": 1, "arguments": {"q": "x"}}, tool=tool)
    r = asyncio.run(n._run())
    # MCPService 返回的 result.content 数组映射到 output_values["result"]
    assert r.output_values["result"] == [{"type": "text", "text": repr({"q": "x"})}]
    assert r.output_values["is_error"] is False
    assert r.output_values["error"] is None
    # 调用链:ToolNode 透传 tenant_id + tool_name + 渲染后的 arguments
    last_call = n.db.mcp_service.calls[-1]
    assert last_call["tenant_id"] == 1
    assert last_call["tool_name"] == "search"
    assert last_call["input_data"] == {"q": "x"}


def test_tool_node_not_found_raises_value_error():
    n = _make_tool_node({"tool_id": 99, "arguments": {}}, tool=None)
    with pytest.raises(ValueError, match="not found"):
        asyncio.run(n._run())


def test_tool_node_inactive_raises():
    tool = _FakeMCPTool(id=1, name="x", is_active=False)
    n = _make_tool_node({"tool_id": 1, "arguments": {}}, tool=tool)
    with pytest.raises(ValueError, match="not found"):
        asyncio.run(n._run())


def test_tool_node_cross_tenant_raises():
    tool = _FakeMCPTool(id=1, name="x", tenant_id=2)
    n = _make_tool_node({"tool_id": 1, "arguments": {}}, tool=tool)
    with pytest.raises(ValueError, match="not found"):
        asyncio.run(n._run())


def test_tool_node_arguments_template_rendered():
    tool = _FakeMCPTool(id=1, name="x", tenant_id=1)
    n = _make_tool_node({
        "tool_id": 1,
        "arguments": {"q": "{{#input.user_query#}}", "raw": 42},
    }, tool=tool)
    n.pool.add(["input", "user_query"], "hello world")
    r = asyncio.run(n._run())
    db_call = n.db.mcp_service.calls[-1]
    # 字符串值走模板渲染,非字符串原样透传
    assert db_call["input_data"]["q"] == "hello world"
    assert db_call["input_data"]["raw"] == 42


def test_tool_node_returns_is_error_when_tool_says_so():
    tool = _FakeMCPTool(id=1, name="x", tenant_id=1)
    n = _make_tool_node({"tool_id": 1, "arguments": {}}, tool=tool)

    async def _bad_svc(db, tenant_id, tool_name, input_data):
        return {"content": None, "isError": True, "error": "tool said no"}

    n.db.mcp_service.execute_tool = _bad_svc
    r = asyncio.run(n._run())
    assert r.output_values["is_error"] is True
    assert r.output_values["error"] == "tool said no"


def test_tool_node_missing_tool_id_raises():
    n = _make_tool_node({"arguments": {}})
    with pytest.raises(ValueError):
        asyncio.run(n._run())


def test_tool_node_timeout_via_handler():
    from lumen_core.workflow import executor_helpers
    from lumen_core.workflow.retry import NodeRunError
    n = _make_tool_node({"tool_id": 1, "timeout": 0.05})
    tool = _FakeMCPTool(id=1, name="x", tenant_id=1)
    n.db = _ToolDB(tool)
    n.db.mcp_service = _FakeMCPService(n.db)

    async def slow_exec(db, tenant_id, tool_name, input_data):
        import asyncio as _a
        await _a.sleep(1.0)
        return {}

    n.db.mcp_service.execute_tool = slow_exec
    with pytest.raises(NodeRunError) as exc:
        asyncio.run(executor_helpers.run_node_with_handling(n))
    assert "timed out" in str(exc.value).lower()


def test_tool_node_error_strategy_default_value():
    from lumen_core.workflow import executor_helpers
    n = _make_tool_node({
        "tool_id": 1,
        "error_strategy": "default_value",
        "default_value": {"result": "fallback", "is_error": True, "error": "n/a"},
    })
    # No tool configured → _run raises ValueError → executor_helpers 应用 default_value
    r = asyncio.run(executor_helpers.run_node_with_handling(n))
    assert r.output_values["result"] == "fallback"
    assert r.output_values["is_error"] is True
    assert "not found" in r.error


# ===== KnowledgeRetrievalNode =====

from lumen_core.workflow.nodes.knowledge_retrieval import (
    KnowledgeRetrievalNode, KnowledgeRetrievalNodeData,
)


class _FakeKB:
    """测试替身:mock KnowledgeBase ORM 行。"""

    def __init__(self, id, tenant_id=1, is_active=True, embedding_model_config_id=0):
        self.id = id
        self.tenant_id = tenant_id
        # KnowledgeBase 真实字段是 status="active";"is_active" 仅作 fake 抽象,
        # 节点的 .filter(... status == "active") 不会被 fake 走 — 我们用
        # ``_KBDB`` 跳过这一层(它不模拟 filter 链),直接 first() 给出 KB。
        self.is_active = is_active
        # M28 后 ``get_retrieval_pipeline`` 必须收到 ``model_config_id`` 才能构造
        # collection name;fake 默认 0 让旧测试不动,新测试可以 override。
        self.embedding_model_config_id = embedding_model_config_id


class _FakePipeline:
    """测试替身:mock RetrievalPipeline。``search(**kw)`` 记录全部 kwargs。"""

    def __init__(self, results):
        self.results = results
        self.calls: list[dict] = []

    async def search(self, **kw):
        self.calls.append(kw)
        return self.results


class _KBDB:
    """最小 db fake:支持 chainable query/filter/filter_by + first。"""

    def __init__(self, kb):
        self._kb = kb
        self.pipeline: _FakePipeline | None = None

    def query(self, *a, **kw):
        return self

    def filter(self, *a, **kw):
        return self

    def filter_by(self, **kw):
        return self

    def first(self):
        return self._kb


def _make_kb_node(
    config: dict, kb: _FakeKB | None = None, results: list | None = None
) -> KnowledgeRetrievalNode:
    """构造 KnowledgeRetrievalNode,带 fake db + 通过 monkeypatch 注入 fake pipeline。

    调用方需要自己 ``monkeypatch.setattr(svc, "get_retrieval_pipeline", ...)``:
    ``_FakePipeline.search(**kw)`` 接受任意 kwargs。
    """
    db = _KBDB(kb)
    db.pipeline = _FakePipeline(results if results is not None else [])
    pool = VariablePool()
    return KnowledgeRetrievalNode(
        node_id="k1", config=config, pool=pool, db=db, tenant_id=1
    )


def _patch_kb_pipeline(monkeypatch, db: _KBDB):
    """把 ``app.services.retrieval.get_retrieval_pipeline`` 替换成返回 ``db.pipeline`` 的 lambda。

    M28 后 ``get_retrieval_pipeline`` 签名是 3-arg ``(kb_id, model_config_id, db)``,
    mock lambda 必须匹配(测试 fixture 跟破损实现同 typo 是 M28 升级最常见的坑)。
    """
    import lumen_services.retrieval as svc
    monkeypatch.setattr(
        svc, "get_retrieval_pipeline", lambda kb_id, model_config_id, db: db.pipeline
    )


def test_kb_node_outputs_declaration():
    n = _make_kb_node({"kb_id": 1})
    assert {o.name for o in n.outputs()} == {"chunks", "merged_text", "count", "error"}


def test_kb_node_returns_chunks(monkeypatch):
    results = [
        {"id": "c1", "content": "Hello", "score": 0.9, "source": "doc1", "metadata": {}},
        {"id": "c2", "content": "World", "score": 0.7, "source": "doc2", "metadata": {}},
    ]
    n = _make_kb_node(
        {"kb_id": 1, "query": "q", "top_k": 5},
        kb=_FakeKB(1),
        results=results,
    )
    _patch_kb_pipeline(monkeypatch, n.db)
    r = asyncio.run(n._run())
    assert r.output_values["count"] == 2
    assert r.output_values["chunks"][0]["chunk_id"] == "c1"
    assert "Hello" in r.output_values["merged_text"]
    assert "World" in r.output_values["merged_text"]


def test_kb_node_empty_results(monkeypatch):
    n = _make_kb_node(
        {"kb_id": 1, "query": "q"},
        kb=_FakeKB(1),
        results=[],
    )
    _patch_kb_pipeline(monkeypatch, n.db)
    r = asyncio.run(n._run())
    assert r.output_values["count"] == 0
    assert r.output_values["merged_text"] == ""
    assert r.output_values["chunks"] == []


def test_kb_node_score_threshold_passed_to_pipeline(monkeypatch):
    n = _make_kb_node(
        {"kb_id": 1, "query": "q", "score_threshold": 0.5},
        kb=_FakeKB(1),
    )
    _patch_kb_pipeline(monkeypatch, n.db)
    asyncio.run(n._run())
    call = n.db.pipeline.calls[-1]
    # 节点把 score_threshold 折叠进 filter_expr 供真实 pipeline 使用。
    # 注意:score_threshold 不再作为独立 kwarg 传给 pipeline(真实签名只支持
    # query/k/filter_expr/rerank);过滤后的 kwargs 集合见 _build_search_kwargs。
    # filter_expr 也应包含 score 阈值(供 _normalise_filter 之外的 ES DSL 使用)
    assert "0.5" in call["filter_expr"]


def test_kb_node_rerank_flag_passed(monkeypatch):
    n = _make_kb_node(
        {"kb_id": 1, "query": "q", "rerank_enabled": False},
        kb=_FakeKB(1),
    )
    _patch_kb_pipeline(monkeypatch, n.db)
    asyncio.run(n._run())
    call = n.db.pipeline.calls[-1]
    assert call["rerank"] is False


def test_kb_node_hybrid_flag_passed(monkeypatch):
    n = _make_kb_node(
        {"kb_id": 1, "query": "q", "hybrid_search": False},
        kb=_FakeKB(1),
    )
    _patch_kb_pipeline(monkeypatch, n.db)
    asyncio.run(n._run())
    # ``hybrid_search`` 是 ``**kwargs`` 透传配置,真实 ``RetrievalPipeline.search``
    # 不接受此参数(永远 hybrid),所以被 ``_build_search_kwargs`` 过滤掉。
    # 这里直接断言节点数据保留了配置(配置仍存在于 ``KnowledgeRetrievalNodeData`` 中,
    # 留作未来扩展或 fake pipeline 兼容)。
    assert isinstance(n._data, KnowledgeRetrievalNodeData)
    assert n._data.hybrid_search is False


def test_kb_node_query_template_rendered(monkeypatch):
    n = _make_kb_node(
        {"kb_id": 1, "query": "{{#input.user_query#}}"},
        kb=_FakeKB(1),
    )
    _patch_kb_pipeline(monkeypatch, n.db)
    n.pool.add(["input", "user_query"], "what is AI")
    asyncio.run(n._run())
    call = n.db.pipeline.calls[-1]
    assert call["query"] == "what is AI"


def test_kb_node_not_found_raises(monkeypatch):
    n = _make_kb_node(
        {"kb_id": 99, "query": "q"},
        kb=None,
    )
    _patch_kb_pipeline(monkeypatch, n.db)
    with pytest.raises(ValueError, match="not found"):
        asyncio.run(n._run())


def test_kb_node_cross_tenant_raises(monkeypatch):
    kb = _FakeKB(1, tenant_id=2)
    n = _make_kb_node(
        {"kb_id": 1, "query": "q"},
        kb=kb,
    )
    _patch_kb_pipeline(monkeypatch, n.db)
    with pytest.raises(ValueError, match="not found"):
        asyncio.run(n._run())


def test_kb_node_default_value_strategy_on_failure(monkeypatch):
    from lumen_core.workflow import executor_helpers

    class _FailingPipeline:
        async def search(self, **kw):
            raise RuntimeError("nope")

    n = _make_kb_node(
        {
            "kb_id": 1,
            "query": "q",
            "error_strategy": "default_value",
            "default_value": {
                "chunks": [],
                "merged_text": "",
                "count": 0,
                "error": None,
            },
        },
        kb=_FakeKB(1),
    )
    # 直接 patch 成抛错的 pipeline
    import lumen_services.retrieval as svc
    monkeypatch.setattr(
        svc, "get_retrieval_pipeline", lambda kb_id, model_config_id, db: _FailingPipeline()
    )
    r = asyncio.run(executor_helpers.run_node_with_handling(n))
    assert r.output_values["count"] == 0
    assert r.output_values["chunks"] == []


# ===== TemplateTransformNode =====

from lumen_core.workflow.nodes.template_transform import (
    TemplateTransformNode, TemplateTransformNodeData,
)


def _make_tt_node(config: dict) -> TemplateTransformNode:
    from lumen_core.workflow.variable_pool import VariablePool
    pool = VariablePool()
    pool.add(["llm", "response"], "hello")
    pool.add(["items", "list"], [1, 2, 3])  # 2-element selector (plan's 1-element would crash)
    return TemplateTransformNode(node_id="t1", config=config, pool=pool, db=None, tenant_id=1)


def test_tt_node_outputs_declaration():
    n = _make_tt_node({"template": "x"})
    assert {o.name for o in n.outputs()} == {"output", "error"}


def test_tt_node_simple_interpolation():
    n = _make_tt_node({"template": "{{ llm.response }}"})
    r = asyncio.run(n._run())
    assert r.output_values["output"] == "hello"


def test_tt_node_conditional():
    n = _make_tt_node({"template": "{% if llm.response %}YES{% else %}NO{% endif %}"})
    r = asyncio.run(n._run())
    assert r.output_values["output"] == "YES"


def test_tt_node_loop():
    n = _make_tt_node({"template": "{% for i in items.list %}{{ i }}\n{% endfor %}"})
    r = asyncio.run(n._run())
    assert "1\n2\n3" in r.output_values["output"]


def test_tt_node_filter():
    n = _make_tt_node({"template": "{{ llm.response | upper }}"})
    r = asyncio.run(n._run())
    assert r.output_values["output"] == "HELLO"


def test_tt_node_strict_undefined_raises():
    n = _make_tt_node({"template": "{{ missing_thing }}"})
    with pytest.raises(ValueError, match="Template error"):
        asyncio.run(n._run())


def test_tt_node_syntax_error_raises():
    n = _make_tt_node({"template": "{% if x %}oops"})
    with pytest.raises(ValueError, match="Template error"):
        asyncio.run(n._run())


def test_tt_node_autoescape_off_html_passes_through():
    n = _make_tt_node({"template": "<b>{{ llm.response }}</b>"})
    r = asyncio.run(n._run())
    assert r.output_values["output"] == "<b>hello</b>"


# ===== ParameterExtractorNode =====

from lumen_core.workflow.nodes.parameter_extractor import (
    ParameterExtractorNode, ParameterExtractorNodeData, ParameterDef,
)


class _FakeChat:
    def __init__(self, content):
        self.content = content
    async def ainvoke(self, prompt):
        class _R:
            def __init__(self, c): self.content = c
        return _R(self.content)


class _FakeModelConfig:
    def __init__(self, id=1, model_type="ollama", model_name="x", is_active=True, tenant_id=1):
        self.id = id; self.model_type = model_type; self.model_name = model_name
        self.is_active = is_active; self.tenant_id = tenant_id
        self.base_url = None; self.api_key = None


class _PEDB:
    def __init__(self, mc):
        self._mc = mc
    def query(self, *a, **kw): return self
    def filter(self, *a, **kw): return self
    def filter_by(self, **kw): return self
    def first(self): return self._mc


def _make_pe_node(config: dict, llm_content: str = '{"name":"Alice","age":30}') -> ParameterExtractorNode:
    from lumen_core.workflow.variable_pool import VariablePool
    pool = VariablePool()
    mc = _FakeModelConfig()
    db = _PEDB(mc)
    node = ParameterExtractorNode(
        node_id="p1", config=config, pool=pool, db=db, tenant_id=1
    )
    # Patch create_chat_model to return a fake chat
    from lumen_core.workflow.nodes import parameter_extractor as mod
    mod.create_chat_model = lambda **kw: _FakeChat(llm_content)
    return node


def test_pe_node_outputs_includes_each_parameter():
    cfg = {
        "model_config_id": 1,
        "input_text": "Alice is 30 years old",
        "parameters": [
            ParameterDef(name="name", type="string", description="the name", required=True).model_dump(),
            ParameterDef(name="age", type="number", description="age", required=True).model_dump(),
        ],
    }
    n = _make_pe_node(cfg)
    outs = n.outputs()
    assert "name" in {o.name for o in outs}
    assert "age" in {o.name for o in outs}
    assert "_raw" in {o.name for o in outs}
    assert "_error" in {o.name for o in outs}


def test_pe_node_extracts_parameters():
    cfg = {
        "model_config_id": 1,
        "input_text": "Alice is 30",
        "parameters": [
            ParameterDef(name="name", type="string", description="name", required=True).model_dump(),
            ParameterDef(name="age", type="number", description="age", required=True).model_dump(),
        ],
    }
    n = _make_pe_node(cfg, llm_content='{"name":"Alice","age":30}')
    r = asyncio.run(n._run())
    assert r.output_values["name"] == "Alice"
    assert r.output_values["age"] == 30.0
    assert r.output_values["_error"] is None


def test_pe_node_non_json_response_raises():
    cfg = {
        "model_config_id": 1,
        "input_text": "x",
        "parameters": [ParameterDef(name="a", type="string", description="x").model_dump()],
    }
    n = _make_pe_node(cfg, llm_content="not json at all")
    with pytest.raises(ValueError, match="non-JSON"):
        asyncio.run(n._run())


def test_pe_node_required_parameter_missing_raises():
    cfg = {
        "model_config_id": 1,
        "input_text": "x",
        "parameters": [ParameterDef(name="a", type="string", description="x", required=True).model_dump()],
    }
    n = _make_pe_node(cfg, llm_content='{"other": 1}')
    with pytest.raises(ValueError, match="missing"):
        asyncio.run(n._run())


def test_pe_node_type_coercion_string_to_number():
    cfg = {
        "model_config_id": 1,
        "input_text": "x",
        "parameters": [ParameterDef(name="n", type="number", description="x").model_dump()],
    }
    n = _make_pe_node(cfg, llm_content='{"n": "3.5"}')
    r = asyncio.run(n._run())
    assert r.output_values["n"] == 3.5


def test_pe_node_model_inactive_raises():
    from lumen_core.workflow.nodes import parameter_extractor as mod
    from lumen_core.workflow.variable_pool import VariablePool
    db = _PEDB(None)  # no model
    n = ParameterExtractorNode(
        node_id="p1",
        config={"model_config_id": 99, "input_text": "x", "parameters": []},
        pool=VariablePool(), db=db, tenant_id=1,
    )
    with pytest.raises(ValueError, match="not found"):
        asyncio.run(n._run())


def test_pe_node_model_cross_tenant_raises():
    mc = _FakeModelConfig(tenant_id=2)
    from lumen_core.workflow.variable_pool import VariablePool
    db = _PEDB(mc)
    n = ParameterExtractorNode(
        node_id="p1",
        config={"model_config_id": 1, "input_text": "x", "parameters": []},
        pool=VariablePool(), db=db, tenant_id=1,
    )
    with pytest.raises(ValueError, match="not found"):
        asyncio.run(n._run())


def test_pe_node_input_text_template_rendered():
    cfg = {
        "model_config_id": 1,
        "input_text": "{{#input.user_query#}}",
        "parameters": [],
    }
    n = _make_pe_node(cfg, llm_content="{}")
    n.pool.add(["input", "user_query"], "some text")
    asyncio.run(n._run())  # asserts no error → template rendered without crashing


def test_pe_node_empty_schema_returns_just_raw():
    cfg = {"model_config_id": 1, "input_text": "x", "parameters": []}
    n = _make_pe_node(cfg, llm_content="{}")
    r = asyncio.run(n._run())
    assert r.output_values["_raw"] == "{}"
    # No user-defined outputs
    assert "name" not in r.output_values


def test_pe_node_outputs_count_matches():
    cfg = {
        "model_config_id": 1, "input_text": "x",
        "parameters": [ParameterDef(name=f"p{i}", type="string", description="x").model_dump() for i in range(3)],
    }
    n = _make_pe_node(cfg)
    outs = n.outputs()
    # 3 user params + 2 system (_raw, _error)
    assert len(outs) == 5


# ===== QuestionClassifierNode =====

from lumen_core.workflow.nodes.question_classifier import (
    QuestionClassifierNode, QuestionClassifierNodeData, Category,
)


class _FakeChatQC:
    def __init__(self, content): self.content = content
    async def ainvoke(self, prompt):
        class _R:
            def __init__(self, c): self.content = c
        return _R(self.content)


class _QCDB:
    def __init__(self, mc):
        self._mc = mc
    def query(self, *a, **kw): return self
    def filter(self, *a, **kw): return self
    def filter_by(self, **kw): return self
    def first(self): return self._mc


def _make_qc_node(config: dict, content: str = "billing") -> QuestionClassifierNode:
    from lumen_core.workflow.variable_pool import VariablePool
    mc = _FakeModelConfig()
    db = _QCDB(mc)
    node = QuestionClassifierNode(
        node_id="q1", config=config, pool=VariablePool(), db=db, tenant_id=1
    )
    from lumen_core.workflow.nodes import question_classifier as mod
    mod.create_chat_model = lambda **kw: _FakeChatQC(content)
    return node


def test_qc_node_outputs_declaration():
    n = _make_qc_node({
        "model_config_id": 1, "input_text": "x",
        "categories": [Category(id="a", name="A", description="x").model_dump()],
    })
    assert {o.name for o in n.outputs()} == {"class_name", "class_id", "confidence", "_raw", "_error"}


def test_qc_node_classifies_correctly():
    n = _make_qc_node({
        "model_config_id": 1, "input_text": "my bill is wrong",
        "categories": [
            Category(id="billing", name="账单", description="billing issues").model_dump(),
            Category(id="tech", name="技术", description="tech issues").model_dump(),
        ],
    }, content="billing")
    r = asyncio.run(n._run())
    assert r.output_values["class_id"] == "billing"
    assert r.output_values["class_name"] == "账单"
    assert r.output_values["confidence"] == 1.0


def test_qc_node_unknown_class_raises():
    n = _make_qc_node({
        "model_config_id": 1, "input_text": "x",
        "categories": [Category(id="billing", name="账单", description="x").model_dump()],
    }, content="unknown_class")
    with pytest.raises(ValueError, match="unknown class"):
        asyncio.run(n._run())


def test_qc_node_strips_whitespace():
    n = _make_qc_node({
        "model_config_id": 1, "input_text": "x",
        "categories": [Category(id="billing", name="账单", description="x").model_dump()],
    }, content="  billing\n")
    r = asyncio.run(n._run())
    assert r.output_values["class_id"] == "billing"


def test_qc_node_empty_categories_raises():
    n = _make_qc_node({"model_config_id": 1, "input_text": "x", "categories": []})
    with pytest.raises(ValueError, match="至少一个"):
        asyncio.run(n._run())


def test_qc_node_input_template_rendered():
    n = _make_qc_node({
        "model_config_id": 1, "input_text": "{{#input.q#}}",
        "categories": [Category(id="a", name="A", description="x").model_dump()],
    }, content="a")
    n.pool.add(["input", "q"], "my question")
    asyncio.run(n._run())  # no error → rendered correctly


def test_qc_node_model_inactive_raises():
    from lumen_core.workflow.variable_pool import VariablePool
    db = _QCDB(None)
    n = QuestionClassifierNode(
        node_id="q1",
        config={"model_config_id": 99, "input_text": "x", "categories": [Category(id="a", name="A", description="x").model_dump()]},
        pool=VariablePool(), db=db, tenant_id=1,
    )
    with pytest.raises(ValueError, match="not found"):
        asyncio.run(n._run())


def test_qc_node_model_cross_tenant_raises():
    from lumen_core.workflow.variable_pool import VariablePool
    mc = _FakeModelConfig(tenant_id=2)
    n = QuestionClassifierNode(
        node_id="q1",
        config={"model_config_id": 1, "input_text": "x", "categories": [Category(id="a", name="A", description="x").model_dump()]},
        pool=VariablePool(), db=_QCDB(mc), tenant_id=1,
    )
    with pytest.raises(ValueError, match="not found"):
        asyncio.run(n._run())


def test_qc_node_default_value_strategy():
    from lumen_core.workflow import executor_helpers
    n = _make_qc_node({
        "model_config_id": 1, "input_text": "x",
        "categories": [Category(id="a", name="A", description="x").model_dump()],
        "error_strategy": "default_value",
        "default_value": {"class_id": "default", "class_name": "默认", "confidence": 0.0, "_raw": "", "_error": None},
    }, content="unknown")
    r = asyncio.run(executor_helpers.run_node_with_handling(n))
    assert r.output_values["class_id"] == "default"


def test_qc_node_instruction_template():
    n = _make_qc_node({
        "model_config_id": 1,
        "input_text": "x",
        "categories": [Category(id="a", name="A", description="x").model_dump()],
        "instruction": "{{#input.instr#}}",
    }, content="a")
    n.pool.add(["input", "instr"], "分类提示")
    asyncio.run(n._run())  # no error


# ===== VariableAssignerNode =====

from lumen_core.workflow.nodes.variable_assigner import (
    VariableAssignerNode, VariableAssignerNodeData, Assignment,
)


def _make_va_node(config: dict) -> VariableAssignerNode:
    from lumen_core.workflow.variable_pool import VariablePool
    pool = VariablePool()
    pool.add(["upstream", "x"], 10)
    pool.add(["upstream", "y"], 20)
    return VariableAssignerNode(node_id="va1", config=config, pool=pool, db=None, tenant_id=1)


def test_va_node_constant_assignment():
    n = _make_va_node({
        "operations": [
            Assignment(variable="foo", value_source="constant", constant_value=42).model_dump(),
        ]
    })
    r = asyncio.run(n._run())
    assert n.pool.get(["va1", "foo"]).value == 42
    assert r.output_values["_assigned"] == {"foo": 42}


def test_va_node_upstream_ref_assignment():
    n = _make_va_node({
        "operations": [
            Assignment(variable="x_copy", value_source="upstream_ref", upstream_ref=["upstream", "x"]).model_dump(),
        ]
    })
    r = asyncio.run(n._run())
    assert n.pool.get(["va1", "x_copy"]).value == 10


def test_va_node_expression_assignment():
    n = _make_va_node({
        "operations": [
            Assignment(variable="sum", value_source="expression", expression="upstream.x + upstream.y").model_dump(),
        ]
    })
    r = asyncio.run(n._run())
    assert n.pool.get(["va1", "sum"]).value == 30


def test_va_node_multiple_operations():
    n = _make_va_node({
        "operations": [
            Assignment(variable="a", value_source="constant", constant_value=1).model_dump(),
            Assignment(variable="b", value_source="constant", constant_value=2).model_dump(),
            Assignment(variable="c", value_source="constant", constant_value=3).model_dump(),
        ]
    })
    r = asyncio.run(n._run())
    assert r.output_values["_assigned"] == {"a": 1, "b": 2, "c": 3}


def test_va_node_upstream_ref_missing_raises():
    n = _make_va_node({
        "operations": [
            Assignment(variable="x", value_source="upstream_ref", upstream_ref=["upstream", "missing"]).model_dump(),
        ]
    })
    with pytest.raises(ValueError, match="upstream_ref"):
        asyncio.run(n._run())


def test_va_node_expression_syntax_error_raises():
    n = _make_va_node({
        "operations": [
            Assignment(variable="x", value_source="expression", expression="{{ broken").model_dump(),
        ]
    })
    with pytest.raises(ValueError, match="Template"):
        asyncio.run(n._run())


def test_va_node_outputs_dynamically_exposes_each_operation():
    n = _make_va_node({
        "operations": [
            Assignment(variable="a", value_source="constant", constant_value=1).model_dump(),
            Assignment(variable="b", value_source="constant", constant_value=2).model_dump(),
        ]
    })
    outs = n.outputs()
    names = {o.name for o in outs}
    assert "a" in names
    assert "b" in names
    assert "_assigned" in names
    assert "_error" in names


def test_va_node_timeout_does_not_affect_in_process():
    """Pure in-process, timeout=0.001 should not affect normal completion."""
    n = _make_va_node({
        "operations": [Assignment(variable="x", value_source="constant", constant_value=1).model_dump()],
        "timeout": 0.001,
    })
    r = asyncio.run(n._run())
    assert r.output_values["_assigned"] == {"x": 1}


def test_va_node_error_strategy_ignore_leaves_pool_untouched():
    from lumen_core.workflow import executor_helpers
    n = _make_va_node({
        "operations": [Assignment(variable="x", value_source="upstream_ref", upstream_ref=["upstream", "missing"]).model_dump()],
        "error_strategy": "ignore",
    })
    r = asyncio.run(executor_helpers.run_node_with_handling(n))
    # No new variable written under va1
    assert n.pool.get(["va1", "x"]).value is None
    assert r.output_values == {}


def test_va_node_cross_workflow_run_isolation():
    """Two different runs, same assigner pool config, don't share state."""
    from lumen_core.workflow.variable_pool import VariablePool
    p1 = VariablePool()
    p2 = VariablePool()
    for p in (p1, p2):
        n = VariableAssignerNode(
            node_id="va1",
            config={"operations": [Assignment(variable="v", value_source="constant", constant_value=42).model_dump()]},
            pool=p, db=None, tenant_id=1,
        )
        asyncio.run(n._run())
    assert p1.get(["va1", "v"]).value == 42
    assert p2.get(["va1", "v"]).value == 42
    # Pools are independent
    assert p1 is not p2


# ===== VariableAggregatorNode =====

from lumen_core.workflow.nodes.variable_aggregator import (
    VariableAggregatorNode, VariableAggregatorNodeData,
)


def _make_vagg_node(config: dict) -> VariableAggregatorNode:
    from lumen_core.workflow.variable_pool import VariablePool
    pool = VariablePool()
    pool.add(["upstream", "results"], [1, 2, 3])
    pool.add(["upstream", "strings"], ["a", "b"])
    return VariableAggregatorNode(node_id="vagg1", config=config, pool=pool, db=None, tenant_id=1)


def test_vagg_node_outputs_declaration():
    n = _make_vagg_node({"source_node_id": "upstream", "source_var": "results", "aggregation": "collect"})
    assert {o.name for o in n.outputs()} == {"output", "count", "_error"}


def test_vagg_collect():
    n = _make_vagg_node({"source_node_id": "upstream", "source_var": "results", "aggregation": "collect"})
    r = asyncio.run(n._run())
    assert r.output_values["output"] == [1, 2, 3]
    assert r.output_values["count"] == 3


def test_vagg_sum():
    n = _make_vagg_node({"source_node_id": "upstream", "source_var": "results", "aggregation": "sum"})
    r = asyncio.run(n._run())
    assert r.output_values["output"] == 6.0


def test_vagg_average():
    n = _make_vagg_node({"source_node_id": "upstream", "source_var": "results", "aggregation": "average"})
    r = asyncio.run(n._run())
    assert r.output_values["output"] == 2.0


def test_vagg_join():
    n = _make_vagg_node({
        "source_node_id": "upstream", "source_var": "strings",
        "aggregation": "join", "join_separator": ",",
    })
    r = asyncio.run(n._run())
    assert r.output_values["output"] == "a,b"


def test_vagg_first_last():
    n1 = _make_vagg_node({"source_node_id": "upstream", "source_var": "results", "aggregation": "first"})
    n2 = _make_vagg_node({"source_node_id": "upstream", "source_var": "results", "aggregation": "last"})
    assert asyncio.run(n1._run()).output_values["output"] == 1
    assert asyncio.run(n2._run()).output_values["output"] == 3


def test_vagg_source_node_missing_raises():
    n = _make_vagg_node({"source_node_id": "nonexistent", "source_var": "results", "aggregation": "collect"})
    with pytest.raises(ValueError):
        asyncio.run(n._run())


def test_vagg_source_not_a_list_raises():
    from lumen_core.workflow.variable_pool import VariablePool
    pool = VariablePool()
    pool.add(["upstream", "scalar"], "not a list")
    n = VariableAggregatorNode(
        node_id="vagg1",
        config={"source_node_id": "upstream", "source_var": "scalar", "aggregation": "collect"},
        pool=pool, db=None, tenant_id=1,
    )
    with pytest.raises(ValueError, match="expects list"):
        asyncio.run(n._run())


def test_vagg_empty_list_sum_is_zero():
    from lumen_core.workflow.variable_pool import VariablePool
    pool = VariablePool()
    pool.add(["upstream", "empty"], [])
    n = VariableAggregatorNode(
        node_id="vagg1",
        config={"source_node_id": "upstream", "source_var": "empty", "aggregation": "sum"},
        pool=pool, db=None, tenant_id=1,
    )
    r = asyncio.run(n._run())
    assert r.output_values["output"] == 0


def test_vagg_empty_list_average_is_zero():
    from lumen_core.workflow.variable_pool import VariablePool
    pool = VariablePool()
    pool.add(["upstream", "empty"], [])
    n = VariableAggregatorNode(
        node_id="vagg1",
        config={"source_node_id": "upstream", "source_var": "empty", "aggregation": "average"},
        pool=pool, db=None, tenant_id=1,
    )
    r = asyncio.run(n._run())
    assert r.output_values["output"] == 0.0

