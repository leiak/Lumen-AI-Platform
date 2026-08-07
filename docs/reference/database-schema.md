# 数据模型参考

> Lumen AI Platform 全部 69 张表的速查表。
> 想知道某张表存在哪、归哪个模块管、有哪些索引,查这里。

**生成时间**:2026-08-06(dev DB 实际 schema)

**总表数**:70 张
**charset**:utf8mb4 + utf8mb4_0900_ai_ci

---

## 1. 一览表(按模块)

| 模块 | 表数 | 表 |
|------|------|-----|
| **鉴权 / RBAC** | 7 | `users`, `tenants`, `roles`, `permissions`, `role_permissions`, `audit_logs`, `operation_logs` |
| **Chat / Agent** | 5 | `agents`, `agent_knowledge_bases`, `agent_tools`, `conversations`, `messages` |
| **Agent Team** | 4 | `agent_teams`, `agent_team_members`, `agent_team_routes`, `conversation_memories` |
| **Memory** | 2 | `global_memories`, `conversation_memories` |
| **Knowledge Base** | 3 | `knowledge_bases`, `documents`, `document_chunks` |
| **FAQ** | 1 | `faq_entries` |
| **Model Config** | 1 | `model_configs` |
| **Image Generation** | 1 | `generated_images` |
| **TTS** | 1 | `generated_audios` |
| **Subtitle** | 1 | `subtitles` |
| **Video** | 1 | `generated_videos` |
| **Stock Assets** | 1 | `stock_assets` |
| **PPT** | 1 | `ppt_tasks` |
| **Workflow** | 5 | `workflows`, `workflow_runs`, `workflow_node_runs`, `workflow_schedules`, `workflow_templates` |
| **NLP Training** | 3 | `nlp_classification`, `nlp_annotation`, `nlp_qa` |
| **Vision Training** | 2 | `vision_classification`, `vision_image` |
| **Skill / Marketplace** | 3 | `skills`, `installed_skills`, `skill_marketplace` |
| **Playbook** | 1 | `playbooks` |
| **MCP** | 3 | `mcp_servers`, `mcp_tools`, `mcp_tool_executions` |
| **Notification** | 1 | `notifications` |
| **External App (Widget)** | 2 | `external_apps`, `external_visitors` |
| **Customer CRM** | 3 | `customers`, `customer_field_definitions`, `customer_follow_ups` |
| **Wx Publisher** | 5 | `wx_accounts`, `wx_templates`, `wx_drafts`, `wx_draft_sections`, `wx_materials`, `wx_publish_records` |
| **Text2SQL** | 2 | `text2sql_data_sources`, `text2sql_queries` |
| **Eval (M37)** | 4 | `eval_datasets`, `eval_dataset_items`, `eval_runs`, `eval_run_results` |
| **LLM / Embedding 日志** | 2 | `llm_call_logs`, `embedding_call_logs` |
| **Settings** | 4 | `system_settings`, `security_settings`, `system_configs`, `query_logs` |

---

## 2. 详细字段

### 2.1 鉴权 / RBAC

#### `users`
```sql
id, tenant_id, email, username, password_hash, full_name, is_active,
is_superuser, last_login_at, created_at, updated_at
```
**索引**: `(tenant_id, email)` UNIQUE, `(tenant_id, is_active)`

#### `tenants`
```sql
id, name, slug, is_active, created_at, updated_at
```
**索引**: `slug` UNIQUE

#### `roles` / `permissions` / `role_permissions`
RBAC 三件套。MVP 阶段 `roles` 表暂空(用 `is_superuser` 简化为二档)。详见 [RBAC 文档](../architecture/05-auth-rbac.md)。

#### `audit_logs` / `operation_logs`
审计日志(管理员操作)。**当前为空表**,schema 已就位,集成待补。

---

### 2.2 Chat / Agent

#### `agents`
```sql
id, tenant_id, name, description, avatar, system_prompt, greeting,
model_config_id, embedding_model_config_id, temperature, max_tokens,
memory_strategy, memory_window_size, is_default, is_active, created_at, updated_at
```
**索引**: `(tenant_id, is_active)`, `(tenant_id, created_at)`

#### `agent_knowledge_bases`
```sql
id, agent_id, knowledge_base_id, created_at
```
**索引**: `agent_id`, `knowledge_base_id`, UNIQUE(agent_id, knowledge_base_id)

#### `conversations`
```sql
id, tenant_id, user_id, agent_id, team_id, external_app_id, title,
status, agent_type, created_at, updated_at, deleted_at
```
**索引**: `(tenant_id, user_id, created_at)`, `(team_id, created_at)`, `(external_app_id, created_at)`

#### `messages`
```sql
id, conversation_id, role, content, tool_calls, tool_call_id, name,
tokens, latency_ms, created_at
```
**索引**: `(conversation_id, created_at)`

