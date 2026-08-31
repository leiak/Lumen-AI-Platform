# Lumen AI Platform

流明企业级 AI Agent 平台,完整自托管:**知识库 RAG**、**AI Agent 对话与团队协作**、**可视化工作流编排**、**MCP 协议集成**、**模型训练**、**Electron 桌面端**、**可嵌入 Chat Widget**、**图片生成**、**TTS 语音合成**、**SRT 字幕生成**、**Playbook 风格系统**、**LLM 调用级可观测性**、**公众号助手**、**智能问数 (Text2SQL)**。

---

## 技术栈

| 层 | 选型 |
|----|------|
| 后端 | FastAPI + SQLAlchemy 2.0 + Pydantic 2 + Python 3.11 |
| 前端 | Next.js 15 App Router + Ant Design 5 + TypeScript 5 |
| AI 运行时 | LangChain 1.0 + LangGraph 1.0 |
| 模型服务 | Ollama (`nomic-embed-text` + `qwen2.5:7b`) + OpenAI 兼容 provider |
| 持久化 | MySQL 8 (schema: `ai_platform`) + FAISS (向量) + Elasticsearch 8 (BM25 + 混合检索) |
| 桌面端 | Electron + WebSocket |
| Widget | Lit 3 Web Component + esbuild |

---

## 功能模块

- **认证 & 多租户** — OAuth2 + JWT 认证、RBAC 角色权限、用户/角色/权限管理
- **知识库 RAG** — 文档上传/解析(Docling)/分块/向量化;支持混合搜索(向量+BM25)+ Rerank 精排 + per-KB embedding 工厂
- **KB Workspace + Folder** — Workspace 三层侧边栏(`workspace → KB → folder → document`)+ 文档文件夹组织
- **Workspace RBAC** — 19 项 ACL permission(workspace×5 / KB×4 / folder×5 / document×5)+ owner / superuser / workspace_id IS NULL 三层 bypass + implication 链
- **AI Agent** — Agent CRUD、流式对话(SSE)、工具绑定(5 轮 tool loop)、记忆策略、多 Agent 团队协作(LangGraph `StateGraph`)
- **工作流编排** — LangGraph DAG 执行器、22 个节点(Code / HTTP / Tool / Knowledge Retrieval / Template Transform / Parameter Extractor / Question Classifier / Variable Assigner / Variable Aggregator / ...)、定时触发、模板市场、可视化设计器(@xyflow/react)、节点级可观测性 + 真分页
- **MCP 集成** — MCP Server 注册、Tool 发现与执行、Marketplace、真实 HTTP / JSON-RPC 协议、本地 demo server
- **图片生成** — OpenAI / Stability / Ollama / Stub Provider 抽象、后台任务、WS 通知、缩略图持久化
- **视频合成 (M36)** — ffmpeg 拼装图片 + 字幕 + 音频、`/api/v1/videos/` + `/cancel` + `/download`、celery 异步任务、`composing` 状态机
- **股票素材库 (M36.2.1)** — 30 张预置图片、`/api/v1/stock-assets/*`、`<video>` / `<img>` 走 fetch+blob+createObjectURL Bearer 模式
- **配乐生成 BGM (M36.2.2)** — `stock_musics` 表 + 30 首预置 BGM + MusicPickerModal + 视频合成 `_mux_audio` 自动混音(bgm_volume / fade_in / fade_out_ms)
- **语音合成 (TTS)** — Edge TTS / Piper / OpenAI / Stub 多 provider 工厂(零 API key 免费),FastAPI BackgroundTasks 异步,`/tts/jobs/{id}/audio` Bearer-auth 流式下载
- **字幕生成 (SRT)** — 纯 Python 算法按字符密度分配时间戳,中英混合不报错,可被 VLC 正常解析
- **Playbook 风格系统** — YAML 驱动的视觉/语音风格 token(`keywords` / `palette` / `avoid` / `voice_direction`),自动注入到 image prompt 与 TTS voice direction;5 个内置 playbook(clean-professional / anime-ghibli / cinematic-dark / tech-minimalist / warm-storytelling)
- **LLM 调用级可观测性** — `LoggingChatModel` 代理 5 模块插桩、`llm_call_logs` 表、trace_id 串联、`/dashboard/logs` UI
- **Embedding 调用可观测性** — `LoggingEmbeddings` 代理 → `embedding_call_logs` 表
- **Storage 抽象 (M38.1)** — `lumen_services/storage/` 本地 backend + S3 backend 工厂、STORAGE_BACKEND 切换、admin-only migrate-to-s3 endpoint
- **多模态 Embedding 选型 (M38.4)** — `jina-clip-v2` 1024 dim(HuggingFace transformers 本地)为主、`clip_base_32` 兜底;`multimodal_embedding_configs` + `image_assets` 表 + KB multimodal_enabled 开关
- **技能 (Skills)** — 类型化抽象(Prompt / Script / Http / Tool / Knowledge Retrieval / Workflow / Composite)、市场 + 已安装管理、Tool Calling
- **Embedding 模型管理** — ModelConfig 用途标志、`/models/import-from-ollama` 批量导入、per-KB 工厂;`tenant_id=NULL` 全局 builtin 对所有租户可见
- **模型训练** — NLP (TF-IDF + LR) + Vision (Color Histogram + LR) 训练与预测
- **公众号助手** — 草稿 + AI 创作 + 一键排版 + 微信 API 接入、模板市场、admin-only 永久删除账号
- **智能问数 (Text2SQL)** — 自然语言转 SQL、SQLGuard 静态校验、两阶段 LLM 引擎、安全试执行
- **RAG 评测 (M37)** — EvalDataset / EvalRun / EvalRunner / Celery 异步 + Judge LLM 评分 + Run 看板 + 实时刷新
- **记忆 & 全局记忆** — 对话级记忆 + 跨会话全局记忆
- **外部应用授权** — 公钥/私钥签发 + Origin 白名单
- **可嵌入 Chat Widget** — `<lumen-chat>` Web Component、一行 `<script>` 嵌入、浮动按钮、程序化 API
- **文档生成** — Word / Excel 导出
- **Electron 桌面端** — 远程工具执行器 + 本地工具执行器(路径 jail)+ WS 集成

