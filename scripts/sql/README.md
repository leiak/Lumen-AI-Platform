# scripts/sql — 一键导入新库

> 给新接入者的"开箱即用"数据库 bootstrap。导完直接能登录、能用所有核心功能。

## 快速开始(2 步,3 分钟)

```bash
# 1. 建空 schema(70 张表,无数据)
mysql -uroot -p -e "CREATE DATABASE ai_platform DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci"
mysql -uroot -p ai_platform < scripts/sql/schema.sql

# 2. 灌入"系统出厂数据"(默认租户 + admin + 模型 + 模板 + 素材库等)
mysql -uroot -p ai_platform < scripts/sql/data.sql
```

完成后:

- 浏览器打开后端: `http://localhost:11335/docs`
- 默认账号: `admin` / `admin123`
- 默认租户: `code=default`,`id=1`
- 默认 LLM: 3 个 chat 模型(占位 api_key,见下面)+ 1 个本地 embedding(`nomic-embed-text`)+ 1 个图像生成(`minimax-image`)+ 4 个 TTS/SRT

## data.sql 里有什么(14 张表,~117 行)

| 表 | 行数 | 内容 |
|---|---|---|
| `tenants` | 1 | `code='default'` 默认租户 |
| `users` | 1 | `admin` 超级用户,密码 `admin123` |
| `model_configs` | 9 | 3 chat + 1 embedding + 1 image + 4 TTS/SRT |
| `system_configs` | 2 | `skill_http_allowed_domains` + `eval_default_config` |
| `mcp_servers` | 1 | `local-demo` 本地 MCP 演示服务 |
| `mcp_tools` | 7 | 6 个 demo 工具 + M33 智能问数 |
| `skill_marketplace` | 25 | 6 基础 prompt + 3 Puppeteer + 15 M34 扩充(3 http / 5 script / 1 text2sql 等) |
| `installed_skills` | 1 | "智能问数" 装到 default 租户 |
| `external_apps` | 1 | 聊天 widget demo external app |
| `text2sql_data_sources` | 1 | 默认 `ai_platform` 数据源(无 allowlist) |
| `workflow_templates` | 8 | 8 个 starter 模板(简单 LLM / RAG / HTTP / 条件 / Code / 模板 / 多步 / 参数提取) |
| `wx_templates` | 15 | 5 类 × 3 个 = 15 个系统模板(缩略图 `NULL`,需重新生成) |
| `stock_assets` | 30 | 30 张图素材元数据(PNG 文件需重新生成) |
| `stock_musics` | 5 | 5 段 BGM 元数据(MP3 文件需重新生成) |

剩余 56 张表都是空的(agent / KB / conversation / workflow / run / 等业务数据),由你用 UI 创建。

## ⚠️ 必须做的事

### 1. 填上真实的 LLM API key

`data.sql` 里的 `model_configs.api_key` 是占位符,**不填实际 key 跑不了 chat / 图像**:

```sql
-- 把 minimax(MiniMax-M2.7-highspeed / M3 / image-01)的 key 改成你的
UPDATE model_configs
SET api_key = 'sk-ant-...你的真实 key...'
WHERE model_type = 'minimax';

-- OpenAI / Anthropic / 其他按需
UPDATE model_configs SET api_key = 'sk-...'
WHERE model_type = 'openai';
```

或者直接编辑 `data.sql` 再 `mysql < data.sql`(在干净库上)。

### 2. 重新生成磁盘上的 BLOB / 资源

`data.sql` 只写元数据,**PNG / MP3 / 缩略图** 这些实际文件需要重新生成:

```bash
cd backend

# 15 个 wx 模板的缩略图(Pillow 直绘,~1MB)
python -m scripts.seed_wx_template_thumbnails

# 30 张 stock 图(Pillow,~5MB)
python -m lumen_scripts.seed_stock_assets

# 5 段 BGM(wave 合成 + ffmpeg 编码 MP3,~150KB)
python -m lumen_scripts.seed_stock_musics
```

每个脚本都是 idempotent(已存在就跳过),随时可以重跑。

### 3. (可选)改默认 admin 密码

`admin/admin123` 是明文 bootstrap,首次登录后在 `/dashboard/users` 改密。或者导出前在 `backend/.env` 设:

