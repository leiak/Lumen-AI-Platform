# 文档维护日志

> 文档的变更历史。每个里程碑结束后同步更新。

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
