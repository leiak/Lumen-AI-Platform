# 模块拓扑

> 详细列出后端 9 大模块 + 前端 44 页面 + 跨切面关注点的拓扑关系。
> 适合工程师在改模块前先看清边界。

---

## 1. 后端模块

后端 9 大模块在 `lumen_*` 平铺目录下,各司其职:

### 1.1 `lumen_main.py`(应用入口)
- 路径:`backend/lumen_main.py`
- 职责:创建 FastAPI 实例 + 注册路由 + 启动钩子 + CORS + 静态文件
- 关键行:
  - `:121-126` 创建 FastAPI
  - `:172-179` 注册 `DynamicCORSMiddleware`
  - `:182-278` `@app.on_event("startup")` 启动钩子(ensure_*, 模型预热)
  - `:289` `app.include_router(v1_router, prefix="/api/v1")`
  - `:296-306` widget 静态文件 mount

### 1.2 `lumen_api/`(路由层)
**只做入参校验 + 调服务 + 返回响应信封**。所有 endpoint 装饰 `response_model=SingleResponse[T]` 或 `PaginatedResponse[T]`。

| 路由文件 | 业务模块 | 端点 |
|---------|---------|------|
| `auth.py` | 认证 | `/auth/login`, `/auth/me` |
| `users.py` | 用户管理 | `/users/*` |
| `roles.py` | 角色权限 | `/roles/*` |
| `chat.py` | 对话 | `/chat/*` + `/chat/stream` (SSE) |
| `agent.py` | 单 Agent | `/agents/*` |
| `agent_team.py` | 多 Agent | `/agent-teams/*` |
| `knowledge.py` | 知识库 | `/knowledge/*` |
| `document.py` | 文档生成 | `/documents/generate/{word,excel}` |
| `workflow.py` | 工作流 | `/workflows/*` + `/workflows/run` |
| `workflow_template.py` | 模板市场 | `/workflow-templates/*` |
| `workflow_nodes.py` | 节点预览 | `/workflow-nodes/http/preview` |
| `mcp.py` | MCP | `/mcp/*` |
| `memory.py` | 记忆 | `/memory/*` |
| `models.py` | 模型管理 | `/models/*` |
| `image_generation.py` | 图片生成 | `/image-generations/*` |
| `tts.py` | TTS | `/tts/*` |
| `subtitle.py` | 字幕 | `/subtitles/*` |
| `playbook.py` | Playbook | `/playbooks/*` |
| `skill_market.py` | 技能市场 | `/skills/*` |
| `customer.py` | 客户 CRM | `/customers/*` |
| `external_app.py` | 外部应用 | `/external-apps/*` + `/external/...` (用 app_key) |
| `notification.py` | 通知 | `/notifications/*` |
| `llm_call_log.py` | LLM 日志 | `/llm-call-logs/*` |
| `text2sql.py` | 智能问数 | `/text2sql/*` |
| `video.py` | 视频 | `/videos/*` |
| `stock.py` | 股票素材 | `/stock-assets/*` |
| `eval_*.py` | RAG 评测 | `/eval/*` |
| `system_config.py` | 系统设置 | `/system-configs/*` |
| `wx_publisher.py` | 公众号 | `/wx-publisher/*` |
| `websocket.py` | WS | `/ws/web` |
| `deps.py` | 跨切面依赖 | `get_current_external_app` |

详见 [reference/api.md](../reference/api.md) 完整端点清单。

### 1.3 `lumen_services/`(业务逻辑层)
按业务模块拆,每个服务一个文件:

| 服务 | 职责 |
|------|------|
| `auth_service` | 认证 / token 签发 / 密码校验 |
| `user_service` | 用户 CRUD |
| `role_service` | 角色权限 |
| `chat_service` | 对话 + 流式 |
| `agent_service` | Agent CRUD + 单轮调用 |
| `agent_team_service` | 多 Agent 路由 |
| `knowledge_service` | KB CRUD + 检索 + per-KB embedding 工厂 |
| `document_service` | 文档上传 + 解析 + 切块 + 向量化 |
| `workflow_executor` | LangGraph StateGraph 编排 |
| `workflow_service` | Workflow CRUD + 模板 + 调度 |
| `mcp_service` | MCP 注册 + 工具发现 + 调用 |
| `memory_service` | 记忆 CRUD + 策略执行 |
| `model_service` | 模型 CRUD + Ollama 导入 |
| `image_generation_service` | 图片生成(后台任务) |
| `tts_service` | TTS 任务 |
| `subtitle_service` | SRT 生成 |
| `video_compose_service` | 视频合成(ffmpeg) |
| `stock_service` | 股票素材库 |
| `playbook_service` | Playbook CRUD |
| `skill_market_service` | 技能市场 + 安装 |
| `customer_service` | CRM |
| `external_app_service` | 外部应用 + JWT 签发 |
| `notification_service` | 通知 |
| `llm_call_log_service` | LLM 日志 |
| `text2sql_service` | NL→SQL + SQLGuard |
| `eval_dataset_service` | 评测集 |
| `eval_run_service` | Eval Run + 触发 |
| `eval_report_service` | Eval 报告 |
| `system_config_service` | 系统设置 |
| `wx_publisher_service` | 公众号 |
| `observability_service` | trace_id 生成 + LLMCallLog 包装 |

