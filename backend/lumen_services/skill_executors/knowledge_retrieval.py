"""KnowledgeRetrieval skill executor — wraps M13 KB retrieval as a LangChain tool."""
import re
from typing import Any, Dict, Optional
from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, ConfigDict, Field, create_model
from lumen_models.skill_marketplace import SkillMarketplace
from lumen_schemas.skill import KnowledgeRetrievalTypeConfig
from lumen_services.skill_executors.base import BaseSkillExecutor
import logging

logger = logging.getLogger(__name__)


class KnowledgeRetrievalExecutor(BaseSkillExecutor):
    type = "knowledge_retrieval"

    def to_system_prompt(self, skill: SkillMarketplace) -> Optional[str]:
        return None

    def to_langchain_tool(
        self, skill: SkillMarketplace, tenant_id: int
    ) -> Optional[BaseTool]:
        cfg = KnowledgeRetrievalTypeConfig(**(skill.type_config or {}))

        # Build input schema from query_template placeholders
        if cfg.query_template and "{{" in cfg.query_template:
            arg_names = re.findall(r"\{\{(\w+)\}\}", cfg.query_template)
            if arg_names:
                fields: Dict[str, Any] = {
                    name: (str, Field(...)) for name in arg_names
                }
                input_model = create_model("KBInput", **fields)  # type: ignore
            else:
                # LangChain 1.0: empty schema is treated as "no args"
                # and the input dict is dropped. The ``data`` placeholder
                # forces get_fields() to be non-empty so the input lands
                # in **kwargs of _run. See ScriptExecutor._empty_input_model
                # docstring for the full rationale.
                class KBInput(BaseModel):
                    model_config = ConfigDict(extra="allow")
                    data: Optional[Dict[str, Any]] = None
                input_model = KBInput
        else:
            class KBInput(BaseModel):
                query: str = Field(...)
            input_model = KBInput

        def _run(input_data=None, **kwargs) -> str:
            # LangChain 1.0: StructuredTool.run(dict) no longer spreads
            # dict as **kwargs; the dict lands as the first positional
            # arg. Normalise to a dict for the executor.
            if input_data is None:
                input_data = kwargs
            elif kwargs:
                input_data = {**input_data, **kwargs}
            try:
                # Replace placeholders in query_template
                query = cfg.query_template
                for k, v in input_data.items():
                    query = query.replace("{{" + k + "}}", str(v))
                if not query or query == cfg.query_template:
                    # No placeholders replaced — use first arg as query
                    query = next(iter(input_data.values()), "")

                # M17 V1: T7 SkillTestRunner handles real KB execution with DB.
                # This stub returns a placeholder. Future V2 will plumb DB.
                return f"[KB executor: kb_id={cfg.kb_id}, top_k={cfg.top_k}, query='{query}']"
            except Exception as e:
                logger.warning(f"KB executor failed for skill {skill.id}: {e}")
                return f"Error: {e}"

        tool = StructuredTool.from_function(
            func=_run,
            name=f"skill_{skill.id}_kb",
            description=skill.description or f"KB retrieval for skill {skill.id}",
            args_schema=input_model,
        )
        return tool
