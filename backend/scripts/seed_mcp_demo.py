"""
Idempotently insert the local MCP demo data into MySQL.

Inserts (if not already present):
  - 1 server:  name="local-demo", url="http://127.0.0.1:8765/mcp"
  - 6 tools:   list_agents, list_knowledge_bases, search_knowledge_base,
               list_chat_sessions, list_workflows, run_workflow

Safe to re-run; existing rows are updated in place (description, input_schema,
server_id, is_enabled).

Usage:
    cd backend && python -m scripts.seed_mcp_demo
"""
import os
import sys

# Make ``app`` importable when invoked as a module.
_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from lumen_core.database import SessionLocal
# Register the Tenant model so mcp_servers.tenant_id FK resolves.
from lumen_models import tenant  # noqa: F401
from lumen_models.mcp import MCPServer, MCPTool

TOOL_SCHEMAS = {
    "list_agents": {
        "description": "列出当前租户所有 Agent(按更新时间倒序)",
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "default": 20,
                          "description": "最多返回数量"},
                "tenant_id": {"type": "integer",
                              "description": "可选,显式指定租户 ID"},
            },
        },
    },
    "list_knowledge_bases": {
        "description": "列出当前租户所有知识库(含 KB id、名称、文档数)",
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "default": 20,
                          "description": "最多返回数量"},
                "tenant_id": {"type": "integer",
                              "description": "可选,显式指定租户 ID"},
            },
        },
    },
    "search_knowledge_base": {
        "description": "在指定知识库里做 RAG 检索。复用平台 HybridRetriever。",
        "input_schema": {
            "type": "object",
            "required": ["query", "kb_name"],
            "properties": {
                "query": {"type": "string", "description": "查询语句"},
                "kb_name": {"type": "string", "description": "目标知识库名"},
                "top_k": {"type": "integer", "default": 5,
                          "description": "返回 TopK"},
                "tenant_id": {"type": "integer",
                              "description": "可选,显式指定租户 ID"},
            },
        },
    },
    "list_chat_sessions": {
        "description": "列出某用户的最近聊天会话",
        "input_schema": {
            "type": "object",
            "required": ["user_id"],
            "properties": {
                "user_id": {"type": "integer", "description": "用户 ID"},
                "limit": {"type": "integer", "default": 20,
                          "description": "最多返回数量"},
            },
        },
    },
    "list_workflows": {
        "description": "列出当前租户所有工作流(按更新时间倒序)",
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "default": 20,
                          "description": "最多返回数量"},
                "tenant_id": {"type": "integer",
                              "description": "可选,显式指定租户 ID"},
            },
        },
    },
    "run_workflow": {
        "description": "同步执行指定工作流,返回执行结果",
        "input_schema": {
            "type": "object",
            "required": ["name", "input_data"],
            "properties": {
                "name": {"type": "string", "description": "工作流名"},
                "input_data": {"type": "object", "description": "输入 JSON"},
                "tenant_id": {"type": "integer",
                              "description": "可选,显式指定租户 ID"},
            },
        },
    },
    "query_database": {
        "description": "M33 智能问数(Text2SQL) — 自然语言查询业务数据库",
        "input_schema": {
            "type": "object",
            "required": ["question"],
            "properties": {
                "question": {
                    "type": "string",
                    "description": "用户的自然语言问题(中文或英文)",
                },
                "db_alias": {
                    "type": "string",
                    "default": "ai_platform",
                    "description": "数据库别名(目前仅支持 ai_platform)",
                },
                "tenant_id": {
                    "type": "integer",
                    "description": "可选,显式指定租户 ID",
                },
            },
        },
    },
}


def main():
    db = SessionLocal()
    tenant_id = int(os.getenv("MCP_DEFAULT_TENANT_ID", "1"))
    try:
        # 1. Upsert server
        server = (
            db.query(MCPServer)
            .filter_by(tenant_id=tenant_id, name="local-demo")
            .first()
        )
        if not server:
            server = MCPServer(
                tenant_id=tenant_id, name="local-demo",
                url="http://127.0.0.1:8765/mcp", status="disconnected",
            )
            db.add(server)
        else:
            server.url = "http://127.0.0.1:8765/mcp"
            server.status = "disconnected"
        db.commit()
        db.refresh(server)

        # 2. Upsert each tool
        for tool_name, schema in TOOL_SCHEMAS.items():
            tool = (
                db.query(MCPTool)
                .filter_by(tenant_id=tenant_id, name=tool_name)
                .first()
            )
            if not tool:
                tool = MCPTool(
                    tenant_id=tenant_id, server_id=server.id,
                    name=tool_name,
                    description=schema["description"],
                    input_schema=schema["input_schema"],
                    is_enabled=1,
                )
                db.add(tool)
            else:
                tool.description = schema["description"]
                tool.input_schema = schema["input_schema"]
                tool.server_id = server.id
                tool.is_enabled = 1
        db.commit()

        print(f"[OK] Seeded 1 server + {len(TOOL_SCHEMAS)} tools for tenant {tenant_id}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
