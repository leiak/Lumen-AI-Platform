from typing import Annotated, Any, Literal, Union
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from lumen_core.workflow.types import SegmentType


class Variable(BaseModel):
    """变量基类。selector 是 [node_id, var_name, ...sub_path]。

    Base type is narrowed by each subclass via Literal[SegmentType.XXX]
    (Pydantic discriminator). Do NOT instantiate Variable directly.
    """

    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    type: SegmentType
    value: Any = None
    description: str = ""
    selector: list[str] = Field(default_factory=list)


class StringVariable(Variable):
    type: Literal[SegmentType.STRING] = SegmentType.STRING


class NumberVariable(Variable):
    type: Literal[SegmentType.NUMBER] = SegmentType.NUMBER


class BooleanVariable(Variable):
    type: Literal[SegmentType.BOOLEAN] = SegmentType.BOOLEAN


class ObjectVariable(Variable):
    type: Literal[SegmentType.OBJECT] = SegmentType.OBJECT


class ArrayStringVariable(Variable):
    type: Literal[SegmentType.ARRAY_STRING] = SegmentType.ARRAY_STRING


class ArrayNumberVariable(Variable):
    type: Literal[SegmentType.ARRAY_NUMBER] = SegmentType.ARRAY_NUMBER


class ArrayObjectVariable(Variable):
    type: Literal[SegmentType.ARRAY_OBJECT] = SegmentType.ARRAY_OBJECT


class FileVariable(Variable):
    type: Literal[SegmentType.FILE] = SegmentType.FILE


class SecretVariable(Variable):
    type: Literal[SegmentType.SECRET] = SegmentType.SECRET


class NoneVariable(Variable):
    type: Literal[SegmentType.NONE] = SegmentType.NONE


VariableUnion = Annotated[
    Union[
        StringVariable, NumberVariable, BooleanVariable, ObjectVariable,
        ArrayStringVariable, ArrayNumberVariable, ArrayObjectVariable,
        FileVariable, SecretVariable, NoneVariable,
    ],
    Field(discriminator="type"),
]


def wrap_in_variable(value: Any, name: str, selector: list[str]) -> VariableUnion:
    """根据 Python 值类型自动包成对应 Variable 子类。"""
    if value is None:
        return NoneVariable(name=name, selector=list(selector))
    if isinstance(value, bool):
        return BooleanVariable(name=name, value=value, selector=list(selector))
    if isinstance(value, (int, float)):
        return NumberVariable(name=name, value=value, selector=list(selector))
    if isinstance(value, str):
        return StringVariable(name=name, value=value, selector=list(selector))
    if isinstance(value, list):
        if all(isinstance(x, str) for x in value):
            return ArrayStringVariable(name=name, value=value, selector=list(selector))
        if all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in value):
            return ArrayNumberVariable(name=name, value=value, selector=list(selector))
        return ArrayObjectVariable(name=name, value=value, selector=list(selector))
    if isinstance(value, dict):
        return ObjectVariable(name=name, value=value, selector=list(selector))
    return ObjectVariable(name=name, value=value, selector=list(selector))
