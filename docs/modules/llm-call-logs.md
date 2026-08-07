# 模块:LLM / Embedding 调用日志(M26 + M27)

> 平台每个 LLM / Embedding 调用都留一行日志,加 trace_id 串起来。
> 文档讲透这两张表怎么写、怎么查、怎么保留、怎么排错。

---

## 1. 产品定位

**LLM / Embedding 调用日志是什么?**

- 每次 LLM / Embedding 调用都持久化到 DB,**完整保留入参和出参**
- 一次请求里的所有调用共享一个 `trace_id`,可串成链路
- 用于:**事后分析**(为什么回答错了)+ **性能监控**(哪步慢)+ **费用审计**(哪个模型最贵)

**为什么每条都存?**

- LLM 的"行为"是不可预测的 —— 同样的 prompt 可能产出不同结果
- 用户报"答错了"时,**只能基于当时实际发了什么**去还原现场
- 现场就在 `messages` / `response_content` / `tool_calls` 这种 JSON 字段里

**和"普通日志"区别?**

| 维度 | 应用日志 | LLM 调用日志 |
|------|---------|--------------|
| 格式 | 文本行 | JSON 字段 |
| 关注点 | "程序做了什么" | "模型收到什么、回什么" |
| 查询 | grep / kibana | DB 表 + 复合索引 |
| 保留 | 几天 | 90 天 + 永久存档 |
| 脱敏 | 可选 | 强制(用户输入都进 text 字段) |

---

## 2. 功能清单

| 功能 | 描述 |
|------|------|
| 自动记录 | 每次 LLM / Embedding 调用都自动写一行 |
| Trace 串联 | 一次请求里所有调用共享 `trace_id` |
| 全量入参 | `messages` / `tools` / `system_messages` 完整存 |
| 全量出参 | `response_content` / `tool_calls` / `token_usage` 完整存 |
| 时延分解 | `first_token_latency_ms` + `duration_ms` |
| 失败追踪 | `status` / `error_type` / `error_message` / `retry_count` |
| 上下文关联 | `conversation_id` / `agent_id` / `team_id` / `workflow_run_id` / `image_id` |
| 统计聚合 | `GET /logs/llm-calls/stats` 实时聚合 |
| 保留策略 | 默认 90 天软删 + 180 天硬删 |
| 归档 | `archived_at` 标记,可恢复 |

---

## 3. 数据模型

### 3.1 `llm_call_logs`(M26)

| 字段组 | 字段 | 说明 |
|--------|------|------|
| 身份 | `call_id` (UUID) | 唯一 |
| 身份 | `parent_call_id` | 工具调用时链回主调用 |
| 身份 | `trace_id` | 一次请求所有调用共享 |
| 身份 | `call_type` | chat / agent_team / workflow.llm / image_generation / eval_judge |
| 身份 | `call_index` | trace 内序号 |
| 触发者 | `tenant_id` / `user_id` / `username` / `client_app` | |
| 关联 | `conversation_id` / `message_id` / `agent_id` / `team_id` / `team_member_id` / `workflow_id` / `workflow_run_id` / `workflow_node_id` / `image_id` | 可空 |
| 模型 | `model_type` / `model_name` / `model_config_id` / `temperature` / `max_tokens` | |
| 入参 | `system_messages` / `user_message` / `messages` / `tools` / `extra_params` / `input_chars` / `input_tokens_estimate` | JSON |
| 出参 | `response_content` / `finish_reason` / `tool_calls` / `output_chars` / `output_tokens_estimate` | JSON |
| 用量 | `token_usage` (JSON: prompt_tokens / completion_tokens / total_tokens) | |
| 时延 | `started_at` / `finished_at` / `duration_ms` / `first_token_latency_ms` | |
| 状态 | `status` / `error_type` / `error_message` / `retry_count` | |
| 元数据 | `request_ip` / `user_agent` / `extra` | |
| 保留 | `archived_at` | M27 retention |

**复合索引**:
- `(tenant_id, created_at)` — 多租户列表
- `(call_type, created_at)` — 按模块聚合
- `(model_name, created_at)` — 按模型聚合
- `(conversation_id, created_at)` — 查对话的 LLM 历史
- `(trace_id, call_index)` — 一次 trace 的所有调用
- `(status, created_at)` — 失败监控

### 3.2 `embedding_call_logs`(M27)

结构类似,字段简化:

| 字段组 | 字段 | 说明 |
|--------|------|------|
| 身份 | `call_id` / `parent_call_id` / `trace_id` / `call_type` / `call_index` | |
| 触发者 | `tenant_id` / `user_id` / `username` / `client_app` | |
| 关联 | `conversation_id` / `agent_id` / `team_id` / `workflow_id` / `workflow_run_id` / `workflow_node_id` / `knowledge_base_id` | |
| 模型 | `model_type` / `model_name` / `model_config_id` | |
| 入参 | `text_preview` (200 字符) / `text_chars` / `is_batch` / `batch_size` | **不存完整文本** |
| 出参 | `embedding_dim` / `embedding_bytes` | **不存向量** |
| 时延 | `started_at` / `finished_at` / `duration_ms` | |
| 状态 | `status` / `error_type` / `error_message` / `retry_count` | |
| 保留 | `archived_at` | |

**为什么不存向量**:1 行 768 维 float32 = 3KB。百万行 = 3GB,纯浪费。`embedding_dim` + `embedding_bytes` 够 audit 用。

**为什么不存完整文本**:可能是用户上传的整个文档,体积大。

### 3.3 call_type 枚举

| call_type | 触发模块 |
|-----------|---------|
| `chat` | 普通 chat / widget chat stream |
| `agent_team` | AgentTeam manager_decision / member reply |
| `workflow.llm` | Workflow LLM 节点 |
| `workflow.classifier` | Workflow Question Classifier 节点 |
| `workflow.extractor` | Workflow Parameter Extractor 节点 |
| `image_generation` | M22 图像生成 prompt |
| `eval_judge` | M37.2 RAG 评测 judge(extra 里有 eval_run_id / eval_metric) |

**embedding call_type**:
| call_type | 触发模块 |
|-----------|---------|
| `kb_retrieval` | chat / widget / agent_team / workflow embed 用作检索 |
| `kb_ingest` | reindex / document upload embed_documents |
| `dim_probe` | factory cold-start probe(text == "dim-probe") |
| `workflow_kb` | workflow knowledge_retrieval 节点 |
| `system.kb_ingest` | background reindex(无 current_user) |
| `eval_retrieval` | M37.2 RAG 评测每次 item 的检索(extra 里有 eval_run_id) |

### 3.4 文件清单

| 层 | 路径 |
|----|------|
| ORM | `backend/lumen_models/llm_call_log.py` |
| ORM | `backend/lumen_models/embedding_call_log.py` |
| 服务 | `backend/lumen_services/llm_call_logging.py` |
| 服务 | `backend/lumen_services/embedding_logging.py` |
| 路由 | `backend/lumen_api/v1/logs.py` |
| 保留 | `backend/lumen_services/retention.py` + `retention_scheduler.py` |
| 前端 | `frontend/app/dashboard/logs/` |

---

## 4. 核心流程

### 4.1 写入路径

```python
# backend/lumen_services/llm_call_logging.py

class LLMCallLogger:
    """Per-call context manager. Records one row per call."""

    def __init__(self, *, call_type: str, model_config_id: int | None,
                 trace_id: str, parent_call_id: str | None = None):
        self.call_id = str(uuid.uuid4())
        self.call_type = call_type
        self.trace_id = trace_id
        self.parent_call_id = parent_call_id
        self.started_at = datetime.utcnow()
        self._extra = {}

    def __enter__(self):
        return self

    async def __aenter__(self):
        return self

    def record_request(self, **kwargs):
        """Snapshot of request payload (before call)."""
        self._messages = kwargs.get("messages")
        self._tools = kwargs.get("tools")
        self._temperature = kwargs.get("temperature")
        ...

    def record_response(self, **kwargs):
        """Snapshot of response (after call)."""
        self._response_content = kwargs.get("response_content")
        self._token_usage = kwargs.get("token_usage")
        self._first_token_latency_ms = ...
        self._status = "success"

    def record_error(self, exc: Exception):
        self._status = "error"
        self._error_type = type(exc).__name__
        self._error_message = str(exc)[:500]

    def __exit__(self, *args):
        self._flush()

    def _flush(self):
        row = LLMCallLog(
            call_id=self.call_id,
            trace_id=self.trace_id,
            parent_call_id=self.parent_call_id,
            call_type=self.call_type,
            ...,
        )
        db.add(row)
        db.commit()
```

### 4.2 trace_id 传播

```python
# backend/lumen_core/tracing.py (M27)
from contextvars import ContextVar

_current_trace_id: ContextVar[str | None] = ContextVar("trace_id", default=None)

def get_trace_id() -> str:
    """Return the current trace_id, creating one if absent."""
    tid = _current_trace_id.get()
    if tid is None:
        tid = str(uuid.uuid4())
        _current_trace_id.set(tid)
    return tid

def set_trace_id(tid: str) -> None:
    _current_trace_id.set(tid)
```

**使用**:
```python
# API 入口
@app.middleware("http")
async def trace_middleware(request, call_next):
    tid = request.headers.get("X-Trace-Id") or str(uuid.uuid4())
    set_trace_id(tid)
    response = await call_next(request)
    response.headers["X-Trace-Id"] = tid
    return response

# 业务模块
def chat(...):
    tid = get_trace_id()  # ← middleware 已设
    with LLMCallLogger(call_type="chat", trace_id=tid, ...) as log:
        log.record_request(...)
        response = await call_llm(...)
        log.record_response(response)
```

