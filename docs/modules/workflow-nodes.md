# 模块:工作流 22 节点

> Lumen AI Platform 工作流所有 22 个节点的规格说明。
> 每个节点独立可配,组合实现复杂业务流程。

---

## 1. 节点总览

### 1.1 分类
| 类别 | 节点 |
|------|------|
| **基础结构** | Input / Output |
| **控制流** | Condition / Parallel / Fan Out / Fan In |
| **AI 类** | LLM / Agent |
| **数据处理** | Knowledge Retrieval / Variable Assigner / Variable Aggregator |
| **执行类** | Code / HTTP / Tool |
| **辅助类** | Template Transform / Parameter Extractor / Question Classifier |

### 1.2 共用字段
所有节点都有:
- `node_key`(UUID)
- `node_type`
- `position_x`, `position_y`
- `config`(JSON,每个 type 字段不同)
- `error_strategy` (`fail_fast` / `ignore` / `fallback`)
- `retry_config` (`{max_attempts, backoff, initial_delay_seconds, max_delay_seconds}`)
- `timeout_seconds`(默认 30)

详见 [explanation/error-retry-timeout.md](../explanation/error-retry-timeout.md)。

---

## 2. Input 节点(工作流入口)

### 2.1 用途
- 工作流的"开始"节点
- 定义工作流需要哪些输入参数

### 2.2 配置
```json
{
  "inputs": [
    {"name": "user_query", "type": "string", "required": true, "description": "用户问题"},
    {"name": "user_id", "type": "int", "required": true, "description": "用户ID"}
  ]
}
```

### 2.3 运行时
- Run 时把 inputs 注入到 state
- 下游节点用 `{{inputs.user_query}}` 引用

### 2.4 关键代码
- `backend/lumen_services/workflow_nodes/input.py`
- 前端: `frontend/components/workflow/nodes/input/`

---

## 3. Output 节点(工作流出口)

### 3.1 用途
- 工作流的"结束"节点
- 拼装最终返回

### 3.2 配置
```json
{
  "outputs": {
    "answer": "{{llm_1.content}}",
    "sources": "{{kb_retrieval_1.citations}}"
  }
}
```

### 3.3 运行时
- 渲染模板
- 写到 `state.final_outputs`
- Run.outputs = final_outputs

---

## 4. Condition 节点(条件分支)

### 4.1 用途
- if-else 分支
- LLM / 代码 / 表达式 三种判断

### 4.2 配置
```json
{
  "cases": [
    {
      "name": "billing",
      "condition": "{{llm_1.content}} contains '账单'",
      "target_node_key": "billing_handler"
    },
    {
      "name": "tech",
      "condition": "{{llm_1.content}} contains '技术'",
      "target_node_key": "tech_handler"
    }
  ],
  "default_target_node_key": "fallback"
}
```

### 4.3 关键代码
- `backend/lumen_services/workflow_nodes/condition.py`
- 前端: `frontend/components/workflow/_base/condition/`
- 编辑器: `ConditionCaseEditor`

---

## 5. Parallel 节点(真并行)

### 5.1 用途
- N 个子节点同时跑
- 等齐再继续

### 5.2 配置
```json
{
  "branches": ["agent_a", "agent_b", "agent_c"]
}
```

### 5.3 运行时
- `asyncio.gather` 跑 3 个节点
- 输出: `{"agent_a": {...}, "agent_b": {...}, "agent_c": {...}}`

---

## 6. Fan Out / Fan In 节点

### 6.1 Fan Out(列表展开)
- 输入: list
- 输出: 每个元素独立一个下游实例

### 6.2 Fan In(列表聚合)
- 输入: 多个上游输出
- 输出: 合并为 list

### 6.3 配置示例
```json
{
  "fan_in": {
    "sources": ["worker_1", "worker_2", "worker_3"],
    "mode": "concat"   // or "merge"
  }
}
```

---

## 7. LLM 节点

### 7.1 用途
- 调 LLM,返回 content
- 简单场景,不用工具

