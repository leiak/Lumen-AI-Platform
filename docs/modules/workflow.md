# 模块:可视化工作流

> Lumen AI Platform 的可视化工作流编排系统。
> 文档讲透工作流能做什么、22 节点怎么用、怎么跑、怎么监控。

---

## 1. 产品定位

**工作流是什么?**
- 把多个"动作"按顺序 / 分支 / 并行串起来,实现复杂业务
- 例:"客户提问 → 自动分类 → 查订单 → 生成回复 → 通知销售"
- 不用写代码,拖拽节点 + 连线

**和"ChatGPT + Tools"比有什么不同?**
- 工作流是**显式编排**,LLM 不会"自己选"
- 适合"流程固定"的业务
- 适合"需要审计"的业务(每个节点都留痕)
- 适合"高并发"业务(真并行 + 异步)

---

## 2. 功能清单

| 功能 | 描述 |
|------|------|
| 可视化设计器 | React Flow 拖拽 + 连线 |
| 22 节点类型 | LLM / Code / HTTP / Tool / KB / ... |
| DAG 执行 | LangGraph 编排 |
| 真并行 | Parallel 节点 |
| 错误处理 | error_strategy + retry + timeout |
| undo/redo | M30 ship |
| auto-layout | 自动布局 |
| 断点续跑 | resume |
| 定时触发 | cron schedule |
| 模板市场 | publish + install |
| 实时监控 | 节点级 BFS 日志 |

---

## 3. 数据模型

### 3.1 workflows(定义)
```python
class Workflow(Base):
    id: int
    name: str
    description: str
    config: dict                    # 工作流级配置
    is_active: bool
    tenant_id: int
```

### 3.2 workflow_nodes(节点)
```python
class WorkflowNode(Base):
    id: int
    workflow_id: int
    node_key: str                   # 节点 ID (UUID)
    node_type: str                  # llm / code / http / ...
    position_x: float
    position_y: float
    config: dict                    # 节点配置
    error_strategy: str
    retry_config: dict
    timeout_seconds: int
```

### 3.3 workflow_edges(边)
```python
class WorkflowEdge(Base):
    id: int
    workflow_id: int
    source_node_key: str
    target_node_key: str
    source_handle: str              # 区分 case 边
    condition: str
```

### 3.4 workflow_runs(运行)
```python
class WorkflowRun(Base):
    id: int
    workflow_id: int
    status: str                     # running / success / failed / cancelled
    inputs: dict
    outputs: dict
    error: str
    trace_id: str
    started_at, finished_at
```

### 3.5 workflow_node_runs(节点级日志)
```python
class WorkflowNodeRun(Base):
    id: int
    run_id: int
    node_key: str
    status: str                     # pending / running / success / failed / skipped
    attempt: int
    inputs: dict
    outputs: dict
    error: str
    duration_ms: int
```

### 3.6 文件
- ORM: `backend/lumen_models/workflow.py`
- Schema: `backend/lumen_schemas/workflow.py`
- 服务: `backend/lumen_services/workflow_service.py`
- 执行器: `backend/lumen_services/workflow_executor.py`
- 路由: `backend/lumen_api/v1/workflow.py`

---

## 4. 22 节点类型

详见 [workflow-nodes.md](workflow-nodes.md)。简表:

| 类别 | 节点 |
|------|------|
| **基础** | Input / Output / Condition / Parallel / Fan Out / Fan In |
| **AI** | LLM / Agent |
| **数据** | Knowledge Retrieval / Variable Assigner / Variable Aggregator |
| **执行** | Code / HTTP / Tool |
| **辅助** | Template Transform / Parameter Extractor / Question Classifier |

---

## 5. UI

### 5.1 列表
- 路径: `frontend/app/dashboard/workflow/page.tsx`
- 表格:名字 / 描述 / 创建时间 / 状态 / 操作
- 操作:设计 / 跑 / 复制 / 删 / 发布模板

### 5.2 设计器
- 路径: `frontend/app/dashboard/workflow/designer/page.tsx`
- 画布:React Flow(`@xyflow/react`)
- 左侧:节点面板(22 节点分类)
- 右侧:选中节点 → 属性面板
- 顶部:保存 / 调试 / 撤销 / 重做 / 自动布局
- 底部:运行结果

### 5.3 Run 详情
- 文件: `frontend/components/workflow/RunDetailDrawer.tsx`
- 节点按 BFS 顺序展示
- 每个节点:状态 / 耗时 / attempt / 输入输出

### 5.4 模板中心
- 路径: `frontend/app/dashboard/workflow/templates/page.tsx`
- 平台预置 + 租户发布
- 一键套用

---

## 6. 关键能力详解

### 6.1 可视化设计
- 拖拽节点到画布
- 拖节点边缘连线
- 双击节点配置
- 右键节点 → 删 / 复制 / 设错误策略

