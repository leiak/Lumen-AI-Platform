from pydantic import BaseModel, ConfigDict, Field

from lumen_core.workflow.entities import BaseNodeData, NodeRunResult, OutputVar
from lumen_core.workflow.nodes.base import BaseNode
from lumen_core.workflow.types import SegmentType


class _UserVariable(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str
    type: SegmentType
    required: bool = False
    default: object = None


class InputNodeData(BaseNodeData):
    variables: list[_UserVariable] = Field(default_factory=list)


class InputNode(BaseNode):
    def init_node_data(self, config: dict) -> BaseNodeData:
        cfg = {**config, "version": config.get("version", "1")}
        return InputNodeData.model_validate(cfg)

    def outputs(self) -> list[OutputVar]:
        assert isinstance(self._data, InputNodeData)
        return [
            OutputVar(name=v.name, type=v.type, description=f"输入变量 {v.name}")
            for v in self._data.variables
        ]

    async def _run(self) -> NodeRunResult:
        assert isinstance(self._data, InputNodeData)
        values: dict[str, object] = {}
        for v in self._data.variables:
            var = self.pool.get(["input", v.name])
            values[v.name] = var.value
        return NodeRunResult(node_id=self.node_id, output_values=values)
