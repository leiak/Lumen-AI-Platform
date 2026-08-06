"""Unit tests for the 6 local MCP tool functions.

We call the tool functions directly (not via the FastMCP HTTP layer) so the
tests don't need a running uvicorn process. The FastMCP integration is
covered separately by ``tests/integration/test_mcp_demo_e2e.py``.
"""
import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))


class TestListAgents:
    def test_returns_tenant_scoped(self, tmp_user):
        from lumen_core.database import SessionLocal
        from lumen_models.agent import Agent
        from lumen_core.security import get_password_hash
        from lumen_models.tenant import Tenant
        from lumen_models.user import User
        from lumen_mcp_servers.local_demo import list_agents
        import uuid

        # Insert a foreign-tenant agent that must NOT be returned.
        db = SessionLocal()
        try:
            # Tenant 2 must exist for the FK constraints on User and Agent.
            other_tenant = db.query(Tenant).filter(Tenant.id == 2).first()
            if not other_tenant:
                other_tenant = Tenant(id=2, name="Other Tenant", code="other")
                db.add(other_tenant); db.commit(); db.refresh(other_tenant)
            suffix = uuid.uuid4().hex[:8]
            other_user = User(
                username=f"other_{suffix}", email=f"other_{suffix}@t.local",
                hashed_password=get_password_hash("x"), tenant_id=2, is_active=True,
            )
            db.add(other_user); db.commit(); db.refresh(other_user)
            other_agent = Agent(
                name="other-agent", description="should not appear",
                prompt_template="hi", tenant_id=2, is_active=True,
            )
            db.add(other_agent)

            # Insert a same-tenant agent that MUST be returned.
            mine = Agent(
                name="my-agent", description="d", prompt_template="hi",
                tenant_id=tmp_user.tenant_id, is_active=True,
            )
            db.add(mine); db.commit(); db.refresh(mine)
            mine_id = mine.id
        finally:
            db.close()

        out = list_agents(limit=50)
        assert out["ok"] is True
        names = [a["name"] for a in out["data"]]
        assert "my-agent" in names
        assert "other-agent" not in names
        assert any(a["id"] == mine_id for a in out["data"])

    def test_respects_limit(self, tmp_user):
        from lumen_core.database import SessionLocal
        from lumen_models.agent import Agent
        from lumen_mcp_servers.local_demo import list_agents

        db = SessionLocal()
        created_ids = []
        try:
            for i in range(5):
                a = Agent(
                    name=f"a-{i}", description="d", prompt_template="hi",
                    tenant_id=tmp_user.tenant_id, is_active=True,
                )
                db.add(a)
            db.commit()
        finally:
            db.close()

        out = list_agents(limit=3)
        assert out["ok"] is True
        assert out["count"] == 3
        assert len(out["data"]) == 3


class TestListKnowledgeBases:
    def test_includes_doc_count(self, tmp_user, tmp_kb):
        from lumen_core.database import SessionLocal
        from lumen_models.knowledge import Document
        from lumen_mcp_servers.local_demo import list_knowledge_bases

        # tmp_kb fixture creates a KB with no documents. Add 2 to verify count.
        db = SessionLocal()
        try:
            for i in range(2):
                db.add(Document(
                    filename=f"d{i}.txt", file_path=f"/tmp/d{i}",
                    knowledge_base_id=tmp_kb.id, status="completed",
                ))
            db.commit()
        finally:
            db.close()

        out = list_knowledge_bases(limit=50)
        assert out["ok"] is True
        kb_row = next((k for k in out["data"] if k["id"] == tmp_kb.id), None)
        assert kb_row is not None
        assert kb_row["doc_count"] == 2
        assert kb_row["name"] == tmp_kb.name


