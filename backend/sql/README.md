# Dev DB dump 目录

`ai_platform_dump_<date>.sql` 是 dev 数据库 `ai_platform` (localhost:3307) 的
完整结构 + 数据快照。文件**不进入 git**(见根 `.gitignore`),只在本地
保留作为 dev 环境状态快照。

## 何时打 dump

- 写 spec/plan 提交 PR 前(快照当前 dev DB 状态附在 PR description,方便
  reviewer 了解 "跑测试时数据库长什么样")
- 重要迁移跑过之后(留底以备回滚验证)
- 重大 fix 前(比如 cascade 修复)— 留个 before-state 用于 diff

## 怎么打 dump

`scripts/dump_dev_db.py` 用 `pymysql` 走 `SHOW CREATE TABLE` + `SELECT *`
逐表 dump。**不需要 mysqldump binary**(本机没装)。

```bash
python scripts/dump_dev_db.py backend/sql/ai_platform_dump_2026-MM-DD.sql
```

默认输出 `C:\Users\wma19\ai_platform_dump.sql`。

## 怎么 load dump

把 `.sql` 文件灌回 `ai_platform` DB(请**先确认这不是生产库**):

```bash
# 用项目 Python + pymysql(避免依赖 mysql client)
python -c "
import pymysql
conn = pymysql.connect(host='localhost', port=3307, user='root',
                       password='rootpassword', database='ai_platform',
                       charset='utf8mb4', connect_timeout=10)
cur = conn.cursor()
with open(r'backend/sql/ai_platform_dump_2026-MM-DD.sql', encoding='utf-8') as f:
    sql = f.read()
for stmt in sql.split(';\n'):
    s = stmt.strip()
    if s: cur.execute(s)
conn.commit()
conn.close()
print('LOADED')
"
```

`dump_dev_db.py` 的输出里 `SET FOREIGN_KEY_CHECKS=0` 在头部,`=1` 在尾部,
所以 INSERT 顺序不会撞 FK。loader 拆分 `;\n` 重放即可。

## 内容覆盖范围

dump 当前包含 28 张表完整 schema + 数据:
- agent / chat(conversations, messages) / KB(kb, documents, chunks, faq)
- workflow(workflows / runs / node_runs / templates)
- M27 可观测性(llm_call_logs / embedding_call_logs)
- M32 公众号(wx_drafts / wx_materials / wx_templates)
- M14 widget(external_apps / external_visitors)
- users / tenants / notifications / skills / etc.

## 不要做的事

- ❌ 把 `.sql` 文件加进 git(5 MB 一次,bloat repo)
- ❌ 把 dump 发到生产(包含 user plaintext / API keys / 真实数据)
- ❌ 用 dump 文件做"diff 数据库 schema" — schema drift 看 alembic 迁移脚本