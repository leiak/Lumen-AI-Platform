from collections import defaultdict
from typing import Any

from lumen_core.workflow.variables import (
    NoneVariable, VariableUnion, wrap_in_variable,
)


class VariablePool:
    """按 [node_id, var_name] 二元组索引的类型化变量池。

    add 强制 len(selector) == 2,get 支持 [id, name, ...sub_path] 嵌套访问。
    """

    def __init__(self) -> None:
        self._pool: defaultdict[str, dict[str, VariableUnion]] = defaultdict(dict)

    def add(self, selector: list[str], value: Any, description: str = "") -> None:
        if len(selector) != 2:
            raise ValueError(
                f"selector must be exactly [node_id, var_name], got {selector}"
            )
        node_id, var_name = selector
        var = wrap_in_variable(value, var_name, selector)
        if description:
            var.description = description
        self._pool[node_id][var_name] = var

    def get(self, selector: list[str]) -> VariableUnion:
        if len(selector) < 2:
            raise ValueError(f"selector too short: {selector}")
        node_id, var_name, *sub = selector
        if node_id not in self._pool or var_name not in self._pool[node_id]:
            return NoneVariable(name=var_name, selector=list(selector))
        var = self._pool[node_id][var_name]
        if not sub:
            return var
        return self._descend(var, sub)

    def _descend(self, var: VariableUnion, path: list[str]) -> VariableUnion:
        current = var.value
        consumed: list[str] = []
        for key in path:
            consumed.append(key)
            if not isinstance(current, dict):
                return NoneVariable(
                    name=var.name, selector=list(var.selector) + consumed
                )
            current = current.get(key)
            if current is None:
                return NoneVariable(
                    name=var.name, selector=list(var.selector) + consumed
                )
        return wrap_in_variable(current, var.name, list(var.selector) + path)

    def remove(self, selector: list[str]) -> None:
        if len(selector) == 1:
            self._pool.pop(selector[0], None)
        elif len(selector) == 2:
            self._pool.get(selector[0], {}).pop(selector[1], None)
        else:
            raise ValueError(
                f"remove selector must be length 1 or 2, got {len(selector)}"
            )

    def get_all_in_scope(
        self, node_id: str, before_nodes: list[str]
    ) -> list[VariableUnion]:
        """返回 [node_id, before_nodes..., system] 三个命名空间的所有变量扁平化。"""
        result: list[VariableUnion] = []
        result.extend(self._pool.get(node_id, {}).values())
        for nid in before_nodes:
            result.extend(self._pool.get(nid, {}).values())
        result.extend(self._pool.get("env", {}).values())
        return result

    def snapshot(self) -> dict:
        return {
            k: {vk: v.value for vk, v in vs.items()}
            for k, vs in self._pool.items()
        }
