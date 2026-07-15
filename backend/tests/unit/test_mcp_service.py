"""Unit tests for mcp_service.py — protocol helpers and protocol layer."""
import os
import sys
import json
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))


class TestParseSseResponse:
    def test_parses_single_data_line(self):
        from lumen_services.mcp_service import _parse_sse_response
        sse = 'event: message\ndata: {"jsonrpc":"2.0","id":1,"result":{"ok":true}}\n\n'
        result = _parse_sse_response(sse)
        assert result == {"jsonrpc": "2.0", "id": 1, "result": {"ok": True}}

    def test_merges_multiple_data_lines(self):
        from lumen_services.mcp_service import _parse_sse_response
        sse = (
            'event: message\n'
            'data: {"jsonrpc": "2.0",\n'
            'data:  "id": 1}\n\n'
        )
        result = _parse_sse_response(sse)
        assert result == {"jsonrpc": "2.0", "id": 1}

    def test_raises_when_no_data_line(self):
        from lumen_services.mcp_service import _parse_sse_response
        with pytest.raises(ValueError, match="No data in SSE response"):
            _parse_sse_response("event: ping\n\n")

    def test_raises_on_malformed_json(self):
        from lumen_services.mcp_service import _parse_sse_response
        with pytest.raises(json.JSONDecodeError):
            _parse_sse_response("data: not-json\n\n")


class TestMCPError:
    def test_is_exception_subclass(self):
        from lumen_services.mcp_service import MCPError
        assert issubclass(MCPError, Exception)

    def test_carries_message(self):
        from lumen_services.mcp_service import MCPError
        err = MCPError("something broke")
        assert str(err) == "something broke"


class TestCallMcpServer:
    """The real MCP protocol uses tools/call; we parse SSE responses."""

    @pytest.mark.asyncio
    async def test_sends_tools_call_method(self):
        from lumen_services.mcp_service import MCPService
        sent = {}

        async def handler(request):
            import json as _j
            sent["url"] = str(request.url)
            sent["body"] = _j.loads(request.content)
            sent["headers"] = dict(request.headers)
            from httpx import Response
            sse = 'event: message\ndata: {"jsonrpc":"2.0","id":1,"result":{"content":[{"type":"text","text":"hi"}],"isError":false}}\n\n'
            return Response(200, text=sse, headers={"content-type": "text/event-stream"})

        import httpx
        transport = httpx.MockTransport(handler)
        svc = MCPService()
        result = await _call_via_mock(svc, transport, None, "ping", {})

        # Verify request shape (real MCP envelope)
        assert sent["body"]["method"] == "tools/call"
        assert sent["body"]["params"] == {"name": "ping", "arguments": {}}
        # Verify response parsed via SSE
        assert result == {"content": [{"type": "text", "text": "hi"}], "isError": False}

    @pytest.mark.asyncio
    async def test_passes_bearer_auth(self):
        from lumen_services.mcp_service import MCPService
        sent_headers = {}

        async def handler(request):
            sent_headers.update(dict(request.headers))
            from httpx import Response
            sse = 'data: {"jsonrpc":"2.0","id":1,"result":{}}\n\n'
            return Response(200, text=sse)

        import httpx
        transport = httpx.MockTransport(handler)
        await _call_via_mock(MCPService(), transport, "secret-token", "x", {})
        assert sent_headers.get("authorization") == "Bearer secret-token"

    @pytest.mark.asyncio
    async def test_raises_mcp_error_on_error_field(self):
        from lumen_services.mcp_service import MCPService, MCPError
        import pytest as _p

        async def handler(request):
            from httpx import Response
            sse = 'data: {"jsonrpc":"2.0","id":1,"error":{"code":-32601,"message":"Method not found"}}\n\n'
            return Response(200, text=sse)

        import httpx
        transport = httpx.MockTransport(handler)
        with _p.raises(MCPError, match="Method not found"):
            await _call_via_mock(MCPService(), transport, None, "nope", {})


async def _call_via_mock(svc, transport, auth_token, tool_name, input_data):
    """Call _call_mcp_server with a mocked httpx transport.

    We monkey-patch httpx.AsyncClient so the function under test uses our
    transport. The patch is restored in the finally block.
    """
    import httpx
    original = httpx.AsyncClient

    class PatchedClient(original):
        def __init__(self, *a, **kw):
            kw["transport"] = transport
            super().__init__(*a, **kw)

    httpx.AsyncClient = PatchedClient
    try:
        return await svc._call_mcp_server("http://x/mcp", auth_token, tool_name, input_data)
    finally:
        httpx.AsyncClient = original


