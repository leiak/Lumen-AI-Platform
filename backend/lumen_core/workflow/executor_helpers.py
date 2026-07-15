"""P2 共享执行原语。

集中处理:
- asyncio.wait_for 包裹(per-node timeout)
- 指数退避重试(retry_config)
- error_strategy 决策(fail_branch / default_value / ignore)
- NodeRunError 域错误传播
- _FAILED_RESULT 哨兵(供 WorkflowExecutor 在分支失败时复用)
- _ObjectView:Jinja2 渲染上下文包装器,允许 {{ node_id.var }} 访问
"""
import asyncio
from typing import Any, Iterable, Mapping

from pydantic import BaseModel

from lumen_core.workflow.entities import BaseNodeData, NodeRunResult
from lumen_core.workflow.retry import NodeRunError, RetryConfig
from lumen_core.workflow.types import SegmentType

DEFAULT_TIMEOUT_SECONDS = 60.0  # Was 30s; raised to 60s (2026-07-10) because
# real LLM calls (model_config default inner timeout 120s, Ollama MiniMax
# highspeed, OpenAI streaming + tool-call) routinely exceed 30s for
# max_tokens≥1024, breaking every workflow that didn't manually set
# cfg.timeout. The LLM Panel now exposes an AdvancedOptions collapse
# (mirrors the other 9 P2 nodes) so users can override per-node if 60s
# isn't enough.


_FAILED_RESULT = NodeRunResult(
    node_id="__failed__",
    output_values={},
    error="node failed (default error_strategy)",
)


async def run_node_with_handling(instance, attempt: int = 0) -> NodeRunResult:
    """Wrap instance._run() with timeout + retry + error_strategy.

    instance duck-types BaseNode: it must expose .node_id, ._data, and ._run().

    Failure modes:
    - asyncio.TimeoutError → retried up to retry_config.max_retries with exp backoff.
    - Any Exception → same retry decision.
    - After exhaustion: error_strategy decides.
        * None / "fail_branch"  → raise NodeRunError
        * "default_value"      → return NodeRunResult with cfg.default_value
        * "ignore"             → return NodeRunResult with empty output_values
    """
    cfg: BaseNodeData = instance._data
    timeout = cfg.timeout if cfg.timeout is not None else DEFAULT_TIMEOUT_SECONDS
    retry: RetryConfig = cfg.retry_config or RetryConfig()

    try:
        return await asyncio.wait_for(instance._run(), timeout=timeout)
    except asyncio.TimeoutError:
        err = f"Node '{instance.node_id}' timed out after {timeout}s"
    except Exception as e:  # noqa: BLE001 — we re-raise via NodeRunError below
        err = f"Node '{instance.node_id}' failed: {type(e).__name__}: {e}"

    # Retry decision
    if attempt < retry.max_retries:
        delay = retry.retry_interval * (2 ** attempt)
        await asyncio.sleep(delay)
        return await run_node_with_handling(instance, attempt + 1)

    # error_strategy decision
    strategy = cfg.error_strategy
    if strategy is None or strategy == "fail_branch":
        raise NodeRunError(err)
    if strategy == "default_value":
        return NodeRunResult(
            node_id=instance.node_id,
            output_values=cfg.default_value or {},
            error=err,
        )
    if strategy == "ignore":
        return NodeRunResult(
            node_id=instance.node_id,
            output_values={},
            error=err,
        )
    raise NodeRunError(f"Unknown error_strategy: {strategy!r}")


class _ObjectView(BaseModel):
    """Allow Jinja2 `{{ node_id.var }}` access by wrapping a dict of vars.

    Used by TemplateTransformNode and VariableAssignerNode.
    """
    model_config = {"extra": "allow"}

    def __init__(self, data: Mapping[str, Any] | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._data: dict[str, Any] = dict(data or {})

    def __getattr__(self, item: str) -> Any:
        try:
            return self._data[item]
        except KeyError:
            return None

    def __getitem__(self, item: str) -> Any:
        return self._data[item]

    def keys(self) -> Iterable[str]:
        return self._data.keys()


def build_jinja_context(pool_snapshot: Mapping[str, Mapping[str, Any]]) -> dict[str, _ObjectView]:
    """Convert VariablePool.snapshot() into a Jinja2-friendly context.

    Pool snapshot shape: {node_id: {var_name: value}}
    Jinja2 context:     {node_id: _ObjectView({var_name: value})}

    M30 ship follow-up (2026-06-18): the input node writes its
    declared variables into the pool under the ``["input", k]``
    selector (executor.py:133-135), so a user template like
    ``{{ input.user_name }}`` works but the intuitive
    ``{{ user_name }}`` form fails with
    ``Template error: 'user_name' is undefined`` under
    StrictUndefined. The list-page "执行" flow (InputValuesModal +
    collected by var name) and most seed templates (e.g. "模板渲染")
    expect the flat form. Lift every ``input.*`` key to top-level
    so both forms work — the explicit ``{{ input.x }}`` form is
    preserved alongside the intuitive flat form. The lift is
    last-write-wins-on-conflict: if a downstream node happens to
    share its id with an input variable, the input variable
    (written first into the pool) takes precedence.
    """
    ctx = {nid: _ObjectView(vars_) for nid, vars_ in pool_snapshot.items()}
    if "input" in ctx:
        for var_name, value in ctx["input"]._data.items():
            if var_name not in ctx:
                ctx[var_name] = value
    return ctx
