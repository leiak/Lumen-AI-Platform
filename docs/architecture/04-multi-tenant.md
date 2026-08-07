# 多租户隔离

> Lumen AI Platform 是多租户平台,数据隔离是核心安全要求。
> 文档说明租户模型、隔离策略、全局资源、跨租户访问的边界。

---

## 1. 租户模型

### 1.1 核心实体:`tenants`
- 表: `tenants` (`backend/lumen_models/tenant.py`)
- 字段:
  - `id` — 主键
  - `name` — 租户名称(可重复,展示用)
  - `code` — 租户代码(唯一,如 `acme` / `globex`)
  - `status` — 1=启用, 0=禁用
  - `max_users` — 用户数上限
  - `created_at` / `updated_at`

### 1.2 租户配额(计划中)
- 当前: 仅 `max_users`
- 计划中: `max_knowledge_bases` / `max_workflow_runs` / `max_storage_gb`

---

## 2. 租户与用户

### 2.1 关系
```
tenants (1) ──< users (N)
```

### 2.2 关键字段
- `users.tenant_id` — 必填,外键
- 每个 user 必属于一个 tenant
- **`is_superuser=True` 的用户**属于系统级"超管",可跨租户操作(仅平台运营用)

---

## 3. 业务表的多租户模式

### 3.1 标准模式:`tenant_id` 直接外键
下列表都带 `tenant_id` 外键:
- `agents` / `agent_teams` / `agent_team_members`
- `knowledge_bases` / `documents` / `document_chunks`
- `workflows` / `workflow_runs` / `workflow_node_runs`
- `conversations` / `messages` / `memories`
- `customers` / `customer_follow_ups`
- `external_apps`
- `image_generations` / `tts_jobs` / `videos` / `subtitles`
- `eval_datasets` / `eval_runs`
- `llm_call_logs` / `notifications`
- `wx_publisher_*`(草稿/模板/素材/账号)
- `workflow_templates`(租户发布)
- `playbooks`(租户级)
- `skills`(已安装的租户技能)
- `system_configs`(部分)

### 3.2 全局资源模式:`tenant_id IS NULL`
下列资源是**平台内置,所有租户共享**:
- **系统级 workflow_templates**(M30 ship 时 `tenant_id IS NULL`)
- **stock_assets**(M36.2.1 预置 30 张图,`tenant_id IS NULL`)
- **默认 model_configs**(`is_default=True` + `tenant_id IS NULL`)
- **platform skills**(`is_platform=True` + `tenant_id IS NULL`)
- **system_configs 部分**(如 HTTP allowlist 域名)

**SQL 模式**:
```sql
SELECT * FROM <table> WHERE (tenant_id = :current_tenant OR tenant_id IS NULL)
```

### 3.3 私有模式:无 `tenant_id`(平台独有)
- `tenants` 本身
- `roles` / `permissions`(全局共享,租户通过 `user_roles` 关联)
- `model_providers`(全局 provider 注册)

---

## 4. 隔离实现

### 4.1 后端三层防御

#### 第 1 层:Routing / Service 层显式过滤
```python
# lumen_services/agent_service.py
def list_agents(db: Session, current_user: User) -> list[Agent]:
    query = db.query(Agent)
    if not current_user.is_superuser:
        query = query.filter(Agent.tenant_id == current_user.tenant_id)
    return query.all()
```

#### 第 2 层:ORM Relationship 自动加载
- SQLAlchemy `relationship()` 配合 `lazy="select"` 自动按外键 join
- 例:查 conversation 时,自动加载 `conversation.messages` (按 messages.conversation_id)

#### 第 3 层:数据库约束(不推荐)
- 暂不依赖 DB 级 RLS(避免跨数据库兼容问题)
- 后续可考虑 PostgreSQL RLS

### 4.2 前端
- 用户登录后,token 含 `tenant_id`
- axios 实例 header `X-Tenant-Id`(冗余,后端不信)
- 前端不直接过滤,后端强保证

