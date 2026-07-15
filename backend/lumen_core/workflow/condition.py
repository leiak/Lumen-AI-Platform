from typing import Any

from lumen_core.workflow.entities import (
    ComparisonOperator, Condition, ConditionCase,
)
from lumen_core.workflow.variable_pool import VariablePool
from lumen_core.workflow.variables import NoneVariable


class ConditionProcessor:
    """顺序遍历 cases,每个 case 内部按 logical_operator 聚合。
    首个整体为 True 的 case 返回其 case_id,否则返回 ('false', 'false')。
    """

    @staticmethod
    def process_cases(
        cases: list[ConditionCase], pool: VariablePool
    ) -> tuple[bool, str]:
        for case in cases:
            results = [ConditionProcessor._eval(c, pool) for c in case.conditions]
            if case.logical_operator == "and":
                ok = all(results) if results else False
            else:  # "or"
                ok = any(results) if results else False
            if ok:
                return True, case.case_id
        return False, "false"

    @staticmethod
    def _eval(c: Condition, pool: VariablePool) -> bool:
        var = pool.get(c.variable_selector)
        op = c.comparison_operator
        if op == ComparisonOperator.EXISTS:
            return not isinstance(var, NoneVariable)
        if op == ComparisonOperator.EMPTY:
            return var.value in (None, "", [], {})
        left: Any = var.value
        right: Any = c.value
        try:
            if op == ComparisonOperator.EQUAL:
                return left == right
            if op == ComparisonOperator.NOT_EQUAL:
                return left != right
            if op == ComparisonOperator.GREATER_THAN:
                return left > right
            if op == ComparisonOperator.LESS_THAN:
                return left < right
            if op == ComparisonOperator.GREATER_OR_EQUAL:
                return left >= right
            if op == ComparisonOperator.LESS_OR_EQUAL:
                return left <= right
            if op == ComparisonOperator.CONTAINS:
                return (right in left) if left is not None else False
            if op == ComparisonOperator.NOT_CONTAINS:
                return (right not in left) if left is not None else True
            if op == ComparisonOperator.STARTS_WITH:
                return isinstance(left, str) and left.startswith(str(right))
            if op == ComparisonOperator.ENDS_WITH:
                return isinstance(left, str) and left.endswith(str(right))
        except TypeError:
            return False
        return False
