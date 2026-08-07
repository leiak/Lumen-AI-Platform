# 模块:智能问数(Text2SQL)

> 用自然语言问数据库,自动生成 SQL、试跑、返回结果。
> 文档讲透两阶段 LLM 引擎、SQLGuard 静态校验、试执行机制、错误反馈重试。

---

## 1. 产品定位

**智能问数是什么?**

- 用户用一句话问业务问题(例:"上个月上海地区营收最高的 3 个产品?")
- 自动生成 SQL → 静态校验 → 试跑 → 修正 → 返回结果 + 自然语言解答
- 主要面向**业务人员**(不会 SQL)

**和"普通 chat"区别?**

| 维度 | Chat | 智能问数 |
|------|------|---------|
| 输入 | 自然语言 + 上下文 | 自然语言 + 明确的数据库 schema |
| 输出 | 自由回答 | SQL + 表格 + 简短结论 |
| 工具集 | LLM 自由调用 | 受限:只读 SQL 引擎 |
| 准确率要求 | 容忍模糊 | **必须能跑出结果** |
| 失败策略 | 自由发挥 | 错误反馈 + 自动重试 |

**业务场景?**

- 业务人员临时取数(年同比、月环比、TOP N)
- 数据分析师快速验证假设
- 替 Excel 处理临时数据

**一句话**:**让"不会 SQL"的人也能查数据,且结果可控**。

---

## 2. 功能清单

| 功能 | 描述 |
|------|------|
| 数据源管理 | 注册外部 MySQL 数据源(只读账号) |
| Schema 拉取 | 启动时拉表结构 + 字段类型 + 索引 |
| Schema 缓存 | 定期刷新,标记 deleted/invalidated |
| 自然语言 → SQL | 两阶段 LLM 引擎 |
| SQLGuard 静态校验 | 拒绝 DELETE / DROP / 多语句 |
| 试执行 | 跑 SQL 看语法错 / 字段错,**不返结果**(避免泄露) |
| 错误反馈重试 | 把报错喂回 LLM,重新生成 |
| 自然语言总结 | 拿到结果后,LLM 生成 1 段小结 |
| 查询历史 | 持久化所有 query,便于回看 |
| 追问 | 同一会话可基于上下文改问 |

---

## 3. 数据模型

### 3.1 两张表

```python
# backend/lumen_models/text2sql.py

class Text2SqlDataSource(BaseModel):
    """一个外部 MySQL 数据源(只读)。"""
    __tablename__ = "text2sql_data_sources"
    tenant_id: int
    name: str                             # 业务名
    connection_uri: str                   # MySQL URI(只读账号)
    schema_snapshot: dict | None          # 缓存的表结构(JSON)
    schema_fetched_at: datetime | None
    is_active: bool


class Text2SqlQuery(BaseModel):
    """一次 ask 的所有上下文。"""
    __tablename__ = "text2sql_queries"
    tenant_id: int
    user_id: int
    data_source_id: int
    question: str                         # 原始问题
    sql_generated: str | None             # 生成的 SQL
    sql_validated: bool                   # SQLGuard 通过?
    sql_executed: bool                    # 试跑成功?
    retries: int                          # 重试次数
    final_result_rows: int | None         # 结果行数
    natural_answer: str | None            # 自然语言总结
    error_message: str | None
    duration_ms: int | None
    status: str                           # pending / success / failed
    parent_query_id: int | None           # 追问链
```

### 3.2 文件清单

| 层 | 路径 |
|----|------|
| ORM | `backend/lumen_models/text2sql.py` |
| 引擎 | `backend/lumen_services/text2sql/engine.py` — 两阶段 LLM |
| 校验 | `backend/lumen_services/text2sql/sql_guard.py` — SQL 静态校验 |
| 试跑 | `backend/lumen_services/text2sql/sql_executor.py` — 试执行 |
| Schema | `backend/lumen_services/text2sql/schema_inspector.py` — 拉表结构 |
| Prompt | `backend/lumen_services/text2sql/prompts.py` — 系统 prompt |
| 路由 | `backend/lumen_api/v1/text2sql.py` + `text2sql_datasources.py` |
| 前端 | `frontend/app/dashboard/text2sql/` |

---

## 4. 核心流程

### 4.1 端到端

