"""HTTP skill executor — wraps HttpCaller as a LangChain tool."""
import builtins
import json
from typing import Any, Dict, Optional
from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, ConfigDict, Field, create_model
from lumen_models.skill_marketplace import SkillMarketplace
from lumen_schemas.skill import HttpTypeConfig
from lumen_services.skill_executors.base import BaseSkillExecutor
from lumen_core.sandbox.http_caller import HttpCaller
from lumen_core.skill_errors import SkillSecurityError, SkillExecutionError


def _resolve_allowed_domains() -> list:
    """Read the platform allowlist from SystemConfig.

    Reads ``system_configs.key = 'skill_http_allowed_domains'`` and
    returns it as a list. Returns ``[]`` (fail-closed) when:
      - the ``system_configs`` table or row is missing
      - the value is malformed JSON
      - any DB error (so a transient connection blip doesn't open
        the allowlist wide)

    The row is seeded idempotently by
    :func:`lumen_core.database.ensure_system_configs_table` on first
    uvicorn startup, so a freshly-created dev DB has the 3 default
    entries (api.open-meteo.com / api.frankfurter.app / is.gd)
    out-of-the-box without an extra INSERT step.
    """
    from lumen_core.database import SessionLocal
    from lumen_models.system_config import SystemConfig

    db = SessionLocal()
    try:
        row = db.query(SystemConfig).filter(
            SystemConfig.key == "skill_http_allowed_domains"
        ).first()
        if row is None:
            return []
        val = row.value
        if isinstance(val, list):
            return val
        return json.loads(val) if isinstance(val, str) else []
    except Exception:
        return []
    finally:
        db.close()


class HttpExecutor(BaseSkillExecutor):
    type = "http"

    @staticmethod
    def _empty_input_model() -> "builtins.type[BaseModel]":
        """Pydantic model with extra='allow' so arbitrary kwargs pass through.

        The ``data: Optional[Dict[str, Any]] = None`` placeholder
        is critical: LangChain 1.0's ``StructuredTool._to_args_and_kwargs``
        treats an *empty* args_schema (``get_fields() == []``) as
        "no args" and drops the input dict on the floor. See
        ``ScriptExecutor._empty_input_model`` docstring for the
        full rationale.
        """
        class HttpInput(BaseModel):
            model_config = ConfigDict(extra="allow")
            data: Optional[Dict[str, Any]] = None
        return HttpInput

    def to_system_prompt(self, skill: SkillMarketplace) -> Optional[str]:
        return None

    def to_langchain_tool(
        self, skill: SkillMarketplace, tenant_id: int
    ) -> Optional[BaseTool]:
        cfg_dict = dict(skill.type_config) if skill.type_config else {}
        cfg = HttpTypeConfig(**cfg_dict)

        # Build input model from body_template placeholders.
        # When no body_template, use extra='allow' so arbitrary kwargs
        # (e.g. query params) aren't stripped by Pydantic validation.
        if cfg.body_template and "{{" in cfg.body_template:
            # Extract {{arg}} placeholders
            import re
            arg_names = re.findall(r"\{\{(\w+)\}\}", cfg.body_template)
            if arg_names:
                fields: Dict[str, Any] = {
                    name: (str, Field(...)) for name in arg_names
                }
                input_model = create_model("HttpInput", **fields)  # type: ignore
            else:
                input_model = self._empty_input_model()
        else:
            input_model = self._empty_input_model()

        def _run(input_data=None, **kwargs) -> str:
            # LangChain 1.0: StructuredTool.run(dict) no longer spreads
            # dict as **kwargs; the dict lands as the first positional
            # arg. Normalise to a dict for HttpCaller.
            if input_data is None:
                input_data = kwargs
            elif kwargs:
                input_data = {**input_data, **kwargs}
            try:
                allowed = _resolve_allowed_domains()
                return HttpCaller.execute(cfg, input_data, allowed)
            except SkillSecurityError as e:
                return f"SecurityError: {e}"
            except SkillExecutionError as e:
                return f"ExecutionError: {e}"

        tool = StructuredTool.from_function(
            func=_run,
            name=f"skill_{skill.id}_http",
            description=str(skill.description or skill.name or f"HTTP call for skill {skill.id}"),
            args_schema=input_model,
        )
        return tool
