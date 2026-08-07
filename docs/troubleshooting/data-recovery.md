# 排错:数据恢复与修复

> 数据出问题了怎么办。
> 覆盖:备份 / 恢复 / 一致性修复 / 误删挽救 / 批量清理。

---

## ⚠️ 动手之前

**任何写操作之前,先确认你连的是哪个库。**

```sql
SELECT @@hostname, @@port, DATABASE();
```

期望:`localhost` / `3307` / `ai_platform`。

**如果不是,停下。**通用 MCP 工具默认连的是远端共享 MySQL(29 个 schema),在那上面跑 DELETE 会误伤别的项目。

**铁律**:
- ✅ `mcp__ai_platform_docker_mysql__mysql_query`
- ❌ `mcp__mcp_server_mysql__mysql_query`

**任何批量删除之前,先备份。**见 §1。

---

## 1. 备份

### 1.1 全量逻辑备份

```bash
docker exec lumen-platform-mysql \
  mysqldump -uroot -prootpassword \
  --single-transaction --routines --triggers \
  ai_platform > backup_$(date +%Y%m%d_%H%M%S).sql
```

`--single-transaction` 保证 InnoDB 一致性快照且不锁表。

### 1.2 只备份要动的表(更快,批量操作前必做)

```bash
docker exec lumen-platform-mysql \
  mysqldump -uroot -prootpassword \
  --single-transaction \
  ai_platform agent_teams agent_team_members conversations messages \
  > backup_teams_$(date +%Y%m%d_%H%M%S).sql
```

### 1.3 只备份结构

```bash
docker exec lumen-platform-mysql \
  mysqldump -uroot -prootpassword --no-data ai_platform > schema.sql
```

### 1.4 文件存储备份

DB 只是一半。文件在磁盘上:

```
storage/
├── documents/            # 上传的原始文档
├── generated_images/     # 生成的图片
├── generated_audio/      # TTS 音频
├── generated_videos/     # 合成的视频
├── stock_assets/         # 平台预置素材
├── vector_store/         # FAISS index 文件
└── _tmp/                 # 临时文件(可以不备份)
```

```bash
tar czf storage_$(date +%Y%m%d).tar.gz storage/ --exclude=storage/_tmp
```

> **DB 和文件必须同时备份**。只恢复 DB 会得到一堆指向不存在文件的记录。

---

## 2. 恢复

### 2.1 全量恢复

```bash
docker exec -i lumen-platform-mysql \
  mysql -uroot -prootpassword ai_platform < backup_20260806_120000.sql
```

### 2.2 只恢复某张表

从全量备份里抽单表(用 `sed` 截取该表的段落),或者恢复到临时库再选择性导:

```bash
# 1. 建临时库
docker exec lumen-platform-mysql mysql -uroot -prootpassword -e "CREATE DATABASE ai_platform_restore;"

# 2. 恢复到临时库
docker exec -i lumen-platform-mysql mysql -uroot -prootpassword ai_platform_restore < backup.sql

# 3. 选择性拷回
docker exec lumen-platform-mysql mysql -uroot -prootpassword -e "
  INSERT INTO ai_platform.agents
  SELECT * FROM ai_platform_restore.agents WHERE id IN (12, 15, 23);
"

# 4. 清理
docker exec lumen-platform-mysql mysql -uroot -prootpassword -e "DROP DATABASE ai_platform_restore;"
```

**这是误删单表数据时最安全的路子** —— 不覆盖现有数据。

---

## 3. 一致性修复

### 3.1 NULL 时间戳导致 list API 500

**症状**:
```
ValidationError: created_at — Input should be a valid datetime [input_value=None]
```

**根因**:早期 fixture / 迁移脚本直插 SQL 绕过 ORM 默认值。

**排查影响面**:

```sql
SELECT COUNT(*) FROM agents      WHERE created_at IS NULL OR updated_at IS NULL;
SELECT COUNT(*) FROM conversations WHERE created_at IS NULL OR updated_at IS NULL;
```

**批量修**:

```bash
cd backend && python scripts/backfill_null_timestamps.py
```

脚本行为:扫全部表,`UPDATE t SET created_at = COALESCE(created_at, NOW())`,**不动业务数据**。

**根治**(补列默认值,避免复发):

```bash
cd backend && python scripts/ensure_timestamp_defaults.py
```

**预防**:新加时间列必须写

```python
created_at: Mapped[datetime] = mapped_column(
    DateTime, server_default=func.now(), nullable=False
)
```

### 3.2 孤儿数据(父记录没了,子记录还在)

因为多数表没有 `ON DELETE CASCADE`,手工删父表容易留孤儿。

**扫描孤儿**:

