from lumen_core.workflow.entities import BaseNodeData, NodeRunResult, OutputVar
from lumen_core.workflow.nodes.base import BaseNode, _passthrough_outputs


class StartNode(BaseNode):
    def init_node_data(self, config: dict) -> BaseNodeData:
        return BaseNodeData.model_validate(config)

    def outputs(self) -> list[OutputVar]:
        return _passthrough_outputs()

    async def _run(self) -> NodeRunResult:
        return NodeRunResult(node_id=self.node_id, output_values={})
