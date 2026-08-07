# 架构总览

> 一张图总览 Lumen AI Platform 的系统架构,适合工程师 / 架构师 / 资深产品快速建立全局视图。
>
> 详细分述见:
> - [技术栈](01-tech-stack.md)
> - [模块拓扑](02-module-topology.md)
> - [数据流](03-data-flow.md)
> - [多租户](04-multi-tenant.md)
> - [认证与 RBAC](05-auth-rbac.md)
> - [端口分配](06-port-alloc.md)

---

## 1. 整体架构图

```
                  ┌────────────────────────────────────────┐
                  │  第三方网站 (Customer Site)            │
                  │  <script src="lumen-chat.js">          │
                  │  <lumen-chat app-key="...">            │
                  └─────────────────┬──────────────────────┘
                                    │ HTTP / SSE / WS
                                    ▼
┌────────────────────────────────────────────────────────────────────┐
│ 桌面端 (Electron 33)                                                │
│  ┌────────────────────┐  ┌──────────────────────────────────────┐  │
│  │ Main Process       │  │ Renderer (loads localhost:11334)    │  │
│  │ - WS 客户端         │  │ - Next.js 前端                       │  │
│  │ - 本地工具执行器    │  │                                      │  │
│  │ - safeStorage      │  │                                      │  │
│  └─────────┬──────────┘  └────────────────┬─────────────────────┘  │
└────────────┼──────────────────────────────┼─────────────────────────┘
             │ WS (远程工具)                │ HTTP / SSE / WS
             ▼                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│ Backend  (FastAPI 11335)                                              │
│ ┌──────────────────┐  ┌──────────────────┐  ┌────────────────────┐   │
│ │ lumen_api/       │  │ lumen_services/  │  │ lumen_models/      │   │
│ │ (路由)           │  │ (业务逻辑)        │  │ (ORM)              │   │
│ │ /api/v1/*        │  │ - knowledge_svc  │  │ - User, Agent,     │   │
│ │                  │  │ - workflow_exec  │  │ - KB, Document,    │   │
│ │                  │  │ - image_gen_svc  │  │ - Workflow, Run,   │   │
│ │                  │  │ - tts_svc        │  │ - Chat, Memory,    │   │
│ │                  │  │ - video_svc      │  │ - Skill, MCP,      │   │
│ │                  │  │ - ...            │  │ - Image, TTS,      │   │
│ │                  │  │                  │  │ - Video, Eval,     │   │
│ │                  │  │                  │  │ - LLMCallLog,      │   │
│ │                  │  │                  │  │ - SystemConfig     │   │
│ └──────────────────┘  └──────────────────┘  └────────────────────┘   │
│         ▲                      ▲                       ▲             │
│         │                      │                       │             │
│         └──────────────────────┼───────────────────────┘             │
│                                │                                     │
│ ┌──────────────────┐  ┌─────────┴────────┐  ┌────────────────────┐    │
│ │ lumen_core/      │  │ lumen_tools/     │  │ lumen_tasks/       │    │
│ │ - config         │  │ - vector_store   │  │ (Celery)           │    │
│ │ - database       │  │ - embedding_fac  │  │ - document_tasks   │    │
│ │ - auth           │  │ - chunker        │  │ - image_gen_tasks  │    │
│ │ - middleware     │  │ - rerank         │  │ - tts_tasks        │    │
│ │ - logging        │  │ - httpx client   │  │ - eval_tasks       │    │
│ │ - trace_id       │  │ - image_prov     │  │ - workflow_tasks   │    │
│ │ - model_provider │  │ - tts_provider   │  │                    │    │
│ │ - observability  │  │ - mcp_client     │  │                    │    │
│ │                  │  │ - srt            │  │                    │    │
│ │                  │  │ - video_compose  │  │                    │    │
│ │                  │  │ - stock          │  │                    │    │
│ │                  │  │ - docling        │  │                    │    │
│ │                  │  │ - ffmpeg         │  │                    │    │
│ └──────────────────┘  └──────────────────┘  └────────────────────┘    │
│         ▲                      ▲                       ▲             │
│         │                      │                       │             │
│         └──────────────────────┴───────────────────────┘             │
│                                                                       │
│ ┌─────────────────────────────────────────────────────────────────┐   │
│ │ lumen_schemas/  (Pydantic 入参出参)                              │   │
│ │ - common.SingleResponse[T] / PaginatedResponse[T]              │   │
│ │ - 各模块 Read/Create/Update schemas                            │   │
│ └─────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
             │                              │
             ▼                              ▼
┌──────────────────────┐    ┌─────────────────────────────────────┐
│ MySQL 8 (Docker 3307)│    │ Ollama 11434                         │
│ schema: ai_platform  │    │ - embedding: nomic-embed-text       │
│ 80+ tables           │    │ - chat: qwen2.5:7b                  │
│ UTF-8                │    └─────────────────────────────────────┘
└──────────────────────┘
             ▲
             │
┌──────────────────────┐    ┌─────────────────────────────────────┐
│ Redis (Docker 6379)  │    │ FAISS + Elasticsearch 8 (混合检索)    │
│ - Celery broker      │    │ - FAISS: 向量相似度                  │
│ - pubsub             │    │ - ES: BM25 关键词                    │
└──────────────────────┘    └─────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────────┐
│ 外部服务                                                            │
│  - OpenAI (LLM / Embedding / TTS / Image)                            │
│  - Stability AI (Image)                                              │
│  - 微信 API (公众号发布)                                             │
│  - SMTP (邮件通知)                                                   │
└────────────────────────────────────────────────────────────────────┘
```