### 6.2 变量引用
- LLM prompt 用 `{{variables.user_name}}` 引用
- 节点输出用 `{{node_outputs.<key>.<field>}}` 引用
- 解析器扫可用变量(从 inputs + 已完成节点)
- UI: `VarReferencePicker` 让用户选

### 6.3 错误处理基础设施
详见 [explanation/error-retry-timeout.md](../explanation/error-retry-timeout.md)。

### 6.4 undo/redo
- M30 ship
- 栈:操作历史数组
- 快捷键:Ctrl+Z / Ctrl+Shift+Z

### 6.5 auto-layout
- M30 ship
- dagre / elk 算法
- 一键整理节点位置

### 6.6 真并行
- Parallel 节点 + N 子节点
- `asyncio.gather` 跑
- 加速 4×(典型)

### 6.7 断点续跑(resume)
- 节点 BFS 落库
- 重启时跳过 success 节点
- 从 pending/failed 继续

### 6.8 定时触发
- 表: `workflow_schedules`
- Celery beat 调度
- cron 表达式

### 6.9 模板市场
- 发布: `workflow_templates` 表
- 安装: 复制到当前租户
- 全局 vs 租户:`tenant_id IS NULL` vs `tenant_id = N`

---

## 7. 执行流程

```
用户点"运行"
   │
   ▼
POST /workflows/{id}/run
   │
   ▼
1. 加载 workflow + nodes + edges
2. 构造 LangGraph StateGraph
3. 编译 graph
4. 创建 workflow_runs 行
5. 异步执行:
   for node in BFS:
     start_node_run
     try:
       output = await asyncio.wait_for(invoke_node(state), timeout)
       finish_node_run(success, output)
       state.node_outputs[key] = output
     except:
       按 error_strategy + retry_config 处理
6. 更新 workflow_runs.status
7. WS 推通知
8. 返回 run_id
```

### 7.1 关键代码
```python
# backend/lumen_services/workflow_executor.py
async def run_workflow(workflow_id: int, inputs: dict, current_user: User) -> WorkflowRun:
    workflow = load_workflow(workflow_id)
    graph = build_graph(workflow)
    app = graph.compile()

    run = create_run(workflow_id, inputs, current_user)

    try:
        final_state = await app.ainvoke({"inputs": inputs, "variables": {}, "node_outputs": {}})
        run.status = "success"
        run.outputs = final_state.get("final_outputs", {})
    except Exception as e:
        run.status = "failed"
        run.error = str(e)
    finally:
        run.finished_at = now()
        save_run(run)

    return run
```

---

## 8. 监控

### 8.1 实时状态
- 节点 BFS 落库
- 前端轮询 `GET /workflow-runs/{id}`
- 或 WS 推送

### 8.2 节点级日志
- 字段: `inputs` / `outputs` / `error` / `duration_ms` / `attempt`
- 前端: `RunDetailDrawer`

### 8.3 Trace 串联
- 每次 Run 生成 `trace_id`
- LLMCallLog 关联 trace
- 查 `/dashboard/logs/trace/[trace_id]` 看全链路

---

## 9. 边界与不做

### 9.1 当前
- ✅ 22 节点
- ✅ DAG 执行
- ✅ 并行 / 续跑
- ✅ undo/redo / auto-layout
- ✅ 错误 / 重试 / 超时
- ✅ 模板市场

### 9.2 不做
- ❌ 循环图(目前严格 DAG)
- ❌ 人工审批节点(计划中)
- ❌ 事件触发(目前手动 + 定时)
- ❌ 子工作流嵌套(计划中)

---

## 10. 升级路径

### 短期
- 📋 人工审批节点
- 📋 WebHook 触发
- 📋 工作流版本管理

### 中期
- 📋 子工作流
- 📋 循环图
- 📋 A/B 测试

### 长期
- 📋 AI 自动优化
- 📋 联邦工作流(跨租户)

---

## 11. 排错

| 症状 | 原因 | 修法 |
|------|------|------|
| 工作流跑不起来 | 节点配置缺失 | 看 error message |
| 节点一直 pending | LangGraph 编译失败 | 查后端日志 |
| 节点 timeout | LLM 慢 / HTTP 慢 | 调 timeout |
| 变量没渲染 | `{{...}}` 拼写错 | 看 Run 详情 |
| 边没走 | 条件 fn 返回错 | 调试 condition |
| 并行不并行 | 没用 Parallel 节点 | 改 Parallel |
| 续跑不续 | run 状态已 finished | 新建 run |

详见 [explanation/workflow-execution.md](../explanation/workflow-execution.md) 和 [troubleshooting/common-errors.md](../troubleshooting/common-errors.md)。

---

**维护者**:全栈架构师
**最近更新**:2026-08-06