### 7.2 配置
```json
{
  "model_config_id": 1,
  "prompt": "你是翻译专家,把下面翻成英文:\n{{inputs.text}}",
  "temperature": 50,
  "max_tokens": 500,
  "system": "You are a translator"
}
```

### 7.3 关键代码
- `backend/lumen_services/workflow_nodes/llm.py`
- 前端: `frontend/components/workflow/nodes/llm/`
- 包装: `LoggingChatModel` 自动写日志

---

## 8. Agent 节点

### 8.1 用途
- 调 1 个 Agent
- 自动 5 轮 tool loop
- 比 LLM 节点更强(能用工具)

### 8.2 配置
```json
{
  "agent_id": 5,
  "user_message": "{{inputs.user_query}}",
  "conversation_id": null  // 可选,继续某会话
}
```

### 8.3 关键代码
- `backend/lumen_services/workflow_nodes/agent.py`
- 复用 `agent_service.chat`

---

## 9. Code 节点

### 9.1 用途
- 跑 Python 代码
- 纯计算 / 数据处理

### 9.2 配置
```json
{
  "code": "result = sum(inputs.numbers) / len(inputs.numbers)\noutput = {'avg': result}",
  "inputs": {"numbers": "{{previous_node.numbers}}"}
}
```

### 9.3 运行时
- exec(code, {"inputs": ..., "output": ...})
- 沙箱:暂未实现,生产慎用

---

## 10. HTTP 节点

### 10.1 用途
- 发 HTTP 请求
- 接 ERP / 业务 API

### 10.2 配置
```json
{
  "method": "POST",
  "url": "https://erp.example.com/api/orders",
  "headers": {"Authorization": "Bearer {{secrets.erp_token}}"},
  "body": {"order_id": "{{inputs.order_id}}"},
  "timeout": 10
}
```

### 10.3 关键代码
- `backend/lumen_services/workflow_nodes/http.py`
- 用 `httpx.AsyncClient`

---

## 11. Tool 节点

### 11.1 用途
- 调 1 个工具(非 LLM loop)
- 内置 / MCP / 技能

### 11.2 配置
```json
{
  "tool_name": "knowledge_retrieval",
  "tool_input": {
    "kb_ids": [1, 2],
    "query": "{{inputs.user_query}}"
  }
}
```

### 11.3 运行时
- 从注册表找 tool
- 调 `tool.ainvoke(input)`

---

## 12. Knowledge Retrieval 节点

### 12.1 用途
- 知识库 RAG 检索
- 不调 LLM,只返 chunks

### 12.2 配置
```json
{
  "kb_ids": [1, 2],
  "query": "{{inputs.user_query}}",
  "top_k": 20,
  "top_n": 5,
  "score_threshold": 0.5,
  "vector_weight": 0.7,
  "keyword_weight": 0.3
}
```

### 12.3 输出
```json
{
  "chunks": [
    {"id": 10, "content": "...", "score": 0.92, "document_id": 3, "metadata": {...}}
  ],
  "citations": [...]
}
```

### 12.4 关键代码
- `backend/lumen_services/workflow_nodes/knowledge_retrieval.py`
- 复用 `knowledge_service.retrieve`

---

## 13. Variable Assigner 节点

### 13.1 用途
- 赋值给工作流变量
- 让后续节点引用

### 13.2 配置
```json
{
  "assignments": {
    "user_name": "{{http_1.body.name}}",
    "user_email": "{{http_1.body.email}}"
  }
}
```

### 13.3 运行时
- 写到 `state.variables[key] = value`
- 下游节点用 `{{variables.user_name}}`

---

## 14. Variable Aggregator 节点

### 14.1 用途
- 合并多个分支的变量
- 在 parallel 后用

### 14.2 配置
```json
{
  "sources": [
    {"source_node_key": "branch_a", "vars": ["score_a", "name_a"]},
    {"source_node_key": "branch_b", "vars": ["score_b", "name_b"]}
  ],
  "merge_strategy": "concat"  // or "merge" / "max"
}
```

---

## 15. Template Transform 节点

### 15.1 用途
- Jinja2 模板渲染
- 不调 LLM,只拼字符串

