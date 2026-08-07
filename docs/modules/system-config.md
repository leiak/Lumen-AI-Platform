# 模块:系统配置(System Config)

> 平台级 KV 配置存储,first consumer 是 M16 HTTP 技能的白名单。
> 文档讲透怎么加新配置、怎么读、怎么改。

---

## 1. 产品定位

**SystemConfig 是什么?**

- 一张平台级的 KV 表,存**单例** + **全局** + **载体任意的**配置
- Schema 灵活:`value` 是 JSON,可以是 list / dict / scalar
- 第一个消费者:`HttpExecutor._resolve_allowed_domains` 读 `skill_http_allowed_domains`

**和 `system_settings` 区别?**

| 维度 | `system_settings` | `system_configs` |
|------|-------------------|------------------|
| 隔离 | **per-tenant** | **platform-wide**(单例) |
| Schema | 固定列(default_model / chat_history_days / 系统名 / 描述) | 灵活 JSON |
| 改法 | UI Settings 页 | 暂时 SQL / 未来 admin UI |
| 谁用 | 平台业务 | 平台 operator / 内部服务 |

**业务场景?**

- HTTP 技能白名单域名 (`skill_http_allowed_domains`)
- 平台级 feature flag
- 第三方集成的全局阈值
- 频繁改但又不想走代码的开关

**一句话**:**operator-tunable 平台设置,不要塞进 ENV 变量,也不要塞进代码**。

---

## 2. 功能清单

| 功能 | 描述 |
|------|------|
| 启动 seed | `ensure_system_configs_table` 启动时 idempotent 写入默认值 |
| 读 | 服务层 `get(key)` / `set(key, value)` |
| 强类型 | `value` JSON,接入方自己反序列化 |
| 不覆盖 | seed 只填空行,**不覆盖**已有行(防止踩掉手动改的配置) |
| 多形式 | 任意 JSON 形态:list / dict / scalar |
| 列出 | 全部 key + value 列表(管理员) |

---

## 3. 数据模型

### 3.1 `system_configs`

```python
# backend/lumen_models/system_config.py

class SystemConfig(BaseModel):
    __tablename__ = "system_configs"

    key: str            # VARCHAR(100), UNIQUE — 点分, e.g. "skill_http_allowed_domains"
    value: dict         # JSON, nullable=False, 任意结构
```

**`id` / `created_at` / `updated_at`**:继承 `BaseModel`。

### 3.2 当前的 key 清单

| key | value 类型 | 默认 | 用法 |
|-----|-----------|------|------|
| `skill_http_allowed_domains` | `list[str]` | `[]` | HTTP 技能允许的域名白名单 |
| (其他由 `lumen_scripts/seed_system_configs.py` 填) | | | |

**seed 入口**:`backend/lumen_scripts/seed_system_configs.py`

### 3.3 文件清单

| 层 | 路径 |
|----|------|
| ORM | `backend/lumen_models/system_config.py` |
| 启动 seed | `lumen_core/database.py::ensure_system_configs_table` |
| 操作服务 | `backend/lumen_services/settings_service.py` |
| Seed 脚本 | `backend/lumen_scripts/seed_system_configs.py` |
| 路由 | 暂无专属,直接 SQL 改 |

---

## 4. 核心流程

### 4.1 启动 seed

```python
# backend/lumen_core/database.py

def ensure_system_configs_table() -> None:
    """Idempotent create + seed system_configs.

    Creates the table if missing, then inserts the default rows via
    INSERT IGNORE so manual admin updates are NOT clobbered.
    """
    Base.metadata.create_all(_engine, tables=[SystemConfig.__table__])

    defaults = [
        ("skill_http_allowed_domains", ["api.openai.com", "api.anthropic.com",
                                          "httpbin.org", "localhost"]),
        # ... 其他模块如果有
    ]
    with _engine.begin() as conn:
        for k, v in defaults:
            stmt = (
                mysql.insert(SystemConfig.__table__)
                .values(key=k, value=v)
                .prefix_with("IGNORE")  # ← INSERT IGNORE
            )
            conn.execute(stmt)
```