### 1.4 `lumen_models/`(数据模型)
69 张表的 SQLAlchemy ORM,每个模型一个文件:
`user.py`, `agent.py`, `knowledge_base.py`, `workflow.py`, `chat.py`, `memory.py`, `model_config.py`, `image_generation.py`, `tts.py`, `video.py`, `eval_dataset.py`, `wx_publisher.py`, ...

详见 [database-schema](../reference/database-schema.md)。

### 1.5 `lumen_schemas/`(入参出参)
Pydantic schema,按模块拆:
- `common.py` — `SingleResponse[T]` / `PaginatedResponse[T]`
- `auth.py` / `user.py` / `agent.py` / `knowledge.py` / ...
- 每个 schema 文件包含 `Read` / `Create` / `Update` / `Query` 4 个基础 schema

### 1.6 `lumen_core/`(核心基础设施)
- `config.py` — `Settings` 读取 `.env`
- `database.py` — `engine` + `SessionLocal` + `Base` + 18 个 `ensure_*` 迁移
- `auth.py` — OAuth2 + JWT
- `middleware/` — `DynamicCORSMiddleware` 等
- `observability.py` — `LoggingChatModel` 包装
- `model_providers.py` — LLM / Embedding / Image / TTS provider 注册中心
- `trace_id.py` — `trace_id` 生成 + 透传
- `rate_limiter.py` — 限流

### 1.7 `lumen_tools/`(工具)
- `vector_store_factory.py` — FAISS 工厂
- `embedding_factory.py` — per-KB embedding
- `chunker.py` — 文档切块
- `rerank.py` — Rerank 精排
- `httpx_client.py` — HTTP 客户端
- `image_providers/` — 多 provider 图片生成
- `tts_providers/` — 多 provider TTS
- `mcp_client.py` — MCP 客户端(JSON-RPC)
- `srt.py` — SRT 生成
- `video_compose.py` — ffmpeg 拼装
- `stock.py` — 股票素材查询
- `docling_parser.py` — Docling 文档解析
- `playbook_renderer.py` — Playbook 风格注入

### 1.8 `lumen_tasks/`(Celery 异步任务)
- `document_tasks.py` — 文档解析/切块/向量化
- `image_gen_tasks.py` — 图片生成
- `tts_tasks.py` — TTS
- `video_tasks.py` — 视频合成
- `eval_tasks.py` — Eval Run

### 1.9 `lumen_mcp_servers/`(MCP server 实现)
- `local_demo_server.py` — 本地 demo,8765 端口,6 工具

---

## 2. 前端页面

### 2.1 路由结构
```
frontend/app/
├── layout.tsx                  根 layout(AntdRegistry + QueryProvider)
├── page.tsx                    → redirect /dashboard
├── (auth)/
│   ├── layout.tsx              无 chrome
│   └── login/page.tsx          登录
└── dashboard/
    ├── layout.tsx              ProLayout + 顶栏 + 侧栏
    ├── page.tsx                工作台首页(Statistic 卡片)
    ├── knowledge/page.tsx      知识库
    ├── agent/
    │   ├── page.tsx            Agent 列表
    │   ├── team/page.tsx       Agent 团队
    │   └── __tests__/          page test
    ├── chat/page.tsx           聊天
    ├── customer/
    │   ├── page.tsx            客户列表
    │   ├── [id]/page.tsx       客户详情
    │   └── settings/page.tsx   字段定义
    ├── wx-publisher/
    │   ├── page.tsx            → redirect drafts
    │   ├── drafts/page.tsx + [id]/page.tsx  草稿
    │   ├── templates/page.tsx  模板
    │   ├── materials/page.tsx  素材
    │   └── accounts/page.tsx   账号
    ├── image-generation/page.tsx   图片
    ├── videos/page.tsx             视频
    ├── text2sql/page.tsx           智能问数
    ├── eval/
    │   ├── page.tsx            评测看板
    │   ├── datasets/page.tsx + [id]/page.tsx  数据集
    │   └── runs/[id]/page.tsx  Run 详情
    ├── memory/page.tsx         记忆
    ├── workflow/
    │   ├── page.tsx            工作流列表
    │   ├── designer/page.tsx   设计器
    │   └── templates/page.tsx  模板中心
    ├── marketplace/page.tsx    工作流市场
    ├── mcp/page.tsx            MCP
    ├── electron/page.tsx       桌面端
    ├── skills/
    │   ├── installed/page.tsx  我的技能
    │   ├── market/page.tsx     技能市场
    │   └── page.tsx            技能管理
    ├── system/
    │   ├── users/page.tsx      用户
    │   ├── roles/page.tsx      角色
    │   ├── models/page.tsx     模型
    │   ├── settings/page.tsx   设置
    │   ├── skills/page.tsx     平台技能
    │   └── playbooks/page.tsx  Playbook
    ├── external-apps/
    │   ├── page.tsx            列表
    │   ├── new/page.tsx        新建
    │   └── [id]/page.tsx       详情
    ├── document/page.tsx       文档处理
    ├── training/
    │   ├── nlp/{page, annotation/page, classification/page, qa/page}.tsx
    │   └── vision/{image/page, classification/page}.tsx
    ├── tts/page.tsx            TTS
    └── logs/
        ├── page.tsx            日志总
        ├── llm-call-detail.tsx 单次 LLM
        └── trace/[trace_id]/page.tsx  Trace
```

