"""Script skill executor — wraps ScriptSandbox as a LangChain tool."""
import builtins
from typing import Any, Dict, Optional
from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, ConfigDict, Field, create_model
from lumen_models.skill_marketplace import SkillMarketplace
from lumen_schemas.skill import ScriptTypeConfig
from lumen_services.skill_executors.base import BaseSkillExecutor
from lumen_core.sandbox.script_sandbox import ScriptSandbox
from lumen_core.skill_errors import SkillSecurityError, SkillTimeoutError, SkillExecutionError


class ScriptExecutor(BaseSkillExecutor):
    type = "script"

    @staticmethod
    def _empty_input_model() -> "builtins.type[BaseModel]":
        """Pydantic model with extra='allow' so arbitrary kwargs pass through.

        The ``data: Optional[Dict[str, Any]] = None`` placeholder
        is critical: LangChain 1.0's ``StructuredTool._to_args_and_kwargs``
        treats an *empty* args_schema (``get_fields() == []``) as
        "no args" and drops the input dict on the floor. A single
        non-underscore placeholder field makes ``get_fields()`` return
        a non-empty list, so the input dict lands in ``**kwargs`` of
        the bound ``_run`` (see the ``def _run(input_data=None, **kwargs)``
        signature below).
        """
        class ScriptInput(BaseModel):
            model_config = ConfigDict(extra="allow")
            data: Optional[Dict[str, Any]] = None
        return ScriptInput

    def to_system_prompt(self, skill: SkillMarketplace) -> Optional[str]:
        return None

    def to_langchain_tool(
        self, skill: SkillMarketplace, tenant_id: int
    ) -> Optional[BaseTool]:
        cfg_dict = dict(skill.type_config) if skill.type_config else {}
        cfg = ScriptTypeConfig(**cfg_dict)

        # Build dynamic Pydantic input schema for the tool.
        # When no input_schema is provided, use extra='allow' so Pydantic
        # does NOT strip arbitrary kwargs passed via tool.run({"x": 7}).
        if cfg.input_schema and "properties" in cfg.input_schema:
            fields: Dict[str, Any] = {}
            required = cfg.input_schema.get("required", [])
            for name, prop in cfg.input_schema["properties"].items():
                default = prop.get("default", None)
                fields[name] = (
                    prop.get("type", "string"),
                    Field(default=default, description=prop.get("description", "")),
                )
            input_model = create_model("ScriptInput", **fields)  # type: ignore
        else:
            input_model = self._empty_input_model()

        def _run(input_data=None, **kwargs):
            # LangChain 1.0: StructuredTool.run(dict) no longer spreads
            # dict as **kwargs. The dict lands as the first positional
            # argument. Older LangChain 0.3 + bare-kwargs callers still
            # work via the **kwargs fallback. Normalise to a dict for
            # ScriptSandbox.
            if input_data is None:
                input_data = kwargs
            elif kwargs:
                # Merge — later kwargs win on conflict, matches 0.3
                # behaviour where LLM args were merged into input schema.
                input_data = {**input_data, **kwargs}
            try:
                return ScriptSandbox.execute(cfg.code, input_data, cfg.timeout)
            except SkillSecurityError as e:
                return f"SecurityError: {e}"
            except SkillTimeoutError as e:
                return f"TimeoutError: {e}"
            except SkillExecutionError as e:
                return f"ExecutionError: {e}"

        tool = StructuredTool.from_function(
            func=_run,
            name=f"skill_{skill.id}_script",
            description=str(skill.description or skill.name or f"Run script for skill {skill.id}"),
            args_schema=input_model,
        )
        return tool
