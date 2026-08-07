# Lumen AI Platform — 产品文档

> 本目录是 Lumen AI Platform 的 **产品需求与功能文档**,供产品经理、运营、销售、客服、新入职工程师等角色使用。
>
> **技术实现细节**(API 字段、Docker 命令、节点 spec)放在 `docs/reference/` 和 `docs/modules/`;
> **排错 / 运维**放在 `docs/troubleshooting/` 和 `docs/how-to/`。

---

## 目录结构

```
docs/
├── README.md                  ← 本文件(主索引 + 快速跳转)
├── SUMMARY.md                 ← 详细目录,按"阅读顺序"组织
│
├── requirements/              ← PRD 维度(产品视角)
│   ├── 00-product-vision.md       产品定位 / 价值主张 / 目标客户
│   ├── 01-personas.md             用户画像 / 角色
│   ├── 02-feature-list.md         全部功能清单 + 状态 + 优先级
│   ├── 03-user-journeys.md        关键用户旅程(销售、运营、客服、客户、开发者)
│   └── 04-roadmap-milestones.md   M1~M37 里程碑时间线
│
├── architecture/              ← 架构维度(系统如何组织)
│   ├── 00-overview.md            一张图总览
│   ├── 01-tech-stack.md          技术选型 + 理由
│   ├── 02-module-topology.md     后端 9 大模块 + 前端 44 页面 + 跨切面
│   ├── 03-data-flow.md           典型请求的数据流(LLM 调用 / RAG 检索 / 工作流执行)
│   ├── 04-multi-tenant.md        多租户隔离策略
│   ├── 05-auth-rbac.md           认证 + 角色权限矩阵
│   └── 06-port-alloc.md          端口分配(硬编码,为什么)
│
├── modules/                   ← 业务模块维度(每个模块讲透)
│   ├── auth-and-rbac.md          认证 / 角色 / 权限
│   ├── agent.md                  AI Agent(单智能体)
│   ├── agent-team.md             多智能体团队(LangGraph)
│   ├── chat.md                   聊天 / 对话 / 流式
│   ├── knowledge-base.md         知识库 RAG
│   ├── workflow.md               可视化工作流
│   ├── workflow-nodes.md         22 节点总览(每个节点 spec 链接)
│   ├── skill-market.md           技能市场
│   ├── mcp.md                    MCP 协议集成
│   ├── image-generation.md       AI 图片生成
│   ├── tts.md                    语音合成
│   ├── subtitle.md               SRT 字幕生成
│   ├── video-composition.md      视频合成
│   ├── stock-assets.md           股票素材库
│   ├── playbook.md               Playbook 风格系统
│   ├── memory.md                 对话级 + 全局记忆
│   ├── model-management.md       LLM/Embedding/Image/TTS 模型管理
│   ├── model-training.md         NLP + 视觉训练
│   ├── external-app-auth.md      外部应用授权(Widget 嵌入)
│   ├── customer-crm.md           客户 CRM
│   ├── notification.md           通知中心
│   ├── wx-publisher.md           公众号助手
│   ├── text2sql.md               智能问数
│   ├── rag-evaluation.md         RAG 评测体系
│   ├── llm-call-logs.md          LLM 调用日志 + Trace
│   └── system-config.md          系统设置 / 平台级技能 / 平台级 Playbook
│
├── reference/                 ← 信息查阅维度(查得到)
│   ├── api.md                    API 端点速查表(按模块)
│   ├── database-schema.md        数据库表结构 + ER 关系
│   └── environment-config.md     .env / 环境变量 / 配置项
│
├── explanation/               ← 概念解释维度(为什么这样设计)
│   ├── response-envelope.md      响应信封的来由
│   ├── embedding-pipeline.md     Docling → 切块 → 向量化 → 检索 流水线
│   ├── workflow-execution.md     LangGraph DAG 执行原理
│   ├── observability.md          LoggingChatModel 插桩 + trace_id 串联
│   ├── tool-calling.md           Agent 工具调用 5 轮循环机制
│   ├── error-retry-timeout.md    工作流节点错误处理 / 重试 / 超时共享基础设施
│   └── chat-sse-streaming.md     SSE 流式输出前端解析
│
├── tutorials/                 ← 教程(逐步操作)
│   ├── getting-started.md        新人第一天(从 0 到启动)
│   └── first-7-days.md           新人第一周(从启动到交付)
│
├── how-to/                    ← 操作指南(问题驱动)
│   ├── dev-env.md                准备开发环境
│   ├── deploy.md                 生产部署
│   ├── e2e-screenshots.md        Playwright 截图验证
│   ├── add-new-workflow-node.md  新增一个工作流节点
│   ├── add-new-skill.md          新增一个技能
│   └── faq.md                    常见问题
│
└── troubleshooting/           ← 故障排查
    ├── uvicorn-zombie.md         uvicorn --reload Windows 僵尸进程
    ├── common-errors.md          常见错误码 + 修法
    ├── performance-tuning.md     性能调优
    └── data-recovery.md          数据恢复 / 删库跑路
```