---

### 2.3 Knowledge Base

#### `knowledge_bases`
```sql
id, tenant_id, name, description, embedding_model_config_id,
search_weights, status, chunk_size, chunk_overlap, is_active,
total_documents, total_chunks, created_at, updated_at
```

#### `documents`
```sql
id, knowledge_base_id, filename, file_path, file_size, file_type,
status, error_message, chunk_count, created_at, updated_at
```

#### `document_chunks`
```sql
id, document_id, knowledge_base_id, chunk_index, content,
# 向量(明文存,不走 ORM,直读写) — 实际在 FAISS index 里
token_count, created_at
```

**`document_chunks` 没有向量列**:向量在 FAISS index 里持久化,`document_chunks` 只存文本 + 元数据。

---

### 2.4 Workflow

#### `workflows`
```sql
id, tenant_id, name, description, nodes, edges, variables,
is_template, category, enabled, version, created_at, updated_at
```
**注意**:`nodes` / `edges` 是 JSON(整张画布的快照)。

#### `workflow_runs`
```sql
id, workflow_id, tenant_id, user_id, status, inputs, outputs,
variables_snapshot, error_message, started_at, finished_at,
duration_ms, parent_run_id, created_at
```

#### `workflow_node_runs`
```sql
id, workflow_run_id, node_id, node_type, status, inputs, outputs,
error_message, retry_count, duration_ms, started_at, finished_at,
created_at
```
**索引**: `(workflow_run_id, started_at)`

---

### 2.5 Eval (M37)

#### `eval_datasets`
```sql
id, tenant_id, name, description, source, is_active, created_at, updated_at
```

#### `eval_dataset_items`
```sql
id, dataset_id, query, expected_doc_chunk_ids, expected_keywords,
ground_truth_answer, tags, created_at
```
**索引**: `dataset_id`

#### `eval_runs`
```sql
id, tenant_id, dataset_id, name, model_config_id, top_k,
search_weights, status, total_items, completed_items, avg_metrics,
started_at, finished_at, created_at
```

#### `eval_run_results`
```sql
id, run_id, dataset_item_id, query, retrieved_chunk_ids,
retrieval_metrics, generated_answer, judge_metrics, latency_ms,
created_at
```
**索引**: `(run_id, dataset_item_id)`

---

### 2.6 External App

#### `external_apps`
```sql
id, tenant_id, name, app_key, app_secret_hash, allowed_origins,
allowed_agent_ids, allowed_team_ids, scopes, rate_limit_per_min,
is_active, description, created_by, last_used_at, created_at, updated_at
```
**索引**: `app_key` UNIQUE, `(tenant_id, is_active)`

#### `external_visitors`
```sql
id, app_id, visitor_id, display_name, visitor_metadata,
first_seen_at, last_seen_at
```
**索引**: UNIQUE(app_id, visitor_id), `(app_id, last_seen_at)`

---

### 2.7 LLM / Embedding 日志

#### `llm_call_logs`(M26)
详见 [llm-call-logs.md](../modules/llm-call-logs.md) § 3.1。

**70+ 列**,核心有:`call_id`, `parent_call_id`, `trace_id`, `call_type`, `call_index`,
`tenant_id`, `user_id`, `model_name`, `messages`, `response_content`,
`token_usage`, `duration_ms`, `first_token_latency_ms`, `status`,
`archived_at`, `created_at`。

**保留**:90 天软删 + 180 天硬删(retention scheduler)。

#### `embedding_call_logs`(M27)
类似,字段简化 — 不存向量、不存完整文本。详见 [llm-call-logs.md](../modules/llm-call-logs.md) § 3.2。

---

### 2.8 Notification

#### `notifications`
```sql
id, user_id, type, title, body, resource_type, resource_id,
metadata_json, read_at, created_at
```
**索引**: `(user_id, read_at, created_at)` — 一个索引顶三个查询

---

### 2.9 其他重要表

