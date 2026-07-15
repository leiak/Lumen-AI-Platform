from enum import Enum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from lumen_core.workflow.retry import NodeRunError, RetryConfig  # noqa: F401  (re-exported)
from lumen_core.workflow.types import SegmentType

__all__ = [
    "BaseNodeData",
    "Condition",
    "ConditionCase",
    "ComparisonOperator",
    "ErrorStrategy",  # deprecated alias, P1 兼容
    "NodeRunError",  # re-exported from retry
    "NodeRunResult",
    "OutputVar",
    "RetryConfig",  # re-exported from retry
]


class OutputVar(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str
    type: SegmentType
    description: str = ""
    children: list["OutputVar"] = Field(default_factory=list)


# P1 兼容:ErrorStrategy 仍被部分旧 import 引用,P2 改为 Literal 但保留别名
class ErrorStrategy(str, Enum):
    FAIL_BRANCH = "fail_branch"
    DEFAULT_VALUE = "default_value"
    IGNORE = "ignore"


class BaseNodeData(BaseModel):
    model_config = ConfigDict(extra="ignore")
    title: str = "Node"
    desc: str | None = None
    version: str = "1"
    # P2 新增
    timeout: float | None = None
    default_value: dict[str, Any] | None = None
    error_strategy: Literal["fail_branch", "default_value", "ignore"] | None = None
    # P1 已有(从 retry.py 重新 import 以保持单一来源)
    retry_config: RetryConfig = Field(default_factory=RetryConfig)
    outputs: list[OutputVar] = Field(default_factory=list)


class ComparisonOperator(str, Enum):
    EQUAL = "="
    NOT_EQUAL = "!="
    CONTAINS = "contains"
    NOT_CONTAINS = "not contains"
    GREATER_THAN = ">"
    LESS_THAN = "<"
    GREATER_OR_EQUAL = ">="
    LESS_OR_EQUAL = "<="
    EXISTS = "exists"
    EMPTY = "empty"
    STARTS_WITH = "starts_with"
    ENDS_WITH = "ends_with"


class Condition(BaseModel):
    model_config = ConfigDict(extra="ignore")
    variable_selector: list[str]
    comparison_operator: ComparisonOperator
    value: Any | None = None


class ConditionCase(BaseModel):
    model_config = ConfigDict(extra="ignore")
    case_id: str = Field(default_factory=lambda: str(uuid4())[:8])
    logical_operator: Literal["and", "or"] = "and"
    conditions: list[Condition] = Field(default_factory=list)


class NodeRunResult(BaseModel):
    model_config = ConfigDict(extra="ignore")
    node_id: str
    outputs: list[OutputVar] = Field(default_factory=list)
    output_values: dict[str, Any] = Field(default_factory=dict)
    edge_source_handle: str | None = None
    error: str | None = None
