from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session
import httpx
import json
import logging
from datetime import datetime

from lumen_models.mcp import MCPServer as DBMCPServer, MCPTool as DBMCPTool, MCPToolExecution

logger = logging.getLogger(__name__)


def _probe_health(url: str, timeout: float = 2.0) -> str:
    """P0-3 (2026-06-20): sync HTTP HEAD/GET health probe.

    Returns "connected" if 2xx/3xx/4xx (server reachable),
    "disconnected" if timeout, connection refused, DNS fail, 5xx, or other.

    用 urllib 而非 httpx 避免 async-in-sync 问题 (list_servers 在 sync
    FastAPI 路径里, 已经在 event loop 中不能 asyncio.run).
    4xx 也算 connected 因为 server 进程在跑只是 endpoint 路径错 — 跟用户
    期待"server 是否运行"对齐, 不是"endpoint 是否正确".
    """
    import urllib.request
    import urllib.error

    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            code = resp.getcode()
            if 200 <= code < 500:
                return "connected"
            return "disconnected"
    except urllib.error.HTTPError as e:
        # 4xx = server 进程在跑, 路径可能错
        if 400 <= e.code < 500:
            return "connected"
        return "disconnected"
    except (urllib.error.URLError, OSError, TimeoutError):
        return "disconnected"


def _parse_sse_response(text: str) -> dict:
    """
    Parse the SSE-encoded response from an MCP Streamable-HTTP server.

    Streamable HTTP wraps the JSON-RPC payload as one or more ``data:`` lines:
        event: message
        data: {"jsonrpc":"2.0","id":1,"result":{...}}
        <blank line>

    Multiple data lines are concatenated (FastMCP occasionally splits a JSON
    value across lines when the body is large). The combined string is parsed
    as a single JSON object.
    """
    data_lines = []
    for line in text.split("\n"):
        if line.startswith("data: "):
            data_lines.append(line[len("data: "):])
        elif line.startswith("data:"):
            # tolerate "data:foo" (no space) too
            data_lines.append(line[len("data:"):])
    if not data_lines:
        raise ValueError("No data in SSE response")
    return json.loads("\n".join(data_lines))


class MCPError(Exception):
    """Raised when an MCP server returns a JSON-RPC ``error`` field."""
    pass