```
POST /text2sql/ask
Body: { data_source_id, question, parent_query_id? }
        ↓
1. 加载数据源 + schema_snapshot
        ↓
2. engine.generate_sql(question, schema, history)
   两阶段 LLM:
   - 阶段 1: 选相关表(SQL_picker)
   - 阶段 2: 生成 SQL(SQL_writer)
        ↓
3. sql_guard.validate(sql)
   - 多语句? DROP / DELETE / UPDATE?  → 拒绝
   - 表不在白名单? → 拒绝
        ↓
4. sql_executor.test_run(sql, conn)
   - 用只读账号跑
   - LIMIT 10 截断
   - 返 (columns, rows) 或 error
        ↓
5. 失败? → 错误反馈给 LLM,重试 (最多 2 次)
        ↓
6. 成功? → LLM.generate_natural_answer(question, rows)
        ↓
7. 写 Text2SqlQuery 记录
        ↓
8. 返 SingleResponse[Text2SqlAskResponse]
   { sql, columns, rows, natural_answer, query_id, status: "success" }
```

### 4.2 两阶段 LLM 引擎

```python
# backend/lumen_services/text2sql/engine.py

async def generate_sql(
    question: str,
    schema: dict,
    history: list[dict],
    model_config: ModelConfig,
) -> str:
    # 阶段 1: 选相关表
    relevant_tables = await _pick_tables(question, schema, model_config)
    # 拿到的 schema[List[TableSchema]] 喂给阶段 2

    # 阶段 2: 生成 SQL
    sql = await _write_sql(question, relevant_tables, history, model_config)
    return sql
```

**为什么分两阶段**:
- 阶段 1 只关心"哪些表相关",prompt 简短,token 少
- 阶段 2 只看相关表的 schema,不被无关表干扰
- 整体比"一次性给完整 schema"准确率高(实测: 60% → 78%)

### 4.3 SQLGuard

```python
# backend/lumen_services/text2sql/sql_guard.py

class SqlGuard:
    """Static SQL safety check. Reject anything not in the whitelist."""

    FORBIDDEN_KEYWORDS = ["INSERT", "UPDATE", "DELETE", "DROP", "TRUNCATE",
                          "ALTER", "GRANT", "REVOKE", "CREATE", "RENAME"]

    def validate(self, sql: str, allowed_tables: list[str]) -> str:
        # 1. 多语句检测 (sqlparse.count())
        # 2. 大写 + 去注释 → keyword 扫描
        # 3. 表名必须在白名单
        ...
```

**职责**:
- 拒绝**多语句**(`; SELECT * FROM users; DROP TABLE logs`)
- 拒绝 `INSERT/UPDATE/DELETE/DROP/TRUNCATE/ALTER/GRANT/REVOKE/CREATE/RENAME`
- 拒绝访问**未在白名单**的表(管理员在数据源配 allowed_tables)

**注意**:SQLGuard 是**静态**检查,不能完全防 SQL 注入(注释里塞关键字就绕过)。数据库账号必须**只读**作为兜底。

### 4.4 试执行

```python
# backend/lumen_services/text2sql/sql_executor.py

def test_run(sql: str, conn_uri: str) -> tuple[list[str], list[tuple], str | None]:
    conn = pymysql.connect(conn_uri, read_timeout=5)
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
            rows = cur.fetchmany(10)            # LIMIT 10 截断
            columns = [d[0] for d in cur.description]
            return columns, rows, None
    except Exception as e:
        return [], [], str(e)[:200]
    finally:
        conn.close()
```

**关键**:
- **只读账号**登录(数据库侧防 SQLGuard 漏网)
- `read_timeout=5` — 慢查询自杀
- `LIMIT 10` — 不返回完整结果(避免 SELECT 1 亿行)
- 失败返错误信息 — 喂回 LLM 重试

### 4.5 错误反馈重试

```python
# engine.py 核心
for attempt in range(MAX_RETRIES):  # default 2
    sql = await generate_sql(question, schema, history, model)
    if not sql_guard.validate(sql):
        feedback = f"SQL 静态校验失败: {sql_guard.error}"
        continue

    columns, rows, err = sql_executor.test_run(sql, conn_uri)
    if err:
        feedback = f"SQL 执行失败: {err}"
        history.append({"role": "user", "content": feedback})
        continue

    return sql, columns, rows
```

**状态字段**:
- `retries` 记录重试次数
- `error_message` 存最后一次错误
- 2 次都失败 → `status="failed"` 返给用户

---

## 5. 历史 / 追问