---

## 2. 关键设计原则

### 2.1 单体仓库(Monorepo)
一个仓库包含 4 个子项目:`frontend/` + `widget/` + `electron-desktop/` + `backend/`。
- 优势:统一 PR、版本管理、共享 `.env`、本地联调
- 共享方式:`backend` 是部署单元,其他三项目独立打包但通过 HTTP/SSE 接入

### 2.2 后端分层
- **路由层**(`lumen_api/v1/`):只做入参校验 + 调服务 + 返回响应信封
- **业务逻辑层**(`lumen_services/`):编排多个 ORM / 工具
- **数据模型层**(`lumen_models/`):SQLAlchemy ORM,纯数据库映射
- **核心层**(`lumen_core/`):跨切面(config / database / auth / middleware / observability)
- **工具层**(`lumen_tools/`):可独立测试的工具(向量库、embedding 工厂、provider 等)
- **任务层**(`lumen_tasks/`):Celery 异步任务
- **Schema 层**(`lumen_schemas/`):Pydantic 入参出参

**禁止**业务逻辑写在路由里,禁止 ORM 在路由里直接用。

### 2.3 响应信封
所有 endpoint 返回 `SingleResponse[T]` 或 `PaginatedResponse[T]`(`lumen_schemas/common.py`),前端统一读 `body.code === 200` + `body.data`。
详见 [response-envelope 契约](../explanation/response-envelope.md)。

### 2.4 多租户隔离
以 `tenant_id` 为主键外键贯穿核心表(agents, knowledge_bases, conversations, workflows, customers 等)。
`tenant_id IS NULL` 表示平台内置全局资源(默认 model、stock assets 等)。
详见 [multi-tenant](04-multi-tenant.md)。

### 2.5 可观测性优先
每个 LLM 调用必须经 `LoggingChatModel` 包装,自动写 `llm_call_logs` 表 + `trace_id` 串联。
详见 [observability](../explanation/observability.md)。

### 2.6 失败友好
- 错误处理统一 5xx + 业务 4xx + 详细 message
- 工作流节点级 error_strategy / retry_config / timeout
- uvicorn 静默挂掉有专门排错文档

---

## 3. 子项目职责

| 子项目 | 端口 | 技术 | 职责 |
|--------|------|------|------|
| `backend/` | **11335** | FastAPI + SQLAlchemy + LangChain | 后端服务 / 业务逻辑 / 异步任务 |
| `frontend/` | **11334** | Next.js 15 + AntD 5 | 主后台 UI(管理员 + 开发者) |
| `widget/` | (嵌入) | Lit 3 + esbuild | 第三方网站 `<lumen-chat>` 嵌入 |
| `electron-desktop/` | (桌面) | Electron 33 | Windows / macOS / Linux 桌面客户端 |

---

## 4. 关键依赖关系

```
Frontend  →  Backend (HTTP / SSE / WS)
Widget    →  Backend (HTTP / SSE)
Electron  →  Backend (HTTP) + Backend (WS 远程工具)

Backend   →  MySQL (ORM)
Backend   →  Redis (Celery broker)
Backend   →  Ollama (embedding + chat)
Backend   →  FAISS / ES (RAG 检索)
Backend   →  OpenAI / Stability / 微信 (外部 API)
Backend   →  Celery worker (异步任务)
```

