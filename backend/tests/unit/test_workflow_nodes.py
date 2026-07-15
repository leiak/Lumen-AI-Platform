import asyncio
from lumen_core.workflow.nodes.input import InputNode
from lumen_core.workflow.nodes.output import OutputNode
from lumen_core.workflow.variable_pool import VariablePool
from lumen_core.workflow.types import SegmentType


def _run(coro):
    return asyncio.run(coro)


def test_input_node_outputs_match_user_variables():
    pool = VariablePool()
    config = {
        "title": "Input",
        "version": "1",
        "variables": [
            {"name": "user_query", "type": "string"},
            {"name": "user_id", "type": "number"},
        ],
    }
    node = InputNode("in1", config, pool, None)
    outputs = node.outputs()
    names = [o.name for o in outputs]
    assert "user_query" in names
    assert "user_id" in names
    assert any(o.type == SegmentType.STRING for o in outputs)
    assert any(o.type == SegmentType.NUMBER for o in outputs)


def test_input_node_run_copies_input_namespace():
    pool = VariablePool()
    pool.add(["input", "user_query"], "hi")
    pool.add(["input", "user_id"], 7)
    config = {
        "variables": [
            {"name": "user_query", "type": "string"},
            {"name": "user_id", "type": "number"},
        ],
    }
    node = InputNode("in1", config, pool, None)
    _run(node.run())
    assert pool.get(["in1", "user_query"]).value == "hi"
    assert pool.get(["in1", "user_id"]).value == 7


def test_output_node_field_current():
    pool = VariablePool()
    pool.add(["n1", "response"], "the answer")
    config = {"field": "current"}
    node = OutputNode("out1", config, pool, None)
    _run(node.run())
    assert pool.get(["out1", "value"]).value == "the answer"


def test_output_node_field_input():
    pool = VariablePool()
    pool.add(["input", "user_query"], "hello")
    config = {"field": "input"}
    node = OutputNode("out1", config, pool, None)
    _run(node.run())
    assert pool.get(["out1", "value"]).value == "hello"


def test_output_node_field_all_returns_pool_snapshot():
    pool = VariablePool()
    pool.add(["n1", "x"], 1)
    pool.add(["n2", "y"], "two")
    config = {"field": "all"}
    node = OutputNode("out1", config, pool, None)
    _run(node.run())
    assert pool.get(["out1", "value"]).value == {"n1": {"x": 1}, "n2": {"y": "two"}}


def test_output_node_field_custom_key():
    pool = VariablePool()
    pool.add(["n1", "response"], "A")
    pool.add(["n1", "model"], "glm-4")
    config = {"field": "n1.model"}
    node = OutputNode("out1", config, pool, None)
    _run(node.run())
    assert pool.get(["out1", "value"]).value == "glm-4"


def test_output_node_legacy_output_field_fallback():
    """`{"output": {"field": "n1.response"}}` config should set field from output.field."""
    pool = VariablePool()
    pool.add(["n1", "response"], "ok")
    config = {"output": {"field": "n1.response"}}
    node = OutputNode("out1", config, pool, None)
    _run(node.run())
    assert pool.get(["out1", "value"]).value == "ok"


from lumen_core.workflow.entities import ComparisonOperator, Condition, ConditionCase
from lumen_core.workflow.nodes.condition import ConditionNode


def test_condition_node_outputs_declaration():
    node = ConditionNode(
        "c1",
        {"cases": [ConditionCase(conditions=[]).model_dump()]},
        VariablePool(),
        None,
    )
    outputs = node.outputs()
    names = [o.name for o in outputs]
    assert "result" in names
    assert "selected_case_id" in names
    assert any(o.type == SegmentType.BOOLEAN for o in outputs)


def test_condition_node_run_sets_source_handle():
    pool = VariablePool()
    pool.add(["n1", "x"], "hello")
    case = ConditionCase(
        case_id="case_a",
        conditions=[Condition(
            variable_selector=["n1", "x"],
            comparison_operator=ComparisonOperator.EQUAL,
            value="hello",
        )],
    )
    config = {"cases": [case.model_dump()]}
    node = ConditionNode("c1", config, pool, None)
    result = _run(node.run())
    assert result.edge_source_handle == "case_a"


