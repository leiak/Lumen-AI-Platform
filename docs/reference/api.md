# API 参考

> Lumen AI Platform 全部 REST endpoint 的速查表。
> **完整可调 schema 看 `/docs` 和 `/redoc`**(`http://localhost:11335/docs`)。
> 文档讲透"哪些端点归哪个模块、统一请求响应格式、鉴权约定"。

**生成时间**:2026-08-06
**OpenAPI 自动生成**: `GET /openapi.json`(差异会被 CI 跟踪)

---

## 1. 总览

| 维度 | 数字 |
|------|------|
| Router 文件 | 38 个(`lumen_api/v1/*.py` + `wx_publisher/*.py` + `external/*.py`) |
| 端点总数 | ~250 |
| 鉴权 | JWT(60% 端点)+ External Token(7 个 widget 端点)+ 公开(2 个) |
| 响应信封 | `SingleResponse[T]` / `PaginatedResponse[T]` 100% 覆盖 |

**前置约定**:
- Base URL: `http://localhost:11335/api/v1`(dev) / `https://your-domain/api/v1`(prod)
- 除 `/auth/login` 外,**所有路由都需要 JWT**
- `/external/*` 路由使用 **External Token** 应用凭证
- 已 token 鉴权失败 → 401;过期 → 401;权限不够 → 403

---

## 2. 路由文件总览

### 2.1 鉴权 / 账号

| 文件 | 路径前缀 | 端点 |
|------|---------|------|
| `auth.py` | `/auth` | POST `/login`, GET `/me` |
| `users.py` | `/users` | GET `/assignable`, `/{id}`, POST/PUT/DELETE |
| `roles.py` | `/roles` | GET/POST/DELETE |

### 2.2 业务资源

| 文件 | 路径前缀 | 端点数 |
|------|---------|--------|
| `agent.py` | `/agents` | 7(CRUD + count + chat) |
| `agent_team.py` | `/agent-teams` | 8(成员 + chat 含 stream) |
| `chat.py` | `/chat` | 8(stream / upload / 对话) |
| `knowledge.py` | `/knowledge` | 16(CRUD + 文档 + 检索 + 重做) |
| `workflow.py` | `/workflows` | 13(CRUD + run + stream + 调度) |
| `workflow_nodes.py` | `/workflows/nodes` | 2+ (节点预览) |
| `workflow_template.py` | `/workflow-templates` | 4 |
| `skill_market.py` | `/skill-market` | 7(分类 / 安装 / 卸载) |
| `skills.py` | `/skills` | 6(CRUD + run) |
| `playbooks.py` | `/playbooks` | 6 |
| `mcp.py` | `/mcp` | 7(servers / tools / marketplace) |
| `memory.py` | `/memory` | 7(对话级 + 全局) |
| `image_generation.py` | `/image-generation` | 7 |
| `tts.py` | `/tts` | 7 |
| `subtitles.py` | `/subtitles` | 5 |
| `videos.py` | `/videos` | 6 |
| `stock_assets.py` | `/stock-assets` | 3 |
| `ppt.py` | `/ppt` | 3 |
| `customer.py` | `/customers` | 6(field defs + 跟进) |
| `notifications.py` | `/notifications` | 4(列表游标 + count + read) |
| `nlp.py` | `/nlp` | 14 |
| `vision.py` | `/vision` | 8 |
| `text2sql.py` + `text2sql_datasources.py` | `/text2sql` | 10 |
| `external_apps.py` | `/external-apps` | 7(管理) |
| `wx_publisher/accounts.py` | `/wx-publisher/accounts` | 7 |
| `wx_publisher/templates.py` | `/wx-publisher/templates` | 7 |
| `wx_publisher/drafts.py` | `/wx-publisher/drafts` | 13(CRUD + AI 4 + 渲染) |
| `wx_publisher/materials.py` | `/wx-publisher/materials` | 4 |
| `wx_publisher/publish.py` | `/wx-publisher/publish` | 2 |
| `eval_datasets.py` | `/eval/datasets` | 9 |
| `eval_runs.py` | `/eval/runs` | 5(run + compare) |
| `logs.py` | `/logs` | 8(LLM / audit / 统计) |
| `settings.py` | `/settings` | 4(per-tenant) |
| `admin_skills.py` | `/admin-skills` | 5 |
| `export.py` | `/export` | 多端点(导出对话/KB) |
| `screen.py` | `/screen` | 5(看板) |
| `dashboard.py` | `/dashboard` | 1(stats) |
| `models.py` | `/models` | 7(ML 模型配置) |
| `document.py` | `/documents` | (实际并入 knowledge) |

