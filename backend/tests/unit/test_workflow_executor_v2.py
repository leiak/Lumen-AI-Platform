import asyncio
import pytest
from unittest.mock import MagicMock

from lumen_core.workflow.entities import NodeRunResult
from lumen_services.workflow_executor import WorkflowExecutor


def _stub_workflow():
    """input → llm → output linear workflow, all LLM/agent deps stubbed.

    Returns the workflow *definition* (`{"nodes": [...], "edges": [...]}`),
    matching what WorkflowExecutor.execute() now accepts and what
    WorkflowService passes via workflow.definition.
    """
    return {
        "nodes": [
            {
                "id": "input_1",
                "type": "input",
                "config": {
                    "title": "Input",
                    "version": "1",
                    "variables": [{"name": "user_query", "type": "string", "required": True}],
                },
            },
            {
                "id": "llm_1",
                "type": "llm",
                "config": {
                    "title": "LLM",
                    "version": "1",
                    "model_name": "test-model",
                    "prompt": "echo: {{#input_1.user_query#}}",
                },
            },
            {
                "id": "output_1",
                "type": "output",
                "config": {
                    "title": "Output",
                    "version": "1",
                    "field": "llm_1.response",
                },
            },
        ],
        "edges": [
            {"id": "e1", "source": "input_1", "target": "llm_1", "sourceHandle": "default"},
            {"id": "e2", "source": "llm_1", "target": "output_1", "sourceHandle": "default"},
        ],
    }


@pytest.fixture
def mock_create_chat_model(monkeypatch):
    """LLM._run calls create_chat_model(...).invoke(...). Return a factory Mock that
    records calls to create_chat_model and returns a stub whose .invoke() returns
    a fixed AIMessage-shaped object.

    Note: the test assertions below treat ``mock_create_chat_model`` as the
    factory itself (so ``.called``, ``.call_args.kwargs["model_name"]`` and
    ``.return_value.invoke.call_args[0][0]`` all work), not the inner fake model.

    M26: nodes/llm.py:178 reads ``response.content`` (AIMessage contract).
    Returning a bare string here broke once the M26 LoggingChatModel
    wrapper was added — the old "return whatever str(response) gives"
    branch was replaced with the AIMessage contract.
    """
    from langchain_core.messages import AIMessage
    fake_model = MagicMock()
    fake_model.invoke.return_value = AIMessage(content="stubbed-llm-response")
    factory = MagicMock(return_value=fake_model)
    monkeypatch.setattr(
        "lumen_core.workflow.nodes.llm.create_chat_model", factory
    )
    return factory


def test_executor_runs_linear_input_llm_output(mock_create_chat_model):
    wf = _stub_workflow()
    executor = WorkflowExecutor()
    result = asyncio.run(
        executor.execute(
            definition=wf,
            input_data={"user_query": "hi"},
            tenant_id=1,
            run_id=1,
            db=MagicMock(),
        )
    )
    assert result["status"] == "completed"
    # LLM response was templated + invoked
    assert mock_create_chat_model.called
    call_args = mock_create_chat_model.call_args
    assert call_args.kwargs["model_name"] == "test-model"
    # Prompt interpolated: "echo: hi"
    invoke_arg = mock_create_chat_model.return_value.invoke.call_args[0][0]
    assert invoke_arg == "echo: hi"
    # All 3 nodes ran
    assert "input_1" in result["results"]
    assert "llm_1" in result["results"]
    assert "output_1" in result["results"]
    # final_output contains LLM response
    assert result["final_output"].get("value") == "stubbed-llm-response"


def test_executor_routes_by_source_handle_for_condition(monkeypatch):
    """Condition node + 2 outgoing edges with different sourceHandle → only matched edge fires."""
    wf = {
        "nodes": [
            {
                "id": "cond",
                "type": "condition",
                "config": {
                    "title": "Cond",
                    "version": "1",
                    "cases": [
                        {
                            "case_id": "case_yes",
                            "logical_operator": "and",
                            "conditions": [
                                {
                                    "variable_selector": ["input", "flag"],
                                    "comparison_operator": "=",
                                    "value": True,
                                }
                            ],
                        }
                    ],
                },
            },
            {
                "id": "yes_path",
                "type": "output",
                "config": {"title": "Yes", "version": "1", "field": "all"},
            },
            {
                "id": "no_path",
                "type": "output",
                "config": {"title": "No", "version": "1", "field": "all"},
            },
        ],
        "edges": [
            {"id": "e1", "source": "cond", "target": "yes_path", "sourceHandle": "case_yes"},
            {"id": "e2", "source": "cond", "target": "no_path", "sourceHandle": "false"},
        ],
    }
    executor = WorkflowExecutor()
    # flag=True → case_yes path runs
    result = asyncio.run(
        executor.execute(definition=wf, input_data={"flag": True}, tenant_id=1, run_id=1, db=MagicMock())
    )
    assert "yes_path" in result["results"]
    assert "no_path" not in result["results"]