---

## 快速启动

### 端口分配(硬编码,别改)

| 服务 | 端口 | 启动命令 |
|------|------|----------|
| 前端 (Next.js) | **11334** | `cd frontend && npm run dev` |
| 后端 (uvicorn) | **11335** | `cd backend && uvicorn lumen_main:app --port 11335` |
| Ollama | **11434** | embedding(`nomic-embed-text`) + chat(`qwen2.5:7b`) |
| 本地 MCP demo | 8765 | `cd backend && python run_mcp_server.py` |

### 首次启动步骤

```bash
# 1. 启动依赖服务 (5 个 lumen-platform-* 容器)
cd backend && docker compose up -d

# 2. 拉 Ollama 模型
ollama pull nomic-embed-text && ollama pull qwen2.5:7b

# 3. 初始化 dev 数据库 (schema + 18 ensure_* + demo 数据)
cd backend && python scripts/init_dev_db.py

# 4. 启动后端
cd backend && uvicorn lumen_main:app --port 11335

# 5. 启动前端
cd frontend && npm run dev

# 6. (可选) 启动本地 MCP demo server
cd backend && python run_mcp_server.py
```

API 文档:<http://localhost:11335/docs> · Redoc:<http://localhost:11335/redoc>

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
   MySQL 8 · Redis · Elasticsearch 8 · Ollama · Celery
```

### 典型请求数据流(以 chat 为例)

```
[Next.js frontend]
  POST /api/v1/chat/stream  (SSE)
    Authorization: Bearer <access_token>
    │
    ▼
[FastAPI router lumen_api/v1/chat.py]
  Pydantic 验证 → 查 conversation → 准备 features (4 步 pipeline)
    │
    ▼
[lumen_services/chat_features.py]
  Step 0: skills 注入
  Step 1: attachments 处理
  Step 2: web_search (可选)
  Step 3: deep_thinking (可选)
  Step 4: agent KB 注入 (可选)
    │
    ▼
[lumen_services/model_loader.py]
  LoggingChatModel 包装 → 记录到 llm_call_logs
  bind_tools → 5 轮 tool call loop
    │
    ▼