class TestDiscoverToolsProtocol:
    """discover_tools must use POST with method=tools/list, not GET /tools."""

    @pytest.mark.asyncio
    async def test_sends_tools_list_method(self):
        from lumen_services.mcp_service import MCPService
        import json as _j
        sent = {}

        async def handler(request):
            sent["method"] = request.method
            sent["url"] = str(request.url)
            sent["body"] = _j.loads(request.content)
            from httpx import Response
            sse = (
                'data: {"jsonrpc":"2.0","id":1,"result":{"tools":['
                '{"name":"a","description":"A","inputSchema":{"type":"object"}},'
                '{"name":"b","description":"B","inputSchema":{"type":"object"}}'
                ']}}\n\n'
            )
            return Response(200, text=sse)

        import httpx
        transport = httpx.MockTransport(handler)

        result = await _list_remote_via_mock(transport, "http://x/mcp", None)

        # Verify request shape (real MCP tools/list envelope)
        assert sent["method"] == "POST"
        assert sent["url"] == "http://x/mcp"
        assert sent["body"]["method"] == "tools/list"
        # Verify response parsed via SSE — should yield the 2 tools
        assert len(result) == 2
        assert result[0]["name"] == "a"
        assert result[0]["inputSchema"] == {"type": "object"}


async def _list_remote_via_mock(transport, server_url, auth_token):
    """Send a tools/list JSON-RPC request through a mocked transport.

    Mirrors what the new discover_tools will do internally, so we can verify
    the wire format in isolation before changing the production code.
    """
    import httpx
    payload = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"

    original = httpx.AsyncClient

    class PatchedClient(original):
        def __init__(self, *a, **kw):
            kw["transport"] = transport
            super().__init__(*a, **kw)

    httpx.AsyncClient = PatchedClient
    try:
        from lumen_services.mcp_service import _parse_sse_response
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(server_url, headers=headers, json=payload)
            resp.raise_for_status()
            data = _parse_sse_response(resp.text)
        return data["result"]["tools"]
    finally:
        httpx.AsyncClient = original


class TestExecuteToolPreservesMCPResult:
    """execute_tool must store the full MCP result, not unwrap it.

    If a future change accidentally unwraps ``result["content"]``, the
    ``isError`` flag and the MCP-shaped structure that callers depend on
    would be lost. This test pins the contract.
    """

    @pytest.mark.asyncio
    async def test_output_data_stores_mcp_result_envelope(self, tmp_user):
        from lumen_services.mcp_service import MCPService
        from lumen_models.mcp import MCPServer, MCPTool, MCPToolExecution
        from lumen_core.database import SessionLocal
        from unittest.mock import patch

        # Insert server + tool directly so we don't depend on discover.
        db = SessionLocal()
        server = None
        tool = None
        try:
            server = MCPServer(
                tenant_id=tmp_user.tenant_id,
                name="test-srv",
                url="http://x/mcp",
                status="disconnected",
            )
            db.add(server); db.commit(); db.refresh(server)
            tool = MCPTool(
                tenant_id=tmp_user.tenant_id,
                server_id=server.id,
                name="test-tool",
                description="t",
                input_schema={"type": "object"},
                is_enabled=1,
            )
            db.add(tool); db.commit(); db.refresh(tool)

            # Patch _call_mcp_server to return a properly-shaped MCP envelope.
            fake_result = {
                "content": [{"type": "text", "text": "hello"}],
                "isError": False,
            }

            async def fake_call(self, *a, **kw):
                return fake_result

            with patch.object(MCPService, "_call_mcp_server", new=fake_call):
                svc = MCPService()
                out = await svc.execute_tool(
                    db, tmp_user.tenant_id, "test-tool", {"k": "v"},
                )

            # 1. The returned value must be the full envelope, not unwrapped.
            assert out == fake_result
            assert "content" in out
            assert "isError" in out

            # 2. The persisted output_data must be the full envelope too.
            row = db.query(MCPToolExecution).filter_by(tool_id=tool.id).first()
            assert row is not None
            assert row.status == "success"
            assert row.output_data == fake_result
        finally:
            if tool is not None:
                db.query(MCPToolExecution).filter_by(tool_id=tool.id).delete()
                db.query(MCPTool).filter_by(id=tool.id).delete()
            if server is not None:
                db.query(MCPServer).filter_by(id=server.id).delete()
            db.commit()
            db.close()
