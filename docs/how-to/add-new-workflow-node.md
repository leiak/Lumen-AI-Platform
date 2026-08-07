# How-to:新增一个工作流节点

> 业务需要新能力 → 加一个工作流节点类型。
> 5 个步骤:Python 类 → Registry → 测试 → 前端 Panel → 截图。

---

## 1. 总览

每个工作流节点由 3 部分组成:

| 部分 | 位置 | 职责 |
|------|------|------|
| **后端节点** | `backend/lumen_services/workflow_nodes/<node_type>.py` | 执行逻辑 |
| **节点规范** | `backend/lumen_services/workflow_nodes/__init__.py::NODE_REGISTRY` | 注册 |
| **前端 Panel** | `frontend/components/workflow/nodes/<NodeType>Panel.tsx` | 配置 UI |
| **前端节点** | `frontend/components/workflow/nodes/NodeTypeNode.tsx` | 画布节点 |

**前置**:
- 读 [workflow-nodes.md](../modules/workflow-nodes.md) — 22 节点规范
- 读 [spec](#5-节点开发规范) — 节点规范

---

## 2. 步骤

### 2.1 创建后端节点

**文件**:`backend/lumen_services/workflow_nodes/my_node.py`

```python
"""My custom node — does something."""
from typing import Any, Dict
from lumen_services.workflow_nodes.base import BaseNode
from lumen_models.workflow import WorkflowNodeRun


class MyNode(BaseNode):
    """Brief description on one line. (英文 1 行摘要,中文详细)"""

    node_type = "my_node"

    # 配置 schema(Pydantic)
    config_schema = {
        "type": "object",
        "properties": {
            "input_field": {"type": "string"},
            "max_retries": {"type": "integer", "default": 3},
        },
        "required": ["input_field"],
    }

    # 输出 schema
    output_schema = {
        "type": "object",
        "properties": {
            "result": {"type": "string"},
            "metadata": {"type": "object"},
        },
    }

    async def invoke(self, state: Dict[str, Any], config: Dict[str, Any]) -> Dict[str, Any]:
        """执行节点逻辑。

        Args:
            state: 当前工作流状态(包含前置节点的输出)
            config: 节点配置

        Returns:
            dict: 写入 state 的键值对
        """
        input_value = self.render_template(self.config["input_field"], state)

        # 业务逻辑
        result = await self.do_something(input_value)

        return {
            "result": result,
            "metadata": {"input_value": input_value},
        }

    async def do_something(self, value: str) -> str:
        # 实际工作
        return value.upper()
```

### 2.2 注册节点

**文件**:`backend/lumen_services/workflow_nodes/__init__.py`

```python
from lumen_services.workflow_nodes.my_node import MyNode

NODE_REGISTRY = {
    # ... 其他节点
    "my_node": MyNode,
}
```

### 2.3 写测试

**文件**:`backend/tests/unit/test_workflow_my_node.py`

```python
import pytest
from lumen_services.workflow_nodes.my_node import MyNode


@pytest.mark.asyncio
async def test_my_node_basic():
    node = MyNode(config={"input_field": "hello"})
    state = {}
    result = await node.invoke(state, node.config)
    assert result["result"] == "HELLO"


@pytest.mark.asyncio
async def test_my_node_template():
    """test that {{ ... }} 模板渲染"""
    node = MyNode(config={"input_field": "{{ user_input }}"})
    state = {"user_input": "world"}
    result = await node.invoke(state, node.config)
    assert result["result"] == "WORLD"


@pytest.mark.asyncio
async def test_my_node_retry_on_error():
    """test error_strategy + retry_config"""
    node = MyNode(
        config={"input_field": "boom"},
        error_strategy="retry",
        retry_config={"max_attempts": 3},
    )
    # mock 让它失败
    with pytest.raises(Exception):
        await node.invoke({}, node.config)
```

### 2.4 前端 Panel

**文件**:`frontend/components/workflow/nodes/MyNodePanel.tsx`

```tsx
"use client";
import React from "react";
import { Form, Input, InputNumber } from "antd";

interface Props {
  config: Record<string, any>;
  onChange: (config: Record<string, any>) => void;
}

export default function MyNodePanel({ config, onChange }: Props) {
  return (
    <Form layout="vertical">
      <Form.Item label="输入字段">
        <Input
          value={config.input_field || ""}
          onChange={(e) => onChange({ ...config, input_field: e.target.value })}
          placeholder="支持 {{ ... }} 模板"
        />
      </Form.Item>
      <Form.Item label="最大重试">
        <InputNumber
          value={config.max_retries || 3}
          onChange={(v) => onChange({ ...config, max_retries: v })}
          min={0}
          max={10}
        />
      </Form.Item>
    </Form>
  );
}
```

### 2.5 前端画布节点

**文件**:`frontend/components/workflow/nodes/MyNodeNode.tsx`

```tsx
"use client";
import React from "react";
import { Handle, Position, NodeProps } from "reactflow";

export default function MyNodeNode({ data, selected }: NodeProps) {
  return (
    <div className={`node my-node ${selected ? "selected" : ""}`}>
      <Handle type="target" position={Position.Top} />
      <div className="node-header">
        <span className="icon">🎯</span>
        <span className="title">My Node</span>
      </div>
      <div className="node-body">
        <code>{data.input_field || "(empty)"}</code>
      </div>
      <Handle type="source" position={Position.Bottom} />
    </div>
  );
}
```

### 2.6 注册到前端

**文件**:`frontend/components/workflow/registry.ts`

```ts
import MyNodePanel from "./nodes/MyNodePanel";
import MyNodeNode from "./nodes/MyNodeNode";

export const NODE_TYPES = {
  // ...
  my_node: {
    label: "My Node",
    icon: "🎯",
    category: "execution",
    Panel: MyNodePanel,
    Node: MyNodeNode,
    defaultConfig: { input_field: "", max_retries: 3 },
  },
};
```

### 2.7 集成测

```bash
# 跑后端测试
cd backend && pytest tests/unit/test_workflow_my_node.py -v

# 跑前端测试
cd frontend && npm run test:unit -- workflow-nodes

# 跑全套
cd backend && pytest
cd frontend && npm run test:unit
```

### 2.8 截图验证

```bash
# 启 dev
docker compose up -d
cd backend && uvicorn lumen_main:app --reload --port 11335
cd frontend && npm run dev

# 用 Playwright 截图
python backend/scripts/e2e_screenshot.py my_node
```

详见 [e2e-screenshots.md](e2e-screenshots.md)。

---

## 3. 节点规范

### 3.1 必须

- **`async def invoke(self, state, config) -> dict`**
- **config_schema / output_schema**
- **错误处理**:try/except → 设置 `error_strategy` 行为
- **写入 WorkflowNodeRun**:`self.record_run(...)`

### 3.2 最佳实践

- **别同步阻塞**:用 `async` 包装同步操作
- **限流**:外部 API 调用要限速
- **超时**:默认 30 秒,每个调用都设
- **单元测试**:`invoke` 必须有至少 1 个测试

### 3.3 严禁

- ❌ 不要 `print()` — 用 `logger`
- ❌ 不要 `try/except` 吞错 — 透传
- ❌ 不要同步阻塞 — `time.sleep(1)` 不行
- ❌ 不要写数据库不放进 transaction
- ❌ 不要把 LLM token 写进 node.inputs(可能被 LLMCallLog 重复存)

---

## 4. 节点类型示例

### 4.1 简单转换节点

```python
class StringUpperNode(BaseNode):
    node_type = "string_upper"

    async def invoke(self, state, config):
        return {"output": self.config["text"].upper()}
```

### 4.2 异步 HTTP 节点

```python
class HttpRequestNode(BaseNode):
    node_type = "http_request"

    async def invoke(self, state, config):
        url = self.render_template(config["url"], state)
        method = config.get("method", "GET").upper()
        headers = config.get("headers", {})
        body = config.get("body")

        timeout = config.get("timeout", 30)

        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as session:
            async with session.request(method, url, headers=headers, json=body) as resp:
                if resp.status >= 400:
                    raise NodeError(f"HTTP {resp.status}: {await resp.text()}")
                return {
                    "status": resp.status,
                    "body": await resp.json(),
                }
```

### 4.3 条件分支节点

```python
class ConditionNode(BaseNode):
    node_type = "condition"

    async def invoke(self, state, config):
        """Returns { branch: "true"|"false" } for downstream routing."""
        expr = self.config["expression"]
        result = self.eval_expression(expr, state)
        return {
            "branch": "true" if result else "false",
            "evaluated": result,
        }
```

### 4.4 长跑任务节点

```python
class LongRunningNode(BaseNode):
    node_type = "long_running"

    async def invoke(self, state, config):
        task_id = await self.submit_task(config)
        result = await self.poll_task(task_id, timeout=300)
        return {"result": result}
```

---

## 5. 调试

### 5.1 单元测试

```python
@pytest.mark.asyncio
async def test_my_node_with_state():
    node = MyNode(config={"input_field": "{{ foo }}"})
    state = {"foo": "bar"}
    result = await node.invoke(state, {})
    assert result["result"] == "BAR"
```

### 5.2 跑真实工作流

```bash
# 创建工作流
curl -X POST http://localhost:11335/api/v1/workflows \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"name":"test","nodes":[...]}'

# 跑
curl -X POST http://localhost:11335/api/v1/workflows/$ID/run \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"input": "hello"}'
```

### 5.3 看 trace

```bash
# 节点级
curl http://localhost:11335/api/v1/logs/llm-calls/trace/$TRACE_ID \
  -H "Authorization: Bearer $TOKEN"
```

---

## 6. 集成测试

**文件**:`backend/tests/integration/test_workflow_my_node.py`

```python
def test_my_node_in_workflow(client, headers):
    # 1. 创建工作流
    workflow = client.post("/api/v1/workflows", json={
        "name": "test_my_node",
        "nodes": [
            {"node_type": "input", "config": {"inputs": [{"name": "x", "type": "string"}]}},
            {"node_type": "my_node", "config": {"input_field": "{{ x }}"}},
            {"node_type": "output", "config": {"output_key": "result"}},
        ],
    }, headers=headers).json()["data"]

    # 2. 跑
    run = client.post(f"/api/v1/workflows/{workflow['id']}/run",
                      json={"x": "hello"}, headers=headers).json()["data"]

    # 3. 验证
    assert run["status"] == "success"
    assert run["outputs"]["result"] == "HELLO"
```

---

## 7. 文档

**更新**:
- `docs/modules/workflow-nodes.md` — 加 §"MyNode 节点"
- `docs/requirements/02-feature-list.md` — 加新功能行
- `docs/requirements/04-roadmap-milestones.md` — 加 milestone

---

## 8. PR 模板

```markdown
## 新工作流节点:MyNode

### 动机
业务需要 [具体场景]

### 实现
- 后端:`backend/lumen_services/workflow_nodes/my_node.py`
- 前端:`frontend/components/workflow/nodes/MyNode*.tsx`
- 测试:8 个后端 + 4 个前端

### 配置
- input_field(模板字符串)
- max_retries

### 输出
- result
- metadata.input_value

### 测试
- pytest: 8 passed
- vitest: 4 passed
- mypy: 0 errors
- tsc: 0 errors
```

---

## 9. 排错

| 症状 | 原因 | 修法 |
|------|------|------|
| 节点不显示在前端 | 没在 registry | 检查 `frontend/components/workflow/registry.ts` |
| 节点跑不起来 | 后端没注册 | 检查 `NODE_REGISTRY` |
| 模板 `{{ x }}` 不渲染 | `state` 没传 | 链前面的节点输出 |
| 节点 500 | 没 try/except | 改用 `error_strategy` |
| 异步任务卡住 | 没加 timeout | 加 `timeout_seconds` |
| 前端 Alert | 后端 registry 改了但前端没更新 | 同步 |
| LLMs 没有响应 | Prompt 里 token 太多 | 减少 input |

---

**相关文档**
- [workflow.md](../modules/workflow.md)
- [workflow-nodes.md](../modules/workflow-nodes.md) — 22 节点
- [workflow-execution.md](../explanation/workflow-execution.md) — 执行机制
- [错误处理与重试](../explanation/error-retry-timeout.md)
- [可观测性](../explanation/observability.md) — trace_id

**维护者**:全栈架构师
**最近更新**:2026-08-06
