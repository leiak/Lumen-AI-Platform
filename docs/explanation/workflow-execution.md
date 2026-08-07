# 工作流执行原理

> Lumen AI Platform 的可视化工作流是怎么跑起来的。
> 文档用 LangGraph 的 `StateGraph` 视角解释执行模型,适合工程师实现 / 排查工作流。

---

## 1. 工作流的本质

### 1.1 用户视角
工作流是**有向无环图(DAG)**:
- 节点(Vertex): 一个具体动作(LLM / HTTP / Code / KB 检索 / 条件分支 / 变量赋值 / ...)
- 边(Edge): 节点间的流向
- 状态(State): 跨节点共享的变量池

### 1.2 实现视角
工作流是**LangGraph `StateGraph` 实例**:
- 节点对应 `StateGraph.add_node(name, fn)`
- 边对应 `add_edge(from, to)` 或 `add_conditional_edges(from, condition_fn, path_map)`
- 状态对应 `StateGraph(state_schema=TypedDict)`

---

## 2. 数据模型

### 2.1 三张核心表
```sql
-- 工作流定义
CREATE TABLE workflows (
  id INT PRIMARY KEY,
  name VARCHAR(200),
  description TEXT,
  tenant_id INT,
  config JSON,                -- 工作流级配置
  created_at, updated_at
);

-- 工作流节点
CREATE TABLE workflow_nodes (
  id INT PRIMARY KEY,
  workflow_id INT,
  node_key VARCHAR(100),     -- 节点 ID (UUID)
  node_type VARCHAR(50),      -- "llm" / "code" / "http" / ...
  position_x, position_y,    -- 画布位置
  config JSON,                -- 节点配置
  error_strategy VARCHAR(20),
  retry_config JSON,
  timeout_seconds INT
);

-- 工作流边
CREATE TABLE workflow_edges (
  id INT PRIMARY KEY,
  workflow_id INT,
  source_node_key VARCHAR(100),
  target_node_key VARCHAR(100),
  source_handle VARCHAR(100), -- "true" / "false" / "case_1"
  condition TEXT
);

-- 每次运行
CREATE TABLE workflow_runs (
  id INT PRIMARY KEY,
  workflow_id INT,
  status VARCHAR(20),         -- running / success / failed / cancelled
  inputs JSON,
  outputs JSON,
  error TEXT,
  started_at, finished_at,
  trace_id VARCHAR(50)
);

-- 节点级 BFS 日志
CREATE TABLE workflow_node_runs (
  id INT PRIMARY KEY,
  run_id INT,
  node_key VARCHAR(100),
  status VARCHAR(20),         -- pending / running / success / failed / skipped
  inputs JSON,
  outputs JSON,
  error TEXT,
  started_at, finished_at,
  duration_ms INT,
  attempt INT                 -- 重试次数
);
```

### 2.2 文件
- 路由: `backend/lumen_api/v1/workflow.py`
- 服务: `backend/lumen_services/workflow_service.py`
- 执行器: `backend/lumen_services/workflow_executor.py`

---

## 3. 执行器

### 3.1 主流程
```python
async def run_workflow(workflow_id: int, inputs: dict) -> RunResult:
    # 1. 加载工作流定义
    workflow = load_workflow(workflow_id)
    nodes = load_nodes(workflow_id)
    edges = load_edges(workflow_id)

    # 2. 构造 LangGraph StateGraph
    graph = StateGraph(state_schema=WorkflowState)

    for node in nodes:
        graph.add_node(node.node_key, build_node_fn(node))

    for edge in edges:
        if edge.condition:
            graph.add_conditional_edges(
                edge.source_node_key,
                build_condition_fn(edge),
                path_map
            )
        else:
            graph.add_edge(edge.source_node_key, edge.target_node_key)

    # 3. 编译
    app = graph.compile()

    # 4. 创建 Run
    run = create_workflow_run(workflow_id, inputs)

    # 5. 执行
    try:
        final_state = await app.ainvoke({"inputs": inputs, ...})
        run.status = "success"
        run.outputs = final_state.get("outputs", {})
    except Exception as e:
        run.status = "failed"
        run.error = str(e)
    finally:
        run.finished_at = now()
        save_run(run)
```