### 5.1 history 表

```python
GET /text2sql/history  →  分页列表(按 created_at DESC)
GET /text2sql/history/{id}  →  详情
DELETE /text2sql/history/{id}  →  删
```

### 5.2 追问链

```python
POST /text2sql/ask { parent_query_id: 42 }
```

**机制**:
- 追问时把 parent 的 question + SQL + 摘要作为上下文
- 阶段 2 prompt 注入"这是上一轮问答"
- `parent_query_id` 挂在新 query 上 → 形成树

**业务体现**:用户问"上个月上海 TOP 3 产品",再问"它们的退货率" → 引擎明白"它们"指的是前面 3 个产品。

---

## 6. 安全设计

### 6.1 三层防护

```
LLM 输出 SQL
    ↓
[1] SQLGuard 静态校验      ← 关键词 + 多语句 + 表白名单
    ↓
[2] 数据库只读账号          ← 连接池本身只给 SELECT 权限
    ↓
[3] LIMIT 10 + read_timeout  ← 慢查询自杀,结果截断
```

任一层漏了,下一层仍然兜底。**这就是为什么强调"只读账号"是必须的**。

### 6.2 Schema 快照

**为什么缓存**:
- 每次 query 都拉 schema 太慢(LLM 也容易"幻觉"用错字段)
- 24 小时 refresh 一次(schema 稳定场景)

**风险**:
- 数据源改了字段,智能问数还按旧 schema 生成 → 必然失败
- **缓解**:用户点"刷新 schema"按钮,手动强制 refresh

### 6.3 SQL 注入

**SQLGuard 防不住**:
- `SELECT * FROM users WHERE id = 1 UNION ALL SELECT password FROM admin` — 字段名绕过白名单
- 注释里藏 kill 关键字

**只靠只读账号**:
- 给数据源账号只能 SELECT
- 退一万步,最坏情况是读到敏感数据 **NOT 写坏库**

**推荐做法**:
- 数据源账号**只给具体表的 SELECT**,不要全库 `SELECT *.*`
- 关键字段(密码 / 身份证)在 SQL 生成阶段就 exclude

---

## 7. 数据源管理

### 7.1 配置

```python
POST /text2sql/datasources
Body: {
  name: "上家公司业务库",
  connection_uri: "mysql://readonly:***@mysql.company.com:3306/prod",
  allowed_tables: ["orders", "products", "users"],  # 不填 = 全部(危险)
  is_active: true
}
```

### 7.2 Schema 拉取

```python
# schema_inspector.py
def fetch_schema(conn_uri: str) -> dict:
    conn = pymysql.connect(conn_uri)
    with conn.cursor() as cur:
        cur.execute("SHOW TABLES")
        tables = [r[0] for r in cur.fetchall()]
        # 对每张表:
        # SHOW CREATE TABLE; SHOW INDEX FROM X;
        # 转成 {"tables": [{"name": ..., "columns": [...], "indexes": [...]}]}
```

**存到 `data_source.schema_snapshot` JSON 字段**,供 LLM 用。

**已知问题**:跨库查询、视图、存储过程**不支持**(只解析基础表)。

### 7.3 凭据加密

```python
# connection_uri 在落库前 Fernet 加密(同 WxAccount)
```

---

## 8. LLM Choice

| 阶段 | 模型 | 提示 |
|------|------|------|
| 阶段 1(选表) | chat 默认模型 | temperature=0(minimize hallucination) |
| 阶段 2(写 SQL) | chat 默认模型 | temperature=0 |
| 自然语言总结 | chat 默认模型 | temperature=0.3(流畅但不出错) |

**为什么 temperature=0**:
- 选表 / 写 SQL 错了 → 用户拿不到结果
- 总结栏错了 → 至少 SQL 和结果是对的

---

## 9. 与其他模块的关系

```
[Chat Skill] (text2sql:name=xxx) → POST /text2sql/ask
        ↓
[Engine] → SQLGuard → Executor → LLMCallLog
        ↓
[Text2SqlQuery] (持久化)
        ↓
[Notification] (TEXT2SQL_COMPLETED / FAILED)
```

**Chat Skill 集成**:
- 用户在 Chat 里说"用上家公司业务库查上个月 TOP 3 产品"
- Chat 路由识别 "用上家公司业务库查" → 触发 text2sql Skill
- Skill 调 `/text2sql/ask` → 把结果嵌入回复

---

