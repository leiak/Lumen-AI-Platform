# Lumen AI Platform

企业级 AI Agent 平台,完整自托管。围绕**知识库 RAG**、**AI Agent 对话与团队协作**、**可视化工作流编排**、**MCP 协议集成** 四大核心,配套图片 / 视频生成、TTS、字幕、Playbook 风格系统、公众号助手、智能问数 (Text2SQL)、RAG 评测、可嵌入 Chat Widget、Electron 桌面端、LLM 调用级可观测性等能力。

---

## 技术栈

| 层 | 选型 |
|----|------|
| 后端 | FastAPI + SQLAlchemy 2.0 + Pydantic 2 + Python 3.11 |
| 前端 | Next.js 15 App Router + Ant Design 5 + TypeScript 5 |
| AI 运行时 | LangChain 1.0 + LangGraph 1.0 |
| 模型服务 | Ollama (`nomic-embed-text` + `qwen2.5:7b`) + OpenAI 兼容 provider |
| 持久化 | MySQL 8 (`ai_platform` schema) + FAISS (向量) + Elasticsearch 8 (BM25 混合检索) + MinIO (S3-compatible 存储) |
| 桌面端 | Electron + WebSocket |
| Widget | Lit 3 Web Component + esbuild |

---

## 功能模块

**核心**
- **认证 & 多租户** — OAuth2 + JWT 认证、RBAC 角色权限、用户/角色/权限管理
- **知识库 RAG** — 文档上传/解析/分块/向量化;混合检索(向量 + BM25)+ Rerank 精排 + per-KB embedding 工厂
- **KB Workspace + Folder** — 三层侧边栏(`workspace → KB → folder → document`)+ 文档文件夹组织
- **Workspace RBAC** — 19 项 ACL permission + owner / superuser / workspace_id IS NULL 三层 bypass
- **AI Agent** — Agent CRUD、流式对话 (SSE)、工具绑定(5 轮 tool loop)、记忆策略、多 Agent 团队协作(LangGraph `StateGraph`)
- **工作流编排** — LangGraph DAG 执行器、22 个节点、可视化设计器(@xyflow/react)、节点级可观测性 + 真分页
- **MCP 集成** — MCP Server 注册、Tool 发现与执行、Marketplace、HTTP / JSON-RPC 协议、本地 demo server

**内容生成**
- **图片生成** — OpenAI / Stability / Ollama 多 provider 抽象、后台任务、WS 通知
- **视频合成** — ffmpeg 拼装图片 + 字幕 + 音频、celery 异步任务
- **股票素材库** — 30 张预置图片 + 30 首预置 BGM,可直接用于视频合成
- **TTS 语音合成** — Edge TTS / Piper / OpenAI 多 provider 工厂,零 API key 免费
- **SRT 字幕生成** — 中英混合按字符密度分配时间戳
- **Playbook 风格系统** — YAML 驱动的视觉/语音风格 token,自动注入到 image prompt 与 TTS voice

**平台能力**
- **LLM 调用级可观测性** — `LoggingChatModel` 代理 → `llm_call_logs` 表 + `/dashboard/logs` UI
- **Storage 抽象** — Local + S3 双 backend 工厂,默认 MinIO 自托管
- **多模态 Embedding** — `jina-clip-v2` 为主,支持 KB multimodal toggle
- **技能 (Skills)** — 类型化抽象、市场 + 已安装管理、Tool Calling 集成
- **Embedding 模型管理** — ModelConfig 用途标志、Ollama 批量导入、per-KB 工厂
- **模型训练** — NLP (TF-IDF + LR) + Vision (Color Histogram + LR)
- **公众号助手** — 草稿 + AI 创作 + 一键排版 + 微信 API 接入
- **智能问数 (Text2SQL)** — 自然语言转 SQL + SQLGuard 静态校验
- **RAG 评测** — EvalDataset + Runner + Judge LLM 评分 + 看板
- **记忆 & 全局记忆** — 对话级 + 跨会话全局
- **外部应用授权** — 公钥/私钥签发 + Origin 白名单
- **可嵌入 Chat Widget** — `<lumen-chat>` Web Component + 程序化 API
- **Electron 桌面端** — 远程工具执行器 + 本地工具执行器(路径 jail)+ WS 集成