**关键**:
- `INSERT IGNORE` — 已存在则跳过,**保护手动改过的值**
- 用 `_engine.begin()`(自动 commit) + `prefix_with("IGNORE")` 而非 `ON DUPLICATE KEY UPDATE`(那会覆盖)

### 4.2 读取

```python
# backend/lumen_services/settings_service.py(or 各 module 自查)

def get_system_config(key: str, default=None):
    """Get value for key. Returns default if not found."""
    with session_scope() as db:
        row = db.scalar(select(SystemConfig).where(SystemConfig.key == key))
        return row.value if row else default
```

**典型用法**(HTTP 技能):
```python
# backend/lumen_services/skill_executors/http_executor.py (M16)

def _resolve_allowed_domains() -> list[str]:
    """Dynamic read — operator may update the SQL row at runtime."""
    row = db.scalar(select(SystemConfig).where(
        SystemConfig.key == "skill_http_allowed_domains"
    ))
    return row.value if row else []
```

**每次调用都读 DB**:性能可接受(单条主键查询,毫秒级)。**缓存是改进方向**(见 §10)。

### 4.3 更新

**当前**:
- 直连 SQL: `UPDATE system_configs SET value = '["..."]' WHERE key = '...'`
- 未来 admin UI

**不暴露 API**:`/api/v1/system-configs` **没有**端点,因为:
- 平台级配置,租户不该改
- 改坏的代价太大,需要 operator 走 SQL 思考

---

## 5. 关键设计决策

### 5.1 INSERT IGNORE 而非 ON DUPLICATE KEY UPDATE

```sql
-- ✅ 用 INSERT IGNORE
INSERT IGNORE INTO system_configs (key, value) VALUES ('x', '["a"]');

-- ❌ 用 ON DUPLICATE KEY UPDATE
INSERT INTO ... ON DUPLICATE KEY UPDATE value = '["a"]';
```

**为什么**:`ON DUPLICATE KEY UPDATE` 会**覆盖**手动改的配置;`INSERT IGNORE` 保留。

**场景**:operator 上线时手动加了一个允许域名,后续启动时 seed 又跑 → 如果用 ON DUPLICATE 会清掉。IGNORE 保留。

### 5.2 不暴露 API

**为什么**:
- 平台级配置 → 改坏影响所有租户
- 通过 chat / workflow 间接调用时**无法限制** "只读特定 key"
- operator 走 SQL 反而**有审计痕迹**(general log)

### 5.3 频繁读 DB 而非缓存

```python
# http_executor.py 每次调用都 SELECT
# WHY:
- 缓存要 invalidate,新增 key 时容易踩坑
- 单次主键查询 < 1ms
- 容量压力极小(几十个 key)
```

**升级路径**:进程内 LRU + 30s TTL,见 §10。

### 5.4 不放 ENV 变量

**为什么**:ENV 变量改完要重启,且不容易审计。**SystemConfig 改一行 SQL 立即生效**(虽然当前没有动态监听,但 hot reload 是改进方向)。

---

## 6. 与其他模块的关系

```
[Operator] → SQL 更新 system_configs
        ↓
[启动 seed] → INSERT IGNORE 默认行
        ↓
[HttpExecutor] 每次调用 SELECT
        ↓
[拒绝 / 允许] (HTTP 技能白名单)
```

**跨模块复用**:
- 任何平台级 KV 配置都可以用这张表
- 加新 key 步骤: ① ORM 不动 ② seed 加默认 ③ 业务 SELECT

---

## 7. 已知局限

| 局限 | 影响 | 缓解 |
|------|------|------|
| 每次读 DB | 1ms 延迟 × 调用次数 | 进程内缓存 |
| 没有 API | operator 改 SQL 容易错 | 未来 admin UI |
| 没有版本 | 改了想回滚得备份 | 手动备份 |
| 没有 audit | 谁/何时改了不知道 | general log |
| 没有 key 校验 | 任意字符串都能塞 | 业务层校验 |
| 进程不监听变更 | 改完 SQL,运行中进程不会立即刷新 | 缓存 30s TTL |

