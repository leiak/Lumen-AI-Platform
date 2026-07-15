import pytest
from lumen_core.workflow.condition import ConditionProcessor
from lumen_core.workflow.entities import (
    ComparisonOperator, Condition, ConditionCase,
)
from lumen_core.workflow.variable_pool import VariablePool


def _case(*conds, op="and", case_id="c1"):
    return ConditionCase(
        case_id=case_id, logical_operator=op,
        conditions=list(conds),
    )


def _cond(selector, op, value=None):
    return Condition(
        variable_selector=list(selector),
        comparison_operator=op,
        value=value,
    )


def test_equal_true():
    pool = VariablePool()
    pool.add(["n1", "x"], "hello")
    matched, cid = ConditionProcessor.process_cases(
        [_case(_cond(["n1", "x"], ComparisonOperator.EQUAL, "hello"))], pool
    )
    assert matched is True
    assert cid == "c1"


def test_equal_false():
    pool = VariablePool()
    pool.add(["n1", "x"], "hi")
    matched, cid = ConditionProcessor.process_cases(
        [_case(_cond(["n1", "x"], ComparisonOperator.EQUAL, "bye"))], pool
    )
    assert matched is False
    assert cid == "false"


def test_greater_than():
    pool = VariablePool()
    pool.add(["n1", "n"], 100)
    matched, cid = ConditionProcessor.process_cases(
        [_case(_cond(["n1", "n"], ComparisonOperator.GREATER_THAN, 50))], pool
    )
    assert matched is True


def test_contains_string():
    pool = VariablePool()
    pool.add(["n1", "s"], "hello world")
    matched, cid = ConditionProcessor.process_cases(
        [_case(_cond(["n1", "s"], ComparisonOperator.CONTAINS, "world"))], pool
    )
    assert matched is True


def test_exists():
    pool = VariablePool()
    pool.add(["n1", "x"], "x")
    matched, cid = ConditionProcessor.process_cases(
        [_case(_cond(["n1", "x"], ComparisonOperator.EXISTS))], pool
    )
    assert matched is True


def test_exists_missing():
    pool = VariablePool()
    matched, cid = ConditionProcessor.process_cases(
        [_case(_cond(["n1", "missing"], ComparisonOperator.EXISTS))], pool
    )
    assert matched is False


def test_and_short_circuit_false():
    pool = VariablePool()
    pool.add(["n1", "a"], 1)
    pool.add(["n1", "b"], 1)
    matched, cid = ConditionProcessor.process_cases(
        [_case(
            _cond(["n1", "a"], ComparisonOperator.EQUAL, 1),
            _cond(["n1", "b"], ComparisonOperator.EQUAL, 2),  # False
            op="and",
        )], pool
    )
    assert matched is False


def test_or_short_circuit_true():
    pool = VariablePool()
    pool.add(["n1", "a"], 1)
    matched, cid = ConditionProcessor.process_cases(
        [_case(
            _cond(["n1", "a"], ComparisonOperator.EQUAL, 2),  # False
            _cond(["n1", "a"], ComparisonOperator.EQUAL, 1),  # True
            op="or",
        )], pool
    )
    assert matched is True


def test_first_matching_case_wins():
    pool = VariablePool()
    pool.add(["n1", "x"], "hi")
    matched, cid = ConditionProcessor.process_cases([
        _case(_cond(["n1", "x"], ComparisonOperator.EQUAL, "hi"), case_id="first"),
        _case(_cond(["n1", "x"], ComparisonOperator.EQUAL, "hi"), case_id="second"),
    ], pool)
    assert cid == "first"


def test_all_false_returns_false_handle():
    pool = VariablePool()
    matched, cid = ConditionProcessor.process_cases([
        _case(_cond(["n1", "x"], ComparisonOperator.EQUAL, "no"), case_id="a"),
    ], pool)
    assert matched is False
    assert cid == "false"
