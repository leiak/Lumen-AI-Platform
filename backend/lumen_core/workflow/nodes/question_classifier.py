"""QuestionClassifierNode — LLM-based 问题分类(用户定义类别列表)。"""
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from lumen_core.llm_call_context import LLMCallContext, set_call_context, reset_call_context
from lumen_core.workflow.entities import BaseNodeData, NodeRunResult, OutputVar
from lumen_core.workflow.nodes.base import BaseNode
from lumen_core.workflow.template_parser import VariableTemplateParser
from lumen_core.workflow.types import SegmentType
from lumen_models.model_config import ModelConfig
from lumen_services.model_loader import create_chat_model


class Category(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    name: str
    description: str = ""


class QuestionClassifierNodeData(BaseNodeData):
    model_config = ConfigDict(extra="ignore", protected_namespaces=())
    model_config_id: int | None = None
    model_name_cache: str = ""
    input_text: str = ""
    categories: list[Category] = Field(default_factory=list)
    system_prompt: str = ""
    temperature: float = 0.0
    instruction: str = "请把以下问题分类到最合适的类别,只输出类别 ID:"


class QuestionClassifierNode(BaseNode):
    def init_node_data(self, config: dict) -> BaseNodeData:
        return QuestionClassifierNodeData.model_validate(
            {**config, "version": config.get("version", "1")}
        )

    def outputs(self) -> list[OutputVar]:
        return [
            OutputVar(name="class_name", type=SegmentType.STRING, description="命中的类别显示名"),
            OutputVar(name="class_id", type=SegmentType.STRING, description="命中的类别 ID"),
            OutputVar(name="confidence", type=SegmentType.NUMBER, description="置信度(0-1)"),
            OutputVar(name="_raw", type=SegmentType.STRING, description="LLM 原始输出"),
            OutputVar(name="_error", type=SegmentType.STRING, description="错误信息"),
        ]

    async def _run(self) -> NodeRunResult:
        assert isinstance(self._data, QuestionClassifierNodeData)
        d: QuestionClassifierNodeData = self._data
        if not d.categories:
            raise ValueError("至少一个类别")
        text = VariableTemplateParser(d.input_text).format(self.pool)

        if self.db is None:
            raise ValueError("QuestionClassifierNode 需要 db session 才能查找模型")
        mc = (
            self.db.query(ModelConfig)
            .filter(ModelConfig.id == d.model_config_id, ModelConfig.is_active.is_(True))
            .first()
        )
        if mc is not None and self.tenant_id is not None and mc.tenant_id != self.tenant_id:
            mc = None
        if not mc:
            raise ValueError("Model not found or inactive")

        cats_str = "\n".join(
            f"- {c.id} ({c.name}): {c.description}" for c in d.categories
        )
        prompt = f"{d.instruction}\n\nCategories:\n{cats_str}\n\nQuestion:\n{text}\n\nClass ID:"

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
            call_type="workflow.question_classifier",
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
        predicted_id = raw.strip()
        cat = next((c for c in d.categories if c.id == predicted_id), None)
        if not cat:
            raise ValueError(f"LLM returned unknown class: {predicted_id!r}")
        return NodeRunResult(
            node_id=self.node_id,
            output_values={
                "class_name": cat.name,
                "class_id": cat.id,
                "confidence": 1.0,
                "_raw": raw,
                "_error": None,
            },
        )
