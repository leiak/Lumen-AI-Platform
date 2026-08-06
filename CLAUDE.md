# CLAUDE.md — Lumen AI Platform

> 项目铁律。**Claude 在这个仓库里工作时必须遵守**。
> 详细背景见 `docs/tutorials/`、`docs-internal/roadmap/`、`docs-internal/superpowers/`。

## 1. 端口分配(硬编码,别改)

| 服务 | 端口 | 备注 |
|------|------|------|
| 前端 dev (Next.js) | **11334** | `npm run dev` |
| 后端 (uvicorn) | **11335** | API + Swagger `/docs` + Redoc `/redoc` |
| Ollama | 11434 | embedding(`nomic-embed-text`)+ chat(`qwen2.5:7b`) |
| 本地 MCP demo server | 8765 | `backend/run_mcp_server.py` |

> `localhost:8000` / `localhost:3000` **不存在**。本机就用 11335 / 11334。

## 2. 后端响应信封(契约)

所有 endpoint 返回 **`SingleResponse[T]`** 或 **`PaginatedResponse[T]`**(在 `lumen_schemas/common.py`),**禁止**直接返回 ORM 对象或裸 dict。

```python
# ✅ 对
@router.get("/{id}", response_model=SingleResponse[AgentRead])
def get_agent(id: int, ...): ...

# ❌ 错
@router.get("/{id}")
def get_agent(id: int, ...): return db.get(Agent, id)  # 裸 ORM,前端会炸
```

## 3. 前端读取约定

```ts
const res = await api.get(...)
const body = res.data            // AxiosResponse.data → 后端信封
if (body.code === 200) {
  const item: T = body.data       // SingleResponse.data 或 PaginatedResponse.items
}
```

- 鉴权 token key: **`access_token`**(不是 `token`)。`localStorage.getItem("access_token")`。
- 原生 `fetch()` 调用方需手动设 `Authorization: Bearer <access_token>`。
- API base: `http://localhost:11335/api/v1`(`frontend/.env.local` 的 `NEXT_PUBLIC_API_URL`)。

## 4. MCP server 选择(重要)

本项目**专用** MySQL MCP:
- ✅ `mcp__ai_platform_docker_mysql__mysql_query`(项目 Docker MySQL)
- ❌ **不要**用通用的 `mcp__mcp_server_mysql__mysql_query`

## 5. Uvicorn zombie 处理(Windows 专属踩坑)

`uvicorn --reload` 在 Windows 上会**静默失败不重启 worker**。症状:模块 import 正常,但接口返回 `[]` 或异常。

**症状 → 诊断 → 处理**:

1. **症状**:接口莫名返空数据,日志没明显错误。
2. **诊断**:`netstat -ano | grep :11335` → 看 PID 是不是变了,旧 PID 还在 → zombie。
3. **处理 A**(推荐):杀掉旧 worker 子进程,parent reloader 会派新 worker。
   ```powershell
   # parent reloader 不会自动清理 zombie child
   Get-Process | Where-Object {$_.Parent.Id -eq $reloaderPid} | Stop-Process -Force
   ```
4. **处理 B**(fallback):旧 worker 持有 socket 杀不掉时,**用新端口 11336 起新 uvicorn**,前端/API 测试指向那里。
5. **不要反复戳**同一个陈旧实例。重启 uvicorn,不要 poll。

详见 `docs/troubleshooting/uvicorn-zombie.md`。

## 6. Python 环境

**本机的 Anaconda Python 就是能用的那个**。别假设缺模块,先查陈旧 worker 再装包。

## 7. 工作流模块(项目最复杂部分)

- 后端执行器: `backend/lumen_services/workflow_executor.py`
- 节点规范: `docs-internal/superpowers/specs/`(每节点有 spec)
- 实施计划: `docs-internal/superpowers/plans/`
- **P2 已 ship**(2026-06-05):9 个新节点(Code / HTTP / Tool / Knowledge Retrieval / Template Transform / Parameter Extractor / Question Classifier / Variable Assigner / Variable Aggregator)+ 共享 `error_strategy` / `retry_config` / per-node timeout 基础设施
- 实施修改工作流代码前,**先读对应 spec**,规范是单一真相源。

## 8. 测试

| 套件 | 命令 |
|------|------|
| 后端 pytest | `cd backend && pytest` |
| 前端 vitest | `cd frontend && npm run test:unit` |
| widget vitest | `cd widget && npm test` |
| 后端类型检查 (mypy) | `cd backend && mypy lumen_api/ lumen_services/ lumen_models/ lumen_core/` |
| 前端类型检查 (tsc) | `cd frontend && npx tsc --noEmit && cd ../widget && npx tsc --noEmit` |

**基线**(M37, 2026-08-06):后端 pytest **1472 passed / 8 skipped / 1 xfailed / 0 failed**(287s,4min47s),前端 vitest **492 passed / 1 failed**(530s,8min50s,2 个 test file 受牵连)。M37 专项:后端 **74 passed**(dataset/runner/metrics/judge/report/celery/compare/dataset-service 8 套件),前端 **34 passed**(datasets / runs / new-run / results / dashboard 5 套件)。

**已知 1 个 pre-existing 失败**(`frontend/__tests__/workflow/llm-node-skill-picker.test.tsx:132`):测试期望 placeholder = `"从本租户已装技能中选择"`,但 `frontend/components/workflow/nodes/llm/Panel.tsx:164` 实际是 `"从已装技能中选择(最多5个)"` — 自 init commit 起就没匹配过,与 M37 评测无关。**忽略即可**,别在 M37 / 1.0 ship 时花时间修。

## 9. 沟通风格 & 注释语言

**回复语言**:中文(代码、命令、文件内容保持英文;解释/状态/澄清用中文)。
- 状态更新、澄清、决策、解释 → 中文。
- 不要为了简洁而省略错误信息 — 完整 dump 出来。
- commit message: 中文。

**代码注释语言策略**(2026-07-15 立):三档语言分层。

| 层级 | 语言 | 例外 |
|------|------|------|
| **标识符**(变量名 / 类名 / 函数名 / 路由路径 / 文件名 / 表名 / schema 字段名) | **英文,硬性要求** | — |
| **docstring / 文件顶部说明** | 英文 1 行摘要(给 IDE hover / Sphinx / autodoc)+ 中文详细说明 | 公开 SDK / OpenAPI 字段可全英 |
| **行内注释**(`#` / `//` / `/* */`) | **中文为主**,侧重解释"为什么";命令行 flag / 第三方 API / 引用外部 spec 等机械说明保留英文 | — |

**API 响应中面向用户的 `message` 字段用双语**(例: `"已保存 / Saved"`);log 日志关键路径可中文。

**反面例子**(禁止):
- 标识符用中文 — `def 计算总价():` / `let 用户列表 = ...`(破坏 pylance/tsc/grep/补全/codesearch)
- commit message / PR 描述 / 文档标题 英文 — 必须中文
- log 全部英文 — 关键路径要有中文便于排查(例:`log.error("视频合成失败 file=%s reason=%s", path, e)`)

**回归**:旧文件**不回翻**(成本大、引入大量 diff 噪音);**M37 起**新增或大改的文件默认按本策略写,新加代码评审 / AI 生成时遵守。

## 10. Git 提交

- Conventional commits,中文:`feat(workflow):` / `fix(workflow):` / `docs:` 等(scope 可选)。
- **不要**用 `--no-verify` 绕过 hooks。
- 一个 commit 做一件事。
