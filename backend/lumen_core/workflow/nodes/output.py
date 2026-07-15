from pydantic import Field

from lumen_core.workflow.entities import BaseNodeData, NodeRunResult, OutputVar
from lumen_core.workflow.nodes.base import BaseNode
from lumen_core.workflow.types import SegmentType


class OutputNodeData(BaseNodeData):
    field: str = "current"
    output: dict | None = None  # legacy fallback


class OutputNode(BaseNode):
    def init_node_data(self, config: dict) -> BaseNodeData:
        cfg = {**config}
        if "field" not in cfg and isinstance(cfg.get("output"), dict):
            cfg["field"] = cfg["output"].get("field", "current")
        cfg.setdefault("field", "current")
        cfg.setdefault("version", cfg.get("version", "1"))
        return OutputNodeData.model_validate(cfg)

    def outputs(self) -> list[OutputVar]:
        return [OutputVar(name="value", type=SegmentType.OBJECT)]

    async def _run(self) -> NodeRunResult:
        assert isinstance(self._data, OutputNodeData)
        field = self._data.field
        # NOTE: "current" and "input" semantics below are a Phase C placeholder
        # implementation. Phase D (WorkflowExecutor + the migration script) will
        # likely need to redefine these — see the "OutputNode contract" section
        # in docs/superpowers/plans/2026-06-04-workflow-p1-implementation.md
        # (search for "Phase D may revise"). For now, the test contract in
        # tests/unit/test_workflow_nodes.py is the source of truth.
        if field == "current":
            # The most recently added non-self, non-input, non-env variable's
            # value (i.e. the "current state" of execution). For single-value
            # pools (the common case in tests) this is the only candidate.
            value = self._current_value()
        elif field == "input":
            # The only/first input variable's value. The executor injects
            # user input into the ["input", ...] namespace before nodes run.
            value = self._input_value()
        elif field == "all":
            value = self.pool.snapshot()
        else:
            parts = field.split(".")
            value = self.pool.get(parts).value
        return NodeRunResult(node_id=self.node_id, output_values={"value": value})

    def _current_value(self) -> object | None:
        snap = self.pool.snapshot()
        for node_id, vars_ in reversed(list(snap.items())):
            if node_id in (self.node_id, "input", "env"):
                continue
            if vars_:
                last_name = next(reversed(vars_))
                return vars_[last_name]
        return None

    def _input_value(self) -> object | None:
        input_vars = self.pool.snapshot().get("input", {})
        if input_vars:
            first_name = next(iter(input_vars))
            return input_vars[first_name]
        return None
