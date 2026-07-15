import pytest
from lumen_core.workflow.variables import (
    StringVariable, NumberVariable, NoneVariable,
)
from lumen_core.workflow.variable_pool import VariablePool


def test_add_and_get_top_level():
    pool = VariablePool()
    pool.add(["n1", "text"], "hello")
    var = pool.get(["n1", "text"])
    assert isinstance(var, StringVariable)
    assert var.value == "hello"


def test_add_requires_two_element_selector():
    pool = VariablePool()
    with pytest.raises(ValueError, match="selector must be exactly"):
        pool.add(["n1"], "x")
    with pytest.raises(ValueError, match="selector must be exactly"):
        pool.add(["n1", "text", "sub"], "x")


def test_get_returns_none_variable_when_missing():
    pool = VariablePool()
    var = pool.get(["n1", "missing"])
    assert isinstance(var, NoneVariable)


def test_get_requires_at_least_two_elements():
    pool = VariablePool()
    with pytest.raises(ValueError, match="selector too short"):
        pool.get(["n1"])


def test_add_overwrites_same_name():
    pool = VariablePool()
    pool.add(["n1", "x"], "first")
    pool.add(["n1", "x"], "second")
    assert pool.get(["n1", "x"]).value == "second"


def test_get_nested_dict_field():
    pool = VariablePool()
    pool.add(["n1", "data"], {"a": 1, "b": {"c": 2}})
    inner = pool.get(["n1", "data", "b", "c"])
    assert isinstance(inner, NumberVariable)
    assert inner.value == 2


def test_get_nested_missing_field_returns_none_variable():
    pool = VariablePool()
    pool.add(["n1", "data"], {"a": 1})
    var = pool.get(["n1", "data", "missing"])
    assert isinstance(var, NoneVariable)


def test_remove_single_var():
    pool = VariablePool()
    pool.add(["n1", "x"], "hello")
    pool.remove(["n1", "x"])
    assert isinstance(pool.get(["n1", "x"]), NoneVariable)


def test_remove_whole_node_namespace():
    pool = VariablePool()
    pool.add(["n1", "a"], 1)
    pool.add(["n1", "b"], 2)
    pool.add(["n2", "c"], 3)
    pool.remove(["n1"])
    assert isinstance(pool.get(["n1", "a"]), NoneVariable)
    assert isinstance(pool.get(["n1", "b"]), NoneVariable)
    assert pool.get(["n2", "c"]).value == 3


def test_remove_rejects_too_long_selector():
    pool = VariablePool()
    with pytest.raises(ValueError, match="remove selector must be length"):
        pool.remove(["n1", "x", "sub"])


def test_get_all_in_scope():
    pool = VariablePool()
    pool.add(["input", "user_query"], "hi")
    pool.add(["n1", "x"], 1)
    pool.add(["env", "time"], "2026-06-04")
    pool.add(["n99", "unrelated"], 999)
    result = pool.get_all_in_scope("target", ["input", "n1"])
    values = [v.value for v in result]
    assert "hi" in values
    assert 1 in values
    assert "2026-06-04" in values
    assert 999 not in values


def test_snapshot():
    pool = VariablePool()
    pool.add(["n1", "x"], 1)
    pool.add(["n2", "y"], "two")
    snap = pool.snapshot()
    assert snap == {"n1": {"x": 1}, "n2": {"y": "two"}}


def test_get_descend_through_none_value_returns_none_variable():
    """Walking through a None value in a nested dict returns NoneVariable, not a crash."""
    pool = VariablePool()
    pool.add(["n1", "data"], {"a": None})
    var = pool.get(["n1", "data", "a", "b"])
    assert isinstance(var, NoneVariable)


def test_get_descend_through_non_dict_value_returns_none_variable():
    """Walking through a non-dict value (e.g., a string) returns NoneVariable."""
    pool = VariablePool()
    pool.add(["n1", "data"], {"a": "hello"})
    var = pool.get(["n1", "data", "a", "b"])
    assert isinstance(var, NoneVariable)


def test_get_all_in_scope_includes_node_id_namespace():
    """Variables in the target node's own namespace appear in scope."""
    pool = VariablePool()
    pool.add(["target", "self_var"], "from-self")
    pool.add(["n1", "x"], 1)
    pool.add(["env", "time"], "now")
    result = pool.get_all_in_scope("target", ["n1"])
    values = [v.value for v in result]
    assert "from-self" in values
    assert 1 in values
    assert "now" in values