---

## 快速启动

### 端口分配(硬编码,别改)

| 服务 | 端口 | 启动命令 |
|------|------|----------|
| 前端 (Next.js) | **11334** | `cd frontend && npm run dev` |
| 后端 (uvicorn) | **11335** | `cd backend && uvicorn lumen_main:app --port 11335` |
| Ollama | 11434 | `ollama serve`(embedding + chat) |
| 本地 MCP demo | 8765 | `cd backend && python run_mcp_server.py` |
| MinIO | 29000(S3 API)/ 29001(Web Console) | `cd backend && docker compose up -d minio` |

### 启动步骤

```bash
# 1. 启动依赖服务 (6 个 lumen-platform-* 容器: mysql + redis + ollama + es + celery + minio)
cd backend && docker compose up -d

# 2. 拉 Ollama 模型
ollama pull nomic-embed-text && ollama pull qwen2.5:7b

# 3. 初始化 dev 数据库 (schema + ensure_* + demo 数据)
cd backend && python scripts/init_dev_db.py

# 4. (可选) 建 MinIO dev bucket 一次性
docker exec lumen-platform-minio mc alias set local http://localhost:9000 minioadmin minioadmin
docker exec lumen-platform-minio mc mb local/lumen-dev

# 5. 启动后端
cd backend && uvicorn lumen_main:app --port 11335

# 6. 启动前端
cd frontend && npm run dev

# 7. (可选) 启动本地 MCP demo server
cd backend && python run_mcp_server.py
```

API 文档:<http://localhost:11335/docs> · Redoc:<http://localhost:11335/redoc>

**测试用户 / 租户隔离验证 / Docker compose 完整配置** 详见 [`docs/how-to/dev-env.md`](docs/how-to/dev-env.md)。

---

## 架构概览

Lumen AI Platform 是单体仓库(monorepo),4 个子项目 + 1 个共享后端。

```
   frontend/   widget/   electron-desktop/
   (Next.js 15)(Lit 3)   (Electron 33)
       │         │            │
       └────┬────┘            │
            │ HTTP/SSE/WS    │ WS
            ▼                 ▼
   ┌─────────────────────────────────────┐
   │  backend/lumen_main.py (FastAPI)    │
   │  端口 11335 · Swagger /docs         │
   │                                     │
   │  lumen_api/      → 路由 (/api/v1)   │
   │  lumen_services/ → 业务逻辑         │
   │  lumen_models/   → SQLAlchemy ORM   │
   │  lumen_schemas/  → Pydantic 信封    │
   │  lumen_tasks/    → Celery worker    │
   │  lumen_mcp_servers/ → 本地 MCP     │
   │  lumen_tools/    → 工具/执行器      │
   └─────────────────────────────────────┘
            │
            ▼
   MySQL 8 · Redis · Elasticsearch 8 · Ollama · Celery · MinIO
```

### 典型请求数据流(以 chat 为例)

```
[Next.js frontend]
  POST /api/v1/chat/stream  (SSE) — Authorization: Bearer <access_token>
    ▼
[FastAPI router lumen_api/v1/chat.py]
  Pydantic 验证 → 查 conversation → 准备 features (4 步 pipeline)
    ▼
[lumen_services/chat_features.py]
  Step 0: skills 注入
  Step 1: attachments 处理
  Step 2: web_search (可选)
  Step 3: deep_thinking (可选)
  Step 4: agent KB 注入 (可选)
    ▼
[lumen_services/model_loader.py]
  LoggingChatModel 包装 → 记录到 llm_call_logs
  bind_tools → 5 轮 tool call loop
    ▼
[SSE stream back to frontend]
```