```sql
-- 没有对应 conversation 的 message
SELECT COUNT(*) FROM messages m
LEFT JOIN conversations c ON m.conversation_id = c.id
WHERE c.id IS NULL;

-- 没有对应 KB 的 document
SELECT COUNT(*) FROM documents d
LEFT JOIN knowledge_bases k ON d.knowledge_base_id = k.id
WHERE k.id IS NULL;

-- 没有对应 team 的 member
SELECT COUNT(*) FROM agent_team_members m
LEFT JOIN agent_teams t ON m.team_id = t.id
WHERE t.id IS NULL;
```

**清理**(先备份):

```sql
DELETE m FROM messages m
LEFT JOIN conversations c ON m.conversation_id = c.id
WHERE c.id IS NULL;
```

### 3.3 DB 记录指向不存在的文件

```sql
SELECT id, file_path FROM documents WHERE status = 'success';
```

拿出来逐个 `os.path.exists` 检查:

```python
import os, pymysql

conn = pymysql.connect(host="localhost", port=3307, user="root",
                       password="rootpassword", database="ai_platform")
cur = conn.cursor()
cur.execute("SELECT id, file_path FROM documents WHERE file_path IS NOT NULL")
missing = [(i, p) for i, p in cur.fetchall() if not os.path.exists(p)]
print(f"{len(missing)} 条记录的文件不存在")
for i, p in missing[:20]:
    print(f"  id={i} path={p}")
```

**处理选项**:
- 文件能找回 → 放回原路径
- 找不回 → 把记录标成 `failed` 让用户重传,**不要直接删记录**(会连带丢引用关系)

### 3.4 向量库和文档表不一致

**症状**:文档表里有 100 个 chunk,但检索永远召不回某些内容。

**诊断**:
```sql
SELECT knowledge_base_id, COUNT(*) FROM document_chunks GROUP BY knowledge_base_id;
```

对比 FAISS index 的向量数量。

**修法**:重建索引(触发该 KB 全量重新向量化)。

> 重建前确认 KB 的 `embedding_model_config_id` 指向的模型还在、还能用。模型换了维度对不上,索引会建不起来。

---

## 4. 批量清理(测试污染 / 演示数据)

### 4.1 通用流程

```
1. SELECT COUNT(*) 先数一遍,确认范围
2. mysqldump 备份这几张表
3. 按 FK 依赖顺序 DELETE(子表 → 父表)
4. 再 SELECT COUNT(*) 验证
```

**永远不要跳过第 1 步和第 2 步。**

### 4.2 AgentTeam(4 层依赖)

```
messages → conversations(team_id) → agent_team_members(team_id) → agent_teams(id)
```

```sql
-- 数一遍
SELECT
  (SELECT COUNT(*) FROM agent_teams WHERE id > 15) AS teams,
  (SELECT COUNT(*) FROM conversations WHERE team_id > 15) AS convs,
  (SELECT COUNT(*) FROM agent_team_members WHERE team_id > 15) AS members,
  (SELECT COUNT(*) FROM messages
     WHERE conversation_id IN (SELECT id FROM conversations WHERE team_id > 15)) AS msgs;

-- 删(顺序不能变)
DELETE FROM messages WHERE conversation_id IN (SELECT id FROM conversations WHERE team_id > 15);
DELETE FROM conversations WHERE team_id > 15;
DELETE FROM agent_team_members WHERE team_id > 15;   -- ← 最容易漏的一张
DELETE FROM agent_teams WHERE id > 15;

-- 验证:上面那条 SELECT 再跑一遍,应该全 0
```

### 4.3 KnowledgeBase

```
document_chunks → documents → knowledge_bases
```

另外要处理:
- `agents` 表里对该 KB 的绑定关系
- 磁盘上的 FAISS index 文件
- ES 里对应的索引

### 4.4 Agent

```
messages → conversations(agent_id) → memories(agent_id) → agent_team_members(agent_id) → agents
```

### 4.5 清理后重置 AUTO_INCREMENT

```sql
ALTER TABLE agent_teams AUTO_INCREMENT = 1;
```

> InnoDB 不会真的从 1 开始,会自动用 `max(id)+1`。这条语句的实际作用是**消除 AUTO_INCREMENT 与 max(id) 之间的 gap**。
> MCP 禁 DDL,用 Python 直连跑。

---

## 5. 误删挽救

### 5.1 立刻停手

**不要**继续写操作。每一次新写入都在降低恢复成功率。

如果是生产:停掉后端和 Celery worker。

```bash
docker compose stop celery
# 后端进程也停掉
```

### 5.2 有备份 → 走临时库路线

见 §2.2。恢复到 `ai_platform_restore`,选择性 INSERT 回来。这是最安全的。

### 5.3 没备份 → 试 binlog

前提:MySQL 开了 binlog。

```sql
SHOW VARIABLES LIKE 'log_bin';        -- 期望 ON
SHOW BINARY LOGS;
```