[SSE stream back to frontend]
```

每个 endpoint 返回**响应信封**:
```python
SingleResponse[T]    # {"code": 200, "data": T}
PaginatedResponse[T] # {"code": 200, "data": {items: [...], total, page, ...}}
```
前端 `res.data.code === 200` 然后 `res.data.data` 拿值。**禁止**直接返 ORM 对象。

### 跨切关注点

| 关注点 | 实现位置 |
|--------|----------|
| 鉴权 | `lumen_api/deps.py` 的 `get_current_user` 依赖,JWT Bearer token,key=`access_token` |
| 多租户 | 所有表带 `tenant_id`,service 层强制 WHERE 过滤 |
| LLM 调用可观测性 | `lumen_core/llm_call_context.py` ContextVar + `LoggingChatModel` 代理 → `llm_call_logs` 表 |
| Embedding 调用可观测性 | `lumen_core/embedding_call_context.py` + `LoggingEmbeddings` 代理 → `embedding_call_logs` 表 |
| Trace 串联 | `trace_id` UUID 透传 chat / widget / agent_team / workflow / image_gen 5 个模块 |

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

## 数据库表

### 业务表

| 表名 | 说明 |
|------|------|
| `tenants` | 租户表 |
| `users` | 用户表 |
| `roles` | 角色表 |
| `permissions` | 权限表 |
| `role_permissions` | 角色权限关联表 |
| `system_settings` | 系统设置表 |
| `security_settings` | 安全设置表 |
| `model_configs` | 模型配置表(用途标志) |

### 核心业务表

| 表名 | 说明 |
|------|------|
| `agents` | Agent 定义表 |
| `agent_tools` | Agent 工具关联表 |
| `agent_knowledge_bases` | Agent 知识库关联表 |
| `knowledge_bases` | 知识库表 |
| `documents` | 文档表 |
| `document_chunks` | 文档分块表 |
| `conversations` | 对话会话表 |
| `messages` | 消息表 |
| `generated_audios` | TTS 合成结果表(M35) |
| `subtitles` | SRT 字幕表(M35) |
| `playbooks` | 风格 Playbook 表(M35) |

### 工作流表

| 表名 | 说明 |
|------|------|
| `workflows` | 工作流定义表 |
| `workflow_runs` | 工作流执行记录表 |
| `workflow_node_runs` | 工作流节点执行记录表 |
| `workflow_templates` | 工作流模板(发布/分类/导入) |

### 训练模块表

| 表名 | 说明 |
|------|------|
| `nlp_classification` | NLP 分类表 |
| `nlp_annotation` | NLP 标注表 |
| `nlp_qa` | NLP 问答表 |
| `vision_classification` | Vision 分类表 |
| `vision_image` | Vision 图像表 |

### MCP / 记忆 / 技能表

| 表名 | 说明 |
|------|------|
| `mcp_servers` | MCP 服务器配置表 |
| `mcp_tools` | MCP 工具定义表 |
| `mcp_tool_executions` | MCP 工具执行日志表 |
| `conversation_memories` | 对话记忆持久化表 |
| `global_memories` | 全局记忆持久化表 |
| `skills` | 技能表 |
| `skill_marketplace` | 技能市场目录表 |
| `installed_skills` | 已安装技能记录表 |

### 多 Agent 协作表

| 表名 | 说明 |
|------|------|
| `agent_teams` | 多 Agent 团队 |
| `agent_team_members` | 团队成员(关联到具体 `agents`) |
| `agent_team_routes` | 团队对话路由策略 |

### KB Workspace / Folder / RBAC 表

| 表名 | 说明 |
|------|------|
| `workspaces` | KB 工作空间,KnowledgeBase.workspace_id NULL-able |
| `workspace_member_permissions` | 19 项 ACL(workspace×5 / KB×4 / folder×5 / document×5)+ implication 链(M38.2.x) |
| `document_folders` | 文档文件夹,Document.folder_id NULL-able(M38.2) |

### RAG 评测表 (M37)

| 表名 | 说明 |
|------|------|
| `eval_datasets` | 评测数据集定义 |
| `eval_dataset_items` | 数据集条目(question / ground_truth / contexts) |
| `eval_runs` | 评测运行记录 + 配置快照 |
| `eval_run_results` | 每条 dataset_item 的运行结果,Judge LLM 评分落库 |

### 公众号助手表 (M32 / M37.1)

| 表名 | 说明 |
|------|------|
| `wx_accounts` | 公众号账号(app_id / app_secret / tenant_id)+ admin-only purge 支持 |
| `wx_templates` | 排版模板 + 11 维 CSS |
| `wx_materials` | 素材库(可来自 KB) |
| `wx_drafts` | 公众号草稿 + AI 创作状态 |
| `wx_draft_sections` | 草稿段落结构 |
| `wx_publish_records` | 发布历史 + 数据回流 |

### 智能问数 / 客户管理 / 系统配置表

| 表名 | 说明 |
|------|------|
| `text2sql_data_sources` | Text2SQL 数据源(数据源 schema 缓存)(M33) |
| `text2sql_queries` | 自然语言查询历史 + 试执行日志 |
| `customers` | 客户主表 + 负责人 Select(M32.1 owner) |
| `customer_field_definitions` | 客户自定义字段定义 |
| `customer_follow_ups` | 客户跟进记录 |
| `system_configs` | 系统级配置(M34)+ HTTP allowlist 域名 |
| `notifications` | 通知中心(WS 推送 + 站内消息) |
| `ppt_tasks` | PPT 解析任务 |

### 多媒体生成 / 素材库 / 多模态 Embedding 表

| 表名 | 说明 |
|------|------|
| `generated_images` | 图片生成产物 |
| `image_assets` | 多模态 image asset(M38.4)+ document_id FK CASCADE + chunk_id FK SET NULL + storage_key |
| `generated_videos` | 视频合成产物(M36)+ status 机(pending/composing/done/failed) |
| `stock_assets` | 股票素材库 30 张预置图(M36.2.1)+ `tenant_id IS NULL OR =tenant_id` 全局 builtin |
| `stock_musics` | BGM 配乐库 30 首(M36.2.2)+ 同样全局 builtin |
| `multimodal_embedding_configs` | 多模态 Embedding 配置(M38.4)+ provider enum(`jina_clip_v2` / `clip_base_32` / `openai_vision` / `qwen_vl` / `nomic_v15` / `azure_vision`) |
| `documents.storage_backend` / `documents.asset_storage_key` | M38.1 storage 抽象 列(M38.1) |

---

## 公众号助手 (WxPublisher)

全流程 AI 驱动的公众号内容工作室。围绕 **选材 → 整理 → 格式 → 发送 → 数据回流** 四步闭环,每步既可独立使用,也可一键串联。

### 4 个核心模块

| 模块 | 定位 | 关键能力 |
|------|------|----------|
| **智能选材与灵感库** | 运营者的"外脑"和"素材水池" | 热点雷达(微博热搜 / 百度指数 / 知乎热榜 / RSS)+ 灵感收集器(浏览器插件 / 微信聊天导入 / 语音转文字)+ 选题工坊(AI 组合多个素材生成角度) |
| **内容整理与 AI 创作** | 碎片素材 → 结构化初稿 | 智能大纲生成(3 种逻辑框架)+ 素材填充 + 风格模仿(学习历史文风)+ 事实核查高亮 + 协作评论 |
| **格式排版与视觉包装** | 一键生成精美排版 | 20+ 模板库 + 一键魔法排版(粘贴纯文本自动解析套版)+ 智能图片优化(压缩 / WebP 转换 / 封面图生成)+ 全真预览(iPhone/安卓微信) |
| **发布与数据追踪** | 安全 + 灵活发布 | 多账号管理 + API 直发(需认证服务号)+ 模拟群发(个人订阅号弹窗提醒)+ 定时发布 + 合规检查(敏感词 / 死链 / 原创检测)+ 数据回流 + 智能复盘报告 |

### 关键工作流

```
[热点/素材源] → [灵感库&选题推荐] → [AI辅助成文/改写] → [一键排版+样式模板] → [预览/定时/多账号群发] → [发布效果跟踪]
```

### 风险与对策

- **API 群发限制**:订阅号每天 1 次,服务号每月 4 次。助手需提示余量,支持"仅存草稿"。
- **内容同质化风险**:过度依赖 AI 会导致面孔模糊。强调"人工主导,AI 辅助"。
- **版权风险**:采集素材明确记录来源,成文时自动生成引用标注。

---

## 主要子系统速览

> 完整端点见 Swagger `http://localhost:11335/docs`。每个子系统都是「前端 `/dashboard/<scope>` + 后端 `/api/v1/<scope>`」完整闭环。