def test_condition_node_no_match_returns_false_handle():
    pool = VariablePool()
    pool.add(["n1", "x"], "bye")
    case = ConditionCase(
        case_id="case_a",
        conditions=[Condition(
            variable_selector=["n1", "x"],
            comparison_operator=ComparisonOperator.EQUAL,
            value="hello",
        )],
    )
    config = {"cases": [case.model_dump()]}
    node = ConditionNode("c1", config, pool, None)
    result = _run(node.run())
    assert result.edge_source_handle == "false"


# ---------------------------------------------------------------------------
# Task 9: LLMNode + AgentNode
#
# Spec-bug fix notes (kept here for posterity):
#   1) AgentService() takes NO constructor args. The plan's verbatim code
#      wrote `AgentService(self.db)` — that is wrong; AgentService.__init__
#      in app/services/agent_service.py is a no-arg constructor.
#   2) AgentService.run(agent_id, message, tenant_id) is already async and
#      returns str. Do NOT wrap it in asyncio.to_thread and do NOT pass
#      self.db to it (run opens its own SessionLocal).
#   3) create_chat_model's first parameter is `model_type` (a positional
#      string), not a `type=` kwarg. The plan's verbatim code wrote
#      `create_chat_model(type=...)` which would TypeError.
# These three deviations are intentional; see Step 3 / Step 4 implementations.
# ---------------------------------------------------------------------------

from unittest.mock import MagicMock, patch
from lumen_core.workflow.nodes.llm import LLMNode
from lumen_core.workflow.nodes.agent import AgentNode


def test_llm_node_outputs_declaration():
    node = LLMNode("l1", {"prompt": "hi"}, VariablePool(), None)
    names = [o.name for o in node.outputs()]
    assert "response" in names
    assert "model" in names
    assert "finish_reason" in names
    assert "usage" in names


def test_llm_node_run_resolves_template():
    pool = VariablePool()
    pool.add(["in1", "user_query"], "你好")
    config = {
        "model_config_id": 7,
        "model_name": "glm-4",
        "prompt": "把 {{#in1.user_query#}} 翻译成英文",
        "temperature": 0.7,
    }
    with patch("lumen_core.workflow.nodes.llm.create_chat_model") as mock_factory:
        mock_chat = MagicMock()
        # M26: chat.invoke returns an AIMessage-shaped object; nodes/llm.py
        # reads ``response.content`` (line 178). The historical mock of
        # returning a bare string broke once the wrapper path was
        # exercised (the bare-string test only ever worked because the
        # code branch read ``str(response)`` directly, which the M26
        # refactor replaced with the AIMessage contract).
        from langchain_core.messages import AIMessage
        mock_chat.invoke.return_value = AIMessage(content="Hello")
        mock_factory.return_value = mock_chat
        # 同时 mock 掉 db 查询
        node = LLMNode("l1", config, pool, db=MagicMock())
        node.db.query.return_value.filter.return_value.first.return_value = MagicMock(
            id=7, model_name="glm-4", model_type="zhipu",
            base_url="https://api.test", api_key="k", is_active=True,
        )
        result = _run(node.run())
    call_args = mock_chat.invoke.call_args[0][0]
    assert "把 你好 翻译成英文" in call_args
    assert pool.get(["l1", "response"]).value == "Hello"
    assert pool.get(["l1", "model"]).value == "glm-4"
    # Lock in spec-bug fix: create_chat_model first param is model_type, not type
    assert mock_factory.call_args.kwargs == {
        "model_type": "zhipu",
        "model_name": "glm-4",
        "base_url": "https://api.test",
        "api_key": "k",
    }


