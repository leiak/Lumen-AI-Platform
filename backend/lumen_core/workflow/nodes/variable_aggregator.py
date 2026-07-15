"""VariableAggregatorNode — 聚合上游单一节点单一 list-typed var。

跟 FanIn 区别:FanIn 接收"多个上游节点同名 var",VariableAggregator 接收"单一上游 list var"
做集合/数值/字符串聚合。
"""
from typing import Any, Literal

from pydantic import ConfigDict

from lumen_core.workflow.entities import BaseNodeData, NodeRunResult, OutputVar
from lumen_core.workflow.nodes.base import BaseNode
from lumen_core.workflow.types import SegmentType
from lumen_core.workflow.variables import NoneVariable

Aggregation = Literal["collect", "sum", "average", "join", "first", "last"]


class VariableAggregatorNodeData(BaseNodeData):
    model_config = ConfigDict(extra="ignore")
    source_node_id: str = ""
    source_var: str = "results"
    aggregation: Aggregation = "collect"
    join_separator: str = "\n"


class VariableAggregatorNode(BaseNode):
    def init_node_data(self, config: dict) -> BaseNodeData:
        return VariableAggregatorNodeData.model_validate(
            {**config, "version": config.get("version", "1")}
        )

    def outputs(self) -> list[OutputVar]:
        return [
            OutputVar(name="output", type=SegmentType.OBJECT, description="聚合结果"),
            OutputVar(name="count", type=SegmentType.NUMBER, description="元素数"),
            OutputVar(name="_error", type=SegmentType.STRING, description="错误信息"),
        ]

    async def _run(self) -> NodeRunResult:
        assert isinstance(self._data, VariableAggregatorNodeData)
        d: VariableAggregatorNodeData = self._data
        result = self.pool.get([d.source_node_id, d.source_var])
        if isinstance(result, NoneVariable):
            raise ValueError(
                f"Source variable {d.source_node_id}.{d.source_var} not found in pool"
            )
        items = result.value
        if items is None:
            items = []
        if not isinstance(items, list):
            raise ValueError(
                f"VariableAggregator expects list, got {type(items).__name__} "
                f"from {d.source_node_id}.{d.source_var}"
            )
        agg = d.aggregation
        output: Any
        if agg == "collect":
            output = items
        elif agg == "sum":
            output = sum(float(x) for x in items)
        elif agg == "average":
            output = sum(float(x) for x in items) / len(items) if items else 0.0
        elif agg == "join":
            output = d.join_separator.join(str(x) for x in items)
        elif agg == "first":
            output = items[0] if items else None
        elif agg == "last":
            output = items[-1] if items else None
        else:
            raise ValueError(f"Unknown aggregation: {agg!r}")
        return NodeRunResult(
            node_id=self.node_id,
            output_values={"output": output, "count": len(items), "_error": None},
        )
