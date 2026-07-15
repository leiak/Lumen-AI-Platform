"""TemplateTransformNode — Jinja2 模板渲染。

P2 简化:只暴露 {{ node_id.var }} 一层访问,不支持 {{ node_id.var.subkey }}。
P2.5 升级为递归 PointableValue。
"""
from jinja2 import Environment, StrictUndefined, TemplateError
from pydantic import ConfigDict

from lumen_core.workflow.entities import BaseNodeData, NodeRunResult, OutputVar
from lumen_core.workflow.executor_helpers import build_jinja_context
from lumen_core.workflow.nodes.base import BaseNode
from lumen_core.workflow.types import SegmentType


class TemplateTransformNodeData(BaseNodeData):
    model_config = ConfigDict(extra="ignore")
    template: str = ""


class TemplateTransformNode(BaseNode):
    def init_node_data(self, config: dict) -> BaseNodeData:
        return TemplateTransformNodeData.model_validate(
            {**config, "version": config.get("version", "1")}
        )

    def outputs(self) -> list[OutputVar]:
        return [
            OutputVar(name="output", type=SegmentType.STRING, description="渲染结果"),
            OutputVar(name="error", type=SegmentType.STRING, description="错误信息"),
        ]

    async def _run(self) -> NodeRunResult:
        assert isinstance(self._data, TemplateTransformNodeData)
        d: TemplateTransformNodeData = self._data
        env = Environment(undefined=StrictUndefined, autoescape=False)
        ctx = build_jinja_context(self.pool.snapshot())
        try:
            tmpl = env.from_string(d.template)
            rendered = tmpl.render(**ctx)
        except TemplateError as e:
            raise ValueError(f"Template error: {e}") from e
        return NodeRunResult(
            node_id=self.node_id,
            output_values={"output": rendered, "error": None},
        )
