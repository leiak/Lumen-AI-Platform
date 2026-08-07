# 新人第一周·延伸学习清单

> 给想深入了解某个模块的工程师。
> 第一周能跑通后,7 天里挑几个模块深入读。

---

## Day 1 — 跑通 + 梳理

### 必做

- [ ] 跟着 [getting-started](getting-started.md) 跑通
- [ ] 读 [CLAUDE.md](../../CLAUDE.md)
- [ ] 浏览 [架构总览](../architecture/00-overview.md)

### 不会就问

- 我的 dev 服务起不来?
- 端口冲突怎么解?
- 我用的 mysql MCP 怎么连不上?

---

## Day 2 — 选一个模块深入

挑**一个**你以后会长期维护的模块:

| 模块 | 文档 |
|------|------|
| Agent | [agent.md](../modules/agent.md) |
| Chat | [chat.md](../modules/chat.md) |
| KB | [knowledge-base.md](../modules/knowledge-base.md) |
| Workflow | [workflow.md](../modules/workflow.md) + [workflow-nodes.md](../modules/workflow-nodes.md) |
| Skill Market | [skill-market.md](../modules/skill-market.md) |
| Notification | [notification.md](../modules/notification.md) |
| Image Gen / TTS / Video | [image-generation.md](../modules/image-generation.md) / [tts.md](../modules/tts.md) / [video-composition.md](../modules/video-composition.md) |

### 读法

按这个顺序读:
1. 模块文档(整体)
2. ORM 定义
3. 关键 service 函数
4. router 端点
5. 前端组件

### 验证

- 单独重启这个模块相关服务,不挂
- 改一行 log,看到 ✓
- 跑这个模块的测试
- 看 LLM 日志(org.springframework)

---

## Day 3 — 跑一次修复

找一个模块的"有空修"issue,看代码,提 PR。

或:
- 找一个失败的测试,搞清楚为什么,修
- 找一个被 TODO 标记的代码,补
- 找一份文档,补一段

### 提 PR 流程

```bash
git checkout -b fix/your-fix
# 改
git commit -m "fix(scope): 中文描述"
git push origin fix/your-fix
gh pr create --title "fix(scope): 中文" --body "..."
```

### 必过

- [ ] 后端 `pytest` 全绿
- [ ] 前端 `npm run test:unit` 全绿
- [ ] mypy 0 错
- [ ] tsc 0 错
- [ ] 1 个测试

---

## Day 4 — 深入一个横切关注点

### 选一个

- [ ] **可观测性**: [observability.md](../explanation/observability.md)
- [ ] **错误处理 / 重试**: [error-retry-timeout.md](../explanation/error-retry-timeout.md)
- [ ] **Embedding 流水线**: [embedding-pipeline.md](../explanation/embedding-pipeline.md)
- [ ] **工作流执行**: [workflow-execution.md](../explanation/workflow-execution.md)
- [ ] **SSE 流式**: [chat-sse-streaming.md](../explanation/chat-sse-streaming.md)
- [ ] **Tool Calling**: [tool-calling.md](../explanation/tool-calling.md)
- [ ] **响应信封**: [response-envelope.md](../explanation/response-envelope.md)

### 方式

- 读文档
- 写一段 demo(改这个横切的一个例子)
- 跑通

---

## Day 5 — 看一个模块的演进历史

挑一个**走过大版本的模块**:

- KB(M25 → M27 → M32.1)
- Workflow(M30a → M30b → M30c)
- Chat(M14 → M30a)
- Customer CRM(M25/26)

或者挑几个里程碑:

- [roadmap.md](../requirements/04-roadmap-milestones.md) — M1~M37

### 目标

理解**演进 log**:
- 早期功能是什么样的
- 改了哪些坑
- 哪个 commit 是关键

看 git log:
```bash
git log --oneline --grep "M25"  --grep "feat(knowledge-base)" | head -20
```

---

## Weekend — 进阶

### 读

- [技术栈](../architecture/01-tech-stack.md) — LangChain 1.0 / LangGraph 版本基线
- [Wx Publisher 文档](../modules/wx-publisher.md) — 公众号完整流程
- [Text2SQL 文档](../modules/text2sql.md) — 智能问数全栈
- [Eval 文档](../modules/rag-evaluation.md) — M37 评测体系

### 玩

- 跑一次 RAG 评测:创建数据集 → 跑 → 看指标
- 搭一个简单 workflow:KB 检索 + LLM
- 用 widget 嵌入到一个 demo 网页

### 写

- 给自己的 short blog post:"我第一周学会了什么"
- 整理 1 个文档的 typo / 缺失

---

## 七日评估

第 7 天结束你应该能:

- [ ] 独立起 dev 环境
- [ ] 独立写 1 个小功能(改前端 + 加 endpoint + 写测试)
- [ ] 跑通 1 个评测 / 1 个工作流
- [ ] 读懂 1 个横切关注点
- [ ] 修了 1 个 bug / 补了 1 个文档
- [ ] 提了 1 个 PR

---

## 链接总汇

| 链接 | 用途 |
|------|------|
| [CLAUDE.md](../../CLAUDE.md) | 项目铁律 |
| [架构总览](../architecture/00-overview.md) | 全局图 |
| [模块列表](../SUMMARY.md#第三部分业务模块参考modules) | 26 个模块 |
| [API 参考](../reference/api.md) | 全部端点 |
| [环境配置](../reference/environment-config.md) | ENV |
| [数据库 schema](../reference/database-schema.md) | 69 张表 |
| [排错速查](../troubleshooting/common-errors.md) | 常见错误 |
| [roadmap](../requirements/04-roadmap-milestones.md) | M1~M37 |
| [FAQ](../how-to/faq.md) | 一线问题 |

---

## 进阶方向

按兴趣选:

| 方向 | 关键模块 |
|------|---------|
| **LLM 应用工程** | Chat, Knowledge Base, Memory, Agent |
| **AI 训练 / 评测** | NLP Training, Vision Training, RAG Eval |
| **媒体生成** | Image Generation, TTS, Video Composition |
| **工作流系统** | Workflow, Workflow Nodes |
| **前端** | React + Next.js + AntD |
| **DevOps** | Docker, Celery, MySQL, Redis, ES |
| **多模态** | Image, TTS, Video, Subtitle |
| **集成** | MCP, External App, Wx Publisher |

---

**相关文档**
- [getting-started.md](getting-started.md)
- [CLAUDE.md](../../CLAUDE.md)
- [roadmap.md](../requirements/04-roadmap-milestones.md)

**维护者**:全栈架构师
**最近更新**:2026-08-06
