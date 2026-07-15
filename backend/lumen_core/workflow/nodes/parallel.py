"""ParallelNode — runs N branches concurrently via asyncio.gather.

M30d (D6): the pre-M30d implementation was a stub that just echoed
the branch IDs back. M30d turns it into a real parallel runner:
each branch in `parallel.branches` is an async task (typically a
sleep, but in production it would be a sub-workflow invocation).
``asyncio.gather`` runs them concurrently, so the total wall time
is bounded by the *slowest* branch instead of the sum.

Test for true concurrency: schedule 4 branches each with a 0.2s
delay. Sequential would take ~0.8s; gather finishes in ~0.2s.
"""
import asyncio
import time
from typing import Any

from pydantic import Field

from lumen_core.workflow.entities import BaseNodeData, NodeRunResult, OutputVar
from lumen_core.workflow.nodes.base import BaseNode
from lumen_core.workflow.types import SegmentType


class ParallelNodeData(BaseNodeData):
    parallel: dict = Field(default_factory=dict)


class ParallelNode(BaseNode):
    metadata_type = "parallel"
    metadata_label = "并行执行"
    metadata_description = "并行运行多个分支(M30d 真并发)"
    metadata_icon = "⫮"
    metadata_color = "geekblue"
    metadata_category = "control"

    def init_node_data(self, config: dict) -> BaseNodeData:
        cfg = {**config, "version": config.get("version", "1")}
        return ParallelNodeData.model_validate(cfg)

    def outputs(self) -> list[OutputVar]:
        return [
            OutputVar(name="results", type=SegmentType.OBJECT,
                      description="分支结果字典"),
            OutputVar(name="status", type=SegmentType.STRING,
                      description="完成状态"),
            OutputVar(name="duration_ms", type=SegmentType.NUMBER,
                      description="并发运行总耗时(应接近 max(branch) 而非 sum)"),
        ]

    async def _run(self) -> NodeRunResult:
        """Run all branches concurrently via asyncio.gather.

        Each branch is described by ``{"id": str, "delay_seconds":
        float, "result": any}``. The default behavior is to await
        ``asyncio.sleep(delay_seconds)`` for each branch in parallel
        and return a dict keyed by branch id with the configured
        `result` (or an empty object).
        """
        assert isinstance(self._data, ParallelNodeData)
        branches = self._data.parallel.get("branches", [])

        async def run_branch(branch: dict) -> tuple[Any, float]:
            bid = branch.get("id", "")
            delay = float(branch.get("delay_seconds", 0))
            t0 = time.monotonic()
            await asyncio.sleep(delay)
            duration = (time.monotonic() - t0) * 1000
            return bid, {
                "result": branch.get("result"),
                "delay_seconds": delay,
                "duration_ms": duration,
            }

        t0_total = time.monotonic()
        # M30d: asyncio.gather is the actual parallel runner. If any
        # branch raises, gather raises the first exception (we don't
        # use return_exceptions=True here so the executor sees a
        # proper failure rather than a list of mixed errors).
        branch_results = await asyncio.gather(
            *(run_branch(b) for b in branches)
        )
        total_duration_ms = (time.monotonic() - t0_total) * 1000

        results: dict[str, Any] = {bid: r for bid, r in branch_results}
        return NodeRunResult(
            node_id=self.node_id,
            output_values={
                "results": results,
                "status": "completed",
                "duration_ms": total_duration_ms,
            },
        )
