"""ParameterExtractorNode — LLM-based 参数抽取(用户定义 JSON schema)。"""
import json
import re
import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from lumen_core.llm_call_context import LLMCallContext, set_call_context, reset_call_context
from lumen_core.workflow.entities import BaseNodeData, NodeRunResult, OutputVar
from lumen_core.workflow.nodes.base import BaseNode
from lumen_core.workflow.template_parser import VariableTemplateParser
from lumen_core.workflow.types import SegmentType
from lumen_models.model_config import ModelConfig
from lumen_services.model_loader import create_chat_model


class ParameterDef(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str
    type: Literal["string", "number", "boolean"]
    description: str = ""
    required: bool = True


class ParameterExtractorNodeData(BaseNodeData):
    model_config = ConfigDict(protected_namespaces=(), extra="ignore")
    model_config_id: int | None = None
    model_name_cache: str = ""
    input_text: str = ""
    parameters: list[ParameterDef] = Field(default_factory=list)
    system_prompt: str = ""
    temperature: float = 0.0
    instruction: str = "请从以下文本中提取参数,以 JSON 格式输出:"


_TYPE_MAP = {
    "string": SegmentType.STRING,
    "number": SegmentType.NUMBER,
    "boolean": SegmentType.BOOLEAN,
}


def _strip_code_fence(s: str) -> str:
    s = s.strip()
    s = re.sub(r"^```(?:json)?\s*", "", s)
    s = re.sub(r"\s*```$", "", s)
    return s


def _coerce(v: Any, type_str: str) -> Any:
    if v is None:
        return None
    if type_str == "string":
        return str(v)
    if type_str == "number":
        return float(v)
    if type_str == "boolean":
        if isinstance(v, bool):
            return v
        if str(v).lower() in ("true", "1", "yes"):
            return True
        return False
    return v


class ParameterExtractorNode(BaseNode):
    def init_node_data(self, config: dict) -> BaseNodeData:
        return ParameterExtractorNodeData.model_validate(
            {**config, "version": config.get("version", "1")}
        )

    def outputs(self) -> list[OutputVar]:
        assert isinstance(self._data, ParameterExtractorNodeData)
        d: ParameterExtractorNodeData = self._data
        return [
            OutputVar(name=p.name, type=_TYPE_MAP[p.type], description=p.description)
            for p in d.parameters
        ] + [
            OutputVar(name="_raw", type=SegmentType.STRING, description="LLM 原始输出"),
            OutputVar(name="_error", type=SegmentType.STRING, description="错误信息"),
        ]

    async def _run(self) -> NodeRunResult:
        assert isinstance(self._data, ParameterExtractorNodeData)
        d: ParameterExtractorNodeData = self._data
        text = VariableTemplateParser(d.input_text).format(self.pool)

        if self.db is None:
            raise ValueError("ParameterExtractorNode 需要 db session 才能查找模型")
        mc = (
            self.db.query(ModelConfig)
            .filter(ModelConfig.id == d.model_config_id, ModelConfig.is_active.is_(True))
            .first()
        )
        if mc is not None and self.tenant_id is not None and mc.tenant_id != self.tenant_id:
            mc = None
        if not mc:
            raise ValueError("Model not found or inactive")

        schema_lines = [
            f"- {p.name} ({p.type}{', required' if p.required else ', optional'}): {p.description}"
            for p in d.parameters
        ]
        schema_str = "\n".join(schema_lines)
        prompt = f"{d.instruction}\n\nParameters:\n{schema_str}\n\nText:\n{text}\n\nOutput JSON:"

        chat = create_chat_model(
            model_type=mc.model_type,  # type: ignore[arg-type]
            model_name=mc.model_name,  # type: ignore[arg-type]
            base_url=mc.base_url,      # type: ignore[arg-type]
            api_key=mc.api_key,        # type: ignore[arg-type]
        )
        # M26: stamp an LLMCallContext so the LoggingChatModel wrapper
        # writes one row to llm_call_logs. trace_id / workflow ids are
        # threaded in by WorkflowExecutor before run_node_with_handling
        # invokes _run.
        trace_id = self.config.get("trace_id") or str(uuid.uuid4())
        ctx_token = set_call_context(LLMCallContext(
            call_id=str(uuid.uuid4()),
            trace_id=trace_id,
            parent_call_id=None,
            call_type="workflow.parameter_extractor",
            call_index=0,
            tenant_id=self.config.get("tenant_id"),
            workflow_id=self.config.get("workflow_id"),
            workflow_run_id=self.config.get("workflow_run_id"),
            workflow_node_id=self.node_id,
        ))
        try:
            resp = await chat.ainvoke(prompt)
        finally:
            reset_call_context(ctx_token)
        raw = resp.content if hasattr(resp, "content") else str(resp)
        try:
            extracted = json.loads(_strip_code_fence(raw))
        except Exception as e:
            raise ValueError(f"LLM returned non-JSON: {e}\nRaw: {raw[:200]}")

        values: dict[str, Any] = {}
        for p in d.parameters:
            v = extracted.get(p.name)
            if v is None and p.required:
                raise ValueError(f"Required parameter {p.name!r} missing from LLM output")
            values[p.name] = _coerce(v, p.type)
        values["_raw"] = raw
        values["_error"] = None
        return NodeRunResult(node_id=self.node_id, output_values=values)
