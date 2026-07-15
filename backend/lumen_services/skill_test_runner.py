"""SkillTestRunner — 5-type dry-run wrapper for test-run endpoint (M17)."""
import time
from typing import Any
from sqlalchemy.orm import Session
from lumen_models.skill_marketplace import SkillMarketplace
from lumen_services.skill_executors import get_executor
from lumen_services.skill_executors.prompt import PromptExecutor
from lumen_schemas.skill import SkillTestRunResult
from lumen_core.skill_errors import SkillExecutionError
import logging

logger = logging.getLogger(__name__)


class SkillTestRunner:
    """Dry-run a skill with sample input. Returns the result + latency.

    M17 supports all 5 skill types:
      - prompt:    render the system prompt (no execution)
      - script:    execute in RestrictedPython sandbox
      - http:      call HttpCaller (SSRF + allowlist still enforced)
      - knowledge_retrieval: query KB, return top-k chunks
      - tool:      call MCP tool, return result
    """

    @staticmethod
    def test_run(
        db: Session,
        tenant_id: int,
        skill: SkillMarketplace,
        input_args: dict,
    ) -> SkillTestRunResult:
        start = time.time()
        try:
            result = SkillTestRunner._dispatch(db, tenant_id, skill, input_args)
            latency_ms = int((time.time() - start) * 1000)
            return SkillTestRunResult(
                result=result, latency_ms=latency_ms, type=skill.type,
            )
        except Exception as e:
            latency_ms = int((time.time() - start) * 1000)
            logger.warning(f"SkillTestRunner failed for skill {skill.id}: {e}")
            return SkillTestRunResult(
                result=None, latency_ms=latency_ms, type=skill.type, error=str(e),
            )

    @staticmethod
    def _dispatch(
        db: Session, tenant_id: int, skill: SkillMarketplace, input_args: dict,
    ) -> Any:
        if skill.type == "prompt":
            executor = PromptExecutor()
            content = executor.to_system_prompt(skill)
            return {"preview": content}

        if skill.type == "script":
            from lumen_core.sandbox.script_sandbox import ScriptSandbox
            from lumen_schemas.skill import ScriptTypeConfig
            cfg = ScriptTypeConfig(**(skill.type_config or {}))
            return ScriptSandbox.execute(cfg.code, input_args, cfg.timeout)

        if skill.type == "http":
            from lumen_core.sandbox.http_caller import HttpCaller
            from lumen_services.skill_executors.http import _resolve_allowed_domains
            from lumen_schemas.skill import HttpTypeConfig
            cfg = HttpTypeConfig(**(skill.type_config or {}))
            allowed = _resolve_allowed_domains()
            return HttpCaller.execute(cfg, input_args, allowed)

        if skill.type == "knowledge_retrieval":
            from lumen_core.workflow.nodes.knowledge_retrieval import (
                KnowledgeRetrievalNode, KnowledgeRetrievalNodeData
            )
            from lumen_schemas.skill import KnowledgeRetrievalTypeConfig
            cfg = KnowledgeRetrievalTypeConfig(**(skill.type_config or {}))
            # Build query from template
            query = cfg.query_template
            for k, v in input_args.items():
                query = query.replace("{{" + k + "}}", str(v))
            if not query or query == cfg.query_template:
                query = next(iter(input_args.values()), "")
            node_data = KnowledgeRetrievalNodeData(
                kb_id=cfg.kb_id, top_k=cfg.top_k, score_threshold=cfg.score_threshold,
            )
            node = KnowledgeRetrievalNode(
                node_id=f"skill_{skill.id}", config={"tenant_id": tenant_id}, db=db,
            )
            chunks = node.execute(query, cfg.top_k, cfg.score_threshold)
            return [
                {"text": getattr(c, "text", str(c)),
                 "score": getattr(c, "score", None)}
                for c in chunks
            ]

        if skill.type == "tool":
            from lumen_services.mcp_service import MCPService
            from lumen_schemas.skill import ToolTypeConfig
            cfg = ToolTypeConfig(**(skill.type_config or {}))
            mcp = MCPService(db=db, tenant_id=tenant_id)
            return mcp.mcp_call(tool_name=cfg.tool_name, input_data=input_args)

        raise SkillExecutionError(f"Unsupported skill type: {skill.type}")