### 2.3 公共 Widget 接口

| 文件 | 路径前缀 | 端点 |
|------|---------|------|
| `external/auth.py` | `/external` | POST `/auth/token` |
| `external/agents.py` | `/external` | GET `/agents` |
| `external/chat.py` | `/external` | POST `/chat/stream` |
| `external/conversations.py` | `/external` | GET/POST/DELETE `/conversations`, GET `/conversations/{id}/messages` |
| `external/upload.py` | `/external` | POST `/chat/upload` |

---

## 3. 响应信封(横切所有)

详见 [response-envelope.md](../explanation/response-envelope.md)。

```typescript
// SingleResponse<T>
{
  code: 200,                 // 业务码
  message: "已保存 / Saved",  // 双语 message
  data: T | null             // 真实数据
}

// PaginatedResponse<T>
{
  code: 200,
  message: "...",
  data: T[] | null,          // items
  total: 123,                // 总数
  page: 1,
  page_size: 20
}
```

**前端读法**:
```ts
const res = await api.get('/notifications')
const body = res.data
if (body.code === 200) {
  const items = body.data  // T[]
  const total = body.total
}
```

---

## 4. 鉴权

### 4.1 JWT(内部用户)

Header: `Authorization: Bearer <access_token>`

Token 来自 `POST /auth/login`:
```json
{
  "email": "user@example.com",
  "password": "..."
}
```

**返回**:
```json
{
  "code": 200,
  "data": {
    "access_token": "eyJhbGciOi...",
    "token_type": "bearer",
    "user": { ... }
  }
}
```

### 4.2 External Token(Widget)

Header: `Authorization: Bearer <external_token>`

Token 来自 `POST /external/auth/token`:
```json
{
  "app_key": "lc_pub_xxx",
  "visitor_id": "uuid-or-anything"
}
```

**返回**:
```json
{
  "code": 200,
  "data": {
    "token": "eyJ...",
    "expires_in": 1800,
    "allowed_agents": [...],
    "allowed_teams": [...],
    "visitor_id": 42
  }
}
```

### 4.3 错误响应

```json
// 401 - 鉴权失败
{ "code": 401, "message": "Not authenticated", "data": null }

// 403 - 权限不够
{ "code": 403, "message": "insufficient permissions", "data": null }

// 404 - 资源不存在
{ "code": 404, "message": "agent not found", "data": null }

// 422 - 验证失败
{ "code": 422, "message": "validation error", "data": { "field": [...] } }

// 429 - 限流
{ "code": 429, "message": "rate limited", "data": null,
  "headers": { "Retry-After": "60" } }

// 500 - 服务异常
{ "code": 500, "message": "internal error", "data": null }
```

**注意**:
- 401 / 403 时 `code` 等于 HTTP status
- 500 时不要泄露 stack trace
- 422 时 `data` 是 validation error dict

---

## 5. 公共参数

### 5.1 分页

```http
GET /api/v1/agents?page=1&page_size=20
```

| 参数 | 默认 | 范围 |
|------|------|------|
| `page` | 1 | ≥ 1 |
| `page_size` | 20 | 1-100 |