class TestSearchKnowledgeBase:
    def test_returns_chunks_for_known_kb(self, tmp_user, tmp_kb):
        from unittest.mock import patch, MagicMock
        from lumen_mcp_servers.local_demo import search_knowledge_base

        # Patch get_retrieval_pipeline at the location where it is imported
        # INSIDE the function (lazy import). The function does
        # `from lumen_services.retrieval.pipeline import get_retrieval_pipeline`
        # at call time, so we patch that module path.
        fake_pipeline = MagicMock()
        fake_pipeline.search.return_value = [
            {"chunk_id": "c1", "content": "answer text", "score": 0.9,
             "metadata": {"doc_id": 7}},
            {"chunk_id": "c2", "content": "second", "score": 0.7,
             "metadata": {"doc_id": 8}},
        ]
        with patch(
            "lumen_services.retrieval.pipeline.get_retrieval_pipeline",
            return_value=fake_pipeline,
        ):
            out = search_knowledge_base(
                query="what is X", kb_name=tmp_kb.name, top_k=5,
            )

        assert out["ok"] is True
        assert out["count"] == 2
        assert out["data"][0]["chunk_id"] == "c1"
        assert out["data"][0]["content"] == "answer text"

    def test_returns_error_on_unknown_kb(self, tmp_user):
        from lumen_mcp_servers.local_demo import search_knowledge_base

        out = search_knowledge_base(
            query="anything", kb_name="nonexistent-kb-xyz", top_k=5,
        )
        assert out["ok"] is False
        assert "nonexistent-kb-xyz" in out["error"]
        assert out["data"] is None
        assert out["message"] == "kb_not_found"


class TestListChatSessions:
    def test_filters_by_user_and_tenant(self, tmp_user):
        from lumen_core.database import SessionLocal
        from lumen_core.security import get_password_hash
        from lumen_models.chat import Conversation
        from lumen_models.tenant import Tenant
        from lumen_models.user import User
        from lumen_mcp_servers.local_demo import list_chat_sessions
        import uuid

        db = SessionLocal()
        try:
            # FK setup: real Tenant(id=2) and a real user in tenant 2 for the
            # cross-tenant negative case, and a real user in tenant 1 for the
            # cross-user negative case. The function's filter is what we're
            # verifying, not the FK setup.
            other_tenant = db.query(Tenant).filter(Tenant.id == 2).first()
            if not other_tenant:
                other_tenant = Tenant(id=2, name="Other Tenant", code="other")
                db.add(other_tenant); db.commit(); db.refresh(other_tenant)
            suffix = uuid.uuid4().hex[:8]
            cross_tenant_user = User(
                username=f"cross_tenant_{suffix}", email=f"cross_tenant_{suffix}@t.local",
                hashed_password=get_password_hash("x"), tenant_id=2, is_active=True,
            )
            db.add(cross_tenant_user); db.commit(); db.refresh(cross_tenant_user)
            cross_user = User(
                username=f"cross_user_{suffix}", email=f"cross_user_{suffix}@t.local",
                hashed_password=get_password_hash("x"),
                tenant_id=tmp_user.tenant_id, is_active=True,
            )
            db.add(cross_user); db.commit(); db.refresh(cross_user)

            # Same user, same tenant: 2 sessions, must appear.
            for i in range(2):
                db.add(Conversation(
                    title=f"mine-{i}", user_id=tmp_user.id,
                    tenant_id=tmp_user.tenant_id,
                ))
            # Same user, different tenant: must NOT appear.
            db.add(Conversation(
                title="other-tenant", user_id=tmp_user.id, tenant_id=2,
            ))
            # Different user, same tenant: must NOT appear.
            db.add(Conversation(
                title="other-user", user_id=cross_user.id,
                tenant_id=tmp_user.tenant_id,
            ))
            db.commit()
        finally:
            db.close()

        out = list_chat_sessions(user_id=tmp_user.id, limit=50)
        assert out["ok"] is True
        titles = [s["title"] for s in out["data"]]
        assert "mine-0" in titles
        assert "mine-1" in titles
        assert "other-tenant" not in titles
        assert "other-user" not in titles


