# 工具调用(Tool Calling)

> Agent 怎么"调用工具"的?5 轮 tool loop 是怎么跑的?
> 文档解释 Lumen AI Platform 的工具调用机制,适合工程师扩展 / 排查。

---

## 1. 什么是 Tool Calling

LLM 不只能"聊天",还能"决定调用哪个函数"。这就是 **Tool Calling**(也叫 Function Calling):

```
用户: "今天北京天气怎么样?"
   │
   ▼
LLM: "我需要调 get_weather('北京')"
   │
   ▼
后端: 调 get_weather → "晴, 25°C"
   │
   ▼
LLM: "今天北京天气晴, 25°C"
```

LLM 不会真的"调函数",它返回结构化 `tool_calls` 列表,后端执行后把结果喂回 LLM。

---

## 2. Lumen 的工具注册

### 2.1 Tool 来源
Lumen 中"工具"有 3 种来源:

1. **内置工具**(代码定义)
   - `KnowledgeRetrievalTool` — 知识库 RAG
   - `HTTPRequestTool` — HTTP 请求
   - `CodeExecutionTool` — 跑 Python

2. **MCP 工具**(外部 server)
   - 通过 MCP 协议发现 + 调用
   - 见 [modules/mcp.md](../modules/mcp.md)

3. **技能 Tool**(租户注册)
   - 见 [modules/skill-market.md](../modules/skill-market.md)

### 2.2 工具 schema
每个工具暴露 OpenAI 兼容的 JSON Schema:

```json
{
  "type": "function",
  "function": {
    "name": "get_weather",
    "description": "查询指定城市的天气",
    "parameters": {
      "type": "object",
      "properties": {
        "city": {"type": "string", "description": "城市名"}
      },
      "required": ["city"]
    }
  }
}
```

### 2.3 关键代码
- 工具基类: `backend/lumen_tools/base.py::BaseTool`
- LangChain 适配: `lumen_tools/langchain_adapters.py`
- 工具注册表: `lumen_services/tool_registry.py`

---

## 3. 5 轮 Tool Loop

### 3.1 流程图
```
messages = [user_msg]
   │
   ▼
for attempt in 1..5:
   │
   ▼
  LLM_call(messages, tools)
   │
   ▼
  response = LLM(messages, tools)
   │
   ▼
  if response.tool_calls:
     for tool_call in response.tool_calls:
        try:
           result = invoke_tool(tool_call)
           messages.append(tool_message(result))
        except Exception as e:
           messages.append(tool_message(error=str(e)))
     # 继续下一轮
  else:
     # 没 tool_call,完成
     return response.content
   │
   ▼
# 5 轮跑完还没拿到 content → 取最后一次 content(可能空)
```

### 3.2 关键代码
```python
# lumen_services/agent_service.py
async def chat_with_tools(agent, messages, tools, current_user, max_iterations=5):
    for i in range(max_iterations):
        # 调 LLM(LoggingChatModel 包装,自动写日志)
        model = wrap_chat_model(
            build_chat_model(agent.model_config),
            module="agent",
            user_id=current_user.id,
            tenant_id=current_user.tenant_id,
            trace_id=get_trace_id(),
        )
        response = await model.bind_tools(tools).ainvoke(messages)

        if not response.tool_calls:
            return response.content

        # 执行 tool calls
        messages.append(response)
        for tool_call in response.tool_calls:
            tool = find_tool(tools, tool_call.name)
            try:
                result = await tool.ainvoke(tool_call.args)
                messages.append(ToolMessage(content=result, tool_call_id=tool_call.id))
            except Exception as e:
                messages.append(ToolMessage(content=f"Error: {e}", tool_call_id=tool_call.id))

    # 5 轮跑完
    return response.content
```

### 3.3 为什么是 5 轮
- **够用**: 大多数真实场景 1~3 轮就够
- **不爆**: 5 轮 = 5 × LLM 成本,再高不可控
- **可配**: Agent.tool_choice_max_iterations 可改(默认 5)

### 3.4 工具选择策略
- `auto`(默认):LLM 决定调不调
- `required`:必须调至少一个
- `none`:禁止调工具
- `specific`:必须调指定工具

---

## 4. 工具执行细节

### 4.1 输入
- LLM 返回 `tool_calls: [{name, args, id}]`
- `args` 是 JSON 字符串,Pydantic 校验

### 4.2 执行
- 后端从注册表找 `tool(name)`
- 调 `tool.ainvoke(args)`
- 返回 string(可被 LLM 读)

### 4.3 输出
- `ToolMessage(content=result, tool_call_id=tool_call.id)`
- 追加到 messages

### 4.4 异常处理
- 单个 tool 失败 → 错误信息作 tool message,继续
- 全部失败 → 5 轮后返回错误信息(LLM 决定怎么表达)

### 4.5 5 模块插桩
- 工具执行本身也走 LLMCallLog 包装(若工具内部调 LLM)
- 工具耗时 / 成功 / 失败都记录

