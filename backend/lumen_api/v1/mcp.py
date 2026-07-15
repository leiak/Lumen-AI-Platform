from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Dict, Any, Optional
from lumen_core.database import get_db
from lumen_api.v1.auth import get_current_user
from lumen_models.user import User
from lumen_schemas.common import SingleResponse, PaginatedResponse
from lumen_services.mcp_service import MCPService
from pydantic import BaseModel

router = APIRouter(prefix="/mcp", tags=["mcp"])


class RegisterServerRequest(BaseModel):
    name: str
    url: str
    auth_token: Optional[str] = None
    config: Optional[Dict[str, Any]] = None


class RegisterToolRequest(BaseModel):
    name: str
    description: str
    input_schema: Dict[str, Any]
    output_schema: Optional[Dict[str, Any]] = None
    server_name: str


class ExecuteToolRequest(BaseModel):
    tool_name: str
    input_data: Dict[str, Any]


class MCPServerResponse(BaseModel):
    id: int
    name: str
    url: str
    status: str
    capabilities: Optional[Dict[str, Any]] = None
    created_at: str

    class Config:
        from_attributes = True


class MCPToolResponse(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    input_schema: Dict[str, Any]
    output_schema: Optional[Dict[str, Any]] = None
    server_name: Optional[str] = None

    class Config:
        from_attributes = True


@router.get("/servers", response_model=PaginatedResponse[MCPServerResponse])
async def list_servers(
    page: int = 1,
    page_size: int = 10,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    service = MCPService()
    servers = service.list_servers(db, current_user.tenant_id)
    total = len(servers)
    start = (page - 1) * page_size
    end = start + page_size
    return PaginatedResponse(
        data=[MCPServerResponse(
            id=s.id,
            name=s.name,
            url=s.url,
            status=s.status,
            capabilities=s.capabilities,
            created_at=s.created_at.isoformat() if s.created_at else None
        ) for s in servers[start:end]],
        total=total,
        page=page,
        page_size=page_size
    )


@router.post("/servers", response_model=SingleResponse[MCPServerResponse])
async def register_server(
    data: RegisterServerRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    service = MCPService()
    server = service.register_server(
        db,
        current_user.tenant_id,
        data.name,
        data.url,
        data.auth_token,
        data.config
    )
    return SingleResponse(data=MCPServerResponse(
        id=server.id,
        name=server.name,
        url=server.url,
        status=server.status,
        capabilities=server.capabilities,
        created_at=server.created_at.isoformat() if server.created_at else None
    ))


@router.delete("/servers/{name}")
async def unregister_server(
    name: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    service = MCPService()
    success = service.unregister_server(db, current_user.tenant_id, name)
    if not success:
        raise HTTPException(status_code=404, detail="Server not found")
    return SingleResponse(message="Unregistered successfully")


@router.get("/servers/{name}/discover")
async def discover_server_tools(
    name: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Discover tools from an MCP server"""
    service = MCPService()
    try:
        tools = await service.discover_tools(db, current_user.tenant_id, name)
        return SingleResponse(data=[MCPToolResponse(
            id=t.id,
            name=t.name,
            description=t.description,
            input_schema=t.input_schema,
            output_schema=t.output_schema
        ) for t in tools])
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Discovery failed: {str(e)}")


@router.get("/tools", response_model=PaginatedResponse[MCPToolResponse])
async def list_tools(
    page: int = 1,
    page_size: int = 10,
    server_id: Optional[int] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    service = MCPService()
    tools = service.list_tools(db, current_user.tenant_id, server_id)
    total = len(tools)
    start = (page - 1) * page_size
    end = start + page_size

    # Get server names for response
    server_ids = set(t.server_id for t in tools[start:end])
    from lumen_models.mcp import MCPServer
    servers = db.query(MCPServer).filter(
        MCPServer.id.in_(server_ids),
        MCPServer.tenant_id == current_user.tenant_id
    ).all() if server_ids else []
    server_names = {s.id: s.name for s in servers}

    return PaginatedResponse(
        data=[MCPToolResponse(
            id=t.id,
            name=t.name,
            description=t.description,
            input_schema=t.input_schema,
            output_schema=t.output_schema
        ) for t in tools[start:end]],
        total=total,
        page=page,
        page_size=page_size
    )


@router.post("/tools", response_model=SingleResponse[MCPToolResponse])
async def register_tool(
    data: RegisterToolRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    service = MCPService()

    # Get server ID from server name
    server = service.get_server(db, current_user.tenant_id, data.server_name)
    if not server:
        raise HTTPException(status_code=404, detail=f"Server '{data.server_name}' not found")

    tool = service.register_tool(
        db,
        current_user.tenant_id,
        server.id,
        data.name,
        data.description,
        data.input_schema,
        data.output_schema
    )
    return SingleResponse(data=MCPToolResponse(
        id=tool.id,
        name=tool.name,
        description=tool.description,
        input_schema=tool.input_schema,
        output_schema=tool.output_schema,
        server_name=data.server_name
    ))


@router.post("/tools/execute", response_model=SingleResponse)
async def execute_tool(
    data: ExecuteToolRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    service = MCPService()
    try:
        result = await service.execute_tool(
            db,
            current_user.tenant_id,
            data.tool_name,
            data.input_data
        )
        return SingleResponse(data={"result": result})
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Execution failed: {str(e)}")


@router.get("/marketplace/tools")
async def list_marketplace_tools(
    current_user: User = Depends(get_current_user)
):
    """List available MCP tools from marketplace (simulated)"""
    # Simulated marketplace data - in production would call actual MCP marketplace API
    tools = [
        {"name": "filesystem", "description": "File system operations - read, write, list files", "server": "built-in", "category": "system"},
        {"name": "http_request", "description": "Make HTTP requests to external services", "server": "built-in", "category": "network"},
        {"name": "code_executor", "description": "Execute code snippets in sandbox", "server": "built-in", "category": "developer"},
        {"name": "web_search", "description": "Search the web for information", "server": "built-in", "category": "search"},
        {"name": "database", "description": "Execute database queries", "server": "built-in", "category": "data"},
    ]
    return SingleResponse(data=tools)


@router.post("/marketplace/tools/{tool_name}/install")
async def install_marketplace_tool(
    tool_name: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Install a tool from marketplace"""
    service = MCPService()

    # Get or create a built-in server for marketplace tools
    server = service.get_server(db, current_user.tenant_id, "marketplace")
    if not server:
        server = service.register_server(
            db,
            current_user.tenant_id,
            "marketplace",
            "http://localhost:9090/mcp",  # Placeholder URL
            config={"source": "marketplace"}
        )

    # Register the tool
    tool_defs = {
        "filesystem": {"description": "File system operations", "input_schema": {"type": "object"}},
        "http_request": {"description": "Make HTTP requests", "input_schema": {"type": "object"}},
        "code_executor": {"description": "Execute code snippets", "input_schema": {"type": "object"}},
        "web_search": {"description": "Search the web", "input_schema": {"type": "object"}},
        "database": {"description": "Execute database queries", "input_schema": {"type": "object"}},
    }

    if tool_name not in tool_defs:
        raise HTTPException(status_code=404, detail=f"Tool '{tool_name}' not found in marketplace")

    tool_info = tool_defs[tool_name]
    tool = service.register_tool(
        db,
        current_user.tenant_id,
        server.id,
        tool_name,
        tool_info["description"],
        tool_info["input_schema"]
    )

    return SingleResponse(message=f"Tool {tool_name} installed successfully")
