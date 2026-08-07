# 功能清单

> 截至 M37(2026-08-06),Lumen AI Platform 全部模块的功能清单。
>
> **状态**:✅ Shipped · 🚧 In Progress · 📋 Planned
> **优先级**:P0 核心(必做)· P1 重要 · P2 加分 · P3 探索

---

## 1. 平台基础(7 项)

| # | 功能 | 状态 | 优先级 | 模块文档 |
|---|------|------|--------|---------|
| 1.1 | OAuth2 + JWT 认证 | ✅ | P0 | [auth-and-rbac](../modules/auth-and-rbac.md) |
| 1.2 | 多租户隔离 | ✅ | P0 | [multi-tenant](../architecture/04-multi-tenant.md) |
| 1.3 | RBAC 角色权限矩阵 | ✅ | P0 | [auth-and-rbac](../modules/auth-and-rbac.md) |
| 1.4 | 用户/角色/权限 CRUD | ✅ | P0 | [auth-and-rbac](../modules/auth-and-rbac.md) |
| 1.5 | 系统设置(SystemConfig) | ✅ | P0 | [system-config](../modules/system-config.md) |
| 1.6 | 通知中心(WS 推送 + 抽屉) | ✅ | P0 | [notification](../modules/notification.md) |
| 1.7 | LLM 调用级日志 + trace_id | ✅ | P0 | [llm-call-logs](../modules/llm-call-logs.md) |
| 1.8 | 邀请码接受 | 📋 | P1 | (计划) |

---

## 2. AI Agent 模块(8 项)

| # | 功能 | 状态 | 优先级 | 模块文档 |
|---|------|------|--------|---------|
| 2.1 | Agent CRUD(创建/编辑/删除/启停) | ✅ | P0 | [agent](../modules/agent.md) |
| 2.2 | Agent 流式对话(SSE) | ✅ | P0 | [chat](../modules/chat.md) |
| 2.3 | 系统提示词模板 | ✅ | P0 | [agent](../modules/agent.md) |
| 2.4 | 工具调用 5 轮 tool loop | ✅ | P0 | [tool-calling](../explanation/tool-calling.md) |
| 2.5 | 记忆策略(4 种) | ✅ | P0 | [memory](../modules/memory.md) |
| 2.6 | 知识库关联(多 KB) | ✅ | P0 | [knowledge-base](../modules/knowledge-base.md) |
| 2.7 | 多 Agent 团队 + 路由 | ✅ | P1 | [agent-team](../modules/agent-team.md) |
| 2.8 | Agent 选择策略(auto/required/none/specific) | ✅ | P0 | [agent](../modules/agent.md) |

---

## 3. 知识库 RAG(10 项)

