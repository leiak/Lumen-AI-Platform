"""Tool skill executor — wraps M14 MCP as a LangChain tool."""
from typing import Any, Dict, Optional
from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, ConfigDict, Field, create_model
from lumen_models.skill_marketplace import SkillMarketplace
from lumen_schemas.skill import ToolTypeConfig
from lumen_services.skill_executors.base import BaseSkillExecutor
import logging

logger = logging.getLogger(__name__)


class ToolExecutor(BaseSkillExecutor):
    type = "tool"

    def to_system_prompt(self, skill: SkillMarketplace) -> Optional[str]:
        return None

    def to_langchain_tool(
        self, skill: SkillMarketplace, tenant_id: int
    ) -> Optional[BaseTool]:
        cfg = ToolTypeConfig(**(skill.type_config or {}))

        # Build input schema from param_schema
        if cfg.param_schema and "properties" in cfg.param_schema:
            fields: Dict[str, Any] = {}
            for name, prop in cfg.param_schema["properties"].items():
                fields[name] = (Any, Field(default=None, description=prop.get("description", "")))
            input_model = create_model("ToolInput", **fields)  # type: ignore
        else:
            # LangChain 1.0: empty schema is treated as "no args"
            # and the input dict is dropped. The ``data`` placeholder
            # forces get_fields() to be non-empty. See
            # ScriptExecutor._empty_input_model docstring.
            class ToolInput(BaseModel):
                model_config = ConfigDict(extra="allow")
                data: Optional[Dict[str, Any]] = None
            input_model = ToolInput

        def _run(input_data=None, **kwargs) -> str:
            # LangChain 1.0: StructuredTool.run(dict) no longer spreads
            # dict as **kwargs; the dict lands as the first positional
            # arg. Normalise to a dict for the executor.
            if input_data is None:
                input_data = kwargs
            elif kwargs:
                input_data = {**input_data, **kwargs}
            try:
                # M17 V1: T7 SkillTestRunner handles real MCP execution with DB.
                return (
                    f"[Tool executor: server={cfg.mcp_server}, "
                    f"tool={cfg.tool_name}, args={input_data}]"
                )
            except Exception as e:
                logger.warning(f"Tool executor failed for skill {skill.id}: {e}")
                return f"Error: {e}"

        return StructuredTool.from_function(
            func=_run,
            name=f"skill_{skill.id}_mcp",
            description=skill.description or f"MCP tool for skill {skill.id}",
            args_schema=input_model,
        )
