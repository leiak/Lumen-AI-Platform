"""CodeNode — 执行受限 Python 源码。

- inputs_mapping: {py_var: workflow_selector}
  简化:workflow_selector 是 dot-path,例如 "input.user_query" 或 "llm_1.response"
- output_var: Python 里要被读出到 result 的变量名(默认 "RESULT")
- 输出: stdout / result / error
"""
import io

from pydantic import ConfigDict, Field

from lumen_core.workflow.entities import BaseNodeData, NodeRunResult, OutputVar
from lumen_core.workflow.nodes.base import BaseNode
from lumen_core.workflow.types import SegmentType

# Module-level import (not lazy) so tests can patch
# ``app.core.workflow.nodes.code.run_python_restricted`` with ``unittest.mock.patch``.
from lumen_core.sandbox.runner import run_python_restricted  # noqa: F401


class CodeNodeData(BaseNodeData):
    model_config = ConfigDict(extra="ignore")
    code: str = ""
    inputs_mapping: dict[str, str] = Field(default_factory=dict)
    output_var: str = "RESULT"


class CodeNode(BaseNode):
    def init_node_data(self, config: dict) -> BaseNodeData:
        return CodeNodeData.model_validate(
            {**config, "version": config.get("version", "1")}
        )

    def outputs(self) -> list[OutputVar]:
        return [
            OutputVar(name="stdout", type=SegmentType.STRING, description="print() 输出"),
            OutputVar(name="result", type=SegmentType.OBJECT, description="RESULT 值"),
            OutputVar(name="error", type=SegmentType.STRING, description="错误信息"),
        ]

    def _build_inputs(self) -> dict:
        assert isinstance(self._data, CodeNodeData)
        d: CodeNodeData = self._data
        inputs: dict = {}
        for py_var, expr in d.inputs_mapping.items():
            parts = expr.split(".")
            value = self.pool.get(parts).value
            inputs[py_var] = value
        return inputs

    async def _run(self) -> NodeRunResult:
        # 错误直接透传给 run_node_with_handling 做 error_strategy 决策
        assert isinstance(self._data, CodeNodeData)
        d: CodeNodeData = self._data
        stdout_buf = io.StringIO()
        result = await run_python_restricted(
            code=d.code,
            inputs=self._build_inputs(),
            output_var=d.output_var,
            stdout=stdout_buf,
        )
        return NodeRunResult(
            node_id=self.node_id,
            output_values={
                "stdout": stdout_buf.getvalue(),
                "result": result,
                "error": None,
            },
        )