**核心规则**:
- Frontend / Widget / Electron **不直连 MySQL**,必须经 Backend API
- Backend 是单点入口,所有外部服务都在 Backend 一侧
- Celery worker 共享 Backend 代码,通过 `lumen_tasks` 模块执行

---

## 5. 部署形态

### 开发(单机)
```
本机: Docker (MySQL 3307, Redis 6379, ES 9200, FAISS 嵌入式)
本机: Ollama 11434
本机: uvicorn 11335 (Python 进程)
本机: npm run dev 11334 (Node 进程)
```

### 生产(推荐)
```
LB (Nginx)
 ├─ Frontend (Next.js standalone) 11334
 ├─ Backend (uvicorn + gunicorn workers) 11335
 └─ Celery workers (N 个)
Docker 集群:
 ├─ MySQL 主从
 ├─ Redis
 ├─ Elasticsearch cluster
 └─ Ollama 集群 (或外部 OpenAI)
```

详见 [deploy](../how-to/deploy.md)。

---

## 6. 安全设计

| 维度 | 措施 |
|------|------|
| **认证** | OAuth2 + JWT,token 存 `localStorage.access_token` |
| **授权** | RBAC 角色权限矩阵,API 装饰器检查 |
| **跨域** | `DynamicCORSMiddleware`,动态 Origin 白名单 |
| **限流** | 路由级 rate limiter(M27 加固) |
| **多租户隔离** | `tenant_id` 强制过滤,后端服务层 + ORM 层双保险 |
| **密钥** | `SecretStr` 包装,日志不打印明文 |
| **外部应用** | 公私钥签 JWT,Origin 白名单,Agent 白名单 |
| **桌面端** | `safeStorage` 加密 token |

---

## 7. 性能设计

| 维度 | 措施 |
|------|------|
| **流式输出** | SSE 推送,首 token 延迟 < 2 秒 |
| **异步任务** | Celery + Redis,长任务不阻塞 API |
| **向量检索** | FAISS 内存索引 + per-(kb_id, model_config_id) collection |
| **混合检索** | FAISS + ES + Rerank 三段式 |
| **缓存** | TanStack Query 5 分钟 staleTime,Redis Celery 结果 |
| **前端 bundle** | `optimizePackageImports` 防 OOM,Widget < 250KB |
| **数据库索引** | tenant_id / agent_id / conversation_id 等外键必有索引 |

---

## 8. 监控设计

| 维度 | 工具 |
|------|------|
| **应用日志** | Python `logging` → stdout(可接 ELK / Loki) |
| **LLM 调用日志** | `llm_call_logs` 表(可查 UI) |
| **Trace** | `trace_id` 串联一次请求的所有 LLM call |
| **告警** | [通知中心](../modules/notification.md) + 邮件 + 桌面端托盘 |
| **健康检查** | `GET /health` 返回 200 + DB / Redis / Ollama 状态 |

---

## 9. 关键边界

### 9.1 Backend 内部
- `lumen_api` → `lumen_services` → `lumen_models` + `lumen_tools` + `lumen_core`
- `lumen_services` **不依赖** `lumen_api`
- `lumen_tasks` 共享 `lumen_services` + `lumen_models` + `lumen_tools`
- `lumen_core` 提供 `config / database / auth / middleware / observability`

### 9.2 Backend ↔ Frontend
- Backend 不感知前端技术栈
- 前端不感知后端 ORM
- 边界 = OpenAPI Schema(`/openapi.json`)

### 9.3 Backend ↔ Widget / Electron
- Widget / Electron **不直连数据库**
- 通过 `app_key` 走 `/api/v1/external/*` 端点拿 JWT
- 内部调用走 `/api/v1/*` + `Authorization: Bearer`

---

## 10. 一句话总结

**Lumen AI Platform 是个"FastAPI 单体 + 4 个客户端 + 6 个外部依赖"的私有化 AI 平台,核心特点是"全栈可观测 + 22 节点工作流 + 多渠道交付"。**

---

**维护者**:全栈架构师
**最近更新**:2026-08-06(M37 + 1.0 重命名完成后)