### 15.2 配置
```json
{
  "template": "你好 {{ variables.user_name }},你的订单 {{ inputs.order_id }} 已发货。",
  "output_key": "message"
}
```

---

## 16. Parameter Extractor 节点

### 16.1 用途
- LLM 从自然语言提取结构化参数
- 用 Pydantic schema

### 16.2 配置
```json
{
  "model_config_id": 1,
  "input_text": "{{inputs.user_query}}",
  "schema": {
    "type": "object",
    "properties": {
      "intent": {"type": "string", "enum": ["order", "billing", "tech"]},
      "urgency": {"type": "integer", "minimum": 1, "maximum": 5}
    },
    "required": ["intent"]
  }
}
```

### 16.3 输出
```json
{
  "intent": "order",
  "urgency": 3
}
```

### 16.4 实现
- LLM 生成 JSON
- Pydantic 校验
- 失败重试 + 错误提示

---

## 17. Question Classifier 节点

### 17.1 用途
- 简单分类(多 case)
- 类似 Condition,但用 LLM 判

### 17.2 配置
```json
{
  "model_config_id": 1,
  "input": "{{inputs.user_query}}",
  "categories": [
    {"name": "billing", "description": "关于账单/付款"},
    {"name": "tech", "description": "关于技术支持"},
    {"name": "other", "description": "其他"}
  ]
}
```

### 17.3 输出
```json
{
  "category": "billing"
}
```

### 17.4 vs Parameter Extractor
- Classifier: 1 个 enum
- Extractor: 多个字段

---

## 18. 节点通用错误配置

```json
{
  "error_strategy": "fail_fast",   // fail_fast / ignore / fallback
  "retry_config": {
    "max_attempts": 3,
    "backoff": "exponential",
    "initial_delay_seconds": 1,
    "max_delay_seconds": 60
  },
  "timeout_seconds": 30
}
```

详见 [explanation/error-retry-timeout.md](../explanation/error-retry-timeout.md)。

---

## 19. 节点输入输出规范

### 19.1 输入
- 节点函数签名: `def invoke(state: WorkflowState, config: dict) -> dict`
- state 包含 inputs / variables / node_outputs
- config 是节点配置 JSON

### 19.2 输出
- 返回 dict,自动 merge 到 `state.node_outputs[node_key]`
- 例: `return {"answer": "...", "sources": [...]}`
- 下游节点用 `{{node_<key>.answer}}` 引用

### 19.3 变量引用解析
- `parse_references(template)` → 提取 `{{...}}`
- 解析 → `state.inputs` / `state.variables` / `state.node_outputs[key]`
- 未定义 → 抛错

---

## 20. 节点开发规范

### 20.1 文件结构
```
backend/lumen_services/workflow_nodes/
├── __init__.py
├── base.py                    # 基类
├── input.py
├── output.py
├── condition.py
├── parallel.py
├── fan_out.py
├── fan_in.py
├── llm.py
├── agent.py
├── code.py
├── http.py
├── tool.py
├── knowledge_retrieval.py
├── variable_assigner.py
├── variable_aggregator.py
├── template_transform.py
├── parameter_extractor.py
└── question_classifier.py
```

### 20.2 新增节点
1. 继承 `BaseNode`
2. 实现 `async def invoke(self, state, config) -> dict`
3. 注册到 `NODE_REGISTRY`
4. 加前端 Panel + Node
5. 写测试

详见 [how-to/add-new-workflow-node.md](../how-to/add-new-workflow-node.md)。

---

## 21. 排错

| 症状 | 原因 | 修法 |
|------|------|------|
| 节点 timeout | LLM 慢 | 调 timeout + 选小模型 |
| 变量没渲染 | `{{...}}` 拼写错 | 看 Run 详情 |
| 节点 fail_fast | 错误 | 看 error message |
| retry 不重试 | max_attempts=1 | 改大 |
| 引用 chunks 空 | KB 检索 0 | 上传文档 |
| 并行不并行 | 没用 Parallel | 改 Parallel |

---

**维护者**:全栈架构师
**最近更新**:2026-08-06