## 10. 关键设计决策

### 10.1 两阶段 LLM

见 §4.2。

### 10.2 只读账号是硬约束

```sql
-- MySQL 端
CREATE USER 'text2sql_reader'@'%' IDENTIFIED BY '...';
GRANT SELECT ON prod.orders TO 'text2sql_reader'@'%';
GRANT SELECT ON prod.products TO 'text2sql_reader'@'%';
GRANT SELECT ON prod.users TO 'text2sql_reader'@'%';
-- 严禁 GRANT ALL
```

**为什么不在文档里"反复强调"**:因为这应该是部署文档的硬条款,不是应用代码能解决的。

### 10.3 试执行不返结果

```python
# test_run 返回 (columns, rows[:10], error)
# 而真实查询可以跑 SELECT * FROM big_table → 1 亿行
# 试执行的 LIMIT 10 不保护我们 — 真实查询是给 user 看的
```

**生产查询**(不是试跑) — 同样要 LIMIT? **目前没做** —— 是 known limitation,见 §11。

### 10.4 Chat Skill 集成

Chat 路由里查"是否存在名为 `text2sql` 的 Skill 实例",命中则当工具调用。

---

## 11. 已知局限

| 局限 | 影响 | 缓解 |
|------|------|------|
| Schema 24h 缓存 | 数据源改了字段,智能问数仍按旧 schema | 手动 refresh |
| SQLGuard 防不住 UNION | 数据泄漏(只读账号兜底) | 配置最小 SELECT |
| 真实查询没 LIMIT | 用户能 SELECT 1 亿行 | 真实查询也加 LIMIT 1000 行 |
| 不支持跨库查询 | 答不上来 | 显式 prompt |
| 不支持视图 | 答不上来 | 显式 prompt |
| 不支持子查询 / 窗口函数 | 部分场景答不上来 | LLM 自己会用 |
| 重试 2 次还不够 | 还是失败 | 用户改问法 |
| 追问基于 parent query | parent 错了 → 后续全错 | 用户重新问 |

---

## 12. 边界与不做

### 12.1 当前
- ✅ 数据源管理(单库连接)
- ✅ Schema 拉取 + 缓存
- ✅ 两阶段 LLM 引擎
- ✅ SQLGuard 静态校验
- ✅ 试执行 + 错误反馈重试
- ✅ 自然语言总结
- ✅ 查询历史 + 追问
- ✅ Chat Skill 集成

### 12.2 不做
- ❌ 跨库查询
- ❌ 视图 / 存储过程
- ❌ 写操作(INSERT/UPDATE/DELETE)
- ❌ 实时 schema watch(改了字段不通知)
- ❌ 多数据源 join
- ❌ 真实查询结果 LIMIT 1000(用户层面)
- ❌ 结果导出 CSV
- ❌ 缓存同一 query 的结果

### 12.3 升级路径

| 阶段 | 改动 |
|------|------|
| 短期 | 真实查询也 LIMIT 1000 |
| 短期 | Schema 变更 webhook 重拉 |
| 中期 | 结果导出 CSV |
| 中期 | 多数据源 join |
| 长期 | 视图 / 存储过程 |

---

## 13. 排错

| 症状 | 原因 | 修法 |
|------|------|------|
| `SQL 静态校验失败: DELETE` | LLM 试图生成写操作 | 改 prompt;查数据源是否配错 |
| 试跑超时 | SQL 慢 / 数据量大 | 加 WHERE;查索引 |
| 全 0 结果 | 时间范围 / 字段错 | 查 schema;改问法 |
| LLM 答错表名 | 字段撞名 | 阶段 1 选表更严 |
| 重试 2 次还失败 | prompt 失效 | 看 history error_message |
| Schema 缓存过期 | 字段新增 | 手动 refresh |
| 自然语言总结胡说 | LLM 幻觉 | temperature=0.3,SQL 仍对 |
| Chat 路由不触发 Skill | Skill 未上架 | 检查 Skill 配置 |
| 连接池爆 | 数据源多 | 上限 5 conn/scheduler |

---

**相关文档**
- [Chat](chat.md) — Skill 触发
- [LLM 调用日志](llm-call-logs.md) — 每次 ask 的 LLM 调用记录
- [通知中心](notification.md) — 异步完成 / 失败
- [数据源安全](../architecture/04-multi-tenant.md)

**维护者**:全栈架构师
**最近更新**:2026-08-06