| 表 | 关键字段 | 备注 |
|----|----------|------|
| `model_configs` | `id`, `name`, `model_type`, `provider`, `model_name`, `api_key_encrypted`, `base_url`, `is_chat`, `is_embedding`, `is_default`, `is_active` | 系统模型池 |
| `skill_marketplace` | `id`, `name`, `description`, `category`, `content_json`, `rating` | 15 个 seed + 用户贡献 |
| `installed_skills` | `id`, `tenant_id`, `skill_market_id`, `agent_id`, `installed_at` | 跨租户复用 |
| `stock_assets` | `id`, `tenant_id`(可空), `category`, `filename`, `file_path`, `tags` | 30 张预置 + 用户上传 |
| `text2sql_data_sources` | `id`, `tenant_id`, `name`, `connection_uri`, `schema_snapshot`, `is_active` | 加密存 connection_uri |
| `text2sql_queries` | `id`, `tenant_id`, `user_id`, `data_source_id`, `question`, `sql_generated`, `status`, `parent_query_id` | 树形追问 |
| `wx_accounts` | `id`, `tenant_id`, `name`, `app_id`, `app_secret_encrypted`, `is_active` | 公众号账号 |
| `customers` | `id`, `tenant_id`, `name`, `phone`, `email`, `gender`, `birthday`, `tags`, `metadata_json`, `owner_user_id`, `last_follow_up_at`, `is_active` | 客户档案 |
| `customer_field_definitions` | `id`, `tenant_id`, `field_name`, `field_label`, `field_type`, `options`, `is_required`, `display_order` | 6 种字段类型 |
| `customer_follow_ups` | `id`, `customer_id`, `user_id`, `content`, `follow_up_at`, `created_at` | 跟进记录 |
| `nlp_qa` | `id`, `tenant_id`, `question`, `answer` | FAQ 风格问答对 |
| `nlp_classification` / `nlp_annotation` | NLP 训练分类 + 标注 | |
| `vision_classification` / `vision_image` | Vision 训练分类 + 图片 | |
| `documents` / `document_chunks` | 见 §2.3 | |
| `system_settings` | `id`, `tenant_id`, `default_model_id`, `default_embedding_model_id`, `chat_history_days`, `system_name`, `system_description` | per-tenant |
| `security_settings` | `id`, `tenant_id`, `password_min_length`, `password_require_uppercase`, `password_require_special`, `session_timeout_minutes`, `max_login_attempts` | per-tenant |
| `system_configs` | `id`, `key`, `value` | platform-wide KV(M34) |

---

## 3. 复合索引摘要

按"查询模式"组织的索引,看一遍就知道哪些查询有索引兜底:

| 查询模式 | 索引 |
|---------|------|
| List,按租户过滤,按时间排序 | `(tenant_id, created_at)` |
| List,按状态过滤 | `(tenant_id, status, created_at)` |
| 按对话拉消息 | `(conversation_id, created_at)` |
| 按 trace 拉全链路 LLM | `(trace_id, call_index)` |
| 按 conversation 拉 LLM 历史 | `(conversation_id, created_at)` |
| 未读通知 | `(user_id, read_at, created_at)` |
| 按 doc 拉 chunks | `(document_id, chunk_index)` |
| 按 KB 拉 docs | `(knowledge_base_id, created_at)` |
| Agent → KB 多对多 | `UNIQUE(agent_id, knowledge_base_id)` |
| 按 tenant + active 列 | `(tenant_id, is_active)` |
| 按外部 app + visitor | `UNIQUE(app_id, visitor_id)` |

**该不该建索引的判断**:
- WHERE 子句里的列
- JOIN 的列
- ORDER BY 的列(在复合索引里)
- 外键列(自动建的就不重复)

---

## 4. server_default 铁律

新加时间列**必须**:
```python
created_at: Mapped[datetime] = mapped_column(
    DateTime, server_default=func.now(), nullable=False
)
```

**为什么**:
- 早期 fixture 直插 SQL 跳过 ORM 默认值 → 27 张表 586 行 NULL → Pydantic 严格 schema 500
- `scripts/ensure_timestamp_defaults.py` + `backfill_null_timestamps.py` 一次性扫兜底
- **新加列必须带 `server_default=func.now()` + `nullable=False`**,否则又会被 Pydantic datetime 严格 schema 拦 500

详见 [数据恢复](../troubleshooting/data-recovery.md)。

---

## 5. 软删除 / 硬删除

**软删除**(`is_active` / `deleted_at`):
- `agents` / `knowledge_bases` / `conversations` / `roles` / `mcp_servers` / ...
- 列表 API 默认过滤 `is_active=true` / `deleted_at IS NULL`
- 关联绑定(如 `agent_knowledge_bases`)不主动删,直接断引用

**硬删除**:
- 仅在用户明确删 / 自动 retention(LLM 日志)
- 多数表**没有** `ON DELETE CASCADE`,手工按 FK 顺序删