| 子系统 | 关键端点 | 前端入口 | 说明 |
|--------|----------|----------|------|
| **视频合成 (M36)** | `POST /api/v1/videos/` · `/cancel` · `/download` | `/dashboard/videos` | ffmpeg 拼图+字幕+音频,celery 异步;`<video>` 走 fetch+blob+createObjectURL Bearer 模式 |
| **股票素材库 (M36.2.1)** | `GET /api/v1/stock-assets/*` | `/dashboard/videos` ComposeModal「从素材库选」 | 30 张预置图,`tenant_id IS NULL OR =tenant_id` 全局 builtin |
| **配乐生成 BGM (M36.2.2)** | `GET /api/v1/stock-musics/*` | MusicPickerModal + ComposeModal BGM toggle | 30 首预置 BGM + ffmpeg amix 自动混音(`bgm_volume` / fade_in / fade_out_ms) |
| **RAG 评测 (M37)** | `/api/v1/eval/datasets` · `/runs` · `/runs/{id}` · `/runs/{id}/watch` | `/dashboard/eval` + `/runs` | EvalDataset + Celery Runner + Judge LLM 评分 + 实时刷新看板 |
| **KB Workspace + Folder (M38.2)** | `/api/v1/workspaces` · `/folders` · `/api/v1/knowledge/workspaces` | `/dashboard/knowledge` 三层侧边栏 | `workspace → KB → folder → document` 树状组织 |
| **Workspace RBAC (M38.2.x)** | `/api/v1/workspaces/{id}/members` · `/permissions` · `/transfer-ownership` | WorkspaceMembersModal + TransferOwnershipModal | 19 项 ACL + 4 预设 + 30s 倒计时所有权转让 |
| **Storage 抽象 (M38.1)** | `/api/v1/storage/{health,local/<key>,migrate-to-s3}` | (admin-only) | LocalBackend + S3Backend 工厂,`STORAGE_BACKEND` 切换 |
| **多模态 Embedding (M38.4)** | `/api/v1/multimodal-embedding-configs` | `/dashboard/knowledge` KB multimodal toggle | `jina-clip-v2` 1024 dim 本地为主,`clip_base_32` 兜底 |
| **智能问数 (M33)** | `/api/v1/text2sql/data-sources` · `/queries` | `/dashboard/text2sql` | Text2SQL + SQLGuard 静态校验 + 试执行 |
| **客户管理** | `/api/v1/customers` · `/field-definitions` · `/follow-ups` | `/dashboard/customer` | owner UserSelect + 自定义字段 + 跟进记录 |