---

## 给不同角色的 5 分钟速读

### 产品经理
- 📌 **[产品定位与价值主张](requirements/00-product-vision.md)** —— 5 分钟
- 📌 **[功能清单(全部模块)](requirements/02-feature-list.md)** —— 15 分钟
- 📌 **[关键用户旅程](requirements/03-user-journeys.md)** —— 10 分钟
- 📌 **[里程碑时间线](requirements/04-roadmap-milestones.md)** —— 5 分钟

### 销售 / 售前
- 📌 **[产品定位](requirements/00-product-vision.md)** + **[功能清单](requirements/02-feature-list.md)**
- 📌 **[典型用户旅程](requirements/03-user-journeys.md)** —— 找适合客户的 case

### 运营 / 客服
- 📌 **[功能清单](requirements/02-feature-list.md)** —— 知道系统能做什么
- 📌 **[常见问题](how-to/faq.md)** + **[常见错误](troubleshooting/common-errors.md)**

### 新入职工程师(后端)
- 📌 **[架构总览](architecture/00-overview.md)** + **[技术栈](architecture/01-tech-stack.md)** —— 5 分钟
- 📌 **[模块拓扑](architecture/02-module-topology.md)** —— 10 分钟
- 📌 **[典型数据流](architecture/03-data-flow.md)** —— 10 分钟
- 📌 **[新人第一周](tutorials/first-7-days.md)** —— 30 分钟

### 新入职工程师(前端)
- 📌 **[模块拓扑 - 前端](architecture/02-module-topology.md#前端)** —— 5 分钟
- 📌 **[响应信封契约](explanation/response-envelope.md)** —— 5 分钟
- 📌 **前端 services 速查表**(见 `architecture/02-module-topology.md`)

### 集成开发者(用 Widget)
- 📌 **[外部应用授权](modules/external-app-auth.md)** —— 5 分钟
- 📌 **[Widget 嵌入](modules/external-app-auth.md#widget-嵌入示例)** —— 5 分钟

---

## 文档维护原则

1. **Diátaxis 四象限**:本文档结构遵循 Diátaxis 框架 —— `tutorials`(学习)/ `how-to`(操作)/ `reference`(查阅)/ `explanation`(理解)。每个文档明确归属。
2. **单一真相源**:文档与代码保持一致;代码改了文档必须改;以 `git log` 为准,`CLAUDE.md` 描述项目铁律。
3. **里程碑驱动**:每个 M1~M37 里程碑 ship 时同步更新对应模块的 reference 文档,而不是事后补。
4. **不写废话**:用户来这里是为了查问题;目录跳转、表格、可复制命令是主语。
5. **代码引用格式**:`path/to/file.py:123` 风格,可被 IDE 跳转。

---

## 反馈与贡献

- 文档错误:在仓库根目录提 issue
- 大改/新增:在仓库根目录提 PR,reviewer 检查 `requirements/02-feature-list.md` 是否同步更新
- 紧急修订:直接改 + @ 团队 review(事后补 commit 描述)
- 变更历史:见 [CHANGELOG.md](CHANGELOG.md)

---

**维护者**:全栈架构师
**最近更新**:2026-08-06
