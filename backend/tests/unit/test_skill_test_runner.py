"""Tests for SkillTestRunner (M17)."""
import pytest
from unittest.mock import patch, MagicMock


def _make_skill(type: str, type_config: dict, content: str = None):
    from lumen_core.database import SessionLocal
    from lumen_models.skill_marketplace import SkillMarketplace
    import uuid
    db = SessionLocal()
    s = SkillMarketplace(
        name=f"tr-{type}-{uuid.uuid4().hex[:6]}",
        category="code",
        content=content,
        type=type,
        type_config=type_config,
        is_verified=1,
    )
    db.add(s); db.commit(); db.refresh(s)
    db.close()
    return s


def test_test_run_prompt_returns_preview():
    from lumen_services.skill_test_runner import SkillTestRunner
    from lumen_core.database import SessionLocal
    s = _make_skill("prompt", type_config=None, content="be nice")
    db = SessionLocal()
    try:
        result = SkillTestRunner.test_run(db, 1, s, {})
        assert result.error is None
        assert result.type == "prompt"
        assert result.result == {"preview": "be nice"}
        assert result.latency_ms >= 0
    finally:
        db.close()


def test_test_run_script_succeeds():
    from lumen_services.skill_test_runner import SkillTestRunner
    from lumen_core.database import SessionLocal
    s = _make_skill("script", type_config={
        "code": "def main(x): return x * 2", "timeout": 5,
    })
    db = SessionLocal()
    try:
        result = SkillTestRunner.test_run(db, 1, s, {"x": 7})
        assert result.error is None
        assert result.type == "script"
        assert result.result == 14
    finally:
        db.close()


def test_test_run_script_security_error_returns_error():
    from lumen_services.skill_test_runner import SkillTestRunner
    from lumen_core.database import SessionLocal
    s = _make_skill("script", type_config={
        "code": "import os", "timeout": 5,
    })
    db = SessionLocal()
    try:
        result = SkillTestRunner.test_run(db, 1, s, {})
        assert result.error is not None
        assert result.result is None
    finally:
        db.close()


def test_test_run_kb_returns_chunks():
    from lumen_services.skill_test_runner import SkillTestRunner
    from lumen_core.database import SessionLocal
    s = _make_skill("knowledge_retrieval", type_config={
        "kb_id": 1, "top_k": 3, "score_threshold": 0.5,
        "query_template": "What is {{topic}}?",
    })
    db = SessionLocal()
    try:
        # KnowledgeRetrievalNode.execute is an instance method — patch the
        # constructor to return a mock with a sync .execute() returning chunks.
        mock_node = MagicMock()
        mock_node.execute = MagicMock(return_value=[
            MagicMock(text="chunk1", score=0.9),
            MagicMock(text="chunk2", score=0.8),
        ])
        with patch(
            "lumen_core.workflow.nodes.knowledge_retrieval.KnowledgeRetrievalNode",
            return_value=mock_node,
        ):
            result = SkillTestRunner.test_run(db, 1, s, {"topic": "Python"})
        assert result.error is None
        assert result.type == "knowledge_retrieval"
        assert len(result.result) == 2
        assert result.result[0]["text"] == "chunk1"
    finally:
        db.close()


def test_test_run_tool_returns_mcp_result():
    from lumen_services.skill_test_runner import SkillTestRunner
    from lumen_core.database import SessionLocal
    s = _make_skill("tool", type_config={
        "mcp_server": "demo-mcp", "tool_name": "list_workflows",
    })
    db = SessionLocal()
    try:
        # MCPService.mcp_call is an instance method — patch the constructor.
        mock_mcp = MagicMock()
        mock_mcp.mcp_call = MagicMock(return_value={
            "workflows": [{"id": 1, "name": "wf1"}],
        })
        with patch(
            "lumen_services.mcp_service.MCPService",
            return_value=mock_mcp,
        ):
            result = SkillTestRunner.test_run(db, 1, s, {"page": 1})
        assert result.error is None
        assert result.type == "tool"
        assert result.result == {"workflows": [{"id": 1, "name": "wf1"}]}
    finally:
        db.close()


def test_test_run_handles_executor_exception():
    from lumen_services.skill_test_runner import SkillTestRunner
    from lumen_core.database import SessionLocal
    s = _make_skill("script", type_config={
        "code": "def main(x): return x", "timeout": 5,
    })
    db = SessionLocal()
    try:
        with patch(
            "lumen_core.sandbox.script_sandbox.ScriptSandbox.execute",
            side_effect=RuntimeError("kaboom"),
        ):
            result = SkillTestRunner.test_run(db, 1, s, {"x": 1})
        assert result.error == "kaboom"
        assert result.result is None
        assert result.latency_ms >= 0
    finally:
        db.close()