**响应**:
```json
{
  "code": 200,
  "data": [...],
  "total": 113,
  "page": 1,
  "page_size": 20
}
```

### 5.2 搜索

```http
GET /api/v1/agents?search=客服
```

- `search` 模糊匹配 `name` / `description` (大部分端点)
- 部分端点支持 `q` / `keyword` / `query`(具体看 schema)

### 5.3 排序

```http
GET /api/v1/agents?order_by=created_at&order_dir=desc
```

- 默认 `created_at desc`
- 部分端点支持 `sort_by` / `sort_dir`

### 5.4 游标分页(通知)

```http
GET /api/v1/notifications?limit=20&cursor=<last_id>
```

- 通知用 ID 游标,不用 OFFSET
- 响应里 `next_cursor` 为 null 表示没有更多

---

## 6. 全文路径

### 6.1 鉴权

```http
POST /api/v1/auth/login
GET  /api/v1/auth/me
```

### 6.2 Agent

```http
GET    /api/v1/agents                   # 列表
POST   /api/v1/agents                   # 创建
GET    /api/v1/agents/{id}              # 详情
PUT    /api/v1/agents/{id}              # 更新
DELETE /api/v1/agents/{id}              # 删
GET    /api/v1/agents/count             # 数量
POST   /api/v1/agents/{id}/chat         # 同步调
```

### 6.3 Knowledge Base

```http
GET    /api/v1/knowledge/?page=1
POST   /api/v1/knowledge/
GET    /api/v1/knowledge/parser-types
GET    /api/v1/knowledge/{kb_id}
PUT    /api/v1/knowledge/{kb_id}
DELETE /api/v1/knowledge/{kb_id}
GET    /api/v1/knowledge/count
POST   /api/v1/knowledge/{kb_id}/documents              # 上传
GET    /api/v1/knowledge/{kb_id}/documents?page=1
GET    /api/v1/knowledge/documents/{doc_id}/status
POST   /api/v1/knowledge/documents/{doc_id}/retry
GET    /api/v1/knowledge/documents/{doc_id}/chunks
POST   /api/v1/knowledge/documents/{doc_id}/rechunk
DELETE /api/v1/knowledge/documents/{doc_id}
GET    /api/v1/knowledge/tasks/{task_id}
GET    /api/v1/knowledge/{kb_id}/search?q=...
GET    /api/v1/knowledge/{kb_id}/search/compare?q=...
```

### 6.4 Workflow

```http
GET    /api/v1/workflows
GET    /api/v1/workflows/node-types
POST   /api/v1/workflows
GET    /api/v1/workflows/{id}
PUT    /api/v1/workflows/{id}
DELETE /api/v1/workflows/{id}
POST   /api/v1/workflows/bulk-delete
POST   /api/v1/workflows/{id}/run
POST   /api/v1/workflows/{id}/stream             # SSE
POST   /api/v1/workflows/{id}/runs/{run_id}/cancel
POST   /api/v1/workflows/{id}/runs/{run_id}/resume
GET    /api/v1/workflows/{id}/runs
GET    /api/v1/workflows/{id}/schedules
POST   /api/v1/workflows/{id}/schedules
PUT    /api/v1/workflows/{id}/schedules/{sid}
DELETE /api/v1/workflows/{id}/schedules/{sid}
```

### 6.5 Chat

```http
POST   /api/v1/chat/stream                       # SSE
POST   /api/v1/chat/upload
POST   /api/v1/chat/conversations
GET    /api/v1/chat/conversations
GET    /api/v1/chat/conversations/{conv_id}/messages
PATCH  /api/v1/chat/conversations/{conv_id}
DELETE /api/v1/chat/conversations/{conv_id}
POST   /api/v1/chat/recommend-skills
```

### 6.6 Notification

```http
GET    /api/v1/notifications?cursor=...&limit=20
GET    /api/v1/notifications/unread-count
POST   /api/v1/notifications/{nid}/read
POST   /api/v1/notifications/read-all
```

