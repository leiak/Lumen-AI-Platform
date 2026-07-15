from pydantic import Field

from lumen_core.workflow.condition import ConditionProcessor
from lumen_core.workflow.entities import (
    BaseNodeData, ConditionCase, NodeRunResult, OutputVar,
)
from lumen_core.workflow.nodes.base import BaseNode
from lumen_core.workflow.types import SegmentType


class ConditionNodeData(BaseNodeData):
    cases: list[ConditionCase] = Field(default_factory=list)


class ConditionNode(BaseNode):
    def init_node_data(self, config: dict) -> BaseNodeData:
        cfg = {**config, "version": config.get("version", "1")}
        return ConditionNodeData.model_validate(cfg)

    def outputs(self) -> list[OutputVar]:
        return [
            OutputVar(name="result", type=SegmentType.BOOLEAN, description="求值结果"),
            OutputVar(name="selected_case_id", type=SegmentType.STRING, description="命中的 case_id"),
        ]

    async def _run(self) -> NodeRunResult:
        assert isinstance(self._data, ConditionNodeData)
        matched, case_id = ConditionProcessor.process_cases(
            self._data.cases, self.pool
        )
        return NodeRunResult(
            node_id=self.node_id,
            output_values={"result": matched, "selected_case_id": case_id},
            edge_source_handle=case_id,
        )
