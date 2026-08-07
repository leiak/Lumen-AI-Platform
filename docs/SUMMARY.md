# Lumen AI Platform 文档总目录

> 按"从产品 → 架构 → 模块 → 概念 → 教程 → 排错"的阅读顺序组织,适合系统学习。

---

## 第一部分:产品视角(PRD)

| # | 文档 | 内容 | 适合 |
|---|------|------|------|
| 1 | [产品定位与价值主张](requirements/00-product-vision.md) | 是什么 / 为什么 / 卖给谁 | 全员 |
| 2 | [用户画像](requirements/01-personas.md) | 5 类核心用户 + 场景 + 痛点 | 产品 / 销售 |
| 3 | [功能清单](requirements/02-feature-list.md) | 全部功能 + 状态 + 优先级 | 全员 |
| 4 | [关键用户旅程](requirements/03-user-journeys.md) | 销售 / 运营 / 客服 / 客户 / 开发者 5 条主线 | 产品 / 销售 |
| 5 | [里程碑时间线 M1~M37](requirements/04-roadmap-milestones.md) | 发展史 + 未来规划 | 全员 |

---

## 第二部分:系统架构

| # | 文档 | 内容 | 适合 |
|---|------|------|------|
| 6 | [架构总览](architecture/00-overview.md) | 一张图总览 + 子项目职责 | 工程师 / 架构师 |
| 7 | [技术栈](architecture/01-tech-stack.md) | 选型 + 理由 + 版本 | 工程师 |
| 8 | [模块拓扑](architecture/02-module-topology.md) | 后端 9 大模块 + 前端 44 页面 + 跨切面 | 工程师 |
| 9 | [数据流](architecture/03-data-flow.md) | LLM 调用 / RAG 检索 / 工作流执行 | 工程师 |
| 10 | [多租户](architecture/04-multi-tenant.md) | 隔离策略 / 全局资源 | 工程师 |
| 11 | [认证与 RBAC](architecture/05-auth-rbac.md) | OAuth2 + JWT + 角色权限矩阵 | 工程师 |
| 12 | [端口分配](architecture/06-port-alloc.md) | 4 个核心端口 + 为什么 | 工程师 / 运维 |

---

## 第三部分:业务模块(按使用频率)

### 高频(每天)
| # | 文档 | 内容 |
|---|------|------|
| 13 | [AI Agent](modules/agent.md) | 单智能体 CRUD + 配置 + 工具 |
| 14 | [聊天 / 对话](modules/chat.md) | 对话列表 + 流式输出 |
| 15 | [知识库 RAG](modules/knowledge-base.md) | 文档上传 + 解析 + 检索 |
| 16 | [工作流](modules/workflow.md) | 可视化编排 + 22 节点 + 执行监控 |
| 17 | [工作流节点](modules/workflow-nodes.md) | 22 节点总览 |

### 中频(每周)
| # | 文档 | 内容 |
|---|------|------|
| 18 | [Agent 团队](modules/agent-team.md) | 多智能体协同 + 路由策略 |
| 19 | [MCP 集成](modules/mcp.md) | MCP 协议 + 工具发现 |
| 20 | [技能市场](modules/skill-market.md) | 技能浏览 / 安装 / 类型化抽象 |
| 21 | [模型管理](modules/model-management.md) | LLM/Embedding/Image/TTS 模型 |
| 22 | [记忆](modules/memory.md) | 对话级 + 全局记忆 |
| 23 | [客户 CRM](modules/customer-crm.md) | 客户档案 + 跟进 + 字段定义 |
| 24 | [通知中心](modules/notification.md) | 顶栏红点 + 抽屉 |

### 低频(月度)
| # | 文档 | 内容 |
|---|------|------|
| 25 | [图片生成](modules/image-generation.md) | 多 provider 抽象 + 后台任务 |
| 26 | [TTS 语音合成](modules/tts.md) | Edge TTS / Piper / OpenAI |
| 27 | [SRT 字幕](modules/subtitle.md) | 中英混合时间戳 |
| 28 | [视频合成](modules/video-composition.md) | ffmpeg 拼装 |
| 29 | [股票素材库](modules/stock-assets.md) | 公共图片库 |
| 30 | [Playbook](modules/playbook.md) | 视觉/语音风格 token |
| 31 | [模型训练](modules/model-training.md) | NLP + 视觉训练 |
| 32 | [外部应用授权](modules/external-app-auth.md) | 公钥/私钥 + Widget 嵌入 |
| 33 | [公众号助手](modules/wx-publisher.md) | 草稿 + AI 改写 + 微信 API |
| 34 | [Text2SQL 智能问数](modules/text2sql.md) | NL→SQL + SQLGuard |
| 35 | [RAG 评测](modules/rag-evaluation.md) | 数据集 + Run + Dashboard |
| 36 | [LLM 调用日志](modules/llm-call-logs.md) | 日志 + Trace |
| 37 | [系统配置](modules/system-config.md) | SystemConfig / 平台级技能 |

---

## 第四部分:概念解释(explanation)

> 理解"为什么这样设计",适合新人 / 跨栈工程师 / 准备改架构的人。

- [响应信封](explanation/response-envelope.md) —— SingleResponse[T] / PaginatedResponse[T] 契约的来由
- [Embedding 流水线](explanation/embedding-pipeline.md) —— Docling → 切块 → 向量化 → 检索
- [工作流执行原理](explanation/workflow-execution.md) —— LangGraph DAG 怎么跑
- [可观测性](explanation/observability.md) —— LoggingChatModel 插桩 + trace_id 串联
- [工具调用](explanation/tool-calling.md) —— Agent 5 轮 tool loop 机制
- [错误处理基础设施](explanation/error-retry-timeout.md) —— 节点的 error_strategy / retry_config / timeout
- [SSE 流式](explanation/chat-sse-streaming.md) —— 前端怎么解析 chunk

---

## 第五部分:教程 + 操作指南

### 教程
- [新人第一天](tutorials/getting-started.md) —— 从 0 到启动
- [新人第一周](tutorials/first-7-days.md) —— 从启动到交付第一个功能

### 操作指南
- [准备开发环境](how-to/dev-env.md)
- [生产部署](how-to/deploy.md)
- [Playwright 截图验证](how-to/e2e-screenshots.md)
- [新增工作流节点](how-to/add-new-workflow-node.md)
- [新增技能](how-to/add-new-skill.md)
- [FAQ](how-to/faq.md)

---

## 第六部分:故障排查

- [uvicorn --reload 僵尸进程](troubleshooting/uvicorn-zombie.md) —— Windows 专属
- [常见错误](troubleshooting/common-errors.md) —— 错误码 + 修法
- [性能调优](troubleshooting/performance-tuning.md)
- [数据恢复](troubleshooting/data-recovery.md)

---

## 第七部分:技术参考(reference)

- [API 端点速查表](reference/api.md) —— 按模块组织
- [数据库表结构](reference/database-schema.md) —— 69 张表 + ER
- [环境变量](reference/environment-config.md)
- [响应信封契约](explanation/response-envelope.md) —— 开发查字段用

---

## 文档贡献者

- 文档由产品经理 + 工程师共同维护
- 每次 M 里程碑 ship 时同步更新
- 见每个文档底部的"最近更新"和"维护者"