### 3.2 节点函数
每个节点类型映射到 Python 函数:
```python
def build_node_fn(node: WorkflowNode) -> Callable:
    if node.node_type == "llm":
        return build_llm_node(node)
    elif node.node_type == "code":
        return build_code_node(node)
    elif node.node_type == "http":
        return build_http_node(node)
    # ...
    else:
        raise ValueError(f"Unknown node type: {node.node_type}")
```

每个节点函数:
- 输入: `state: WorkflowState`
- 输出: `dict` (更新 state 的字段)
- 抛异常: 触发 error_strategy

---

## 4. 状态传递

### 4.1 WorkflowState
```python
class WorkflowState(TypedDict, total=False):
    inputs: dict           # 工作流输入
    variables: dict        # 用户定义的变量
    node_outputs: dict     # 节点 key → 输出
    final_outputs: dict    # 最终输出
    error: Optional[str]
```

### 4.2 变量引用
- LLM prompt 里 `{{variables.user_name}}` → 渲染时替换
- 解析: `extract_vars(template) → [user_name, ...]` → 查 `state.variables`
- 未定义 → 抛错

### 4.3 节点输出
- 每个节点输出存到 `state.node_outputs[node_key]`
- 下游节点用 `{{node_outputs.<key>.<field>}}` 引用

---

## 5. 22 节点类型

| 节点 | 类型 | 用途 |
|------|------|------|
| Input | `input` | 工作流入口 |
| Output | `output` | 工作流出口 |
| LLM | `llm` | 调 LLM |
| Agent | `agent` | 调 Agent(带工具循环) |
| Code | `code` | 跑 Python 代码 |
| HTTP | `http` | 发 HTTP 请求 |
| Tool | `tool` | 调注册的 Tool |
| Knowledge Retrieval | `knowledge_retrieval` | 知识库 RAG |
| Template Transform | `template_transform` | Jinja2 模板 |
| Parameter Extractor | `parameter_extractor` | LLM 提取结构化参数 |
| Question Classifier | `question_classifier` | LLM 分类 |
| Variable Assigner | `variable_assigner` | 赋值给变量 |
| Variable Aggregator | `variable_aggregator` | 合并多个分支的变量 |
| Condition | `condition` | if-else 分支 |
| Parallel | `parallel` | 真并行 |
| Fan Out | `fan_out` | 列表展开 |
| Fan In | `fan_in` | 列表聚合 |

详见 [modules/workflow-nodes.md](../modules/workflow-nodes.md) 每个节点的 spec。

---

## 6. 错误处理基础设施

### 6.1 节点级配置
- `error_strategy`: `fail_fast` (默认) / `ignore` / `fallback`
- `retry_config`: `{ max_attempts: 3, backoff: "exponential" }`
- `timeout_seconds`: 30 (默认)

### 6.2 执行流程
```
节点开始
  │
  ▼
try:
  start_node_run(node_key, attempt=1)
  output = await asyncio.wait_for(run_node(state), timeout=timeout_seconds)
  finish_node_run(status=success, outputs=output)
  │
  ▼
except TimeoutError:
  if attempt < max_attempts:
    sleep(backoff(attempt))
    recurse(attempt + 1)
  else:
    if error_strategy == "ignore":
      finish_node_run(status=skipped)
    elif error_strategy == "fallback":
      use_fallback_output()
    else:  # fail_fast
      raise
  │
  ▼
except Exception as e:
  if attempt < max_attempts:
    recurse(attempt + 1)
  else:
    if error_strategy == "ignore":
      finish_node_run(status=skipped)
    else:
      raise
```