### 4.3 中间件
- `lumen_core/middleware/tenant.py` — `TenantContext` ContextVar
- 每次请求设 `TenantContext.set(tenant_id)`
- 服务层可读 `TenantContext.get()`

---

## 5. 跨租户访问

### 5.1 平台超管
- `is_superuser=True` 的用户
- 可访问所有租户(用于运维 / 客服)
- 前端 dashboard 顶部"切换租户"下拉(仅超管可见)

### 5.2 跨租户资源分享
- 暂不直接支持
- 计划:租户间"知识库市场",通过发布 + 订阅

---

## 6. 全局资源的访问规则

### 6.1 读取
- 任意租户可读 `tenant_id IS NULL` 的资源
- 例:所有租户都能用 stock_assets(30 张预置图)
- 例:所有租户都能装 platform skills

### 6.2 写入
- 租户不能直接写全局资源
- 仅 `is_superuser=True` + 平台运营 endpoint 可写
- 例:stock_assets 增删需要超管

### 6.3 引用
- 租户资源可引用全局资源
- 例:Agent 关联的 model_config_id 可以是全局默认 model
- 例:workflow 节点引用的 stock asset id 是全局的

---

## 7. 数据迁移与备份

### 7.1 迁移
- `init_dev_db.py` 跑 18 个 `ensure_*` 函数
- 跨租户约束(删除租户时级联处理)

### 7.2 备份
- 单租户备份: 按 `tenant_id` 导出
- 全量备份: 整个 schema
- 文件存储: 按 `storage/<module>/<tenant_id>/` 分目录

### 7.3 删除租户
- 软删除?目前是硬删除(暂未实现软删除)
- 后续:加 `tenants.deleted_at` + 异步清理

---

## 8. 配额与限流

### 8.1 当前
- `tenants.max_users` — 限制用户数
- 创建用户时校验 `count(users WHERE tenant_id) < max_users`

### 8.2 计划
- `max_knowledge_bases` — 知识库数
- `max_workflow_runs_per_month` — 月度 Run 数
- `max_storage_gb` — 存储上限
- 视频/图片/TTS 月度调用次数

### 8.3 限流
- 关键 API 限流(per IP + per tenant)
- 当前:`lumen_core/rate_limiter.py`

---

## 9. 多租户 UX

### 9.1 顶部
- 右上角显示当前租户名
- 超管可见"切换租户"下拉

### 9.2 列表
- 列表只显示当前租户 + 全局资源
- 超管视图可切换"显示全部租户"

### 9.3 详情
- URL 含 `tenant_id` 时校验是否本人租户
- 跨租户访问 → 404(不泄漏存在性)

---

## 10. 安全审计

### 10.1 当前
- 关键操作(创建/删除/更新租户)写 audit log
- LLM 调用日志带 `tenant_id`

### 10.2 计划
- 租户操作审计 UI
- 异常访问告警(同一用户跨多个租户登录)

---

## 11. 与传统 SaaS 的对比

| 维度 | Lumen(私有化) | 传统 SaaS(多租户 DB) |
|------|--------------|---------------------|
| **数据位置** | 客户内网 | SaaS 提供商 |
| **DB** | 单客户单库(单 schema) | 多客户共享 schema |
| **隔离** | OS / 网络层 | 靠 `tenant_id` |
| **运维** | 客户自运维 | SaaS 运维 |
| **合规** | 数据不出域 | 数据出域 |

**Lumen 的选择**:**单库 + `tenant_id` 过滤**,理由:
- 部署简单(单实例即可)
- 跨租户统计方便
- 性能足够(单租户万级用户规模)
- 严格租户通过"独立 DB 部署"实现(高级版)

---

## 12. 升级到"独立 DB 部署"

针对金融 / 政府等需要物理隔离的客户:
- 单租户独立 MySQL 实例
- 独立 Redis
- 独立 Celery worker
- 共享 frontend + 路由层

实现成本: 1 ~ 2 周(主要工作:配置化连接字符串)

---

**维护者**:全栈架构师
**最近更新**:2026-08-06
