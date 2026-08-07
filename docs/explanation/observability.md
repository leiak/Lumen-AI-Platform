# 可观测性(Observability)

> Lumen AI Platform 的 LLM 调用级可观测性设计。
> 文档说明 trace_id 怎么串联、LLMCallLog 怎么写、5 模块插桩怎么做。

---

## 1. 目标

Lumen 作为 AI 应用平台,需要回答 3 个问题:

1. **"AI 现在在干什么"** — 实时状态(WS 推送)
2. **"AI 刚才为什么答错"** — 调用日志(LLMCallLog + trace)
3. **"AI 跑得慢在哪"** — 性能分析(节点级耗时)

---

## 2. 三大核心机制

### 2.1 trace_id 串联
- **生成**:每次 HTTP 请求 / 工作流 Run / Celery 任务生成 `trace_id`(UUID 短)
- **透传**:
  - HTTP 中间件:`X-Trace-Id` header
  - Celery 任务:task 参数
  - LLM 调用:`LoggingChatModel.metadata`
- **存储**:所有相关日志 / 库表带 `trace_id` 字段

### 2.2 LLMCallLog
- 表: `llm_call_logs`
- 每次 LLM 调用一行
- 字段: `model` / `prompt` / `response` / `tokens` / `duration_ms` / `trace_id` / `tenant_id` / `user_id`
- 写入: `LoggingChatModel` 包装自动写

### 2.3 WorkflowNodeRun BFS 落库
- 详见 [explanation/workflow-execution.md § 10.3](workflow-execution.md)
- 工作流每个节点独立记录,parent run 串联

---

## 3. 5 模块插桩

`LoggingChatModel` 包装 5 个 LLM 调用入口:

### 3.1 1. Agent 对话
- 路径: `lumen_services/agent_service.py::chat`
- 包装点: `await ChatOpenAI(...).ainvoke(messages)`
- 记录:`module="agent"`, `agent_id`, `conversation_id`

### 3.2 2. Chat 流式
- 路径: `lumen_services/chat_service.py::stream`
- 包装点: `ChatOpenAI(...).astream(messages)`
- 记录:`module="chat"`, `conversation_id`, `is_streaming=True`

### 3.3 3. 工作流 LLM 节点
- 路径: `lumen_services/workflow_executor.py::build_llm_node`
- 包装点: 节点函数内 LLM 调用
- 记录:`module="workflow"`, `run_id`, `node_key`

### 3.4 4. 工作流 Agent 节点
- 路径: 同上,Agent 节点
- 包装点: AgentExecutor.ainvoke
- 记录:`module="workflow"`, `run_id`, `node_key`, `agent_id`

### 3.5 5. 评测 Runner
- 路径: `lumen_services/eval_runner.py::run_item`
- 包装点: 评测 LLM 调用
- 记录:`module="eval"`, `eval_run_id`, `dataset_item_id`

---

## 4. LoggingChatModel 实现

### 4.1 包装模式
```python
# lumen_core/observability.py
class LoggingChatModel(BaseChatModel):
    inner: BaseChatModel
    module: str
    user_id: int
    tenant_id: int
    trace_id: str

    async def _agenerate(self, messages, stop=None, **kwargs):
        start = time.time()
        try:
            # 自动加 trace_id 到 metadata
            metadata = {"trace_id": self.trace_id, "module": self.module, **(kwargs.get("metadata") or {})}
            result = await self.inner._agenerate(messages, stop=stop, **{**kwargs, "metadata": metadata})
            self._log(messages, result, time.time() - start, success=True)
            return result
        except Exception as e:
            self._log(messages, None, time.time() - start, success=False, error=str(e))
            raise

    def _log(self, messages, result, duration, success, error=None):
        # 写 llm_call_logs
        llm_log = LLMCallLog(
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            trace_id=self.trace_id,
            module=self.module,
            model=self.inner.model_name,
            prompt=json.dumps(messages, ensure_ascii=False),
            response=result.content if result else None,
            prompt_tokens=result.usage.prompt_tokens if result and result.usage else None,
            completion_tokens=result.usage.completion_tokens if result and result.usage else None,
            duration_ms=int(duration * 1000),
            success=success,
            error=error,
        )
        save(llm_log)
```

### 4.2 工厂
```python
def wrap_chat_model(inner: BaseChatModel, *, module: str, user_id: int, tenant_id: int, trace_id: str) -> BaseChatModel:
    return LoggingChatModel(inner=inner, module=module, user_id=user_id, tenant_id=tenant_id, trace_id=trace_id)
```

