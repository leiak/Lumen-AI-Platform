# 新人第一周·快速上手

> 给新入职工程师的 onboarding 指南。
> 从 0 到能跑、能改、能贡献第一个 PR,大约 5 个工作日。

---

## Day 1 — 环境跑通

### 上午

1. 拉代码
   ```bash
   git clone https://github.com/your-org/lumen-platform.git
   cd lumen-platform
   ```
2. 看 [CLAUDE.md](../../CLAUDE.md) — 项目铁律
3. 看 [架构总览](../architecture/00-overview.md) — 一张图总览

### 下午

4. 启动所有 dev 服务
   ```bash
   docker compose up -d mysql redis ollama elasticsearch
   cd backend && python -m uvicorn lumen_main:app --reload --port 11335
   cd frontend && npm install && npm run dev
   ```
5. 访问 `http://localhost:11334`,用 `admin@example.com` / `admin` 登录
6. 跑通一个最小闭环:创建一个 Agent → 进 Chat → 发条消息 → 收到回复

### 验证清单

- [ ] 后端启动无报错(`Application startup complete.`)
- [ ] 前端 11334 加载 dashboard
- [ ] Ollama 11434 健康(`curl http://localhost:11434/api/version`)
- [ ] MySQL 3307 连得上(`mcp__ai_platform_docker_mysql__mysql_query` 测一句 `SELECT NOW()`)
- [ ] 至少 1 次完整 Chat 对话

### 踩坑预警

**Uvicorn zombie**(Windows):如果接口返空数据,端口 LISTENING,但实际不响应 → 看 [uvicorn-zombie 排错](../troubleshooting/uvicorn-zombie.md)。

---

## Day 2 — 读懂后端分层

### 必读(每个文件 ≤ 5 分钟)

1. `backend/lumen_main.py` — FastAPI 入口
2. `backend/lumen_core/config.py` — Pydantic Settings
3. `backend/lumen_core/database.py` — SQLAlchemy engine + ensure_* 启动迁移
4. `backend/lumen_schemas/common.py` — `SingleResponse` / `PaginatedResponse`
5. `backend/lumen_models/agent.py` — 一个 ORM 的样子
6. `backend/lumen_services/agent_service.py` — 一个 service 的样子
7. `backend/lumen_api/v1/agent.py` — 一个 router 的样子

### 跑通测试

```bash
cd backend
pytest tests/unit/test_chat_*.py -v
```

看:
- 怎么 mock DB
- 怎么测试 FastAPI 端点
- 怎么用 `client` fixture

### 关键约束

- **响应信封**:所有 endpoint 必须 `response_model=SingleResponse[T]` 或 `PaginatedResponse[T]`
- **多租户**:所有 tenant 业务表查 `tenant_id == current_user.tenant_id`
- **跨租户返 404**:不是 403

---

## Day 3 — 读懂前端

### 必读

1. `frontend/app/dashboard/layout.tsx` — Layout
2. `frontend/app/dashboard/chat/page.tsx` — 一个完整页
3. `frontend/services/*.ts` — Axios 封装
4. `frontend/types/chat.ts` — 后端 schema 对应的 TS 类型
5. `frontend/components/notifications/BellBadge.tsx` — 一个小但完整的组件

### 关键约束

- **响应读法**:
  ```ts
  const res = await api.get('/agents')
  const body = res.data
  if (body.code === 200) {
    const items = body.data
  }
  ```
- **Auth token key**:`localStorage.getItem("access_token")`(不是 `"token"`)
- **`<img src=...>` 受保护资源**:必须 `fetch+blob+createObjectURL`(详见 [common-errors](../troubleshooting/common-errors.md))

### 跑通测试

```bash
cd frontend
npm run test:unit -- chat
```

---

## Day 4 — 跑一个工作流

### 选个模板

1. 进 `/dashboard/workflows`
2. 模板 → 选「知识问答基础」
3. 导入 → 跑
4. 看 Run 详情:每个节点的耗时 / 输入 / 输出 / 错误

### 自己搭一个