### 6.7 External App(管理)

```http
GET    /api/v1/external-apps
POST   /api/v1/external-apps
GET    /api/v1/external-apps/{id}
PATCH  /api/v1/external-apps/{id}
DELETE /api/v1/external-apps/{id}
POST   /api/v1/external-apps/{id}/regenerate-secret
GET    /api/v1/external-apps/{id}/usage
```

### 6.8 External Widget(对外)

```http
POST   /api/v1/external/auth/token
GET    /api/v1/external/agents
POST   /api/v1/external/chat/stream
GET    /api/v1/external/conversations
POST   /api/v1/external/conversations
GET    /api/v1/external/conversations/{conv_id}/messages
DELETE /api/v1/external/conversations/{conv_id}
POST   /api/v1/external/chat/upload
```

### 6.9 Wx Publisher

```http
# 账号
GET    /api/v1/wx-publisher/accounts
POST   /api/v1/wx-publisher/accounts
GET    /api/v1/wx-publisher/accounts/{id}
PUT    /api/v1/wx-publisher/accounts/{id}
DELETE /api/v1/wx-publisher/accounts/{id}
POST   /api/v1/wx-publisher/accounts/{id}/refresh

# 模板
GET    /api/v1/wx-publisher/templates
POST   /api/v1/wx-publisher/templates
GET    /api/v1/wx-publisher/templates/{id}
PUT    /api/v1/wx-publisher/templates/{id}
DELETE /api/v1/wx-publisher/templates/{id}
POST   /api/v1/wx-publisher/templates/{id}/render       # 渲染测试
GET    /api/v1/wx-publisher/templates/{id}/thumbnail

# 草稿
GET    /api/v1/wx-publisher/drafts
POST   /api/v1/wx-publisher/drafts
GET    /api/v1/wx-publisher/drafts/{id}
PUT    /api/v1/wx-publisher/drafts/{id}
DELETE /api/v1/wx-publisher/drafts/{id}
POST   /api/v1/wx-publisher/drafts/{id}/ai-outline    # 4 个 AI
POST   /api/v1/wx-publisher/drafts/{id}/ai-expand
POST   /api/v1/wx-publisher/drafts/{id}/ai-polish
POST   /api/v1/wx-publisher/drafts/{id}/ai-summary
POST   /api/v1/wx-publisher/drafts/{id}/ai-materials/extract
POST   /api/v1/wx-publisher/drafts/{id}/render         # 应用模板
POST   /api/v1/wx-publisher/drafts/{id}/sections
PUT    /api/v1/wx-publisher/drafts/{id}/sections/{sid}
DELETE /api/v1/wx-publisher/drafts/{id}/sections/{sid}

# 素材
POST   /api/v1/wx-publisher/materials/upload
POST   /api/v1/wx-publisher/materials/
GET    /api/v1/wx-publisher/materials/
GET    /api/v1/wx-publisher/materials/{id}
DELETE /api/v1/wx-publisher/materials/{id}

# 发布
POST   /api/v1/wx-publisher/publish/                   # 异步,202 Accepted
GET    /api/v1/wx-publisher/publish/{record_id}
```

### 6.10 Text2SQL

```http
GET    /api/v1/text2sql/datasources
POST   /api/v1/text2sql/datasources
PUT    /api/v1/text2sql/datasources/{id}
DELETE /api/v1/text2sql/datasources/{id}
POST   /api/v1/text2sql/ask
GET    /api/v1/text2sql/history
GET    /api/v1/text2sql/history/{qid}
DELETE /api/v1/text2sql/history/{qid}
GET    /api/v1/text2sql/schema
```

### 6.11 Eval(M37)

