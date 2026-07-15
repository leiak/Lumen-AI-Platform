import asyncio

import pytest

from lumen_core.workflow.entities import BaseNodeData, NodeRunResult, OutputVar
from lumen_core.workflow.executor_helpers import (
    _FAILED_RESULT,
    run_node_with_handling,
)
from lumen_core.workflow.retry import NodeRunError, RetryConfig
from lumen_core.workflow.types import SegmentType
from lumen_core.workflow.variable_pool import VariablePool


def _run(coro):
    """Sync wrapper for async tests, matching project convention (test_workflow_nodes.py)."""
    return asyncio.run(coro)


class _StubNode:
    """Minimal duck-typed node for testing run_node_with_handling.

    Mirrors the BaseNode surface that the helper reads (node_id + _data)
    and delegates _run() to a callable.
    """
    def __init__(self, node_id: str, data: BaseNodeData, run_fn):
        self.node_id = node_id
        self._data = data
        self._run_fn = run_fn

    async def _run(self):
        return await self._run_fn()


def _data(**kwargs) -> BaseNodeData:
    base = {"title": "stub", "version": "1"}
    base.update(kwargs)
    return BaseNodeData.model_validate(base)


def test_run_node_with_handling_success_passthrough():
    async def ok():
        return NodeRunResult(node_id="n1", output_values={"v": 42})
    n = _StubNode("n1", _data(), ok)
    r = _run(run_node_with_handling(n))
    assert r.output_values == {"v": 42}
    assert r.error is None


def test_run_node_with_handling_timeout_raises_node_run_error():
    async def slow():
        await asyncio.sleep(0.5)
    n = _StubNode("n1", _data(timeout=0.1), slow)
    with pytest.raises(NodeRunError) as exc_info:
        _run(run_node_with_handling(n))
    assert "timed out" in str(exc_info.value).lower()


def test_run_node_with_handling_retry_then_success():
    attempts = {"n": 0}
    async def flaky():
        attempts["n"] += 1
        if attempts["n"] < 2:
            raise RuntimeError("boom")
        return NodeRunResult(node_id="n1", output_values={"ok": True})
    n = _StubNode("n1", _data(retry_config=RetryConfig(max_retries=2, retry_interval=0.01)), flaky)
    r = _run(run_node_with_handling(n))
    assert r.output_values == {"ok": True}
    assert attempts["n"] == 2


def test_run_node_with_handling_retry_exhausted_raises():
    async def always_fail():
        raise ValueError("nope")
    n = _StubNode("n1", _data(retry_config=RetryConfig(max_retries=1, retry_interval=0.01)), always_fail)
    with pytest.raises(NodeRunError) as exc_info:
        _run(run_node_with_handling(n))
    assert "nope" in str(exc_info.value)


def test_run_node_with_handling_error_strategy_default_value():
    async def fail():
        raise ValueError("explode")
    n = _StubNode(
        "n1",
        _data(error_strategy="default_value", default_value={"fallback": "ok"}),
        fail,
    )
    r = _run(run_node_with_handling(n))
    assert r.output_values == {"fallback": "ok"}
    assert "explode" in r.error


def test_run_node_with_handling_error_strategy_ignore():
    async def fail():
        raise ValueError("ignore me")
    n = _StubNode("n1", _data(error_strategy="ignore"), fail)
    r = _run(run_node_with_handling(n))
    assert r.output_values == {}
    assert "ignore me" in r.error


def test_run_node_with_handling_exp_backoff_timing(monkeypatch):
    """Verify the exponential-backoff schedule is base * 2^attempt.

    We patch `asyncio.sleep` inside `executor_helpers` (the consumer module)
    so the test is deterministic across platforms. Wall-clock-based timing
    assertions are flaky on Windows because asyncio scheduling can deliver
    the resumption a few ms before the configured sleep duration when the
    loop is under load.
    """
    import lumen_core.workflow.executor_helpers as executor_helpers_module

    sleeps: list[float] = []

    async def fake_sleep(d: float) -> None:
        sleeps.append(d)

    monkeypatch.setattr(executor_helpers_module.asyncio, "sleep", fake_sleep)

    async def always_fail():
        raise ValueError("x")

    n = _StubNode(
        "n1",
        _data(retry_config=RetryConfig(max_retries=2, retry_interval=0.1)),
        always_fail,
    )
    with pytest.raises(NodeRunError):
        _run(run_node_with_handling(n))
    # 2 retries → sleep 0.1, then 0.2 (base * 2^attempt where attempt is 0, 1)
    assert sleeps == [0.1, 0.2]


def test_run_node_with_handling_no_retry_no_strategy_raises():
    async def fail():
        raise ValueError("naked")
    n = _StubNode("n1", _data(), fail)  # default: no retry, no strategy
    with pytest.raises(NodeRunError) as exc_info:
        _run(run_node_with_handling(n))
    assert "naked" in str(exc_info.value)


def test_run_node_with_handling_p1_compat_input_node_behavior():
    """P1 节点 (无 error_strategy 字段) 应该跟 P1 行为一致:失败上抛。"""
    async def fail():
        raise ValueError("p1 compat")
    # P1 InputNodeData 没有 error_strategy/retry_config 字段(走 default_factory)
    from lumen_core.workflow.nodes.input import InputNodeData
    d = InputNodeData.model_validate({})
    n = _StubNode("input", d, fail)
    with pytest.raises(NodeRunError):
        _run(run_node_with_handling(n))


def test_failed_result_sentinel_is_shared():
    assert _FAILED_RESULT.node_id == "__failed__"
    assert _FAILED_RESULT.output_values == {}
    assert _FAILED_RESULT.error is not None


def test_default_timeout_seconds_is_60():
    """回归: DEFAULT_TIMEOUT_SECONDS 必须是 60.0,锁住 P35 改的默认值。

    历史: 30s 不够 LLM (max_tokens≥1024, MiniMax highspeed),改成 60s。
    见 lumen_core/workflow/executor_helpers.py 同行注释。
    """
    from lumen_core.workflow.executor_helpers import DEFAULT_TIMEOUT_SECONDS
    assert DEFAULT_TIMEOUT_SECONDS == 60.0
