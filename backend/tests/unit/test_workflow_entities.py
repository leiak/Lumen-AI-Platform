import pytest
from lumen_core.workflow.entities import (
    OutputVar, BaseNodeData, ErrorStrategy, RetryConfig,
    ComparisonOperator, Condition, ConditionCase, NodeRunResult,
)
from lumen_core.workflow.types import SegmentType


def test_output_var_basic():
    v = OutputVar(name="text", type=SegmentType.STRING, description="LLM 输出")
    assert v.name == "text"
    assert v.type == SegmentType.STRING


def test_base_node_data_default_values():
    d = BaseNodeData()
    assert d.title == "Node"
    assert d.version == "1"
    assert d.error_strategy is None
    assert d.retry_config.max_retries == 0
    assert d.outputs == []


def test_base_node_data_extra_ignored():
    d = BaseNodeData.model_validate({
        "title": "X",
        "label": "old field",
        "agent_id": 5,
        "outputs": [],
    })
    assert d.title == "X"
    assert not hasattr(d, "label")


def test_retry_config_validation():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        RetryConfig(max_retries=-1)
    with pytest.raises(ValidationError):
        RetryConfig(max_retries=11)


def test_condition_case_default_case_id():
    c = ConditionCase()
    assert len(c.case_id) == 8
    assert c.logical_operator == "and"
    assert c.conditions == []


def test_condition_basic():
    c = Condition(
        variable_selector=["n1", "text"],
        comparison_operator=ComparisonOperator.EQUAL,
        value="hello",
    )
    assert c.variable_selector == ["n1", "text"]
    assert c.comparison_operator == ComparisonOperator.EQUAL
    assert c.value == "hello"


def test_node_run_result_defaults():
    r = NodeRunResult(node_id="n1")
    assert r.node_id == "n1"
    assert r.outputs == []
    assert r.output_values == {}
    assert r.edge_source_handle is None
    assert r.error is None