| # | 功能 | 状态 | 优先级 | 模块文档 |
|---|------|------|--------|---------|
| 3.1 | 知识库 CRUD | ✅ | P0 | [knowledge-base](../modules/knowledge-base.md) |
| 3.2 | 文档上传(PDF/DOCX/Excel/MD/TXT) | ✅ | P0 | [knowledge-base](../modules/knowledge-base.md) |
| 3.3 | Docling 文档解析 | ✅ | P0 | [embedding-pipeline](../explanation/embedding-pipeline.md) |
| 3.4 | 智能切块(按段/按长度) | ✅ | P0 | [knowledge-base](../modules/knowledge-base.md) |
| 3.5 | Embedding 向量化(per-KB 模型) | ✅ | P0 | [knowledge-base](../modules/knowledge-base.md) |
| 3.6 | FAISS + Elasticsearch 混合检索 | ✅ | P0 | [knowledge-base](../modules/knowledge-base.md) |
| 3.7 | Rerank 精排 | ✅ | P1 | [knowledge-base](../modules/knowledge-base.md) |
| 3.8 | Per-KB 检索配置(top_k / score) | ✅ | P0 | [knowledge-base](../modules/knowledge-base.md) |
| 3.9 | FAQ 管理 | ✅ | P1 | [knowledge-base](../modules/knowledge-base.md#faq) |
| 3.10 | 知识库搜索权重 4 滑块 | ✅ | P1 | [knowledge-base](../modules/knowledge-base.md) |

---

## 4. 工作流(15 项)

| # | 功能 | 状态 | 优先级 | 模块文档 |
|---|------|------|--------|---------|
| 4.1 | 可视化设计器(React Flow) | ✅ | P0 | [workflow](../modules/workflow.md) |
| 4.2 | 22 节点 | ✅ | P0 | [workflow-nodes](../modules/workflow-nodes.md) |
| 4.3 | DAG 执行器(LangGraph) | ✅ | P0 | [workflow-execution](../explanation/workflow-execution.md) |
| 4.4 | 错误处理(error_strategy) | ✅ | P0 | [error-retry-timeout](../explanation/error-retry-timeout.md) |
| 4.5 | 重试(retry_config) | ✅ | P0 | [error-retry-timeout](../explanation/error-retry-timeout.md) |
| 4.6 | 节点级超时 | ✅ | P0 | [error-retry-timeout](../explanation/error-retry-timeout.md) |
| 4.7 | undo/redo | ✅ | P1 | [workflow](../modules/workflow.md#undo-redo) |
| 4.8 | auto-layout(自动布局) | ✅ | P1 | [workflow](../modules/workflow.md#auto-layout) |
| 4.9 | 真并行节点 | ✅ | P1 | [workflow](../modules/workflow.md#并行执行) |
| 4.10 | 断点续跑(resume) | ✅ | P1 | [workflow](../modules/workflow.md#断点续跑) |
| 4.11 | 定时触发(schedule) | ✅ | P1 | [workflow](../modules/workflow.md#定时触发) |
| 4.12 | 模板市场(publish/install) | ✅ | P1 | [workflow](../modules/workflow.md#模板市场) |
| 4.13 | Run 详情 + 节点级 BFS 日志 | ✅ | P0 | [workflow](../modules/workflow.md#监控) |
| 4.14 | 节点输入值手动测试 | ✅ | P1 | [workflow](../modules/workflow.md#节点测试) |
| 4.15 | 工作流市场(workflow marketplace) | ✅ | P2 | [workflow](../modules/workflow.md#市场) |

---

## 5. 媒体流水线(12 项)

| # | 功能 | 状态 | 优先级 | 模块文档 |
|---|------|------|--------|---------|
| 5.1 | AI 图片生成(4 provider) | ✅ | P0 | [image-generation](../modules/image-generation.md) |
| 5.2 | 图片详情 Modal + 重新生成 | ✅ | P0 | [image-generation](../modules/image-generation.md) |
| 5.3 | TTS 语音合成(Edge/Piper/OpenAI/Stub) | ✅ | P0 | [tts](../modules/tts.md) |
| 5.4 | TTS 流式下载(Bearer 鉴权) | ✅ | P0 | [tts](../modules/tts.md) |
| 5.5 | SRT 字幕生成(中英混合) | ✅ | P1 | [subtitle](../modules/subtitle.md) |
| 5.6 | 视频合成(ffmpeg 拼装) | ✅ | P1 | [video-composition](../modules/video-composition.md) |
| 5.7 | 视频合成取消 + 下载 | ✅ | P1 | [video-composition](../modules/video-composition.md) |
| 5.8 | 股票素材库(30 张预置图) | ✅ | P1 | [stock-assets](../modules/stock-assets.md) |
| 5.9 | Playbook 视觉风格(5 内置) | ✅ | P1 | [playbook](../modules/playbook.md) |
| 5.10 | Playbook 语音风格 + 关键词 | ✅ | P1 | [playbook](../modules/playbook.md) |
| 5.11 | 缩略图持久化 | ✅ | P1 | [image-generation](../modules/image-generation.md) |
| 5.12 | 媒体凭证管理 | ✅ | P0 | [model-management](../modules/model-management.md) |

---

## 6. 技能市场(8 项)

| # | 功能 | 状态 | 优先级 | 模块文档 |
|---|------|------|--------|---------|
| 6.1 | 技能类型化抽象(7 类型) | ✅ | P0 | [skill-market](../modules/skill-market.md) |
| 6.2 | 技能浏览 + 搜索 | ✅ | P0 | [skill-market](../modules/skill-market.md) |
| 6.3 | 技能安装(租户级 / 平台级) | ✅ | P0 | [skill-market](../modules/skill-market.md) |
| 6.4 | 技能详情(按 type 渲染) | ✅ | P0 | [skill-market](../modules/skill-market.md) |
| 6.5 | 技能管理(CRUD) | ✅ | P0 | [skill-market](../modules/skill-market.md) |
| 6.6 | Tool Calling 技能 | ✅ | P0 | [skill-market](../modules/skill-market.md) |
| 6.7 | 技能 HTTP 节点白名单 | ✅ | P1 | [skill-market](../modules/skill-market.md) |
| 6.8 | 15 个内置种子技能 | ✅ | P0 | [skill-market](../modules/skill-market.md#种子) |

---

## 7. MCP 集成(6 项)

| # | 功能 | 状态 | 优先级 | 模块文档 |
|---|------|------|--------|---------|
| 7.1 | MCP Server 注册 | ✅ | P0 | [mcp](../modules/mcp.md) |
| 7.2 | 工具发现 + 列表 | ✅ | P0 | [mcp](../modules/mcp.md) |
| 7.3 | 工具执行(JSON-RPC over HTTP/WS) | ✅ | P0 | [mcp](../modules/mcp.md) |
| 7.4 | Marketplace | ✅ | P1 | [mcp](../modules/mcp.md) |
| 7.5 | 本地 demo server(6 工具) | ✅ | P1 | [mcp](../modules/mcp.md#本地-demo) |
| 7.6 | MCP 远程工具(供 Electron 调用) | ✅ | P1 | [electron-desktop](../architecture/02-module-topology.md#electron-桌面端) |

---

## 8. 模型管理(8 项)

| # | 功能 | 状态 | 优先级 | 模块文档 |
|---|------|------|--------|---------|
| 8.1 | LLM 模型 CRUD | ✅ | P0 | [model-management](../modules/model-management.md) |
| 8.2 | Embedding 模型管理 | ✅ | P0 | [model-management](../modules/model-management.md) |
| 8.3 | Ollama 一键导入 | ✅ | P0 | [model-management](../modules/model-management.md) |
| 8.4 | 用途标志(is_chat/is_embedding/is_image/is_tts) | ✅ | P0 | [model-management](../modules/model-management.md) |
| 8.5 | 默认模型 | ✅ | P0 | [model-management](../modules/model-management.md) |
| 8.6 | 模型凭证管理(SecretStr) | ✅ | P0 | [model-management](../modules/model-management.md) |
| 8.7 | NLP 训练(TF-IDF + LR) | ✅ | P1 | [model-training](../modules/model-training.md) |
| 8.8 | 视觉训练(Color Histogram + LR) | ✅ | P1 | [model-training](../modules/model-training.md) |

---

## 9. 记忆系统(4 项)

| # | 功能 | 状态 | 优先级 | 模块文档 |
|---|------|------|--------|---------|
| 9.1 | 对话级记忆(memory_policy 4 种) | ✅ | P0 | [memory](../modules/memory.md) |
| 9.2 | 全局记忆(跨会话) | ✅ | P1 | [memory](../modules/memory.md#全局记忆) |
| 9.3 | 记忆浏览 + 增删 | ✅ | P1 | [memory](../modules/memory.md) |
| 9.4 | 记忆压缩(semantic) | ✅ | P2 | [memory](../modules/memory.md) |

---

## 10. 外部应用授权(6 项)

| # | 功能 | 状态 | 优先级 | 模块文档 |
|---|------|------|--------|---------|
| 10.1 | 外部应用 CRUD | ✅ | P0 | [external-app-auth](../modules/external-app-auth.md) |
| 10.2 | 公私钥签发 | ✅ | P0 | [external-app-auth](../modules/external-app-auth.md) |
| 10.3 | Agent 白名单 | ✅ | P0 | [external-app-auth](../modules/external-app-auth.md) |
| 10.4 | Origin 白名单 | ✅ | P0 | [external-app-auth](../modules/external-app-auth.md) |
| 10.5 | Widget 嵌入(`<lumen-chat>`) | ✅ | P0 | [external-app-auth](../modules/external-app-auth.md#widget) |
| 10.6 | 外部访客追踪 | ✅ | P1 | [external-app-auth](../modules/external-app-auth.md#访客) |

---

## 11. 客户 CRM(7 项)

| # | 功能 | 状态 | 优先级 | 模块文档 |
|---|------|------|--------|---------|
| 11.1 | 客户档案 | ✅ | P1 | [customer-crm](../modules/customer-crm.md) |
| 11.2 | 客户跟进记录 | ✅ | P1 | [customer-crm](../modules/customer-crm.md) |
| 11.3 | 负责人分配(OwnerUserSelect) | ✅ | P1 | [customer-crm](../modules/customer-crm.md) |
| 11.4 | 自定义字段(每租户) | ✅ | P1 | [customer-crm](../modules/customer-crm.md) |
| 11.5 | 客户级别 / 来源 / 标签 | ✅ | P1 | [customer-crm](../modules/customer-crm.md) |
| 11.6 | 跟进提醒 | ✅ | P2 | [customer-crm](../modules/customer-crm.md) |
| 11.7 | AI 建议跟进 | ✅ | P2 | [customer-crm](../modules/customer-crm.md) |

---

## 12. 营销自动化(3 项)

| # | 功能 | 状态 | 优先级 | 模块文档 |
|---|------|------|--------|---------|
| 12.1 | 公众号助手(草稿 + AI 改写 + 微信 API) | ✅ | P1 | [wx-publisher](../modules/wx-publisher.md) |
| 12.2 | 公众号模板市场(11 维 CSS 排版) | ✅ | P1 | [wx-publisher](../modules/wx-publisher.md#模板) |
| 12.3 | 公众号素材库 | ✅ | P1 | [wx-publisher](../modules/wx-publisher.md#素材) |

---

## 13. 数据智能(3 项)

| # | 功能 | 状态 | 优先级 | 模块文档 |
|---|------|------|--------|---------|
| 13.1 | 智能问数(NL→SQL) | ✅ | P1 | [text2sql](../modules/text2sql.md) |
| 13.2 | SQLGuard 静态校验 | ✅ | P1 | [text2sql](../modules/text2sql.md#sqlguard) |
| 13.3 | RAG 评测(数据集 + Run + 看板) | ✅ | P1 | [rag-evaluation](../modules/rag-evaluation.md) |

---

## 14. 多端交付(3 项)

| # | 功能 | 状态 | 优先级 | 模块文档 |
|---|------|------|--------|---------|
| 14.1 | Web 后台(Next.js 15) | ✅ | P0 | [architecture](../architecture/00-overview.md#前端) |
| 14.2 | 桌面端(Electron 33) | ✅ | P1 | [external-app-auth](../modules/external-app-auth.md#electron) |
| 14.3 | Widget(`<lumen-chat>` Lit) | ✅ | P1 | [external-app-auth](../modules/external-app-auth.md#widget) |

---

## 15. 导出(4 项)

| # | 功能 | 状态 | 优先级 | 模块文档 |
|---|------|------|--------|---------|
| 15.1 | 文档生成(Word/Excel) | ✅ | P2 | [system-config](../modules/system-config.md#导出) |
| 15.2 | Markdown 导出 | ✅ | P1 | [export-markdown](..) |
| 15.3 | PDF 导出 | ✅ | P2 | [export-pdf](..) |
| 15.4 | PPT 渲染 | ✅ | P2 | [system-config](../modules/system-config.md#ppt) |

---

## 16. 系统基础(8 项)

| # | 功能 | 状态 | 优先级 | 模块文档 |
|---|------|------|--------|---------|
| 16.1 | 动态 CORS 中间件 | ✅ | P0 | [dynamic-cors](../architecture/05-auth-rbac.md#cors) |
| 16.2 | 限流(rate limiter) | ✅ | P1 | [architecture](../architecture/00-overview.md#限流) |
| 16.3 | WebSocket 实时推送 | ✅ | P0 | [notification](../modules/notification.md) |
| 16.4 | SSE 流式输出 | ✅ | P0 | [chat-sse](../explanation/chat-sse-streaming.md) |
| 16.5 | 健康检查 `/health` | ✅ | P1 | [deploy](../how-to/deploy.md) |
| 16.6 | OpenAPI 文档(`/docs`, `/redoc`) | ✅ | P0 | [reference](../reference/api.md) |
| 16.7 | 软删除(部分表) | ✅ | P1 | [database-schema](../reference/database-schema.md) |
| 16.8 | Celery 异步任务 | ✅ | P0 | [architecture](../architecture/00-overview.md#celery) |

---

## 17. 跨切面:可观测性(7 项)

| # | 功能 | 状态 | 优先级 | 模块文档 |
|---|------|------|--------|---------|
| 17.1 | LLM 调用日志(5 模块插桩) | ✅ | P0 | [llm-call-logs](../modules/llm-call-logs.md) |
| 17.2 | trace_id 串联 | ✅ | P0 | [observability](../explanation/observability.md) |
| 17.3 | 节点级 BFS 执行日志 | ✅ | P0 | [workflow](../modules/workflow.md#监控) |
| 17.4 | Run 趋势看板 | ✅ | P1 | [rag-evaluation](../modules/rag-evaluation.md#趋势) |
| 17.5 | 评测集对比 | ✅ | P1 | [rag-evaluation](../modules/rag-evaluation.md#对比) |
| 17.6 | 单元测试基线 1469+ | ✅ | P0 | [first-7-days](../tutorials/first-7-days.md#测试) |
| 17.7 | Playwright E2E 截图 | ✅ | P1 | [e2e-screenshots](../how-to/e2e-screenshots.md) |

---

## 统计

| 维度 | 数量 |
|------|------|
| **总功能数** | 119 |
| **P0 核心** | 56 |
| **P1 重要** | 48 |
| **P2 加分** | 13 |
| **P3 探索** | 0 |
| **Planned(未做)** | 1(邀请码) |
| **完成度** | 99.2% |

---

## 优先级说明

- **P0**:不做不能上线(MVP 必备)
- **P1**:重要业务能力(决定客户付费意愿)
- **P2**:差异化加分项(竞品对比时凸显)
- **P3**:探索性(留 1~2 个季度做尝试)

---

**维护者**:产品经理 + 全栈架构师
**最近更新**:2026-08-06(M37 评测体系 ship)
