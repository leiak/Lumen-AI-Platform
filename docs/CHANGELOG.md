# 文档维护日志

> 文档的变更历史。每个里程碑结束后同步更新。

---

## 2026-10-06 — M40.1 knowledge page god component refactor ship

### 背景

M40 nitpick 2026-10-04 系统性 7 标记 `frontend/app/dashboard/knowledge/page.tsx` 2098 行 god component(M21~M38.2 持续叠加 + 5 modal + workspace/folder/rbac 三层 navigation 全揉一起)。M30b 已 ship `chat/page.tsx` 938 → 270 行(commit `0ce9ab1`),6 hooks + 6 components 模式,本任务照同款打 knowledge 页。

### 主要工作
- **`page.tsx`**:2098 → **1000 行**(-52.3%),纯 hook 编排层
- **6 hooks**(新文件,`frontend/app/dashboard/knowledge/hooks/`):
  - `useWorkspaceTree` (424 行) — workspace/folder 查询 + 4 modal + 8 handler
  - `useKnowledgeList` (390 行) — KB 列表 + CRUD + blocker modal
  - `useDocumentUpload` (105 行) — 上传 mutation + doc type picker
  - `useDocumentList` (439 行) — documents + 重试/删除/分块/重新分块 + WS 通知订阅
  - `useDocumentSearch` (178 行) — 搜索 + 高级选项 + detail modal
- **5 子组件**(新文件,`frontend/components/knowledge/`):
  - `<CreateKBModal>` (188) — 创建 KB modal
  - `<EditKBModal>` (188) — 编辑 KB modal,Embedding 锁定
  - `<BlockerModal>` (91) — M28 422 拦截
  - `<SearchCard>` (226) — 搜索 Card + 高级选项 + 结果列表
  - `<ViewChunksModal>` (127) — 分块详情 + 末 8 位 vector_id
- **`hooks/README.md`**(新文件):6 hooks 总览 + 5 子组件 + 调用顺序 + 跨 hook 通信矩阵 + 加新 feature 时怎么 hook 化
- **测试**:`__tests__/knowledge/` 6 文件 / 34 测试全过,`tsc --noEmit` 0 knowledge 错误

### 关键 invariant

1. **跨 hook 通信走 props-down + callbacks-up,不上 Context** — Context 在每个 state 变化时 re-render 所有 hook consumer,5 个 hook × ~30 state slot 会让 React.memo 失效。lift 到 page.tsx ~10 行/hook 但可调试。
2. **TDZ 同步用 `useRef` 桥** — hook init 顺序 `kb → ws → up → c1 → s2`,`kb.data` 过滤依赖 `ws.selectedWorkspaceId`。`wsRef.current = ws.selectedWorkspaceId` 每次 render 同步给 kb,handler 内部读 `wsIdRef.current` 拿最新值。
3. **bridge useEffect 内部** — selectedKB / selectedFolderId 变化 → 自动 fetchDocuments / fetchChunks(免暴露 fetchXxx 接口给 page 层)。
4. **setter prop 类型对齐** — hook 暴露 `(v: T) => void` setter,子组件 prop 也用 `(v: T) => void`,**不要** `Dispatch<SetStateAction<T>>`(后者支持 prev callback,hook 不需要这复杂度)。
5. **与 chat refactor 模式完全一致**(2026-06-16 commit `0ce9ab1`)。

### 与 M40 nitpick 修复包合并 ship

本任务跟 M40 nitpick P0 安全洞 + M40.1 quick wins(lifespan 拆 startup/shutdown + 5 个 SingleResponse[dict] leak 补 Pydantic schema)一起 ship,统一在 2026-10-05~06 周窗口内 commit。

---

## 2026-08-27 — M38.2.x v2 Workspace RBAC ship

### 背景
M38.2 把 workspace 落库后只做导航骨架,同 tenant 任何 user 都能看所有 workspace / KB / document,不符合企业内协场景。新 spec `docs-internal/superpowers/specs/2026-08-27-workspace-rbac.md`(200+ 行)定义 19 项 ACL permission + owner/admin bypass + workspace_id IS NULL 默认开放 read + chat/workflow KB RAG 集成。

### 主要工作
- **`docs/requirements/04-roadmap-milestones.md`**:M38.2 段追加 v2 子里程碑 + 时间线追加 2026-08-27 行 + 数字基线更新(后端 1562 / 前端 555,1 pre-existing fail)
- **`docs/modules/knowledge-base.md`**:新增 §3.12 完整描述 RBAC 19 perm 清单 + implication 链 + owner/admin/IS NULL 三层 bypass + API 端点表 + check helper 签名 + chat/workflow KB RAG 集成模式

### 关键 invariant(spec §6)
1. owner bypass:`Workspace.owner_id == user.id` 自动全 19 perm
2. superuser bypass:`User.is_superuser = true` 横跨全 workspace
3. workspace_id IS NULL:read-class 全员开放,写操作仍要 superuser
4. implication 链:`kb.update → kb.read → document.read` 等
5. transfer_ownership 30s 防误点 + workspace 名二次输入 + AuditLog 同事务

---

## 2026-08-26 — M38.2 KB 工作区 + 文档目录层级

### 背景
KB 之上缺少导航层级,租户 > 30 个 KB 或单 KB > 200 文档时 UX 接近不可用。