```bash
# 导出可读的 SQL
docker exec lumen-platform-mysql \
  mysqlbinlog --base64-output=DECODE-ROWS -v \
  /var/lib/mysql/binlog.000123 > binlog.sql

# 找到误删的 DELETE 语句,手工反向构造 INSERT
grep -n "DELETE FROM \`agents\`" binlog.sql | head
```

**注意**:binlog 恢复是手工活,行数多的话很痛苦。**这就是为什么 §1 说批量操作前必须备份。**

### 5.4 没备份也没 binlog

只能重建。这时候:
- 优先恢复**配置类**数据(agents / knowledge_bases / model_configs / playbooks)—— 这些有 seed 脚本可以重跑
- **业务类**数据(conversations / messages)基本无解

```bash
cd backend
python lumen_scripts/seed_playbooks.py
python lumen_scripts/seed_stock_assets.py
python lumen_scripts/seed_mcp_demo.py
# 其他 seed 脚本见 lumen_scripts/
```

---

## 6. 迁移与升级

### 6.1 启动时的自动迁移

后端启动会跑一系列 `ensure_*` 函数(在 `lumen_core/database.py`),做幂等的建表 / 加列 / 加索引。

**卡在 `Waiting for application startup.`** = 迁移的 ALTER 拿不到 MDL,被孤儿连接阻塞。

修法见 [uvicorn-zombie §6](uvicorn-zombie.md#6-连带坑强杀留下-mysql-mdl-孤儿连接)。

### 6.2 加新列的正确写法

```python
new_field: Mapped[str] = mapped_column(
    String(255),
    nullable=False,
    server_default="",        # ← 存量行需要默认值,否则 ALTER 失败
)
```

时间列:

```python
created_at: Mapped[datetime] = mapped_column(
    DateTime, server_default=func.now(), nullable=False
)
```

**存量表加 NOT NULL 列必须给 `server_default`。**

### 6.3 迁移前的检查清单

- [ ] 全量 mysqldump 备份
- [ ] storage/ 目录备份
- [ ] 在**副本库**上先跑一遍迁移,确认无报错
- [ ] 确认新列都有 `server_default`
- [ ] 停 Celery worker(避免迁移中途有任务写入)
- [ ] 迁移后跑一遍 list API 冒烟(最容易暴露 schema 问题)

---

## 7. 健康检查脚本

日常巡检,发现问题早于用户报障:

```python
"""DB health check for Lumen AI Platform."""
import pymysql

conn = pymysql.connect(host="localhost", port=3307, user="root",
                       password="rootpassword", database="ai_platform")
cur = conn.cursor()

CHECKS = [
    ("NULL 时间戳(agents)",
     "SELECT COUNT(*) FROM agents WHERE created_at IS NULL OR updated_at IS NULL"),
    ("孤儿 message",
     "SELECT COUNT(*) FROM messages m LEFT JOIN conversations c "
     "ON m.conversation_id = c.id WHERE c.id IS NULL"),
    ("孤儿 document",
     "SELECT COUNT(*) FROM documents d LEFT JOIN knowledge_bases k "
     "ON d.knowledge_base_id = k.id WHERE k.id IS NULL"),
    ("卡住的文档(超 1 小时还在 processing)",
     "SELECT COUNT(*) FROM documents WHERE status = 'processing' "
     "AND created_at < NOW() - INTERVAL 1 HOUR"),
    ("长时间 Sleep 连接(可能是孤儿)",
     "SELECT COUNT(*) FROM information_schema.processlist "
     "WHERE command = 'Sleep' AND time > 3600"),
    ("多默认模型(同用途应只有 1 个)",
     "SELECT COUNT(*) FROM model_configs WHERE is_default = 1 AND is_chat = 1"),
]

for name, sql in CHECKS:
    cur.execute(sql)
    n = cur.fetchone()[0]
    flag = "⚠️ " if n else "✅"
    print(f"{flag} {name}: {n}")

conn.close()
```

---

## 8. 铁律

1. **写操作前先 `SELECT @@hostname, @@port, DATABASE()`**。
2. **批量 DELETE 前先 mysqldump**。没有例外。
3. **先 `SELECT COUNT(*)` 数一遍**,确认删除范围符合预期。
4. **按 FK 顺序删,子表在前**。
5. **DB 和 storage/ 一起备份**,只恢复一半等于没恢复。
6. **误删后立刻停写**,别让新数据覆盖可恢复空间。
7. **新加列带 `server_default`**,时间列带 `func.now()` + `nullable=False`。

---

**相关文档**
- [常见错误速查](common-errors.md)
- [Uvicorn 僵尸进程](uvicorn-zombie.md)
- [数据模型参考](../reference/database-schema.md)
- [多租户隔离](../architecture/04-multi-tenant.md)

---

**维护者**:全栈架构师
**最近更新**:2026-08-06