### 2.2 公共组件 (`components/`)

| 类别 | 组件 |
|------|------|
| **基础设施** | `QueryProvider`, `ResizeObserverSuppressor`, `ClientConsoleSuppressor` |
| **选择器** | `EmbeddingModelSelect`, `ChatModelSelect`, `PlaybookSelect`, `KBSelector`, `ToolSelector`, `MultiKBSelector`, `OwnerUserSelect` |
| **Agent** | `AgentFormModal`, `AgentKBBadge`, `AgentKBBanner`, `KbRetrievalConfigFields` |
| **KB** | `FAQTab` |
| **技能** | `SkillTypeTag`, `detail/{PromptDetail,ScriptDetail,HttpDetail,KnowledgeRetrievalDetail,ToolDetail}`, `admin/SkillUpsertForm` |
| **工作流** | `KBSelector`, `ToolSelector`, `CreateModelInlineModal`, `designer/{RunResultPanel,InputValuesModal}`, `_base/aimessage`, `_base/hooks/useAvailableVarList`, `_base/variable/{VarReferencePicker,VarReferencePopup,VarReferenceVars,VarList,types}`, `_base/condition/{ConditionRow,ConditionCaseEditor}`, `_base/error/{ErrorStrategyPicker,RetryConfigForm,TimeoutInput,AdvancedOptions,types}`, `nodes/{input,agent,condition,output,parallel,fan_out,fan_in,code,http,knowledge_retrieval,parameter_extractor,question_classifier,template_transform,tool,variable_aggregator,variable_assigner,llm}/{Panel,Node,types}`, `nodes/registry` |
| **通知** | `BellBadge`, `NotificationDrawer` |
| **聊天** | `Markdown`, `CodeBlock`, `Citations`, `AttachmentChip`, `MessageBubble` |
| **外部应用** | `EmbedSnippetBox`, `SecretRevealModal`, `UsageTab` |
| **图片** | `ImageCard`, `DetailModal` |
| **公众号** | `MarkdownEditor`, `HtmlPasteHandler`, `RenderPreview`, `TemplateCard`, `AIRewriteModal`, `AppSecretRevealModal`, `DraftList`, `AccountTable`, `KBImportModal` |
| **Text2SQL** | `index` |
| **Eval** | `ItemFormModal` |
| **导入** | `OllamaImportModal` |

### 2.3 Services 层(API 调用封装)

`frontend/services/` 下,每个文件对应一个后端业务模块:
`auth.ts` / `agent.ts` / `agentTeam.ts` / `chat.ts` / `knowledge.ts` / `workflow.ts` / `workflowTemplate.ts` / `nodes.ts` / `mcp.ts` / `skills.ts` / `models.ts` / `externalApp.ts` / `customers.ts` / `users.ts` / `memory.ts` / `notifications.ts` / `realtime.ts` / `image-generation.ts` / `video.ts` / `stock.ts` / `tts.ts` / `subtitle.ts` / `ppt.ts` / `playbook.ts` / `text2sql.ts` / `wx-publisher.ts` / `settings.ts` / `llm-call-logs.ts` / `eval.ts` / `eval_dataset.ts` / `eval_run.ts` / `nlp.ts` / `vision.ts` / `dashboard.ts`

所有 service 基于 `services/auth.ts` 的 axios 实例,自动 Bearer token 注入 + 401 拦截器。