```http
GET    /api/v1/eval/datasets
POST   /api/v1/eval/datasets
GET    /api/v1/eval/datasets/{id}
PUT    /api/v1/eval/datasets/{id}
DELETE /api/v1/eval/datasets/{id}
GET    /api/v1/eval/datasets/{id}/items
POST   /api/v1/eval/datasets/{id}/items
PATCH  /api/v1/eval/datasets/{id}/items/{item_id}
DELETE /api/v1/eval/datasets/{id}/items/{item_id}

GET    /api/v1/eval/runs
POST   /api/v1/eval/runs
GET    /api/v1/eval/runs/{id}
POST   /api/v1/eval/runs/{id}/cancel
POST   /api/v1/eval/runs/compare
```

### 6.12 Logs

```http
GET    /api/v1/logs/llm-calls?page=1&status=error
GET    /api/v1/logs/llm-calls/stats
GET    /api/v1/logs/llm-calls/{call_id}
GET    /api/v1/logs/llm-calls/trace/{trace_id}
GET    /api/v1/logs/audit
GET    /api/v1/logs/operations
GET    /api/v1/logs/stats
POST   /api/v1/logs/audit
```

### 6.13 其他

```http
# Models(ML 模型配置)
GET    /api/v1/models
POST   /api/v1/models
GET    /api/v1/models/{id}
PUT    /api/v1/models/{id}
DELETE /api/v1/models/{id}
GET    /api/v1/models/providers/list
POST   /api/v1/models/import-from-ollama
POST   /api/v1/models/bulk-create

# Image Generation
POST   /api/v1/image-generation
GET    /api/v1/image-generation
GET    /api/v1/image-generation/{id}
GET    /api/v1/image-generation/{id}/image
GET    /api/v1/image-generation/{id}/thumbnail
POST   /api/v1/image-generation/{id}/regenerate
DELETE /api/v1/image-generation/{id}

# TTS
POST   /api/v1/tts/jobs
GET    /api/v1/tts/jobs
GET    /api/v1/tts/jobs/{id}
POST   /api/v1/tts/jobs/{id}/cancel
GET    /api/v1/tts/voices
GET    /api/v1/tts/jobs/{id}/audio
DELETE /api/v1/tts/jobs/{id}

# Customer
GET    /api/v1/customers
POST   /api/v1/customers
GET    /api/v1/customers/{id}
PUT    /api/v1/customers/{id}
DELETE /api/v1/customers/{id}
GET    /api/v1/customers/field-definitions
POST   /api/v1/customers/field-definitions
PUT    /api/v1/customers/field-definitions/{id}
DELETE /api/v1/customers/field-definitions/{id}
POST   /api/v1/customers/{id}/ai-advisor

# Stock Assets
GET    /api/v1/stock-assets
GET    /api/v1/stock-assets/{id}
GET    /api/v1/stock-assets/{id}/image

# Video
POST   /api/v1/videos
GET    /api/v1/videos
GET    /api/v1/videos/{id}
GET    /api/v1/videos/{id}/download
POST   /api/v1/videos/{id}/cancel
DELETE /api/v1/videos/{id}

# NLP / Vision 训练
GET    /api/v1/nlp/classification/
POST   /api/v1/nlp/classification/
GET    /api/v1/nlp/classification/{id}
PUT    /api/v1/nlp/classification/{id}
DELETE /api/v1/nlp/classification/{id}
GET    /api/v1/nlp/annotation/
POST   /api/v1/nlp/annotation/
DELETE /api/v1/nlp/annotation/{id}
GET    /api/v1/nlp/qa/
POST   /api/v1/nlp/qa/
PUT    /api/v1/nlp/qa/{id}
DELETE /api/v1/nlp/qa/{id}
POST   /api/v1/nlp/train
POST   /api/v1/nlp/predict

GET    /api/v1/vision/classification/
POST   /api/v1/vision/classification/
DELETE /api/v1/vision/classification/{id}
POST   /api/v1/vision/image/
GET    /api/v1/vision/image/
DELETE /api/v1/vision/image/{id}
POST   /api/v1/vision/train
POST   /api/v1/vision/predict

# Memory
GET    /api/v1/memory/conversations/{conv_id}
POST   /api/v1/memory/conversations/{conv_id}/messages
GET    /api/v1/memory/conversations/{conv_id}/search
DELETE /api/v1/memory/conversations/{conv_id}
GET    /api/v1/memory/global
DELETE /api/v1/memory/global

# Subtitle
POST   /api/v1/subtitles
GET    /api/v1/subtitles
GET    /api/v1/subtitles/{id}
GET    /api/v1/subtitles/{id}/content
GET    /api/v1/subtitles/{id}/download
DELETE /api/v1/subtitles/{id}

# PPT
POST   /api/v1/ppt/generate
GET    /api/v1/ppt/tasks/{id}
GET    /api/v1/ppt/tasks/{id}/file

# Playbook
GET    /api/v1/playbooks
GET    /api/v1/playbooks/{id}
POST   /api/v1/playbooks
PUT    /api/v1/playbooks/{id}
DELETE /api/v1/playbooks/{id}
POST   /api/v1/playbooks/import-yaml

# Skills
GET    /api/v1/skills
POST   /api/v1/skills
GET    /api/v1/skills/{id}
PUT    /api/v1/skills/{id}
DELETE /api/v1/skills/{id}
POST   /api/v1/skills/{id}/run

# Skill Market
GET    /api/v1/skill-market
GET    /api/v1/skill-market/categories
POST   /api/v1/skill-market/{id}/install
POST   /api/v1/skill-market/{id}/uninstall
POST   /api/v1/skill-market/batch-uninstall
GET    /api/v1/skill-market/installed
GET    /api/v1/skill-market/{id}

# MCP
GET    /api/v1/mcp/servers
POST   /api/v1/mcp/servers
DELETE /api/v1/mcp/servers/{name}
GET    /api/v1/mcp/servers/{name}/discover
GET    /api/v1/mcp/tools
POST   /api/v1/mcp/tools
POST   /api/v1/mcp/tools/execute
GET    /api/v1/mcp/marketplace/tools
POST   /api/v1/mcp/marketplace/tools/{name}/install

# AgentTeam
GET    /api/v1/agent-teams
POST   /api/v1/agent-teams
GET    /api/v1/agent-teams/{id}
PUT    /api/v1/agent-teams/{id}
DELETE /api/v1/agent-teams/{id}
DELETE /api/v1/agent-teams/{id}/members/{member_id}
POST   /api/v1/agent-teams/{id}/chat
POST   /api/v1/agent-teams/{id}/chat/stream

# Settings
GET    /api/v1/settings
PUT    /api/v1/settings
GET    /api/v1/settings/security
PUT    /api/v1/settings/security

# Dashboard / Screen
GET    /api/v1/dashboard/stats
GET    /api/v1/screen/overview
GET    /api/v1/screen/ai-calls
GET    /api/v1/screen/knowledge
GET    /api/v1/screen/workflows
GET    /api/v1/screen/tenants-users

# Roles
GET    /api/v1/roles
POST   /api/v1/roles
GET    /api/v1/roles/{id}
DELETE /api/v1/roles/{id}

# Users
GET    /api/v1/users/assignable
GET    /api/v1/users
POST   /api/v1/users
GET    /api/v1/users/{id}
PUT    /api/v1/users/{id}
DELETE /api/v1/users/{id}
```

