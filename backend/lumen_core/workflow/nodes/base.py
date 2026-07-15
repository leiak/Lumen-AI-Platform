from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from lumen_core.workflow.entities import BaseNodeData, NodeRunResult, OutputVar
from lumen_core.workflow.variable_pool import VariablePool


class NodeMetadata:
    """M30d: lightweight description of a node type, used by the
    /api/v1/workflow/node-types endpoint and (in future) the designer's
    field-rendering layer. Lives here so the BaseNode subclass authors
    are the single source of truth for both runtime AND the metadata
    surface (no schema drift).

    `category` is one of: input, output, process, control, integration,
    variable. The frontend groups nodes in the library panel by
    category; the backend uses it to validate graph shapes.
    """

    __slots__ = (
        "type", "label", "description", "icon", "color", "category",
        "default_config", "inputs", "outputs", "version",
    )

    def __init__(
        self,
        *,
        type: str,
        label: str,
        description: str = "",
        icon: str = "🔧",
        color: str = "default",
        category: str = "process",
        default_config: Optional[Dict[str, Any]] = None,
        inputs: Optional[List[Dict[str, Any]]] = None,
        outputs: Optional[List[Dict[str, Any]]] = None,
        version: str = "1",
    ) -> None:
        self.type = type
        self.label = label
        self.description = description
        self.icon = icon
        self.color = color
        self.category = category
        self.default_config = default_config or {}
        self.inputs = inputs or []
        self.outputs = outputs or []
        self.version = version

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.type,
            "label": self.label,
            "description": self.description,
            "icon": self.icon,
            "color": self.color,
            "category": self.category,
            "default_config": self.default_config,
            "inputs": self.inputs,
            "outputs": self.outputs,
            "version": self.version,
        }


class BaseNode(ABC):
    """所有节点类的基类。子类实现 init_node_data / outputs / _run。"""

    # M30d: each subclass overrides these class-level attributes to
    # describe itself in the node-types metadata API. Defaults are
    # conservative; the bulk of the work happens in the per-type
    # registry (workflow/node_types_metadata.py).
    metadata_type: str = ""
    metadata_label: str = ""
    metadata_description: str = ""
    metadata_icon: str = "🔧"
    metadata_color: str = "default"
    metadata_category: str = "process"

    def __init__(
        self,
        node_id: str,
        config: dict,
        pool: VariablePool,
        db: Session | None,
        tenant_id: int | None = None,
    ) -> None:
        self.node_id = node_id
        self.config = config
        self.pool = pool
        self.db = db
        self.tenant_id = tenant_id
        # init_node_data 立即执行,把 config 强类型化。子类可以在 _run 中读 self._data。
        # 配置错误会在这里抛出 — 这是预期行为(尽早暴露错误)。
        self._data: BaseNodeData = self.init_node_data(config)

    @classmethod
    def describe(cls) -> NodeMetadata:
        """M30d: return a NodeMetadata instance for this node type.

        Subclasses can override this if they need to compute inputs /
        outputs / default_config dynamically. The default implementation
        uses the class-level attributes (set in each subclass).
        """
        return NodeMetadata(
            type=cls.metadata_type or cls.__name__,
            label=cls.metadata_label or cls.__name__,
            description=cls.metadata_description,
            icon=cls.metadata_icon,
            color=cls.metadata_color,
            category=cls.metadata_category,
        )

    @abstractmethod
    def init_node_data(self, config: dict) -> BaseNodeData:
        """子类实现:把 config dict 校验为强类型 XxxNodeData。"""
        ...

    @abstractmethod
    def outputs(self) -> list[OutputVar]:
        """声明此节点暴露给下游的输出变量(单一事实源)。"""
        ...

    @abstractmethod
    async def _run(self) -> NodeRunResult:
        """实际执行。子类实现。"""
        ...

    async def run(self) -> NodeRunResult:
        """Default P1 behavior: run _run(), record outputs to pool.

        P2 executor does NOT call this; it calls run_node_with_handling()
        which itself awaits instance._run() with retry/timeout wrapping.
        We keep this method for backward compatibility with any caller that
        wants a no-wrapping direct execution (e.g. preview endpoints).
        """
        result = await self._run()
        result.node_id = self.node_id
        result.outputs = self.outputs()
        for name, value in result.output_values.items():
            self.pool.add([self.node_id, name], value)
        return result


def _passthrough_outputs(node_id_field: str = "value") -> list[OutputVar]:
    """Start/End 节点用,占位。子类按需覆盖。"""
    from lumen_core.workflow.types import SegmentType
    return [OutputVar(name=node_id_field, type=SegmentType.OBJECT)]