**结果**:
- 一次 chat 请求 → 3 行 LLMCallLog(主调用 + 2 轮工具调用),共享 trace_id
- `GET /logs/llm-calls/trace/{trace_id}` 拉全链路

### 4.3 工具调用时的 parent_call_id

```python
# LLM 返回 tool_calls 后,工具里的 LLM 调用
def handle_tool_call(tool_call, parent_call_id):
    with LLMCallLogger(
        call_type="chat",
        parent_call_id=parent_call_id,  # ← 链回主调用
        trace_id=get_trace_id(),
    ) as log:
        ...
```

**前端**:`/logs/llm-calls/{call_id}` 详情会显示 "父调用" 链接。

---

## 5. 查询 API

### 5.1 列表

```
GET /api/v1/logs/llm-calls?page=1&page_size=20&status=error&model_name=qwen2.5
```

| 参数 | 说明 |
|------|------|
| `page` / `page_size` | 分页 |
| `tenant_id` | 多租户过滤(管理员可看) |
| `user_id` | 按用户 |
| `call_type` | chat / agent_team / workflow.llm / ... |
| `model_name` | 按模型 |
| `status` | success / error |
| `conversation_id` | 按对话 |
| `workflow_run_id` | 按工作流运行 |
| `created_at__gte` / `created_at__lte` | 时间范围 |
| `archived` | 默认只看未归档 |

### 5.2 详情

```
GET /api/v1/logs/llm-calls/{call_id}
→ 完整 messages / response_content / tool_calls
```

**前端展示**:
- tabs: 入参 / 出参 / 工具调用 / 用量 / 错误
- 入参高亮显示 system / user / assistant messages
- 出参显示完整 text + finish_reason

### 5.3 Trace

```
GET /api/v1/logs/llm-calls/trace/{trace_id}
→ 整个 trace 的所有调用,按 call_index 排序
```

**用途**:用户报"这条对话慢 / 答错了",**一键拉全链路**:
- chat 主调用(call_index=0)
- 3 轮工具调用(call_index=1,2,3)
- 每轮工具的 LLM 调用(call_index=1.1, 2.1)

### 5.4 统计

```
GET /api/v1/logs/llm-calls/stats?range=24h
→ {
    total_calls: 1234,
    success_rate: 0.987,
    avg_duration_ms: 1240,
    p95_duration_ms: 4500,
    total_tokens: 12_340_567,
    by_model: [
      { model_name: "qwen2.5:7b", calls: 1100, avg_ms: 800, total_tokens: 8M },
      { model_name: "MiniMax-...", calls: 134, avg_ms: 2100, total_tokens: 4M },
    ],
    by_call_type: [...]
  }
```

**用途**:性能监控 + 费用分摊。

### 5.5 审计(管理员)

```
GET /api/v1/logs/audit?user_id=12&action=external_app.create
→ 管理员操作日志
```

**注**:审计日志是**人工操作**(创建/删除/修改数据源),不是 LLM 调用日志。

---

## 6. 保留策略(M27 retention)

```python
# backend/lumen_services/retention.py

class RetentionPolicy:
    """Per-table retention envelope.

    Two-stage:
      - soft-delete (archived_at IS NOT NULL) at ``soft_days`` days
      - hard delete (DELETE FROM ...) at ``hard_days`` days
    """

    LLM_CALL_LOGS = RetentionPolicy(
        soft_days=90,   # 90 天后软删
        hard_days=180,  # 180 天后硬删
    )

    EMBEDDING_CALL_LOGS = RetentionPolicy(
        soft_days=30,   # 30 天
        hard_days=90,
    )
```

**调度**:
```python
# backend/lumen_services/retention_scheduler.py
@scheduler.scheduled_job("cron", hour=3, minute=0)  # 每天凌晨 3 点
def run_retention():
    for table in [LLMCallLog, EmbeddingCallLog]:
        # 1. UPDATE ... SET archived_at = NOW() WHERE created_at < cutoff AND archived_at IS NULL
        # 2. DELETE FROM ... WHERE created_at < hard_cutoff
```

**列表 API 默认过滤**:
```python
q = db.query(LLMCallLog).filter(
    LLMCallLog.archived_at.is_(None),  # ← 默认不返归档
    ...
)
```

**恢复**:`UPDATE llm_call_logs SET archived_at = NULL WHERE call_id = ...`

---

## 7. 关键设计决策

### 7.1 全量存 messages