def test_llm_node_run_folds_skill_block_into_prompt():
    """LLMNode._run folds skills + system_prompt + resolved_prompt into the
    single string passed to chat.invoke(), in that order, separated by
    ``\\n\\n---\\n\\n``.
    """
    from lumen_services.skill_runner import RenderedSkill

    pool = VariablePool()
    pool.add(["in1", "user_query"], "你好")

    config = {
        "tenant_id": 1,
        "model_config_id": 7,
        "model_name": "glm-4",
        "prompt": "把 {{#in1.user_query#}} 翻译成英文",
        "system_prompt": "你是一个翻译助手",
        "skill_ids": [11],
    }

    # M16 (2026-06-10, Task 9): SkillRunner.get_active_skills returns
    # (prompts, tools). This test exercises the prompt-only path (no tools).
    fake_prompts = [RenderedSkill(name="代码优化专家", content="优化代码")]
    with patch("lumen_core.workflow.nodes.llm.create_chat_model") as mock_factory, \
         patch(
             "lumen_core.workflow.nodes.llm.SkillRunner.get_active_skills",
             return_value=(fake_prompts, []),
         ) as mock_get_skills:
        mock_chat = MagicMock()
        # M26: same AIMessage contract as test_llm_node_run_resolves_template
        from langchain_core.messages import AIMessage
        mock_chat.invoke.return_value = AIMessage(content="Hello")
        mock_factory.return_value = mock_chat
        node = LLMNode("l1", config, pool, db=MagicMock())
        node.db.query.return_value.filter.return_value.first.return_value = MagicMock(
            id=7, model_name="glm-4", model_type="zhipu",
            base_url="https://api.test", api_key="k", is_active=True,
        )
        _run(node.run())

    # Verify the skill runner was consulted with the right (tenant, ids)
    assert mock_get_skills.called
    skill_call_args = mock_get_skills.call_args
    # positional or kwargs: (db, tenant_id, skill_ids)
    assert skill_call_args.args[1] == 1
    assert list(skill_call_args.args[2]) == [11]

    call_args = mock_chat.invoke.call_args[0][0]
    # All four pieces are present in the single string arg
    assert "【技能:代码优化专家】" in call_args
    assert "优化代码" in call_args
    assert "你是一个翻译助手" in call_args
    assert "把 你好 翻译成英文" in call_args
    # Order: skill block < system_prompt < resolved prompt
    skill_idx = call_args.index("【技能:")
    sys_idx = call_args.index("你是一个翻译助手")
    prompt_idx = call_args.index("把 你好 翻译成英文")
    assert skill_idx < sys_idx < prompt_idx
    # Separator appears at least twice (skill|sys, sys|prompt)
    assert call_args.count("\n\n---\n\n") >= 2


# ---------------------------------------------------------------------------
# M16 (2026-06-10, Task 9): Workflow LLM node tool calling.
#
# Mirrors chat_service.py::stream_chat_messages: when SkillRunner returns a
# non-empty tools list, we bind_tools and run the max-5-rounds tool_call
# loop. The LLM is mocked to return a single tool_call on the first invoke
# and a final content string on the second.
# ---------------------------------------------------------------------------


class _FakeToolCall(dict):
    """Behaves like a LangChain tool_call — supports both dict .get() and
    attribute access via the dict-key path the implementation uses."""

    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError:
            return None


def test_llm_node_run_invokes_bound_tool_and_returns_final_content():
    """When SkillRunner.get_active_skills returns tools, LLMNode binds them,
    executes the tool, and returns the LLM's final content after the loop.
    """
    from lumen_services.skill_runner import RenderedSkill
    from langchain_core.tools import BaseTool

    class EchoTool(BaseTool):
        name: str = "echo"
        description: str = "echo the input"

        def _run(self, text: str) -> str:  # type: ignore[override]
            return f"echoed:{text}"

    tool = EchoTool()
    pool = VariablePool()
    config = {
        "tenant_id": 1,
        "model_config_id": 7,
        "model_name": "glm-4",
        "prompt": "用 echo 工具打个招呼",
        "system_prompt": "",
        "skill_ids": [42],
    }

    # Round 1: LLM emits a tool_call. Round 2: LLM produces final content.
    round1 = MagicMock()
    round1.tool_calls = [
        _FakeToolCall(name="echo", args={"text": "hi"}, id="call-1")
    ]
    round1.content = ""
    round2 = MagicMock()
    round2.tool_calls = []
    round2.content = "好的,已执行"

    bound_chat = MagicMock()
    bound_chat.invoke.side_effect = [round1, round2]

    with patch("lumen_core.workflow.nodes.llm.create_chat_model") as mock_factory, \
         patch(
             "lumen_core.workflow.nodes.llm.SkillRunner.get_active_skills",
             return_value=([], [tool]),
         ):
        mock_factory.return_value.bind_tools.return_value = bound_chat
        node = LLMNode("l1", config, pool, db=MagicMock())
        node.db.query.return_value.filter.return_value.first.return_value = MagicMock(
            id=7, model_name="glm-4", model_type="zhipu",
            base_url="https://api.test", api_key="k", is_active=True,
        )
        result = _run(node.run())

    # bind_tools was called with our tool
    assert mock_factory.return_value.bind_tools.called
    assert mock_factory.return_value.bind_tools.call_args[0][0] == [tool]

    # Two LLM invocations (tool_call + final)
    assert bound_chat.invoke.call_count == 2

    # Final response is the LLM's last content
    assert pool.get(["l1", "response"]).value == "好的,已执行"
    assert result.output_values["response"] == "好的,已执行"