class TestListWorkflows:
    def test_orders_by_updated_at_desc(self, tmp_user):
        from datetime import datetime, timedelta
        from lumen_core.database import SessionLocal
        from lumen_models.workflow import Workflow
        from lumen_mcp_servers.local_demo import list_workflows

        db = SessionLocal()
        try:
            # Clean up any leftover rows from prior runs so the DESC order
            # assertion is deterministic.
            leftover = (
                db.query(Workflow)
                .filter(
                    Workflow.tenant_id == tmp_user.tenant_id,
                    Workflow.name.in_(["old", "middle", "new"]),
                )
                .all()
            )
            for w in leftover:
                db.delete(w)
            db.commit()

            # Create 3 workflows with distinct updated_at values. The shared
            # dev DB may already contain other workflows with more recent
            # updated_at values, so we only assert the relative order of the
            # 3 we just inserted.
            base = datetime(2026, 1, 1, 12, 0, 0)
            for i, name in enumerate(["old", "middle", "new"]):
                wf = Workflow(
                    name=name, description=f"{name} wf",
                    definition={"nodes": [], "edges": []},
                    tenant_id=tmp_user.tenant_id, is_active=True,
                )
                wf.updated_at = base + timedelta(seconds=i)
                db.add(wf)
            db.commit()
        finally:
            db.close()

        out = list_workflows(limit=200)
        assert out["ok"] is True
        # Subset to the rows we just inserted (other workflows in the shared
        # dev DB may have more recent updated_at values).
        inserted_names = [w["name"] for w in out["data"] if w["name"] in {"old", "middle", "new"}]
        assert inserted_names == ["new", "middle", "old"]


class TestRunWorkflow:
    def test_returns_execution_result(self, tmp_user):
        import uuid
        from lumen_core.database import SessionLocal
        from lumen_models.workflow import Workflow
        from lumen_mcp_servers.local_demo import run_workflow
        from unittest.mock import patch

        # Use a unique name so repeat runs against the shared dev DB still
        # resolve to the row we just inserted.
        wf_name = f"test-wf-{uuid.uuid4().hex[:8]}"

        # Create a workflow row.
        db = SessionLocal()
        try:
            wf = Workflow(
                name=wf_name, description="d",
                definition={"nodes": [], "edges": []},
                tenant_id=tmp_user.tenant_id, is_active=True,
            )
            db.add(wf); db.commit(); db.refresh(wf)
            wf_id = wf.id
        finally:
            db.close()

        # Patch WorkflowExecutor.execute (which is async).
        async def fake_execute(self, workflow_dict, input_data, tenant_id, **kw):
            return {"output": "ok", "echoed_input": input_data}

        with patch.object(
            __import__("lumen_services.workflow_executor", fromlist=["WorkflowExecutor"])
            .WorkflowExecutor, "execute", new=fake_execute,
        ):
            out = run_workflow(name=wf_name, input_data={"q": "hello"})

        assert out["ok"] is True
        assert out["data"]["workflow_id"] == wf_id
        assert out["data"]["result"]["output"] == "ok"
        assert out["data"]["result"]["echoed_input"] == {"q": "hello"}
        assert "execution_time_ms" in out["data"]
        assert out["message"] == "ok"

    def test_returns_error_on_unknown_workflow(self, tmp_user):
        from lumen_mcp_servers.local_demo import run_workflow

        out = run_workflow(name="nonexistent-wf-xyz", input_data={})
        assert out["ok"] is False
        assert "nonexistent-wf-xyz" in out["error"]
        assert out["data"] is None
        assert out["message"] == "workflow_not_found"


class TestFastMCPWiring:
    def test_app_is_exported(self):
        from lumen_mcp_servers.local_demo import app, mcp
        # app is a Starlette ASGI app built manually; see NOTE in local_demo.py.
        assert app is not None
        # mcp 当前注册 7 个工具(6 基础 + M33 加的 query_database Text2SQL)。
        tools = asyncio.run(_list_tool_names(mcp))
        assert len(tools) == 7
        expected = {
            "list_agents", "list_knowledge_bases", "search_knowledge_base",
            "list_chat_sessions", "list_workflows", "run_workflow",
            "query_database",
        }
        assert set(tools) == expected


async def _list_tool_names(mcp):
    """Pull the registered tool names from a FastMCP instance."""
    # FastMCP stores its tools on `mcp._tool_manager._tools` (private but
    # stable across 1.x). If the internal shape changes in a future version,
    # we'll need to update this; assert with a clear failure.
    tools_dict = mcp._tool_manager._tools
    return list(tools_dict.keys())