1. 拉一个 Knowledge Retrieval 节点 → 绑定 KB
2. 拉一个 LLM 节点 → 选 chat 模型
3. 拉一个 Output 节点
4. 连起来 → 跑

### 必读

- [workflow.md](../modules/workflow.md) — 整体
- [workflow-nodes.md](../modules/workflow-nodes.md) — 22 节点
- [workflow-execution.md](../explanation/workflow-execution.md) — 执行机制

---

## Day 5 — 第一个贡献

### 选个 issue

- `good first issue` label
- 文档补全
- 测试补全
- 小 bug 修复

### 提 PR 流程

```bash
git checkout -b feat/your-name
# 改完
git commit -m "feat(scope): 中文描述"
git push origin feat/your-name
# 在 GitHub 开 PR
```

### PR 模板

```markdown
## 背景
(为什么改)

## 改动
(改了什么)

## 测试
(怎么验)

## 截图(可选)
(UI 改)
```

### CI 必过

- Backend: `pytest` 全绿
- Frontend: `npm run test:unit` 全绿
- mypy: `cd backend && mypy lumen_api/ lumen_services/ lumen_models/ lumen_core/`
- tsc: `cd frontend && npx tsc --noEmit`

详见 [项目铁律](../../CLAUDE.md)。

---

## 第 5 天 + 周末 · 进阶

### 选读

- [MCP 集成](../modules/mcp.md) — 工具发现
- [技能市场](../modules/skill-market.md) — 技能抽象
- [多智能体](../modules/agent-team.md) — LangGraph
- [可观测性](../explanation/observability.md) — trace_id / LLM 日志
- [性能调优](../troubleshooting/performance-tuning.md) — 哪里慢怎么改

### 看历史

- [里程碑 M1~M37](../requirements/04-roadmap-milestones.md) — 怎么一步步走过来的

### 找 mentor

- 提个 issue 请 mentor review
- 找 1 个不太重要的模块读完整 README

---

## 必备资源

| 资源 | 链接 |
|------|------|
| 后端 Swagger | http://localhost:11335/docs |
| 后端 Redoc | http://localhost:11335/redoc |
| 前端 Dashboard | http://localhost:11334 |
| Ollama | http://localhost:11434 |
| 项目 CLAUDE.md | [CLAUDE.md](../../CLAUDE.md) |
| 项目 README | [README.md](../../README.md) |
| 排错速查 | [common-errors.md](../troubleshooting/common-errors.md) |

---

## 常见疑问

### 我看到奇怪的 `lumen_` 前缀是什么?

1.0 重命名(2026-06-23)从 `app_*` → `lumen_*`。详见 [memory.md 第一段](#)。

### 我可以用通用的 `mcp__mcp_server_mysql__mysql_query` 吗?

**不要**。用 `mcp__ai_platform_docker_mysql__mysql_query`(项目专用 Docker MySQL)。

### 端口冲突怎么办?

11335 / 11334 / 11434 / 8765 都是项目硬编码,**别改**。真冲突就用 fallback 端口(11336 之类,只用于临时绕过)。

### 跑测试很慢?

- 后端:用 `pytest -x -k your_test` 跑单个,不要全跑
- 前端:dev 时 `npx vitest watch`
- mypy 慢:排除 `__init__.py`

### 业务表清单?

[database-schema.md](../reference/database-schema.md) 69 张表。

### 哪里改响应格式?

[lumen_schemas/common.py](../../backend/lumen_schemas/common.py) — `SingleResponse` / `PaginatedResponse`。

---

## 收尾

第 1 周结束你应该能:
- [ ] 独立跑起 dev 环境
- [ ] 读懂一个完整模块(后端 + 前端)
- [ ] 跑通一个工作流
- [ ] 提 1 个 PR 被合并

如果有缺,找 mentor 1:1。

---

**相关文档**
- [架构总览](../architecture/00-overview.md)
- [技术栈](../architecture/01-tech-stack.md)
- [模块拓扑](../architecture/02-module-topology.md)
- [项目铁律](../../CLAUDE.md)

**维护者**:全栈架构师
**最近更新**:2026-08-06
