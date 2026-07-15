from pydantic import Field

from lumen_core.workflow.entities import BaseNodeData, NodeRunResult, OutputVar
from lumen_core.workflow.nodes.base import BaseNode
from lumen_core.workflow.types import SegmentType


class FanInNodeData(BaseNodeData):
    fan_in: dict = Field(default_factory=dict)


class FanInNode(BaseNode):
    def init_node_data(self, config: dict) -> BaseNodeData:
        cfg = {**config, "version": config.get("version", "1")}
        return FanInNodeData.model_validate(cfg)

    def outputs(self) -> list[OutputVar]:
        return [
            OutputVar(name="result", type=SegmentType.OBJECT, description="聚合结果"),
            OutputVar(name="count", type=SegmentType.NUMBER, description="元素数量"),
        ]

    async def _run(self) -> NodeRunResult:
        assert isinstance(self._data, FanInNodeData)
        source = self._data.fan_in.get("source")
        aggregation = self._data.fan_in.get("aggregation", "collect")
        results = self.pool.get([source, "results"]).value if source else []
        count = len(results) if isinstance(results, list) else 0
        if not isinstance(results, list):
            # Missing source or non-list results: fall through to identity return
            value = results
        elif aggregation == "collect":
            value = results
        elif aggregation == "sum":
            value = sum(x.get("x", 0) for x in results if isinstance(x, dict))
        elif aggregation == "average":
            xs = [x.get("x", 0) for x in results if isinstance(x, dict)]
            value = sum(xs) / len(xs) if xs else 0
        else:
            value = results
        return NodeRunResult(
            node_id=self.node_id,
            output_values={"result": value, "count": count},
        )