---

## 8. 边界与不做

### 8.1 当前
- ✅ 平台级 KV,JSON 自由结构
- ✅ 启动 seed(idempotent INSERT IGNORE)
- ✅ 多 module 复用(目前主要是 HTTP 技能)
- ✅ 不覆盖手动配置

### 8.2 不做
- ❌ API endpoint
- ❌ 租户级(per-tenant)配置(用 `system_settings`)
- ❌ UI
- ❌ audit log
- ❌ 版本控制
- ❌ 跨实例广播(改完一个实例,其他实例看不见)
- ❌ 类型校验(运行时类型由业务模块负责)

### 8.3 升级路径

| 阶段 | 改动 |
|------|------|
| 短期 | 进程内 LRU 缓存(30s TTL) |
| 短期 | 加 API + 简单 admin UI |
| 中期 | 多实例广播(Redis pub/sub) |
| 长期 | 版本控制 + audit |
| 长期 | 类型 schema 强制 |

---

## 9. 排错

| 症状 | 原因 | 修法 |
|------|------|------|
| HTTP 技能全部 403 | 白名单被清空 | `UPDATE system_configs SET value = '["..."]' WHERE key = 'skill_http_allowed_domains'` |
| 启动时 seed 把手动改的覆盖了 | (不该发生) | 上 IGNORE 而非 ON DUPLICATE |
| 找不到某 key | `ensure_system_configs_table` 没跑 | 重启 / 手动调 |
| value 是 string 而非 list | 写时没 JSON encode | `value = JSON.dumps([...])` |
| 改了发现不生效 | 进程没刷新 | 缓存住的(尚未实现) |
| 误改 platform-wide 影响所有租户 | 风险 | 必须留 SQL 执行截图,变更审批 |

---

## 10. 关键代码示例

### 10.1 加新 key 的标准流程

```python
# 1. lumen_scripts/seed_system_configs.py
DEFAULT_SYSTEM_CONFIGS = [
    ("skill_http_allowed_domains", [
        "api.openai.com", "api.anthropic.com", "httpbin.org", "localhost",
    ]),
    ("feature_max_concurrent_workflows", 10),  # ← 新加
    ("experiment_new_chat_template", False),  # ← 新加
]

# 2. lumen_core/database.py ensure_system_configs_table() 同样数组

# 3. 业务模块读取
def get_max_concurrent() -> int:
    row = db.scalar(select(SystemConfig).where(
        SystemConfig.key == "feature_max_concurrent_workflows"
    ))
    return int(row.value) if row else 10
```

### 10.2 复杂 value

```python
# 列表
("skill_http_allowed_domains", ["a.com", "b.com"])

# 嵌套
("skill_http_per_method_limits", {
    "GET": 100,
    "POST": 50,
})

# 嵌套列表
("skill_http_method_domain_pairs", [
    {"method": "GET", "domain": "api.openai.com"},
    {"method": "POST", "domain": "api.anthropic.com"},
])
```

---

## 11. 安全

- **平台级**配置 → 改坏的爆炸半径**全租户**
- DB 访问控制:**只允许 DBA / operator 改**
- 一定要有审计日志(production → 接入 audit_logs)
- 临时改后**回滚**(UPDATE 反向或 DELETE 行)
- 默认 INSERT IGNORE 保护手动配置

---

**相关文档**
- [多租户隔离](../architecture/04-multi-tenant.md) — 平台配置 vs 租户配置(`system_settings` / `security_settings`)
- [HTTP 技能](../modules/skill-market.md) — 第一个消费者
- [数据模型参考](../reference/database-schema.md) — 完整 schema

**维护者**:全栈架构师
**最近更新**:2026-08-06