```python
# ✅ 当下
self._messages = kwargs.get("messages")  # 完整 list[dict]
self._tools = kwargs.get("tools")        # 完整 JSON

# ❌ 早期方案(被否)
self._messages_summary = "..."  # 摘要
```

**为什么**:摘要可能丢关键 prompt,无法还原现场。

**磁盘代价**:1 行 ~5-10KB。百万行 = 10GB。可接受。

### 7.2 Embedding 不存向量 / 完整文本

见 §3.2。

### 7.3 trace_id via ContextVar

**为什么不用 thread-local**:asyncio + thread pool 混用,thread-local 不可靠。

**ContextVar 优势**:在 async context 内自动传播,跨 await 不丢。

### 7.4 异步 batch 写入

```python
# 每次调用都 db.commit() 略慢
# 默认同步(便于立即可查)
# 性能敏感场景可以用 batch(50条一 flush)
```

**当前实现**:同步 commit,1 行 1 commit。**性能监控模块**改用 batch waitlist。

### 7.5 不脱敏

**争议**:用户输入里可能有密码 / 信用卡。

**当前**:不脱敏。**理由**:脱敏后会丢复现能力。

**生产推荐**:数据库列加密 + 严格访问控制 + 定期清理。

---

## 8. 与其他模块的关系

```
[Chat] ─┐
[Agent Team] ─┤
[Workflow LLM] ─┼─→ LLMCallLogger (context manager) → llm_call_logs
[Image Gen] ─┤
[Eval Judge] ─┘
        ↓
[Retention Scheduler] (cron)
        ↓
[Archive / Hard Delete]
```

**Dashboard**:
- `/dashboard/logs` 看实时 LLM 调用
- `/dashboard/eval/runs/{id}` 看评测里的 LLM 调用
- `/dashboard/agent-teams/{id}` 看 AgentTeam 的 LLM 调用

---

## 9. 已知局限

| 局限 | 影响 | 缓解 |
|------|------|------|
| 同步 commit | 高并发聊天时会有 DB 写入开销 | 性能监控可用 batch |
| 不脱敏 | 敏感数据落 DB | DB 加密 + 访问控制 |
| Embedding 不存向量 | 无法重算相似度 | 向量本就在 FAISS |
| 100 万行后查询慢 | 业务大时 list API 慢 | archived_at 过滤 + 索引 |
| archived 不能再查 | 偶尔需要历史 | 恢复脚本 |
| trace_id 不跨 worker | Celery 任务另起 trace | 显式传 trace_id |
| retention 不能撤回 | 180 天后真的没了 | 备份 / 导出 |

---

## 10. 边界与不做

### 10.1 当前
- ✅ LLM / Embedding 调用全量记录
- ✅ trace_id 串联
- ✅ 完整入参 / 出参
- ✅ 时延 / token / 状态
- ✅ 90 天软删 + 180 天硬删
- ✅ 多租户隔离
- ✅ 统计聚合

### 10.2 不做
- ❌ 实时分析(Aggregations 实时 dashboard)
- ❌ 流式输出 replay(只能看完整 response)
- ❌ 自动脱敏
- ❌ 列级加密
- ❌ 跨 worker/进程的 trace_id 拼接
- ❌ 关闭记录的开关(默认总开)

### 10.3 升级路径

| 阶段 | 改动 |
|------|------|
| 短期 | 实时 dashboard(Grafana / ClickHouse) |
| 短期 | 流式 response 完整记录(每 token 一行) |
| 中期 | 列级加密 |
| 中期 | 跨 worker trace_id 拼接 |
| 长期 | 自动反推优化建议(基于历史调用) |

---

## 11. 排错

| 症状 | 原因 | 修法 |
|------|------|------|
| 列表 500 | 早期 fixture 直插 SQL 跳过 `created_at` 默认值 | 跑 `scripts/backfill_null_timestamps.py` |
| 性能监控统计很慢 | 千万行未归档 | 修 retention |
| trace 看不到子调用 | parent_call_id 没传 | 工具调用处补 |
| retention 失败 | scheduler 没跑 | 看 Celery beat 日志 |
| `archived_at` 突然有值 | retention 跑到的边界 | 正常 |
| 缺 token 用量 | 早期版本没记录 | 时间过滤 |
| 批量调 Ollama 慢 | commit 太多 | 短期异步 batch |
| embedding 调用没记录 | integration 漏 | 看 `embedding_logging.py` 是否被 import |

---

**相关文档**
- [可观测性](../explanation/observability.md) — 整体观测体系
- [Embedding 流水线](../explanation/embedding-pipeline.md) — 何时记
- [性能调优](../troubleshooting/performance-tuning.md) — 监控指标查询
- [数据模型参考](../reference/database-schema.md) — 表结构 + 保留策略

**维护者**:全栈架构师
**最近更新**:2026-08-06
