"""M30d — true concurrency test for ParallelNode.

Verifies the asyncio.gather implementation in ParallelNode actually
runs branches concurrently (not serially). The test times 4 branches
each with a 0.2s delay; the total should be < 0.5s, not 0.8s.
"""
import asyncio
import time

import pytest

from lumen_core.workflow.nodes.parallel import ParallelNode
from lumen_core.workflow.variable_pool import VariablePool


def _make_node(branches):
    return ParallelNode(
        "p1",
        {"parallel": {"branches": branches}},
        VariablePool(),
        None,
        1,
    )


def test_parallel_runs_branches_concurrently():
    """4 branches × 0.2s should complete in ~0.2s, not ~0.8s.

    Sequential would be 0.8s. asyncio.gather caps the wall time at
    the slowest branch.
    """
    branches = [
        {"id": f"b{i}", "delay_seconds": 0.2, "result": i}
        for i in range(4)
    ]
    node = _make_node(branches)
    t0 = time.monotonic()
    res = asyncio.run(node._run())
    elapsed = time.monotonic() - t0

    # Loose bound: parallel should be < 0.5s; sequential would be 0.8s.
    # The threshold has slack for CI variance.
    assert elapsed < 0.5, f"not parallel: {elapsed:.3f}s >= 0.5s (sequential ~0.8s)"
    assert res.output_values["status"] == "completed"
    assert set(res.output_values["results"].keys()) == {"b0", "b1", "b2", "b3"}


def test_parallel_with_zero_delay_runs_in_negligible_time():
    branches = [{"id": "a"}, {"id": "b"}, {"id": "c"}]
    node = _make_node(branches)
    t0 = time.monotonic()
    res = asyncio.run(node._run())
    elapsed = time.monotonic() - t0
    assert elapsed < 0.1, f"zero-delay parallel took {elapsed:.3f}s"
    assert res.output_values["status"] == "completed"


def test_parallel_records_per_branch_duration():
    """Each branch's individual duration_ms is exposed so the UI can
    show a per-branch timing breakdown."""
    branches = [
        {"id": "slow", "delay_seconds": 0.1, "result": 1},
        {"id": "fast", "delay_seconds": 0.05, "result": 2},
    ]
    node = _make_node(branches)
    res = asyncio.run(node._run())
    results = res.output_values["results"]
    assert "slow" in results and "fast" in results
    # Each branch's own duration >= the configured delay.
    assert results["slow"]["delay_seconds"] == 0.1
    assert results["fast"]["delay_seconds"] == 0.05
    # The reported duration_ms is at least as long as the delay
    # (we sleep then measure).
    #
    # M30 cleanup (2026-06-17): the original `>= 100` / `>= 50` was
    # too strict — under load asyncio.sleep can be slightly off
    # relative to wall time. M37 (2026-08-06) further relaxed the
    # tolerance to 15ms grace — on Windows dev runner the fast
    # branch (50ms) occasionally reports 46ms because asyncio.sleep
    # can resolve a few ms early when the system is busy. The contract
    # is "duration is in the right ballpark", not exact.
    assert results["slow"]["duration_ms"] >= results["slow"]["delay_seconds"] * 1000 - 15
    assert results["fast"]["duration_ms"] >= results["fast"]["delay_seconds"] * 1000 - 15