每个 endpoint 返回**响应信封**(`SingleResponse[T]` / `PaginatedResponse[T]`),**禁止**直接返 ORM 对象。前端 `res.data.code === 200` 然后 `res.data.data` 拿值。完整规范见 [`docs/explanation/response-envelope.md`](docs/explanation/response-envelope.md)。

---

## 子项目

| 目录 | 端口 | 说明 |
|------|------|------|
| `frontend/` | 11334 | Next.js 15 主控台,业务路由(agent / chat / knowledge / workflow / ...) |
| `widget/` | — | 嵌入式 Chat Widget `<lumen-chat>`,Lit Web Component + esbuild bundle |
| `electron-desktop/` | — | Electron 桌面客户端 |
| `frontend-overview/` | 11337 | 大屏子项目(实时数据可视化) |
| `backend/` | 11335 | FastAPI 后端 (`lumen_main:app` 入口) |
| `docs/` | — | 公开文档 (Diátaxis 结构) |

---

## 数据库

75 张 BASE TABLE,详见 [`docs/reference/database-schema.md`](docs/reference/database-schema.md)。完整 schema DDL 可用 `python backend/scripts/dump_schema_ddl.py` 重新生成。

---

## 主要子系统速览

> 完整端点见 Swagger `http://localhost:11335/docs`。每个子系统都是「前端 `/dashboard/<scope>` + 后端 `/api/v1/<scope>`」完整闭环。

| 子系统 | 前端入口 | 说明 |
|--------|----------|------|
| **视频合成** | `/dashboard/videos` | ffmpeg 拼图+字幕+音频+BGM,celery 异步 |
| **股票素材库 + BGM** | `/dashboard/videos` | 30 张预置图 + 30 首预置 BGM,`tenant_id IS NULL OR =tenant_id` 全局 builtin |
| **RAG 评测** | `/dashboard/eval` + `/runs` | EvalDataset + Celery Runner + Judge LLM 评分 + 实时刷新看板 |
| **KB Workspace + Folder + RBAC** | `/dashboard/knowledge` | 三层侧边栏 + 19 项 ACL + WorkspaceMembersModal |
| **Storage 抽象 (Local + S3)** | (admin-only) | `STORAGE_BACKEND` 切换,默认 MinIO,multipart ≥ 5MB 自动走分片上传 |
| **多模态 Embedding** | `/dashboard/knowledge` KB toggle | `jina-clip-v2` 本地为主,`clip_base_32` 兜底 |
| **智能问数 (Text2SQL)** | `/dashboard/text2sql` | 自然语言转 SQL + SQLGuard 静态校验 |
| **公众号助手** | `/dashboard/wx-publisher` | 草稿 + AI 创作 + 一键排版 + 多账号管理 |
| **客户管理** | `/dashboard/customer` | owner UserSelect + 自定义字段 + 跟进记录 |

---

## 开发规范

### 后端

- 路由:snake_case,挂在 `lumen_api/v1/` 下,统一 `/api/v1` 前缀
- 多租户:每个查询必须 `WHERE tenant_id = current_user.tenant_id`
- 响应信封:`SingleResponse[T]` / `PaginatedResponse[T]`,禁止直接返 ORM

```python
@router.post("/", response_model=SingleResponse[AgentRead])
def create_agent(
    agent: AgentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    return agent_service.create_agent(db, agent, current_user.tenant_id)
```

### 前端

- 组件:PascalCase,放 `components/<feature>/`
- 页面:Next.js App Router,放 `app/dashboard/<feature>/`
- API 调用:走 `services/xxx.ts` 封装,统一 axios + 响应信封处理
- 大组件拆 hooks:`app/dashboard/<feature>/hooks/`(单 hook < 400 LOC),跨 hook 通信走 props-down + callbacks-up,**不上 Context**

```typescript
// services/agent.ts
export const agentApi = {
  list: (params?: AgentListParams) =>
    request.get<AgentListResponse>('/agents/', { params }),
  create: (data: AgentCreate) =>
    request.post<AgentResponse>('/agents/', data),
};
```