---

## 5. 工具分类

### 5.1 知识库 RAG 工具
- 名称: `knowledge_retrieval`
- 参数: `{ kb_ids: [int], query: str, top_k: int }`
- 返回: `[{content, score, metadata}]`
- 用途: 让 Agent 自动选 KB 检索

### 5.2 HTTP 工具
- 名称: `http_request`
- 参数: `{ url, method, headers, body }`
- 返回: 响应 body
- 用途: 接 ERP / 业务 API

### 5.3 Code 执行工具
- 名称: `code_execution`
- 参数: `{ code: str, language: "python" }`
- 返回: stdout / 错误
- 用途: 跑计算 / 数据处理
- 安全: 沙箱(暂未实现,生产慎用)

### 5.4 MCP 工具
- 名称: `<mcp_server>__<tool_name>`
- 来源: 外部 MCP server
- 调用: 走 JSON-RPC

### 5.5 技能 Tool
- 名称: `<skill_name>`
- 来源: 租户注册的技能
- 调用: 走技能 adapter

---

## 6. 上下文管理

### 6.1 工具结果塞进 messages
```python
messages = [
    HumanMessage("今天北京天气?"),
    AIMessage(tool_calls=[{name: "get_weather", args: {city: "北京"}, id: "1"}]),
    ToolMessage(content="晴, 25°C", tool_call_id="1"),
    AIMessage("今天北京天气晴, 25°C"),
]
```

### 6.2 上下文爆炸风险
- 5 轮 × 3 tool = 15 个 tool message
- 每个 tool message 1~5 KB
- 上下文可能膨胀到 100+ KB → LLM 拒绝

### 6.3 解决
- **截断**:超过 N 字符截断
- **摘要**:LLM 摘要旧 tool message
- **选择**:让 LLM 决定保留哪些

详见 [记忆系统](../modules/memory.md)。

---

## 7. 并发工具调用

### 7.1 同一轮多个 tool
- LLM 可能一次返回 N 个 tool_calls
- 用 `asyncio.gather` 并发执行
- 全部完成后追加 messages

### 7.2 关键代码
```python
results = await asyncio.gather(
    *[tool.ainvoke(tc.args) for tc in response.tool_calls],
    return_exceptions=True
)
for tc, result in zip(response.tool_calls, results):
    if isinstance(result, Exception):
        messages.append(ToolMessage(content=f"Error: {result}", tool_call_id=tc.id))
    else:
        messages.append(ToolMessage(content=result, tool_call_id=tc.id))
```

---

## 8. 调试与排错

### 8.1 看 LLM 决定调什么
- 路径: `frontend/app/dashboard/logs/llm-call-detail.tsx`
- 字段: `tool_calls` (JSON)
- 字段: `tool result` (返回)

### 8.2 工具失败
- LLMCallLog `success=False, error=...`
- 通知: 关键工具失败推送到通知中心

### 8.3 常见错误

| 症状 | 原因 | 修法 |
|------|------|------|
| LLM 不调工具 | tool_choice=none / 描述不清 | 改 tool_choice + 写好 description |
| LLM 反复调同一工具 | 结果不能解决 | 改 description 提示何时停止 |
| 工具超时 | 工具本身慢 | 调超时或加缓存 |
| 工具返回空 | 参数错 | 看 trace 里 LLM 的 args |
| 5 轮跑完没结果 | 工具链错 / LLM 不会用 | 看 prompt 模板 + tool description |

---

## 9. 扩展:新增工具

### 9.1 步骤
1. 在 `lumen_tools/<your_tool>.py` 实现 `BaseTool`
2. 在 `lumen_services/tool_registry.py` 注册
3. (可选) 加权限检查(谁能用)
4. 写测试

### 9.2 示例
```python
# lumen_tools/my_tool.py
from lumen_tools.base import BaseTool
from pydantic import BaseModel, Field

class MyToolInput(BaseModel):
    query: str = Field(..., description="搜索关键词")

class MyTool(BaseTool):
    name = "my_search"
    description = "在 XXX 系统中搜索"
    args_schema = MyToolInput

    async def _arun(self, query: str) -> str:
        # 你的逻辑
        result = await call_my_api(query)
        return json.dumps(result, ensure_ascii=False)
```

### 9.3 在 Agent 中使用
- 编辑 Agent → "允许使用的工具" → 勾选 "my_search"
- LLM 自动能用

---

## 10. 工具 vs 工作流节点

### 10.1 工具
- **轻量**: 1 次 LLM 调用
- **灵活**: LLM 决定调不调、调几次
- **适合**: 不确定的场景

### 10.2 工作流节点
- **重**: 显式编排
- **固定**: 设计时定好调用顺序
- **适合**: 确定的业务流程

### 10.3 怎么选
- "LLM 自己看着办" → 工具
- "我设计好流程" → 工作流
- 混用:工作流里有 Agent 节点,Agent 用工具

---

**维护者**:全栈架构师
**最近更新**:2026-08-06
