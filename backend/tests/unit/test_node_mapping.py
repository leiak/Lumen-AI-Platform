import pytest
from lumen_core.workflow.node_mapping import (
    NODE_TYPE_CLASSES_MAPPING, resolve_node_class,
)


def test_all_nineteen_business_types_registered():
    expected = {"input", "agent", "code", "llm", "condition", "output",
                "parallel", "fan_out", "fan_in", "http", "start", "end", "tool",
                "knowledge_retrieval", "template_transform", "parameter_extractor",
                "question_classifier", "variable_assigner", "variable_aggregator"}
    assert set(NODE_TYPE_CLASSES_MAPPING.keys()) == expected


def test_every_type_has_v1_class():
    for t, by_version in NODE_TYPE_CLASSES_MAPPING.items():
        assert "1" in by_version, f"{t} missing v1"
        assert by_version["1"] is not None, f"{t} v1 is None"


def test_resolve_node_class_known_type():
    cls = resolve_node_class("input", "1")
    assert cls is not None
    assert cls.__name__ == "InputNode"


def test_resolve_node_class_unknown_type_raises():
    with pytest.raises(ValueError, match="未知节点类型"):
        resolve_node_class("nope_xyz")


def test_resolve_node_class_unknown_version_falls_back_to_v1():
    cls = resolve_node_class("input", "99")
    assert cls.__name__ == "InputNode"


@pytest.mark.parametrize("node_type,expected_class_name", [
    ("input", "InputNode"),
    ("agent", "AgentNode"),
    ("llm", "LLMNode"),
    ("start", "StartNode"),
    ("end", "EndNode"),
])
def test_resolve_node_class_default_version(node_type, expected_class_name):
    cls = resolve_node_class(node_type)
    assert cls.__name__ == expected_class_name