---

## 开发环境配置

### 前置条件

| 软件 | 版本 | 说明 |
|------|------|------|
| Python | 3.11+ | 后端运行时 |
| Node.js | 18+ | 前端运行时 |
| MySQL | 8.0+ | 关系数据库 |
| Ollama | Latest | 本地 LLM 服务(embedding + chat) |
| Docker | Latest | 容器化 (推荐) |

### 后端环境变量

在 `backend/.env` 配置:

```env
# 数据库
DATABASE_URL=mysql+pymysql://root:rootpassword@localhost:3307/ai_platform

# JWT
SECRET_KEY=<your-secret-key>
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30

# Ollama (用于 embedding 和 chat 模型)
OLLAMA_API_BASE=http://localhost:11434
```

### 前端环境变量

在 `frontend/.env.local`:

```env
NEXT_PUBLIC_API_BASE=http://localhost:11335/api/v1
```

### Ollama 模型

```bash
# 启动 Ollama 服务
ollama serve

# 拉取 embedding 模型
ollama pull nomic-embed-text

# 拉取聊天模型
ollama pull qwen2.5:7b
```

### FAISS 向量库

FAISS 索引文件存于 `backend/data/faiss/`(`knowledge_base.index` + `.meta`),通过 `nomic-embed-text` 模型向量化。

### Docker 启动(推荐)

```bash
# 启动所有服务 (5 个 lumen-platform-* 容器)
cd backend && docker compose up -d

# 查看服务状态
docker ps --filter "name=lumen-platform-"

# 停止服务
bash scripts/dev-down.sh
```

---

## 开发规范

### 后端规范

- **路由**:snake_case,挂在 `lumen_api/v1/` 下,统一 `/api/v1` 前缀
- **模型类**:PascalCase,位于 `lumen_models/`
- **函数**:snake_case
- **多租户**:每个查询必须 `WHERE tenant_id = current_user.tenant_id`
- **响应信封**:每个 endpoint 用 `SingleResponse[T]` 或 `PaginatedResponse[T]` 包装,禁止直接返 ORM 对象

```python
@router.post("/", response_model=SingleResponse[AgentRead])
def create_agent(
    agent: AgentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    return agent_service.create_agent(db, agent, current_user.tenant_id)
```

### 前端规范

- **组件**:PascalCase,放 `components/`
- **页面**:Next.js App Router,放 `app/dashboard/`
- **API 调用**:走 `services/xxx.ts` 封装,统一 axios + 响应信封处理

```typescript
// services/agent.ts
export const agentApi = {
  list: (params?: AgentListParams) =>
    request.get<AgentListResponse>('/agents/', { params }),
  create: (data: AgentCreate) =>
    request.post<AgentResponse>('/agents/', data),
};
```