### 4.3 调用方
```python
# lumen_services/agent_service.py
from lumen_core.observability import wrap_chat_model

async def chat(agent: Agent, messages, current_user):
    inner = build_chat_model(agent.model_config)
    model = wrap_chat_model(
        inner,
        module="agent",
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
        trace_id=get_trace_id(),
    )
    return await model.ainvoke(messages)
```

---

## 5. trace_id 中间件

### 5.1 HTTP 中间件
```python
# lumen_core/middleware/trace_id.py
@app.middleware("http")
async def trace_id_middleware(request, call_next):
    trace_id = request.headers.get("X-Trace-Id") or generate_short_uuid()
    set_trace_id(trace_id)
    response = await call_next(request)
    response.headers["X-Trace-Id"] = trace_id
    return response
```

### 5.2 ContextVar
```python
# lumen_core/trace_id.py
_trace_id: ContextVar[str] = ContextVar("trace_id", default="")

def set_trace_id(trace_id: str):
    _trace_id.set(trace_id)

def get_trace_id() -> str:
    return _trace_id.get()
```

### 5.3 跨异步
- `ContextVar` 在 asyncio task 间正确传递
- Celery 任务需要手动 set(worker 进程内)

---

## 6. 日志审计 UI

### 6.1 列表
- 路径: `frontend/app/dashboard/logs/page.tsx`
- API: `GET /api/v1/llm-call-logs?trace_id=&module=&user_id=&page=1`
- 字段:时间 / 模块 / 模型 / 耗时 / tokens / 状态

### 6.2 详情
- 路径: `frontend/app/dashboard/logs/llm-call-detail.tsx`
- 显示: 完整 prompt / 完整 response / 错误信息 / trace_id

### 6.3 Trace 视图
- 路径: `frontend/app/dashboard/logs/trace/[trace_id]/page.tsx`
- 显示:同一 trace 的所有 LLM call
- 串联: 按时间排序,看从用户消息到最终响应的全链路

---

## 7. 工作流可观测性

### 7.1 Run 详情
- API: `GET /api/v1/workflow-runs/{id}`
- 字段:`status` / `inputs` / `outputs` / `error` / `node_runs[]`

### 7.2 节点级 BFS
- 节点按执行顺序(BFS)展示
- 每个节点: `status` / `inputs` / `outputs` / `duration_ms` / `error` / `attempt`

### 7.3 实时推送
- WS 推送节点状态变更
- 前端 `RunResultPanel` 自动更新

---

## 8. RAG 评测可观测性(M37)

### 8.1 Eval Run 看板
- 路径: `frontend/app/dashboard/eval/page.tsx`
- 显示: Run 历史 / 趋势 / 报告

### 8.2 指标
- 召回率(@1, @3, @5)
- 答案相关性(LLM 评分)
- 答案忠实度(LLM 评分)
- 响应延迟

### 8.3 对比
- 多 Run 对比
- 趋势图(每次 Run 关键指标)

详见 [modules/rag-evaluation.md](../modules/rag-evaluation.md)。

---

## 9. 通知中心集成

### 9.1 关键事件
- LLM 调用失败 → 通知"AI 调用失败"
- 工作流 Run 完成 → 通知"工作流 X 已完成"
- 文档解析完成 → 通知"文档 X 已就绪"
- 评测 Run 完成 → 通知"评测已完成"

### 9.2 通知方式
- WS 实时推送到前端
- 邮件(可选)
- 桌面端托盘(Electron)

详见 [modules/notification.md](../modules/notification.md)。

---

## 10. 关键指标

### 10.1 业务指标
- DAU / WAU
- 每日 LLM 调用次数
- 知识库平均 size
- 工作流平均 Run 时长

### 10.2 技术指标
- LLM 调用 P50 / P95 / P99 延迟
- LLM 调用失败率
- Token 消耗(每租户每日)
- 检索召回率
- 检索延迟

### 10.3 业务指标收集
- 当前:不专门收集
- 计划: 用 `events` 表 + 定时聚合

---

## 11. 告警

### 11.1 当前
- 应用错误日志
- 通知中心主动推送

### 11.2 计划
- 异常 LLM 调用率(>10%)→ 邮件告警
- 单租户 Token 异常消耗 → 告警
- 知识库解析失败率 > 5% → 告警

---

## 12. 升级路径

### 短期
- 📋 OpenTelemetry SDK 集成
- 📋 Prometheus exporter
- 📋 Grafana 模板

### 中期
- 📋 业务指标收集
- 📋 异常检测 + 告警

### 长期
- 📋 AI 自我调优(自动调温度 / top_p)
- 📋 调用预测 + 资源预分配

---

**维护者**:全栈架构师
**最近更新**:2026-08-06