def test_agent_node_outputs_declaration():
    node = AgentNode("a1", {"agent_id": 1}, VariablePool(), None)
    names = [o.name for o in node.outputs()]
    assert "response" in names
    assert "usage" in names


def test_agent_node_run_calls_agent_service():
    pool = VariablePool()
    # Spec-bug fix: plan's verbatim test used pool.add(["current"], ...) which
    # violates VariablePool.add's 2-element-selector contract. Use a proper
    # [node_id, var_name] selector (matches the LLM test pattern). The
    # implementation reads from the same selector.
    pool.add(["input", "user_query"], "what is X?")
    config = {"agent_id": 5, "tenant_id": 3}  # node config carries tenant
    with patch("lumen_core.workflow.nodes.agent.AgentService") as MockSvc:
        instance = MockSvc.return_value
        # 实际 AgentService.run 是 async;AsyncMock 才能 await
        from unittest.mock import AsyncMock
        instance.run = AsyncMock(return_value="agent answer")
        # node tenant_id=None lets d.tenant_id (3) win.
        node = AgentNode("a1", config, pool, db=MagicMock())
        result = _run(node.run())
    assert pool.get(["a1", "response"]).value == "agent answer"
    # Verify tenant_id was the one from node config (no workflow override).
    assert instance.run.await_args.kwargs["tenant_id"] == 3


def test_agent_node_uses_workflow_tenant_when_node_tenant_missing():
    """M27 fix: when node config lacks tenant_id, fall back to the
    workflow's tenant_id injected via BaseNode.__init__."""
    pool = VariablePool()
    pool.add(["input", "user_query"], "what is X?")
    config = {"agent_id": 5}  # no tenant_id on the node
    with patch("lumen_core.workflow.nodes.agent.AgentService") as MockSvc:
        instance = MockSvc.return_value
        from unittest.mock import AsyncMock
        instance.run = AsyncMock(return_value="agent answer")
        # Workflow injects tenant_id=2 — this is what M27 wants the
        # node to use.
        node = AgentNode("a1", config, pool, db=MagicMock(), tenant_id=2)
        _run(node.run())
    # tenant_id=2 (the workflow's) was passed to AgentService.run.
    assert instance.run.await_args.kwargs["tenant_id"] == 2


def test_agent_node_raises_when_no_tenant_anywhere():
    """M27 fix: tenant_id missing on BOTH node config and workflow
    raises ValueError instead of silently defaulting to 1."""
    import pytest as _pytest
    pool = VariablePool()
    pool.add(["input", "user_query"], "what is X?")
    config = {"agent_id": 5}  # no tenant_id
    node = AgentNode("a1", config, pool, db=MagicMock(), tenant_id=None)
    with _pytest.raises(ValueError, match="missing tenant_id"):
        _run(node.run())


