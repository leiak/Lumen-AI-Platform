"""VariableAssignerNode — 批量写入 VariablePool。

每个 operation 三种 value_source:
- constant:  字面量
- upstream_ref: 从 pool 的某个 [node_id, var] 读取
- expression:  Jinja2 表达式,可引用 pool 中所有变量

写入位置: [self.node_id, op.variable]
"""
from typing import Any, Literal

from jinja2 import Environment, StrictUndefined, TemplateError
from pydantic import BaseModel, ConfigDict, Field

from lumen_core.workflow.entities import BaseNodeData, NodeRunResult, OutputVar
from lumen_core.workflow.executor_helpers import build_jinja_context
from lumen_core.workflow.nodes.base import BaseNode
from lumen_core.workflow.types import SegmentType
from lumen_core.workflow.variables import NoneVariable


class Assignment(BaseModel):
    model_config = ConfigDict(extra="ignore")
    variable: str
    value_source: Literal["constant", "upstream_ref", "expression"] = "constant"
    constant_value: Any = None
    upstream_ref: list[str] = Field(default_factory=list)
    expression: str = ""


class VariableAssignerNodeData(BaseNodeData):
    model_config = ConfigDict(extra="ignore")
    operations: list[Assignment] = Field(default_factory=list)


class VariableAssignerNode(BaseNode):
    def init_node_data(self, config: dict) -> BaseNodeData:
        return VariableAssignerNodeData.model_validate(
            {**config, "version": config.get("version", "1")}
        )

    def outputs(self) -> list[OutputVar]:
        assert isinstance(self._data, VariableAssignerNodeData)
        d: VariableAssignerNodeData = self._data
        return [
            OutputVar(name=op.variable, type=SegmentType.OBJECT, description=f"赋值变量 {op.variable}")
            for op in d.operations
        ] + [
            OutputVar(name="_assigned", type=SegmentType.OBJECT, description="所有赋值结果"),
            OutputVar(name="_error", type=SegmentType.STRING, description="错误信息"),
        ]

    async def _run(self) -> NodeRunResult:
        assert isinstance(self._data, VariableAssignerNodeData)
        d: VariableAssignerNodeData = self._data
        env = Environment(undefined=StrictUndefined)
        assigned: dict[str, Any] = {}
        for op in d.operations:
            if op.value_source == "constant":
                value: Any = op.constant_value
            elif op.value_source == "upstream_ref":
                if not op.upstream_ref:
                    raise ValueError(f"upstream_ref required for {op.variable!r}")
                resolved = self.pool.get(op.upstream_ref)
                if isinstance(resolved, NoneVariable):
                    raise ValueError(
                        f"upstream_ref {op.upstream_ref!r} not found for {op.variable!r}"
                    )
                value = resolved.value
            elif op.value_source == "expression":
                ctx = build_jinja_context(self.pool.snapshot())
                try:
                    # compile_expression returns a callable that evaluates the
                    # expression with its native Python type (int stays int,
                    # str stays str). from_string+render always stringifies.
                    compiled = env.compile_expression(op.expression)
                    value = compiled(**ctx)
                except TemplateError as e:
                    raise ValueError(f"Template error in expression: {e}") from e
            else:
                raise ValueError(f"Unknown value_source: {op.value_source!r}")
            self.pool.add([self.node_id, op.variable], value)
            assigned[op.variable] = value
        return NodeRunResult(
            node_id=self.node_id,
            output_values={"_assigned": assigned, "_error": None},
        )