详见 [批量清理](../troubleshooting/data-recovery.md#4-批量清理)。

---

## 6. 租户隔离

**所有业务表必有 `tenant_id` 列**。所有查询必须有 `tenant_id == current_user.tenant_id` 过滤。
详见 [多租户隔离](../architecture/04-multi-tenant.md)。

**例外**:
- `system_configs`(platform-wide **单例**)
- `stock_assets` 中 `tenant_id IS NULL`(内置素材,所有人可见)

---

## 7. JSON 字段

| 表 | JSON 字段 | 含义 |
|----|----------|------|
| `agents` | `system_prompt` | 结构化 prompt(可选) |
| `knowledge_bases` | `search_weights` | {vector, bm25, title, recency} 四元组 |
| `conversations` | `metadata_json` | 外部 widget 的 visitor 信息 |
| `agent_knowledge_bases` | `metadata_json` | 绑定附加参数 |
| `documents` | `metadata_json` | 解析中间产物 |
| `workflows` | `nodes`, `edges`, `variables` | 画布完整快照 |
| `workflow_runs` | `inputs`, `outputs`, `variables_snapshot` | 当次运行快照 |
| `mcp_servers` | `config` | 连接配置 |
| `external_apps` | `allowed_origins`, `allowed_agent_ids`, `allowed_team_ids` | 数组 |
| `text2sql_data_sources` | `schema_snapshot` | 缓存的表结构 |
| `system_configs` | `value` | 任意 JSON |
| `llm_call_logs` | `messages`, `tools`, `response_content`, `tool_calls`, `token_usage` | 见 LLM 日志模块 |
| `user_metadata` | `visitor_metadata` | 外部访客属性 |

**性能**:JSON 字段过滤效率低(LONGTEXT 扫描)。要频繁过滤的字段**应该**独立成列。

---

## 8. 不在本表清单的存储

| 存储 | 位置 | 用法 |
|------|------|------|
| FAISS index | `backend/storage/vector_store/` | KB 向量 |
| ES 索引 | `lumen-platform-elasticsearch:9200` | 文档全文检索 |
| 上传文件 | `backend/storage/documents/` | 原始文档 |
| 生成图片 | `backend/storage/generated_images/` | 图片生成 |
| 生成音频 | `backend/storage/generated_audios/` | TTS |
| 生成视频 | `backend/storage/generated_videos/` | 视频合成 |
| 临时文件 | `backend/storage/_tmp/` | 解析中间产物 |

**DB 和文件必须同时备份**(详见 [数据恢复 §1.4](../troubleshooting/data-recovery.md))。

---

## 9. 列长度 / 类型规范

| 类型 | 用途 | 例子 |
|------|------|------|
| `String(36)` | UUID | `call_id`, `trace_id` |
| `String(64)` | 短 Key | `app_key`, `visitor_id` |
| `String(100)` | 名称 | `name`, `username` |
| `String(255)` | URL / 文件名 | `app_secret_hash`, `filename` |
| `String(500)` | UA / 长文本 | `user_agent` |
| `Text` | 长文本 | `content`, `description` |
| `JSON` | 结构化 | `messages`, `nodes` |
| `Integer` | 普通 id | `id`, `tenant_id` |
| `DateTime` | 时间戳 | `created_at` |
| `Boolean` | 开关 | `is_active`, `is_default` |
| `Float` | 数值 | `accuracy`, `temperature` |

---

## 10. 看 schema 的最快方式

```sql
-- 列出所有表
SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA = 'ai_platform';

-- 某张表的字段
DESCRIBE agents;

-- 某张表的索引
SHOW INDEX FROM agents;

-- 某张表的外键
SELECT
  TABLE_NAME, COLUMN_NAME, CONSTRAINT_NAME, REFERENCED_TABLE_NAME, REFERENCED_COLUMN_NAME
FROM information_schema.KEY_COLUMN_USAGE
WHERE TABLE_SCHEMA = 'ai_platform' AND REFERENCED_TABLE_NAME IS NOT NULL
  AND TABLE_NAME = 'agents';
```

生成完整 DDL:

```bash
docker exec lumen-platform-mysql mysqldump --no-data -uroot -prootpassword ai_platform > schema.sql
```

---

## 11. 已知 schema 问题

| 问题 | 影响 | 修法 |
|------|------|------|
| 早期表 `created_at` 无 `DEFAULT` | fixture 直插 SQL 后 NULL | `ensure_timestamp_defaults.py` |
| 多数表无 `ON DELETE CASCADE` | 父表删不动 | 手动按 FK 顺序 |
| `mcp_tool_executions` 表为空 | 使用率不高 | 不删,可能后续用 |
| `audit_logs` / `operation_logs` 空 | 审计集成待补 | 未来 RBAC |
| `roles` / `permissions` 空 | RBAC 简化版 | 未来 RBAC |
| `ppt_tasks` 老表 | M 早期遗留 | 看是否清理 |
| `nlp_qa` / `fa` 等表 | 培训模块在小流量 | 保留 |

---

**相关文档**
- [数据恢复](../troubleshooting/data-recovery.md)
- [数据迁移与升级](../troubleshooting/data-recovery.md#6-迁移与升级)
- [多租户隔离](../architecture/04-multi-tenant.md)
- [知识库 (KB schema)](../modules/knowledge-base.md)
- [LLM 调用日志](../modules/llm-call-logs.md)

**维护者**:全栈架构师
**最近更新**:2026-08-06