### 2.4 状态管理
- **Zustand** 5.x — `frontend/store/notifications.ts`(通知全局态)
- **TanStack Query** 5.x — `frontend/libs/queryClient.ts`(QueryClient)
- **localStorage** — `access_token` + `user`
- **AntD `App.useApp()`** — `message` / `notification` / `modal`(避免静态 import 不渲染)

---

## 3. 跨切面关注点

### 3.1 认证 & 授权
- `lumen_api/deps.py` — `get_current_user`, `require_admin`
- `lumen_core/auth.py` — `create_access_token`, `verify_token`
- 装饰器 `@require_role("admin")` 挂在 endpoint
- 前端 `services/auth.ts` 拦截器统一处理 401

### 3.2 多租户隔离
- `lumen_core/middleware/tenant.py` — `TenantContext` ContextVar
- 强制 `tenant_id` 过滤(后端服务层 + ORM 查询)
- 前端 axios 实例 header `X-Tenant-Id` (多租户切换时设)

### 3.3 CORS
- `lumen_main.py:172-179` — `DynamicCORSMiddleware`
- 动态 Origin 白名单,根据 `request.url` 判断

### 3.4 限流
- `lumen_core/rate_limiter.py` — 路由级 rate limit
- 关键端点:登录、外部应用、JWT 刷新

### 3.5 错误处理
- `lumen_core/middleware/error_handler.py` — 统一 5xx + 业务 4xx
- 响应 message 双语: `"已保存 / Saved"`

### 3.6 可观测性
- `lumen_core/observability.py` — `LoggingChatModel` 包装
- `lumen_core/trace_id.py` — trace_id 透传
- `lumen_services/llm_call_log_service.py` — 写 `llm_call_logs`
- 前端 `services/realtime.ts` — WS 心跳 + 重连

### 3.7 WebSocket
- 后端 `lumen_api/v1/websocket.py` — `/ws/web?token=...`
- 前端 `services/realtime.ts` + `store/notifications.ts` — 通知 + 实时数据

### 3.8 SSE 流式
- 后端 `lumen_api/v1/chat.py` — `StreamingResponse(media_type="text/event-stream")`
- 前端 `lib/chat-sse-utils.ts` — 自实现 SSE parser

### 3.9 健康检查
- `lumen_main.py` 注册 `GET /health` 端点
- 返回 `{ status: "ok", mysql, redis, ollama, es }`

---

## 4. 客户端

### 4.1 Frontend(主后台)
- 端口 11334
- Next.js 15 + AntD 5
- 详细见 [模块拓扑 § 2](#2-前端页面)

### 4.2 Widget(`<lumen-chat>`)
- 路径:`widget/`
- 入口:`<lumen-chat server="..." app-key="...">`
- 双产物:`lumen-chat.js` (IIFE) + `lumen-chat.esm.js` (ESM)
- bundle < 240KB(CI gate)
- Lit 3 + esbuild + markdown-it

### 4.3 Electron 桌面端
- 路径:`electron-desktop/`
- 主入口:`src/main.cjs`
- IPC:`save-token` / `load-token` / `clear-token` / `pick-files` / `save-file` / `navigate`
- WS 客户端:`remote-tool-client.cjs`(连后端远程工具)
- Token 存储:`safeStorage` → `userData/token.bin`

---

## 5. 外部依赖

| 依赖 | 端口/Endpoint | 用途 |
|------|---------------|------|
| MySQL 8 | 3307 | 持久化 |
| Redis 7 | 6379 | Celery broker + pubsub |
| Elasticsearch 8 | 9200 | BM25 |
| Ollama | 11434 | embedding + chat |
| FAISS | (嵌入式) | 向量 |
| OpenAI | api.openai.com | LLM / Embedding / Image / TTS |
| Stability | api.stability.ai | Image |
| 微信 API | api.weixin.qq.com | 公众号 |
| SMTP | (邮件) | 通知 |

---

## 6. 启动顺序

1. **依赖服务**:`docker compose up -d` → MySQL / Redis / ES / Ollama
2. **拉模型**:`ollama pull nomic-embed-text && ollama pull qwen2.5:7b`
3. **初始化 DB**:`python scripts/init_dev_db.py` → 18 个 ensure_* + 种子数据
4. **启动后端**:`uvicorn lumen_main:app --port 11335` → 自动 ensure_* + 模型预热
5. **启动前端**:`npm run dev` → 11334
6. **(可选) 启动 MCP demo**:`python run_mcp_server.py` → 8765
7. **(可选) 启动 Celery worker**:`celery -A lumen_tasks worker -l info`
8. **(可选) 启动 Electron**:`cd electron-desktop && npm start`

详见 [getting-started](../tutorials/getting-started.md) 和 [dev-env](../how-to/dev-env.md)。

---

**维护者**:全栈架构师
**最近更新**:2026-08-06