### Git 规范

- **分支**:`feature/` / `fix/` / `refactor/` / `docs/` / `chore/`
- **Commit**:`<type>(<scope>): <subject>`,中文

---

## 开发环境排错

### 症状:Uvicorn 11335 端口被占,新进程启动后接口返空

详见下方 [Uvicorn zombie 排错](#uvicorn-zombie-排错)。

**快速处理**:
1. `netstat -ano | grep :11335 | grep LISTENING` 看 PID
2. `powershell -NoProfile -Command "Stop-Process -Id <pid>"` 杀旧 worker
3. `cd backend && nohup uvicorn lumen_main:app --port 11335 > /tmp/uv.log 2>&1 & disown`
4. `curl http://localhost:11335/` 确认 `{"message":"Lumen AI Platform API",...}`

### 症状:Docker 容器重启后 mysql / redis / ollama 没起来

```bash
bash scripts/dev-up.sh   # 拉起 5 个 lumen-platform-* 容器,等 ES green/yellow,等 celery ready
bash scripts/dev-down.sh [--keep-base]   # 停服
```

### 症状:Celery worker 启动后 ImportError "partially initialized module"

根因:`celery_app.py` 模块级 import `document_tasks` 形成循环。

**修法**:`Celery(..., include=["lumen_tasks.document_tasks"])` 让 Celery worker 启动时再 import 任务模块。

### 症状:Ollama 模型没拉,Knowledge Base ingest 失败

```bash
docker exec lumen-platform-ollama ollama pull nomic-embed-text
docker exec lumen-platform-ollama ollama pull qwen2.5:7b
```

### 症状:前端 `11334` 起不来,报端口占用

```bash
netstat -ano | grep :11334 | grep LISTENING
powershell -NoProfile -Command "Stop-Process -Id <pid>"
```

Next.js dev 不会留 zombie,直接 Ctrl+C 重启即可。

### 症状:pytest 跑不通,MySQL 报错 "Table doesn't exist"

```bash
cd backend && python scripts/init_dev_db.py
```

会跑 18 个 `ensure_*()` 函数 + seed 默认 model configs / 默认 tenant / 默认 admin 用户 / 默认 MCP demo。

### 症状:某个 endpoint 405 Method Not Allowed

先看 `curl http://localhost:11335/openapi.json | python -c "import sys,json; d=json.load(sys.stdin); [print(m,p) for p in d['paths'] for m in d['paths'][p]]"` 确认路由真的注册了。

如果 openapi 里没有 = 后端没加载新代码 = uvicorn 没 reload,通常是 zombie 或忘记 `--reload`。

### 症状:Widget 构建失败 / dist 不存在

```bash
cd widget && npm install && npm run build
# 输出 dist/lumen-chat.js (IIFE) + dist/lumen-chat.esm.js
```

后端 FastAPI 会 mount `widget/dist/` 到 `/static/widget/`(见 `lumen_main.py` 的 `_widget_dir` 逻辑)。

### 症状:LangSmith tracing 不工作

`backend/.env` 设 `LANGSMITH_API_KEY=...` + `LANGSMITH_TRACING=true`。项目所有 LLM 调用都过 LangChain,会自动 trace。

### 进一步

- 真不行 → 跑 `bash scripts/dev-down.sh && bash scripts/dev-up.sh` 全栈重启

---

## Uvicorn zombie 排错

> **问题类型**:Windows 开发环境
> **症状**:后端改完代码无法重启,`taskkill` 也杀不掉,端口一直被占着

### 症状

- `taskkill /F /PID <pid>` 提示"已终止"
- `Get-NetTCPConnection -LocalPort <port>` 显示端口仍被 LISTENING
- `Get-Process -Id <pid>` 查不到这个 PID
- `python -m uvicorn ... --port <port>` 启动报 `address already in use`

### 根因

Windows 上 `uvicorn --reload`(用 `StatReload`)偶尔会出这个 bug:

1. uvicorn 启动两个进程:父 reloader + 子 worker
2. `StatReload` 检测代码改动,**子 worker 先重启**
3. 子 worker 偶尔卡住或异常退出,父 reloader 收不到信号
4. 父 reloader 自己死掉,但 Windows 内核仍把 LISTENING socket 算在它头上
5. 孤儿 worker 子进程还在,但已经不服务请求

### 排查步骤

```bash
# 1. 找到占着端口的 PID(zombie 父 reloader)
netstat -ano | findstr ":11335.*LISTENING"

# 2. 用 CIM 找这个 PID 的子进程(孤儿 worker)
powershell -Command "(Get-CimInstance Win32_Process -Filter 'Name = \"python.exe\"') | Format-Table ProcessId, CommandLine -AutoSize -Wrap"
# 看 CommandLine 里 parent_pid 等于 zombie PID 的那行

# 3. 杀 worker 子进程(不是 zombie 父进程,taskkill 找不到父进程)
powershell -NoProfile -Command "Stop-Process -Id <worker-pid>"

# 4. 验证端口释放
netstat -ano | findstr ":11335.*LISTENING"
# 应该没有输出

# 5. 重新启动
cd backend && python -m uvicorn lumen_main:app --host 0.0.0.0 --port 11335 --reload
```

### 备选方案

如果 zombie 实在清不掉:
- 重启电脑(最暴力有效)
- `netsh winsock reset` 然后重启(需管理员,会清网络配置)
- 临时换端口启动(hack,但能继续开发)

---

## E2E 截图验证

> **目的**:用 Playwright + 本机 Chromium headless shell 启动浏览器 → 自动登录 → 截图任意前端页面 → 视觉验证 UI 改动

### 一键跑

```bash
# 假设 dev 服务 11335/11334 已起来
cd frontend && node --dns-result-order=ipv4first e2e/render-preview-screenshot.cjs
# → 输出 imgs/<feature>-desktop.png + <feature>-mobile.png
```

### 工具栈

| 工具 | 安装位置 |
|------|----------|
| `playwright` ^1.61 | `frontend/node_modules/playwright` (devDep) |
| `chromium_headless_shell-1223` | `C:/Users/wma19/AppData/Local/ms-playwright/` |

### 关键踩坑

- **必须加 `--dns-result-order=ipv4first`**:Node 22 默认 IPv6 优先 `::1`,但 uvicorn 只 listen `127.0.0.1` (IPv4),否则 `ECONNREFUSED`
- **卡死在 10%?** 多半是 `__dirlock` 死锁,删锁重试:
  ```bash
  rm -rf "$LOCALAPPDATA/ms-playwright/__dirlock"
  npx playwright install chromium-headless-shell
  ```

---

## 测试

### 运行测试

```bash
# 后端
cd backend && pytest                    # 全量
cd backend && pytest tests/unit/         # 单元
cd backend && pytest tests/integration/ # 集成
cd backend && pytest tests/unit/test_xxx.py -v  # 单文件

# 前端
cd frontend && npm run test:unit

# Widget
cd widget && npm test
```

### 编写新测试

```python
# tests/unit/test_example.py
import pytest

class TestExample:
    def test_basic(self):
        assert True

    def test_with_fixture(self, mock_db):
        result = some_function()
        assert result is not None
```

### 测试基线(M37.1,2026-08-07)

| 套件 | 基线 | 备注 |
|------|------|------|
| 后端 pytest | **1502 passed / 8 skipped / 1 xfailed / 0 failed** | 321s(5min21s);含 M37 3 个 wx_account admin purge 测试 |
| 前端 vitest | **492 passed / 1 failed** | 530s(8min50s),1 个 pre-existing fail(`llm-node-skill-picker` placeholder 不匹配,**与 M37 无关**) |
| 后端 mypy | 0 error(新文件) | `lumen_core/__init__.py` + `lumen_models/base.py` 共 5 个 pre-existing error 与新文件无关 |
| 前端 tsc | 0 error | `frontend` + `widget` 双 `tsc --noEmit` |

> 详见 `CLAUDE.md §8 测试`。测试代码风格参考 `backend/tests/unit/` + `frontend/__tests__/`,新写 fixture 必带 teardown(参 `test_agent_team_logs_call.py`)。

---

## 常用开发命令

| 用途 | 命令 |
|------|------|
| 后端测试 | `cd backend && pytest` |
| 前端测试 | `cd frontend && npm run test:unit` |
| Widget 测试 | `cd widget && npm test` |
| Widget CI(构建 + 体积检查 + 测试)| `cd widget && npm run ci` |
| 后端类型检查 | `cd backend && mypy lumen_api/ lumen_services/ lumen_models/ lumen_core/` |
| 前端类型检查 | `cd frontend && npx tsc --noEmit` |
| 重置 dev 数据库 | `cd backend && python scripts/init_dev_db.py` |
| 启动 dev 容器 | `bash scripts/dev-up.sh` |
| 停止 dev 容器 | `bash scripts/dev-down.sh` |

---

### 测试用户（租户隔离验证）

登录 API: `POST /api/v1/auth/login`（表单: `username`, `password`）

| username | password | tenant_id | 用途 |
|----------|----------|-----------|------|
| `tenant1_user1` | `test123` | 1 | 租户1普通用户 |
| `tenant1_user2` | `test123` | 1 | 租户1普通用户 |
| `tenant2_user1` | `test123` | 2 | 租户2普通用户 |
| `tenant2_user2` | `test123` | 2 | 租户2普通用户 |
| `admin` | `admin` | 1 | 租户1超级管理员（默认）|

**验证租户隔离示例**（curl）:

```bash
# 租户1登录
T1_TOKEN=$(curl -s -X POST http://localhost:11335/api/v1/auth/login \
  -d "username=tenant1_user1&password=test123" | python -c "import sys,json; print(json.load(sys.stdin)['data']['access_token'])")

# 租户2登录
T2_TOKEN=$(curl -s -X POST http://localhost:11335/api/v1/auth/login \
  -d "username=tenant2_user1&password=test123" | python -c "import sys,json; print(json.load(sys.stdin)['data']['access_token'])")

# 租户1创建 Agent
curl -X POST http://localhost:11335/api/v1/agents/ \
  -H "Authorization: Bearer $T1_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"my-agent","description":"test","prompt_template":"hi","model_name":"test","temperature":1,"memory_policy":"window","memory_window_size":10,"memory_max_tokens":1000,"memory_compression":false,"tool_choice":"auto","tool_choice_required":false,"allowed_tools":[]}'

# 租户2列出 Agents（不应看到租户1的）
curl http://localhost:11335/api/v1/agents/ -H "Authorization: Bearer $T2_TOKEN"

# 租户1尝试访问租户2的 Agent（应返回 404）
curl http://localhost:11335/api/v1/agents/{id} -H "Authorization: Bearer $T1_TOKEN"
```

---

## 文档

- 项目铁律: [`CLAUDE.md`](CLAUDE.md)
- **公开文档** [`docs/`](docs/) — Diátaxis 结构
  - 主索引: [docs/README.md](docs/README.md) · [docs/SUMMARY.md](docs/SUMMARY.md) · [docs/CHANGELOG.md](docs/CHANGELOG.md)
  - 新人入门: [docs/tutorials/getting-started.md](docs/tutorials/getting-started.md) · [docs/tutorials/first-7-days.md](docs/tutorials/first-7-days.md)
  - 操作指南: [docs/how-to/dev-env.md](docs/how-to/dev-env.md) · [docs/how-to/e2e-screenshots.md](docs/how-to/e2e-screenshots.md) · [docs/how-to/add-new-skill.md](docs/how-to/add-new-skill.md) · [docs/how-to/add-new-workflow-node.md](docs/how-to/add-new-workflow-node.md) · [docs/how-to/deploy.md](docs/how-to/deploy.md) · [docs/how-to/faq.md](docs/how-to/faq.md)
  - 参考: [docs/reference/api.md](docs/reference/api.md) · [docs/reference/database-schema.md](docs/reference/database-schema.md) · [docs/reference/environment-config.md](docs/reference/environment-config.md)
  - 架构: [docs/explanation/chat-sse-streaming.md](docs/explanation/chat-sse-streaming.md) · [docs/explanation/embedding-pipeline.md](docs/explanation/embedding-pipeline.md) · [docs/explanation/error-retry-timeout.md](docs/explanation/error-retry-timeout.md) · [docs/explanation/observability.md](docs/explanation/observability.md) · [docs/explanation/response-envelope.md](docs/explanation/response-envelope.md) · [docs/explanation/tool-calling.md](docs/explanation/tool-calling.md) · [docs/explanation/workflow-execution.md](docs/explanation/workflow-execution.md)
  - 排错: [docs/troubleshooting/uvicorn-zombie.md](docs/troubleshooting/uvicorn-zombie.md) · [docs/troubleshooting/common-errors.md](docs/troubleshooting/common-errors.md) · [docs/troubleshooting/data-recovery.md](docs/troubleshooting/data-recovery.md) · [docs/troubleshooting/performance-tuning.md](docs/troubleshooting/performance-tuning.md)
- Widget: [`widget/README.md`](widget/README.md)
- 内部归档: `docs-internal/` (本地保留,GitHub 不上传) — 含历史 spec / plan / follow-up review / 抓取的 LangGraph + Agents-Flex 参考

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