---

## 7. WebSocket 端点

| 路径 | 用途 | 鉴权 |
|------|------|------|
| `/ws/web` | 通知推送 | JWT(走 query `?token=`) |

详细协议见 [notification.md §6](../modules/notification.md#6-websocket-wsweb)。

---

## 8. SSE 端点

| 路径 | 用途 |
|------|------|
| `/api/v1/chat/stream` | Chat 流式响应 |
| `/api/v1/workflows/{id}/stream` | Workflow 执行流 |
| `/api/v1/workflows/{id}/runs/{run_id}/stream` | 单 run 流 |
| `/api/v1/agent-teams/{id}/chat/stream` | AgentTeam 流 |
| `/api/v1/external/chat/stream` | Widget 流 |

**SSE 协议**:
```
data: {"event": "message", "content": "..."}

data: {"event": "done"}

```

---

## 9. 异步任务 / Celery

| 任务 | 触发端点 | 状态查询 |
|------|---------|---------|
| 文档解析 | `POST /knowledge/{id}/documents` | `GET /knowledge/documents/{id}/status` |
| 文档向量重建 | `POST /knowledge/documents/{id}/rechunk` | 同上 |
| 视频合成 | `POST /videos` | `GET /videos/{id}` |
| 图片生成 | `POST /image-generation` | `GET /image-generation/{id}` |
| TTS | `POST /tts/jobs` | `GET /tts/jobs/{id}` |
| 字幕生成 | `POST /subtitles` | `GET /subtitles/{id}` |
| PPT 生成 | `POST /ppt/generate` | `GET /ppt/tasks/{id}` |
| 评测运行 | `POST /eval/runs` | `GET /eval/runs/{id}` |
| 公众号发布 | `POST /wx-publisher/publish` | `GET /wx-publisher/publish/{id}` |

---

## 10. 限流

| 端点 | 限制 |
|------|------|
| `/auth/login` | 5 次 / 分钟 / IP |
| `/external/auth/token` | 来源 app `rate_limit_per_min` |
| 其他 | 200 次 / 分钟 / 用户(全局) |

**429 响应**:
```json
{
  "code": 429,
  "message": "Too Many Requests",
  "data": null,
  "headers": { "Retry-After": "30" }
}
```

---

## 11. CORS

`http://localhost:11334`(前端 dev) — 默认 allow。
**修改后** 需重启用缓存失效(`BackendConfig.get_cors_cache().invalidate()`)。

详见 [response-envelope.md](../explanation/response-envelope.md) CORS 段。

---

## 12. Content-Type

| 用途 | Type |
|------|------|
| 一般 JSON | `application/json` |
| 文件上传 | `multipart/form-data` |
| 二进制下载 | `application/octet-stream` |
| 流式 | `text/event-stream` |

---

## 13. 错误码汇总

| HTTP code | 含义 | 例子 |
|-----------|------|------|
| 200 | 成功 | |
| 201 | 创建成功 | `POST /agents` |
| 202 | 异步任务提交 | `POST /videos` |
| 204 | 成功无 body | `DELETE` |
| 400 | 业务错误 | `{"code": 400, "message": "Invalid input"}` |
| 401 | 未鉴权 | token 缺失 / 过期 |
| 403 | 权限不足 | 非超管访问管理路由 |
| 404 | 资源不存在 | agent(id) 不存在 |
| 409 | 状态冲突 | 删除有 active 数据的资源 |
| 422 | 验证失败 | 入参格式错 |
| 429 | 限流 | |
| 500 | 服务异常 | |
| 503 | 服务暂不可用 | 启动时 |

---

## 14. 客户端代码生成

**TypeScript**:
```bash
npx openapi-typescript http://localhost:11335/openapi.json -o ./types/api.d.ts
```

**Python**:
```bash
openapi-python-client generate --path http://localhost:11335/openapi.json --output ./client
```

---

## 15. 查看完整 schema

```bash
# Swagger UI
curl http://localhost:11335/docs

# Redoc
curl http://localhost:11335/redoc

# Raw OpenAPI
curl http://localhost:11335/openapi.json
```

---

**相关文档**
- [响应信封](../explanation/response-envelope.md) — 所有 endpoint 通用
- [数据模型参考](database-schema.md) — 表 / 字段
- [环境配置](environment-config.md) — ENV 变量
- [鉴权与 RBAC](../architecture/05-auth-rbac.md) — 权限

**维护者**:全栈架构师
**最近更新**:2026-08-06