详见 [explanation/error-retry-timeout.md](error-retry-timeout.md)。

---

## 7. 真并行

### 7.1 Parallel 节点
- 类型: `parallel`
- 配置: N 个子节点
- 执行:用 `asyncio.gather` 跑全部子节点,等齐再继续
- 输出: dict[子节点 key, 输出]

### 7.2 LangGraph 实现
- `StateGraph` 内置并行(用 asyncio)
- 多个 `add_edge(from, [to1, to2])` → 同步等待

### 7.3 性能
- 串行 4 个 LLM 节点: 4 × 2 秒 = 8 秒
- 并行 4 个 LLM 节点: max(2 秒) = 2 秒
- 加速比 ≈ 4×

---

## 8. 断点续跑(Resume)

### 8.1 场景
- 工作流跑到一半,服务挂了 / 用户取消
- 重新启动 → 不重跑已成功的节点

### 8.2 实现
- 每个节点 `node_runs` 表记 `status`
- 重启时:跳过 `status=success` 的节点,从 `pending` / `failed` 继续
- 输入:从 `node_outputs` 读

### 8.3 代码
```python
async def resume_run(run_id: int):
    run = load_run(run_id)
    completed = load_completed_node_runs(run_id)
    state = reconstruct_state(run, completed)
    return await execute_remaining(graph, state, run)
```

---

## 9. 触发方式

### 9.1 手动触发
- API: `POST /api/v1/workflows/{id}/run`
- 立即跑

### 9.2 定时触发
- 表: `workflow_schedules`
- 字段: `cron` / `interval_seconds` / `enabled`
- Celery beat 调度

### 9.3 事件触发
- 当前:无(暂未实现)
- 计划:WebHook / 邮件触发

---

## 10. 监控

### 10.1 实时状态
- 前端: `frontend/components/workflow/designer/RunResultPanel.tsx`
- 轮询: `GET /api/v1/workflow-runs/{id}/status`
- WS 推送:节点完成时

### 10.2 历史
- 前端: `frontend/components/workflow/RunHistoryDrawer.tsx`
- 列表 + 详情

### 10.3 节点级 BFS 日志
- 表: `workflow_node_runs`
- 字段: `inputs` / `outputs` / `error` / `duration_ms` / `attempt`
- 前端: `frontend/components/workflow/RunDetailDrawer.tsx`

---

## 11. 模板市场

### 11.1 发布
- API: `POST /api/v1/workflow-templates`
- 表: `workflow_templates`
- 状态: `draft` / `published` / `archived`

### 11.2 安装
- API: `POST /api/v1/workflow-templates/{id}/install`
- 行为:复制 workflow + nodes + edges 到当前租户
- 引用:全局资源(模型 / 工具)按名字解析

### 11.3 平台 vs 租户
- 平台模板: `tenant_id IS NULL`(系统预置)
- 租户模板: `tenant_id = current_tenant`(用户发布)

---

## 12. 升级路径

### 短期
- 📋 WebHook 触发
- 📋 事件订阅(节点完成事件)

### 中期
- 📋 子工作流(嵌套)
- 📋 工作流版本管理

### 长期
- 📋 AI 自动优化(自动选 LLM 参数)
- 📋 工作流单元测试

---

## 13. 排错

| 症状 | 原因 | 修法 |
|------|------|------|
| 工作流跑不起来 | 节点配置缺失 | 看 error message,补配置 |
| 节点一直 pending | LangGraph 编译失败 | 查后端日志 |
| 节点 timeout | LLM 慢 / HTTP 慢 | 调 timeout_seconds 或选小模型 |
| 变量没渲染 | `{{...}}` 拼写错 | 看 Run 详情里"原始 prompt" |
| 边没走 | 条件 fn 返回错 | 调试 condition fn |
| 并行不并行 | 没真用 Parallel 节点 | 改用 Parallel 节点 |

---

**维护者**:全栈架构师
**最近更新**:2026-08-06