class MCPService:
    """Service for managing MCP servers and tools with database persistence and real HTTP execution"""

    def __init__(self):
        pass

    def register_server(
        self,
        db: Session,
        tenant_id: int,
        name: str,
        url: str,
        auth_token: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None
    ) -> DBMCPServer:
        """Register a new MCP server"""
        # Check if server already exists
        existing = db.query(DBMCPServer).filter(
            DBMCPServer.tenant_id == tenant_id,
            DBMCPServer.name == name
        ).first()

        if existing:
            # Update existing server
            existing.url = url
            if auth_token:
                existing.auth_token = auth_token
            if config:
                existing.config = config
            existing.status = "disconnected"
            db.commit()
            db.refresh(existing)
            return existing

        server = DBMCPServer(
            tenant_id=tenant_id,
            name=name,
            url=url,
            auth_token=auth_token,
            status="disconnected",
            config=config
        )
        db.add(server)
        db.commit()
        db.refresh(server)
        return server

    def unregister_server(self, db: Session, tenant_id: int, name: str) -> bool:
        """Unregister an MCP server"""
        server = db.query(DBMCPServer).filter(
            DBMCPServer.tenant_id == tenant_id,
            DBMCPServer.name == name
        ).first()

        if not server:
            return False

        # Delete associated tools first
        db.query(DBMCPTool).filter(DBMCPTool.server_id == server.id).delete()
        db.delete(server)
        db.commit()
        return True

    def list_servers(self, db: Session, tenant_id: int) -> List[DBMCPServer]:
        """List all MCP servers for a tenant.

        P0-3 (2026-06-20): 实时探测每个 server 的 health, 刷新 status 字段.
        之前 list_servers 直接读 DB 的 status (注册时初值 "disconnected"),
        永远不变, 前端 mcp 页面一直显示 disconnected 即使 server 实际在跑
        (e.g. local-demo 在 8765). 用 urllib 轻量 HEAD 探测 (timeout 2s)
        避开 async-in-sync 问题, 失败保持 disconnected.
        """
        servers = db.query(DBMCPServer).filter(
            DBMCPServer.tenant_id == tenant_id
        ).all()
        for s in servers:
            new_status = _probe_health(s.url)
            if new_status != s.status:
                s.status = new_status
                db.add(s)
        db.commit()
        return servers

    def get_server(self, db: Session, tenant_id: int, name: str) -> Optional[DBMCPServer]:
        """Get a specific MCP server"""
        return db.query(DBMCPServer).filter(
            DBMCPServer.tenant_id == tenant_id,
            DBMCPServer.name == name
        ).first()

    def register_tool(
        self,
        db: Session,
        tenant_id: int,
        server_id: int,
        name: str,
        description: str,
        input_schema: Dict[str, Any],
        output_schema: Optional[Dict[str, Any]] = None
    ) -> DBMCPTool:
        """Register a tool from an MCP server"""
        # Check if tool already exists
        existing = db.query(DBMCPTool).filter(
            DBMCPTool.tenant_id == tenant_id,
            DBMCPTool.name == name
        ).first()

        if existing:
            existing.description = description
            existing.input_schema = input_schema
            existing.output_schema = output_schema
            existing.server_id = server_id
            db.commit()
            db.refresh(existing)
            return existing

        tool = DBMCPTool(
            tenant_id=tenant_id,
            server_id=server_id,
            name=name,
            description=description,
            input_schema=input_schema,
            output_schema=output_schema
        )
        db.add(tool)
        db.commit()
        db.refresh(tool)
        return tool

    def list_tools(self, db: Session, tenant_id: int, server_id: Optional[int] = None) -> List[DBMCPTool]:
        """List all tools, optionally filtered by server"""
        query = db.query(DBMCPTool).filter(
            DBMCPTool.tenant_id == tenant_id,
            DBMCPTool.is_enabled == 1
        )
        if server_id:
            query = query.filter(DBMCPTool.server_id == server_id)
        return query.all()

    def get_tool(self, db: Session, tenant_id: int, name: str) -> Optional[DBMCPTool]:
        """Get a specific tool by name"""
        return db.query(DBMCPTool).filter(
            DBMCPTool.tenant_id == tenant_id,
            DBMCPTool.name == name,
            DBMCPTool.is_enabled == 1
        ).first()

    async def execute_tool(
        self,
        db: Session,
        tenant_id: int,
        tool_name: str,
        input_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute an MCP tool with real HTTP call"""
        start_time = datetime.utcnow()

        # Get tool and server info
        tool = self.get_tool(db, tenant_id, tool_name)
        if not tool:
            raise ValueError(f"Tool '{tool_name}' not found")

        server = db.query(DBMCPServer).filter(
            DBMCPServer.id == tool.server_id,
            DBMCPServer.tenant_id == tenant_id
        ).first()

        if not server:
            raise ValueError(f"Server for tool '{tool_name}' not found")

        execution = MCPToolExecution(
            tenant_id=tenant_id,
            tool_id=tool.id,
            server_id=server.id,
            input_data=input_data,
            status="pending"
        )
        db.add(execution)
        db.commit()

        try:
            # Make real HTTP call to MCP server
            result = await self._call_mcp_server(
                server.url,
                server.auth_token,
                tool_name,
                input_data
            )

            # Update execution record on success
            execution.status = "success"
            # Preserve the full MCP-protocol envelope: {content, isError}.
            # The API layer is responsible for unwrapping content[] for the
            # HTTP response shape; this service layer keeps the wire format.
            execution.output_data = result
            execution.execution_time_ms = int(
                (datetime.utcnow() - start_time).total_seconds() * 1000
            )
            db.commit()

            return result

        except Exception as e:
            logger.error(f"MCP tool execution failed: {e}")

            # Update execution record on failure
            execution.status = "error"
            execution.error = str(e)
            execution.execution_time_ms = int(
                (datetime.utcnow() - start_time).total_seconds() * 1000
            )
            db.commit()

            raise

    async def _call_mcp_server(
        self,
        server_url: str,
        auth_token: Optional[str],
        tool_name: str,
        input_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Call a remote MCP server's ``tools/call`` JSON-RPC endpoint.

        Sends the standard MCP envelope:
            {"jsonrpc":"2.0","id":1,"method":"tools/call",
             "params":{"name": tool_name, "arguments": input_data}}

        Streamable-HTTP responses are SSE-encoded (one or more ``data:`` lines);
        the JSON payload is extracted via :func:`_parse_sse_response`.

        Returns the protocol ``result`` object — typically
        ``{"content": [...], "isError": false}``.

        Raises :class:`MCPError` if the server returns a JSON-RPC error field.
        """
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": input_data},
        }
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if auth_token:
            headers["Authorization"] = f"Bearer {auth_token}"

        # Phase 1 Group A 2.5 (2026-09-03): transient retry 包 httpx 调用。
        # mcp_server 远程调用易受网络抖动影响(connect refused / read timeout),
        # tenacity 3 次 exponential backoff 0.5/1/2s 后 reraise,失败走 MCPError。
        from lumen_services.retry import call_async_with_retry

        async def _do_post():
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(server_url, headers=headers, json=payload)
                response.raise_for_status()
                return _parse_sse_response(response.text)

        result = await call_async_with_retry(
            _do_post, func_name="mcp_service._call_mcp_server",
        )

        if "error" in result:
            msg = result["error"].get("message", "Unknown MCP error")
            raise MCPError(msg)

        return result.get("result", {})

    async def discover_tools(self, db: Session, tenant_id: int, server_name: str) -> List[DBMCPTool]:
        """
        Discover tools from an MCP server by calling its ``tools/list`` JSON-RPC
        endpoint, then register each result in the ``mcp_tools`` table.

        On success: ``server.status = "connected"``.
        On failure: ``server.status = "error"`` and the exception is re-raised.
        """
        server = self.get_server(db, tenant_id, server_name)
        if not server:
            raise ValueError(f"Server '{server_name}' not found")

        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/list",
            "params": {},
        }
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if server.auth_token:
            headers["Authorization"] = f"Bearer {server.auth_token}"

        try:
            # Phase 1 Group A 2.5 (2026-09-03): transient retry 包 httpx 调用,
            # 跟 _call_mcp_server 同模式。
            from lumen_services.retry import call_async_with_retry

            async def _do_post():
                async with httpx.AsyncClient(timeout=30.0) as client:
                    resp = await client.post(server.url, headers=headers, json=payload)
                    resp.raise_for_status()
                    return _parse_sse_response(resp.text)

            data = await call_async_with_retry(
                _do_post, func_name="mcp_service.discover_tools",
            )

            tools = data["result"]["tools"]
            registered: List[DBMCPTool] = []
            for tool_def in tools:
                tool = self.register_tool(
                    db,
                    tenant_id,
                    server.id,
                    name=tool_def.get("name"),
                    description=tool_def.get("description", ""),
                    input_schema=tool_def.get("inputSchema", {"type": "object"}),
                    output_schema=tool_def.get("outputSchema"),
                )
                registered.append(tool)

            server.status = "connected"
            db.commit()
            return registered

        except Exception as e:
            logger.error(f"Tool discovery failed for {server_name}: {e}")
            server.status = "error"
            db.commit()
            raise


# Singleton instance
mcp_service = MCPService()
