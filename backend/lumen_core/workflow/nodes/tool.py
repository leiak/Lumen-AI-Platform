"""ToolNode — 引用平台 MCP 工具,跨租户查找后通过 MCPService 执行并返回结果。

跨租户隔离:查询 MCPTool 时同时校验 tenant_id。

调用约定:
- ``MCPService.execute_tool`` 的真实签名是
  ``async def execute_tool(self, db, tenant_id, tool_name, input_data) -> dict``。
- 返回的是 MCP 协议 ``result`` 形状 ``{"content": [...], "isError": bool}``(可选 ``error``)。
- 本节点把上述形状统一映射为输出 ``{result, is_error, error}``。
- 兼容旧版 ``{"data", "is_error", "error"}`` 形状(便于测试与未来扩展)。
"""
from typing import Any

from pydantic import ConfigDict, Field

from lumen_core.workflow.entities import BaseNodeData, NodeRunResult, OutputVar
from lumen_core.workflow.nodes.base import BaseNode
from lumen_core.workflow.template_parser import VariableTemplateParser
from lumen_core.workflow.types import SegmentType
from lumen_models.mcp import MCPTool
from lumen_services.mcp_service import MCPService


class ToolNodeData(BaseNodeData):
    """ToolNode 的强类型配置。

    Fields
    ------
    tool_id:
        引用的 ``MCPTool.id``。0/未设置 = 未选择。
    tool_name_cache:
        前端保存的展示用名称(供 UI 回显,不影响执行)。
    arguments:
        传给工具的 JSON 参数;字符串值会通过 ``VariableTemplateParser`` 渲染
        ``{{#node_id.var#}}`` 模板。
    """
    model_config = ConfigDict(extra="ignore")
    tool_id: int = 0
    tool_name_cache: str = ""
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolNode(BaseNode):
    """调用一个已注册的 MCP 工具并把结果向下游暴露。"""

    def init_node_data(self, config: dict) -> BaseNodeData:
        cfg = {**config, "version": config.get("version", "1")}
        return ToolNodeData.model_validate(cfg)

    def outputs(self) -> list[OutputVar]:
        return [
            OutputVar(name="result", type=SegmentType.OBJECT, description="工具返回的 data / content"),
            OutputVar(name="is_error", type=SegmentType.BOOLEAN, description="工具是否报错"),
            OutputVar(name="error", type=SegmentType.STRING, description="错误信息"),
        ]

    async def _run(self) -> NodeRunResult:
        assert isinstance(self._data, ToolNodeData)
        d: ToolNodeData = self._data

        if not d.tool_id:
            raise ValueError("必须选择工具")

        if self.db is None:
            raise ValueError("ToolNode 需要 db session 才能查找 MCP 工具")

        # MCPTool.is_enabled 是 Integer(0/1);filter_by 直接用 is_enabled=1 等价于 ``is_enabled == 1``。
        tool = (
            self.db.query(MCPTool)
            .filter_by(id=d.tool_id, is_enabled=1)
            .first()
        )
        # 跨租户隔离:即使 SQL 命中,tenant_id 不匹配也视为未找到。
        if tool is not None and self.tenant_id is not None and tool.tenant_id != self.tenant_id:
            tool = None
        if not tool:
            raise ValueError(f"Tool {d.tool_id} not found or inactive")

        # 仅对字符串值做模板渲染;dict/list 等复杂值原样透传。
        rendered_args: dict[str, Any] = {}
        for k, v in d.arguments.items():
            if isinstance(v, str):
                rendered_args[k] = VariableTemplateParser(v).format(self.pool)
            else:
                rendered_args[k] = v

        # 允许测试在 db.mcp_service 注入 fake;真实运行走 MCPService() 单例路径。
        svc = getattr(self.db, "mcp_service", None) or MCPService()
        out = await svc.execute_tool(
            self.db,
            self.tenant_id,  # type: ignore[arg-type]
            tool.name,  # type: ignore[arg-type]
            rendered_args,
        )

        # 兼容两种返回形状:旧 {data, is_error, error} 与新 MCP 协议 {content, isError, error}。
        return NodeRunResult(
            node_id=self.node_id,
            output_values={
                "result": out.get("data", out.get("content")),
                "is_error": out.get("is_error", out.get("isError", False)),
                "error": out.get("error"),
            },
        )