def test_executor_returns_failed_envelope_on_node_error(monkeypatch):
    """LLM that raises → executor returns status=failed with error_message."""
    monkeypatch.setattr(
        "lumen_core.workflow.nodes.llm.create_chat_model",
        lambda **kw: (_ for _ in ()).throw(RuntimeError("LLM boom")),
    )
    wf = _stub_workflow()
    executor = WorkflowExecutor()
    result = asyncio.run(
        executor.execute(definition=wf, input_data={"user_query": "hi"}, tenant_id=1, run_id=1, db=MagicMock())
    )
    assert result["status"] == "failed"
    assert "LLM boom" in (result.get("error") or "")


# --- P2 Task 3: BFS loop calls run_node_with_handling + tenant_id injection ---


def test_executor_uses_run_node_with_handling(monkeypatch):
    """P2 refactor: the BFS loop should call run_node_with_handling, not _run() directly.

    Strategy: register a tiny graph, monkeypatch run_node_with_handling to
    record that it was called, and assert the executor still completes.
    """
    from lumen_core.workflow import executor_helpers
    called = {"n": 0, "instance_ids": []}
    orig = executor_helpers.run_node_with_handling

    async def spy(instance, attempt=0):
        called["n"] += 1
        called["instance_ids"].append(instance.node_id)
        return await orig(instance, attempt)

    monkeypatch.setattr(executor_helpers, "run_node_with_handling", spy)
    # WorkflowExecutor imports it lazily; patch the symbol it actually uses.
    monkeypatch.setattr("lumen_services.workflow_executor.run_node_with_handling", spy)

    workflow = {
        "nodes": [
            {"id": "a", "type": "start", "config": {"version": "1"}},
            {"id": "b", "type": "input", "config": {"version": "1", "variables": []}},
            {"id": "c", "type": "end",   "config": {"version": "1"}},
        ],
        "edges": [
            {"source": "a", "target": "b"},
            {"source": "b", "target": "c"},
        ],
    }
    ex = WorkflowExecutor()
    result = asyncio.run(
        ex.execute(workflow, {"x": 1}, tenant_id=1, run_id=1, db=MagicMock())
    )
    assert result["status"] == "completed"
    assert called["n"] >= 3
    assert {"a", "b", "c"}.issubset(set(called["instance_ids"]))


def test_executor_passes_tenant_id_to_nodes(monkeypatch):
    """P2: BaseNode should receive tenant_id so ToolNode/KBNode/LLMNode can enforce it."""
    from lumen_core.workflow import node_mapping
    from lumen_core.workflow.entities import BaseNodeData, NodeRunResult, OutputVar
    from lumen_core.workflow.types import SegmentType
    from lumen_core.workflow.variable_pool import VariablePool

    seen_tenant = []

    class _RecordingNode:
        # Duck-typed BaseNode: same __init__ signature, same surface area used
        # by WorkflowExecutor._instantiate and run_node_with_handling.
        def __init__(self, node_id, config, pool, db, tenant_id=None, user=None):
            self.node_id = node_id
            self.config = config
            self.pool = pool
            self.db = db
            self.tenant_id = tenant_id
            self.user = user  # M38.2.x v2: WorkflowExecutor 现在透传 user 给所有 node
            self._data = BaseNodeData.model_validate(config)
            seen_tenant.append(tenant_id)

        def init_node_data(self, config):
            return BaseNodeData.model_validate(config)

        def outputs(self):
            return [OutputVar(name="value", type=SegmentType.OBJECT)]

        async def _run(self):
            return NodeRunResult(node_id=self.node_id, output_values={})

        async def run(self):
            # Mirror BaseNode.run() so pool-write semantics are preserved.
            result = await self._run()
            result.node_id = self.node_id
            result.outputs = self.outputs()
            for name, value in result.output_values.items():
                self.pool.add([self.node_id, name], value)
            return result

    # Replace the class registry entry for "start"
    original_start = node_mapping.NODE_TYPE_CLASSES_MAPPING["start"]
    node_mapping.NODE_TYPE_CLASSES_MAPPING["start"] = {"1": _RecordingNode}
    try:
        workflow = {
            "nodes": [{"id": "a", "type": "start", "config": {"version": "1"}}],
            "edges": [],
        }
        ex = WorkflowExecutor()
        result = asyncio.run(
            ex.execute(workflow, {}, tenant_id=42, run_id=1, db=MagicMock())
        )
        assert result["status"] == "completed"
        assert seen_tenant == [42]
    finally:
        # Restore the real StartNode registration
        node_mapping.NODE_TYPE_CLASSES_MAPPING["start"] = original_start


# --- Regression: executor must accept the unwrapped definition shape
# that WorkflowService.execute_workflow passes (i.e. workflow.definition,
# which is {"nodes": [...], "edges": [...]} — NOT wrapped in another
# "definition" key). Before the fix this raised KeyError: 'definition'
# and every manual + scheduled workflow run failed.
def test_executor_accepts_unwrapped_definition(mock_create_chat_model):
    definition = _stub_workflow()  # already the unwrapped definition shape
    executor = WorkflowExecutor()
    result = asyncio.run(
        executor.execute(
            definition=definition,
            input_data={"user_query": "hi"},
            tenant_id=1,
            run_id=1,
            db=MagicMock(),
        )
    )
    assert result["status"] == "completed"
    assert "input_1" in result["results"]
    assert "llm_1" in result["results"]
    assert "output_1" in result["results"]
    assert result["final_output"].get("value") == "stubbed-llm-response"