### 主要工作
- **`docs/requirements/04-roadmap-milestones.md`**:新增 M38.2 里程碑条目 + 12 个月时间线 + 数字基线更新
- **`docs/modules/knowledge-base.md`**:新增 §3.6–3.11 六节描述 workspace / folder 数据模型、API、前端导航结构、向后兼容
- **保留 v1 文档路径**:无破坏性变更,workspace_id / folder_id 都是 NULL-able 字段,旧 KB / Document 自动落在「未分组」/「KB 根」

---

## 2026-08-06 — 完整文档体系建立

### 背景

之前的文档散落在多个目录,新模块写完没有同步文档,新人入职上手困难。
本次系统性梳理;按 Diátaxis 框架重组成 4 大维度(已 ship):

| 维度 | 目录 | 数量 |
|------|------|------|
| PRD | `requirements/` | 5 |
| 架构 | `architecture/` | 7 |
| 业务模块 | `modules/` | 26 |
| 概念解释 | `explanation/` | 7 |
| 教程 | `tutorials/` | 2 |
| 操作指南 | `how-to/` | 6 |
| 故障排查 | `troubleshooting/` | 4 |
| 技术参考 | `reference/` | 3 |
| 索引 | `docs/` 根 | 3 |
| **总计** | | **63** |

### 主要工作

#### 新增

- **modules/external-app-auth.md** — 嵌入式 Widget 鉴权
- **modules/wx-publisher.md** — 公众号助手
- **modules/text2sql.md** — 智能问数
- **modules/llm-call-logs.md** — LLM/Embedding 调用日志
- **modules/system-config.md** — 平台级 KV 配置
- **modules/model-training.md** — NLP + Vision 训练
- **modules/customer-crm.md** — 客户 CRM
- **modules/notification.md** — 通知中心
- **tutorials/getting-started.md** — 新人第一天
- **tutorials/first-7-days.md** — 新人第一周
- **how-to/dev-env.md** — 开发环境
- **how-to/deploy.md** — 生产部署
- **how-to/e2e-screenshots.md** — Playwright 截图
- **how-to/add-new-workflow-node.md** — 新增工作流节点
- **how-to/add-new-skill.md** — 新增技能
- **how-to/faq.md** — FAQ
- **reference/api.md** — API 速查表
- **reference/database-schema.md** — 69 张表
- **reference/environment-config.md** — ENV 变量
- **modules/rag-evaluation.md** — M37 评测体系
- **troubleshooting/uvicorn-zombie.md** — Windows 僵尸进程
- **troubleshooting/common-errors.md** — 常见错误
- **troubleshooting/performance-tuning.md** — 性能调优
- **troubleshooting/data-recovery.md** — 数据恢复

#### 重建

- **modules/memory.md** — 记忆系统
- **docs/README.md** — 主索引
- **docs/SUMMARY.md** — 详细目录

### 文档原则

1. **Diátaxis 四象限**:`tutorials` / `how-to` / `reference` / `explanation`
2. **每个文档结尾**:维护者 + 最近更新
3. **代码引用**:`path/to/file.py:123` 风格
4. **三档语言分层**(CLAUDE.md §9):标识符英文 / docstring 中英 / 注释中文
5. **不写废话**:目录跳转、表格、可复制命令

### 已知 TODO

- [ ] 公开 docs 还需要配 `mkdocs.yml` / `docusaurus.config.js` 静态站点
- [ ] 部分 cross-reference 在某些 SDK 渲染下可能 404
- [ ] 文档翻译(i18n)和搜索未做

---

## 2026-08-06 — M37 RAG 评测体系

### 新增

- **modules/rag-evaluation.md** — M37 完整评测体系

### 业务价值

- 数据集 (Gold questions) + Run + Report + Dashboard
- 4 个核心指标:Retrieval Recall / MRR / Faithfulness / Answer Correctness
- A/B 比较两个模型的检索效果

---

## 2026-08-06 — CP7 全量测试修复

详见 `docs/troubleshooting/data-recovery.md` §3.1。

### 修复

- `ensure_timestamp_defaults.py` — 一次性 backfill 86 旧表
- 9 个测试断言更新(测试基线 M37 → M37+CP7)

---

## 2026-06-23 — 1.0 重命名

公开 docs/ 用 **Diátaxis** 框架(13 文件),`docs-internal/` 内部归档(136 文件,不入 git)。

---

## 阅读路径推荐

### 第一次来

1. [README.md](README.md) — 主索引
2. [SUMMARY.md](SUMMARY.md) — 详细目录
3. [requirements/00-product-vision.md](requirements/00-product-vision.md) — 产品定位
4. [architecture/00-overview.md](architecture/00-overview.md) — 架构图

### 工程师上手

1. [tutorials/getting-started.md](tutorials/getting-started.md) — 启动
2. [CLAUDE.md](../CLAUDE.md) — 项目铁律
3. 选一个模块深入

### 故障排查

1. [troubleshooting/common-errors.md](troubleshooting/common-errors.md)
2. [troubleshooting/uvicorn-zombie.md](troubleshooting/uvicorn-zombie.md)(Windows)
3. [troubleshooting/data-recovery.md](troubleshooting/data-recovery.md)

---

**维护者**:全栈架构师
**最近更新**:2026-08-06