def test_agent_node_workflow_tenant_wins_over_node_tenant():
    """M27: workflow's tenant takes precedence over node config's tenant.

    If a node config carries an old/wrong tenant_id (e.g. someone
    edited the JSON definition by hand), the executor's injected
    ``self.tenant_id`` overrides — and we log a warning so the
    inconsistency is visible.
    """
    pool = VariablePool()
    pool.add(["input", "user_query"], "what is X?")
    config = {"agent_id": 5, "tenant_id": 99}  # stale node-level tenant
    with patch("lumen_core.workflow.nodes.agent.AgentService") as MockSvc:
        instance = MockSvc.return_value
        from unittest.mock import AsyncMock
        instance.run = AsyncMock(return_value="answer")
        node = AgentNode("a1", config, pool, db=MagicMock(), tenant_id=2)
        _run(node.run())
    # Workflow's tenant_id=2 wins (not 99)
    assert instance.run.await_args.kwargs["tenant_id"] == 2


# ---------------------------------------------------------------------------
# Task 10: ParallelNode, FanOutNode (stub), FanInNode
# ---------------------------------------------------------------------------

from lumen_core.workflow.nodes.parallel import ParallelNode
from lumen_core.workflow.nodes.fan_out import FanOutNode
from lumen_core.workflow.nodes.fan_in import FanInNode


def test_parallel_node_outputs_declaration():
    node = ParallelNode(
        "p1",
        {"parallel": {"branches": [{"id": "b1"}, {"id": "b2"}]}},
        VariablePool(),
        None,
    )
    names = [o.name for o in node.outputs()]
    assert "results" in names
    assert "status" in names


def test_parallel_node_run_collects_branch_results():
    """M30d: ParallelNode now uses asyncio.gather with per-branch
    timing. Each branch is wrapped as
    ``{result, delay_seconds, duration_ms}`` so the UI can show a
    per-branch timing breakdown.
    """
    pool = VariablePool()
    config = {
        "parallel": {
            "branches": [
                {"id": "b1", "result": "first"},
                {"id": "b2", "result": "second"},
            ]
        }
    }
    node = ParallelNode("p1", config, pool, None)
    _run(node.run())
    values = pool.get(["p1", "results"]).value
    # The shape changed in M30d: each branch is now a dict with
    # `result`, `delay_seconds`, and `duration_ms`. Old test asserted
    # a flat dict — that shape is gone.
    assert set(values.keys()) == {"b1", "b2"}
    assert values["b1"]["result"] == "first"
    assert values["b2"]["result"] == "second"
    assert values["b1"]["delay_seconds"] == 0  # default when not set
    assert "duration_ms" in values["b1"]


def test_fan_out_node_stub_creates_array():
    pool = VariablePool()
    config = {"fan_out": {"items": ["a", "b", "c"], "sub_workflow": None}}
    node = FanOutNode("f1", config, pool, None)
    _run(node.run())
    results = pool.get(["f1", "results"]).value
    assert results == [{"item": "a"}, {"item": "b"}, {"item": "c"}]


def test_fan_in_collect():
    pool = VariablePool()
    pool.add(["f1", "results"], [{"x": 1}, {"x": 2}, {"x": 3}])
    config = {"fan_in": {"source": "f1", "aggregation": "collect"}}
    node = FanInNode("fi1", config, pool, None)
    _run(node.run())
    assert pool.get(["fi1", "result"]).value == [{"x": 1}, {"x": 2}, {"x": 3}]
    assert pool.get(["fi1", "count"]).value == 3


def test_fan_in_sum():
    pool = VariablePool()
    pool.add(["f1", "results"], [{"x": 10}, {"x": 20}])
    config = {"fan_in": {"source": "f1", "aggregation": "sum"}}
    node = FanInNode("fi1", config, pool, None)
    _run(node.run())
    assert pool.get(["fi1", "result"]).value == 30


def test_fan_in_missing_source_does_not_crash():
    """FanInNode with a source that has no results in the pool should
    not raise TypeError; it should return value=results (None) and count=0.
    """
    pool = VariablePool()
    config = {"fan_in": {"source": "missing_node", "aggregation": "sum"}}
    node = FanInNode("fi1", config, pool, None)
    # Should NOT raise
    _run(node.run())
    assert pool.get(["fi1", "count"]).value == 0
