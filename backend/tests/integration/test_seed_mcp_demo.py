"""Integration test for scripts.seed_mcp_demo: idempotent DB seeder."""
import os
import subprocess
import sys

import pytest

BACKEND_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
SEED_MODULE = "scripts.seed_mcp_demo"

EXPECTED_TOOLS = {
    "list_agents", "list_knowledge_bases", "search_knowledge_base",
    "list_chat_sessions", "list_workflows", "run_workflow",
    "query_database",  # M33: Text2SQL MCP tool
}


def _run_seed():
    """Run the seed script as a subprocess (cleans state first)."""
    # Pre-clean: remove the server row and any tool rows this test owns.
    # Also wipe ``mcp_tool_executions`` rows that reference our tools —
    # FK constraint blocks tool delete otherwise (a previous run of
    # /api/v1/mcp/tools/execute may have left execution rows behind).
    from lumen_core.database import SessionLocal
    from lumen_models.mcp import MCPServer, MCPTool, MCPToolExecution
    db = SessionLocal()
    try:
        tool_ids_subq = (
            db.query(MCPTool.id)
            .filter(MCPTool.name.in_(EXPECTED_TOOLS), MCPTool.tenant_id == 1)
            .subquery()
        )
        db.query(MCPToolExecution).filter(
            MCPToolExecution.tool_id.in_(tool_ids_subq),
        ).delete(synchronize_session=False)
        db.query(MCPTool).filter(
            MCPTool.name.in_(EXPECTED_TOOLS),
            MCPTool.tenant_id == 1,
        ).delete(synchronize_session=False)
        db.query(MCPServer).filter_by(tenant_id=1, name="local-demo").delete()
        db.commit()
    finally:
        db.close()

    proc = subprocess.run(
        [sys.executable, "-m", SEED_MODULE],
        cwd=BACKEND_ROOT, capture_output=True, text=True, timeout=60,
    )
    return proc


def test_seed_inserts_one_server_and_seven_tools():
    proc = _run_seed()
    assert proc.returncode == 0, f"seed failed: {proc.stderr}"
    assert "Seeded 1 server + 7 tools" in proc.stdout

    from lumen_core.database import SessionLocal
    from lumen_models.mcp import MCPServer, MCPTool
    db = SessionLocal()
    try:
        server = db.query(MCPServer).filter_by(tenant_id=1, name="local-demo").first()
        assert server is not None
        assert server.url == "http://127.0.0.1:8765/mcp"

        tools = (
            db.query(MCPTool)
            .filter(MCPTool.tenant_id == 1, MCPTool.name.in_(EXPECTED_TOOLS))
            .all()
        )
        assert len(tools) == 7
        actual_names = {t.name for t in tools}
        assert actual_names == EXPECTED_TOOLS
        for t in tools:
            assert t.server_id == server.id
            assert t.is_enabled == 1
    finally:
        db.close()


def test_seed_is_idempotent():
    """Running twice does not create duplicates."""
    proc1 = _run_seed()
    proc2 = _run_seed()
    assert proc1.returncode == 0
    assert proc2.returncode == 0

    from lumen_core.database import SessionLocal
    from lumen_models.mcp import MCPServer, MCPTool
    db = SessionLocal()
    try:
        server_count = (
            db.query(MCPServer)
            .filter_by(tenant_id=1, name="local-demo")
            .count()
        )
        tool_count = (
            db.query(MCPTool)
            .filter(MCPTool.tenant_id == 1, MCPTool.name.in_(EXPECTED_TOOLS))
            .count()
        )
        assert server_count == 1
        assert tool_count == 7
    finally:
        db.close()