### Git

- 分支:`feature/` / `fix/` / `refactor/` / `docs/` / `chore/`
- Commit:`<type>(<scope>): <subject>`,中文
- 一个 commit 做一件事,不要 `--no-verify` 绕过 hooks

---

## 测试

```bash
# 后端
cd backend && pytest                              # 全量
cd backend && pytest tests/unit/                   # 单元
cd backend && pytest tests/integration/            # 集成
cd backend && mypy lumen_api/ lumen_services/ lumen_models/ lumen_core/

# 前端
cd frontend && npm run test:unit                  # vitest
cd frontend && npx tsc --noEmit                   # 类型检查

# Widget
cd widget && npm test
cd widget && npm run ci                           # 构建 + 体积检查 + 测试
```

**测试基线**(M40.1, 2026-10-06):后端 pytest **1502 passed / 8 skipped / 1 xfailed / 0 failed**,前端 vitest **492 passed / 1 pre-existing failed**(`llm-node-skill-picker` placeholder 不匹配,与 M40 评测无关,忽略即可)。

详细基线 + Pre-existing fail 列表见 [`CLAUDE.md` §8](CLAUDE.md)。

---

## 排错

排错内容统一在 [`docs/troubleshooting/`](docs/troubleshooting/) 下:

- [dev-env.md](docs/troubleshooting/dev-env.md) — 启动阶段(端口 / 容器 / Celery / Ollama)
- [uvicorn-zombie.md](docs/troubleshooting/uvicorn-zombie.md) — Windows 专属 uvicorn `--reload` 深度排错
- [common-errors.md](docs/troubleshooting/common-errors.md) — 运行中错误速查
- [performance-tuning.md](docs/troubleshooting/performance-tuning.md) — 性能调优
- [data-recovery.md](docs/troubleshooting/data-recovery.md) — 数据恢复 / fixture 污染清理

---

## 文档

- 项目铁律: [`CLAUDE.md`](CLAUDE.md)
- 公开文档 [`docs/`](docs/) — Diátaxis 结构
  - 主索引: [docs/README.md](docs/README.md) · [docs/SUMMARY.md](docs/SUMMARY.md) · [docs/CHANGELOG.md](docs/CHANGELOG.md)
  - 新人入门: [docs/tutorials/getting-started.md](docs/tutorials/getting-started.md) · [docs/tutorials/first-7-days.md](docs/tutorials/first-7-days.md)
  - 操作指南: [docs/how-to/](docs/how-to/)(dev-env / e2e-screenshots / add-new-skill / add-new-workflow-node / deploy / faq)
  - 参考: [docs/reference/](docs/reference/)(api / database-schema / environment-config)
  - 架构: [docs/explanation/](docs/explanation/)(chat-sse-streaming / embedding-pipeline / error-retry-timeout / observability / response-envelope / storage / tool-calling / workflow-execution)
  - 排错: [docs/troubleshooting/](docs/troubleshooting/)
  - 模块手册: [docs/modules/](docs/modules/)(knowledge-base / agent / workflow / chat / wx-publisher / rag-evaluation / ...)
- 内部归档: `docs-internal/` (本地保留,GitHub 不上传) — 含历史 spec / plan / follow-up review

---

## 相关资源

- [FastAPI 文档](https://fastapi.tiangolo.com/)
- [LangChain 文档](https://python.langchain.com/)
- [LangGraph 文档](https://langchain-ai.github.io/langgraph/)
- [Next.js 文档](https://nextjs.org/docs)
- [Ant Design 文档](https://ant.design/docs/react/introduce)
- [SQLAlchemy 文档](https://docs.sqlalchemy.org/)
- [FAISS 文档](https://github.com/facebookresearch/faiss)
- [Ollama 文档](https://github.com/ollama/ollama)
- [MinIO 文档](https://min.io/docs/minio/linux/index.html)
