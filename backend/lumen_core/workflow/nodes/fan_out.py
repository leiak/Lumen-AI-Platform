from pydantic import Field

from lumen_core.workflow.entities import BaseNodeData, NodeRunResult, OutputVar
from lumen_core.workflow.nodes.base import BaseNode
from lumen_core.workflow.types import SegmentType


class FanOutNodeData(BaseNodeData):
    fan_out: dict = Field(default_factory=dict)


class FanOutNode(BaseNode):
    def init_node_data(self, config: dict) -> BaseNodeData:
        cfg = {**config, "version": config.get("version", "1")}
        return FanOutNodeData.model_validate(cfg)

    def outputs(self) -> list[OutputVar]:
        return [
            OutputVar(
                name="results",
                type=SegmentType.ARRAY_OBJECT,
                description="拆分后的 items 数组(P1 stub)",
            ),
        ]

    async def _run(self) -> NodeRunResult:
        assert isinstance(self._data, FanOutNodeData)
        items = self._data.fan_out.get("items", [])
        return NodeRunResult(
            node_id=self.node_id,
            output_values={"results": [{"item": x} for x in items]},
        )
