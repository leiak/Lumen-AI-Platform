from lumen_core.workflow.types import SegmentType
from lumen_core.workflow.variables import (
    StringVariable, NumberVariable, BooleanVariable, ObjectVariable,
    ArrayStringVariable, ArrayNumberVariable, NoneVariable, wrap_in_variable,
)


def test_segment_type_string_values():
    assert SegmentType.STRING.value == "string"
    assert SegmentType.BOOLEAN.value == "boolean"
    assert SegmentType.ARRAY_STRING.value == "array[string]"


def test_segment_type_exposed_type_passthrough():
    # P1: NUMBER 不再细分 integer/float
    assert SegmentType.NUMBER.exposed_type() == "number"
    assert SegmentType.FILE.exposed_type() == "file"


def test_string_variable_basic():
    v = StringVariable(name="text", value="hello", selector=["n1", "text"])
    assert v.name == "text"
    assert v.value == "hello"
    assert v.type == SegmentType.STRING
    assert v.selector == ["n1", "text"]


def test_wrap_in_variable_string():
    v = wrap_in_variable("hello", "text", ["n1", "text"])
    assert isinstance(v, StringVariable)
    assert v.value == "hello"


def test_wrap_in_variable_int_to_number():
    v = wrap_in_variable(42, "count", ["n1", "count"])
    assert isinstance(v, NumberVariable)


def test_wrap_in_variable_float_to_number():
    v = wrap_in_variable(3.14, "ratio", ["n1", "ratio"])
    assert isinstance(v, NumberVariable)


def test_wrap_in_variable_bool_to_boolean():
    v = wrap_in_variable(True, "ok", ["n1", "ok"])
    assert isinstance(v, BooleanVariable)


def test_wrap_in_variable_dict_to_object():
    v = wrap_in_variable({"a": 1}, "data", ["n1", "data"])
    assert isinstance(v, ObjectVariable)


def test_wrap_in_variable_list_of_strings_to_array_string():
    v = wrap_in_variable(["a", "b"], "items", ["n1", "items"])
    assert isinstance(v, ArrayStringVariable)


def test_wrap_in_variable_list_of_ints_to_array_number():
    v = wrap_in_variable([1, 2, 3], "nums", ["n1", "nums"])
    assert isinstance(v, ArrayNumberVariable)


def test_wrap_in_variable_mixed_list_to_array_object():
    """Heterogeneous lists fall through to ArrayObjectVariable."""
    from lumen_core.workflow.variables import ArrayObjectVariable
    v = wrap_in_variable([1, "a", {"b": 2}], "mix", ["n1", "mix"])
    assert isinstance(v, ArrayObjectVariable)
    assert v.value == [1, "a", {"b": 2}]


def test_wrap_in_variable_bool_excluded_from_array_number():
    """Booleans must be excluded from ArrayNumberVariable (they pass isinstance(int))."""
    from lumen_core.workflow.variables import ArrayObjectVariable
    v = wrap_in_variable([True, 1, 2], "bools", ["n1", "bools"])
    assert isinstance(v, ArrayObjectVariable)


def test_variable_id_factory_unique():
    a = StringVariable(name="x", value="a", selector=["n", "x"])
    b = StringVariable(name="x", value="a", selector=["n", "x"])
    assert a.id != b.id


def test_wrap_in_variable_none_to_none():
    v = wrap_in_variable(None, "x", ["n1", "x"])
    assert isinstance(v, NoneVariable)