```bash
INIT_ADMIN_USERNAME=your_admin
INIT_ADMIN_PASSWORD=你的强密码
cd backend && python -m scripts.export_seed_data    # 重新生成 data.sql
```

## 为什么不直接 dump dev DB?

dev DB 跑了几千次测试,残留大量 fixture:

- 557 个 tenants(只有 id=1 是真的)
- 1441 个 users(只有 admin 是真的)
- 111 个 external_apps(测试创建)
- 21 个 model_configs 里的"global builtin"行其实是 service-account 测试残留(例:`svc_test_global_mc_74134b`)

`data.sql` 是通过以下路径生成的**干净数据**:

```
临时空库(ai_platform_seed_export)
  → source schema.sql
  → reset AUTO_INCREMENT=1(因为 schema.sql 里有 mysqldump 留下的 AUTO_INCREMENT=3731)
  → python -m scripts.init_dev_db                 (10 步:schema + tenant + admin + mcp + skills + 3 chat models + 8 wf templates + 15 wx templates + thumbnails + text2sql)
  → python -m lumen_scripts.seed_stock_assets     (30 PNG)
  → python -m lumen_scripts.seed_stock_musics     (5 BGM)
  → python -m lumen_scripts.seed_m35_default_models (3 TTS + 1 SRT + 5 playbook)
  → python -m lumen_scripts.seed_m37_default_eval_config (写 system_configs[eval_default_config])
  → 手动补:Auto: nomic-embed-text + minimax-image
  → Python 拼 INSERT, 写到 data.sql
  → 删临时库
```

具体看 `backend/scripts/export_seed_data.py`(400+ 行,有详细注释)。

## 重新生成 data.sql

新加 seed 脚本后(比如 M38 加了 5 个新技能),重导:

```bash
cd backend
PYTHONIOENCODING=utf-8 DATABASE_URL="mysql+pymysql://root:rootpassword@localhost:3307/ai_platform" \
    python -m scripts.export_seed_data
# 输出: scripts/sql/data.sql (覆盖)

# 验证还能正常导入干净库
python -m scripts.verify_data_sql
```

## 已知限制

- **eval 默认数据集不导出**:`seed_eval_dataset_default` 需要 KB 里有 5+ 篇文档,空库跑不了。先建 KB → 灌文档 → 再 `python -m lumen_scripts.seed_eval_dataset_default`。
- **api_key 哈希不导出**:数据里 admin 密码是 `admin123` 哈希后的 bcrypt 值(从 seed 脚本现生成,每次盐不同),**只要 .sql 里 hashed_password 没被改,`admin/admin123` 永远能登**。
- **不能往已用库重跑**:`INSERT INTO tenants (code) VALUES ('default')` 会撞 `UNIQUE` 约束,但 `INSERT INTO model_configs` 之类没有 UNIQUE 的表会越灌越多。永远从干净库开始。
- **`schema.sql` 含 mysqldump 残留的 `AUTO_INCREMENT=N`**:在干净库里这个值会被 export 脚本自动重置成 1;`mysql < schema.sql` 直接灌,首个 INSERT 会拿到 3731(对功能无影响,只是 ID 大)。

## FAQ

**Q: 我直接 `mysql < schema.sql` 然后跑 init_dev_db 不就行了?为啥需要 data.sql?**
A: 当然可以。`data.sql` 给你的是 "**不用克隆代码,不用装 Python 依赖,不用 clone backend 整个项目**" 就能跑系统的能力。给纯 DBA / 部署工程师 / 评审人用。

**Q: 用户的 KB / agent / 对话 怎么导出?**
A: 不在 data.sql 范围(用户级数据,不能复用)。需要的话单独写 mysqldump,或者用 `backend/scripts/dump_dev_db.py`。

**Q: `stock_assets.file_path` 是相对路径,真的能工作吗?**
A: 取决于 `STORAGE_DIR` 环境变量(默认 `backend/storage`)。如果你的部署改了 `STORAGE_DIR`,需要把 PNG / MP3 物理文件也复制过去,或者重新跑 seed 让它按你的新 `STORAGE_DIR` 生成。

**Q: 能塞到 CI 里跑吗?**
A: 可以,但要先 clone 整个 repo + 装 Python deps。`data.sql` 的真正价值是 **脱离 repo 也能用**。
