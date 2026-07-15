from enum import Enum


class SegmentType(str, Enum):
    """工作流值类型枚举。后端强类型,前端 mirror VarType。"""

    STRING = "string"
    NUMBER = "number"
    BOOLEAN = "boolean"
    OBJECT = "object"
    ARRAY_STRING = "array[string]"
    ARRAY_NUMBER = "array[number]"
    ARRAY_OBJECT = "array[object]"
    FILE = "file"
    SECRET = "secret"
    NONE = "none"

    def exposed_type(self) -> str:
        """暴露给前端展示用(P1:不再细分 integer / float,统一 NUMBER)。"""
        return self.value
