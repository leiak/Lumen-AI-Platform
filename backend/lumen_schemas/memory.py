"""Pydantic schemas for /api/v1/memory.

M40.1 quick wins: 把 lumen_api/v1/memory.py 内联定义的 ``MemoryMessage``
+ 3 个 ``SingleResponse[dict]`` leak 端点响应的 ``MemoryWriteResponse``
统一抽到 schemas 包,前端 OpenAPI codegen 可见。
"""
from __future__ import annotations

from typing import Optional, Dict, Any

from pydantic import BaseModel


class MemoryMessage(BaseModel):
    """单条 memory 记录(对话级 + 全局级都用)。

    role: ``"user"`` / ``"assistant"`` / ``"system"``
    metadata: 调用方可选附加上下文(MCP 工具调用、模型名等)。
    conversation_id: M15 引入,把全局 memory row 关联回源 conversation,
        UI 据此区分「当前 conv 的 row」vs「其他 conv 流过来的 row」。

    ``content`` 默认空串(早期 row 可能没填);前端展示时为兜底处理。
    """
    role: str
    content: str = ""
    metadata: Optional[Dict[str, Any]] = None
    # M15: source conversation. None for legacy rows and for any future
    # caller that doesn't know the source. The UI uses it to dim/filter
    # current-conv rows in the global context panel.
    conversation_id: Optional[int] = None


class MemoryWriteResponse(BaseModel):
    """M40.1: 3 个 memory 写端点的统一强类型响应(替代 SingleResponse[dict])。

    status 取值:
    - ``"added"`` — POST /conversations/{id}/messages 写完返回。
    - ``"cleared"`` — DELETE /conversations/{id} 和 DELETE /global 清完返回。

    行为约定:端点只关心 status 一值,前端拿到后做 toast 即可,无需拆 endpoint
    分支单独 contract。``affected_rows`` 给个 hint(可选,本期前端没用到,
    留作扩展位)。
    """
    status: str
    affected_rows: Optional[int] = None
