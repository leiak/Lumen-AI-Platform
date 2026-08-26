# How-to:本地开发环境搭建

> 从 0 搭建一套能跑、能改、能调试的开发环境。
> 假设你已经装好了 Docker、Docker Compose、Python 3.11、Node 20+。

---

## 1. 准备工具

### 1.1 必备

| 工具 | 版本 | 用途 |
|------|------|------|
| Docker | 24+ | 跑 MySQL / Redis / Ollama / ES |
| Docker Compose | v2 | 容器编排 |
| Python | 3.11 | 后端 |
| Node | 20+ | 前端开发 |
| Git | 2.30+ | 拉代码 |
| WSL2 / Git bash | — | Windows 必备 |

### 1.2 Python 工具

```bash
pip install -r backend/requirements.txt
```

如果是 Anaconda,**直接用**:Anaconda 自带大部分库。

### 1.3 Node 工具

```bash
cd frontend
npm install
```

### 1.4 MCP(Claude Code)

打开 `.mcp.json` 接受提示:`context7` + `ai_platform_docker_mysql`。

**mysql MCP 凭据**:`backend/.env` 的 `DATABASE_URL` 解析。
**mysql MCP 拒绝的操作**:DDL、CROSS schema、KILL connection。

---

## 2. 启动顺序

### 2.1 启动 Docker 服务

```bash
docker compose up -d mysql redis ollama elasticsearch
```

**首次启动**:
- MySQL 3307 — 5 秒
- Redis 16379 — 2 秒
- Ollama 11434 — 10 秒
- Elasticsearch 9200 — 30 秒(看 CPU)

### 2.2 拉 Ollama 模型

```bash
docker exec lumen-platform-ollama ollama pull nomic-embed-text
docker exec lumen-platform-ollama ollama pull qwen2.5:7b
```

**首次下载**:
- `nomic-embed-text` — 274 MB
- `qwen2.5:7b` — 4.7 GB

**加速**:配置 `OLLAMA_MODELS` 目录到本地磁盘。

### 2.3 启动后端

```bash
cd backend
python -m uvicorn lumen_main:app --reload --port 11335
```

**首次启动**:
- 跑 `ensure_*` 迁移(新建表 / 加列 / 加索引)
- 跑 `seed_*`(初始化默认数据)
- 5-30 秒

**关键 log**:
```
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:11335
```

### 2.4 启动前端

```bash
cd frontend
npm run dev
```

**首次启动**:
- next.js 编译 30-60 秒
- 之后快

### 2.5 验证

```bash
# 后端
curl http://localhost:11335/docs   # 返 Swagger UI

# 前端
curl http://localhost:11334/        # 返 HTML

# Ollama
curl http://localhost:11434/api/version

# ES
curl http://localhost:9200/_cluster/health
```

**完成**。

---

## 3. 端口分配

| 服务 | 端口 | 备注 |
|------|------|------|
| 前端 | **11334** | Next.js dev |
| 后端 | **11335** | uvicorn |
| Ollama | 11434 | embedding + chat |
| MySQL | 3307 | dev 故意错开 3306 |
| Redis | 16379 | 故意错开 6379 |
| ES | 9200 | |
| 本地 MCP demo | 8765 | `backend/run_mcp_server.py` |

**为什么 11334 / 11335**:项目硬编码,**别改**。详见 [port-alloc.md](../architecture/06-port-alloc.md)。

---

## 4. 配置文件

### 4.1 `backend/.env`(可入 git)

```bash
DATABASE_URL=mysql+pymysql://root:rootpassword@localhost:3307/ai_platform
SECRET_KEY=dev-secret-key-change-in-production
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30

ES_HOST=localhost
ES_PORT=9200
ES_INDEX_PREFIX=knowledge
ES_ENABLED=true

REDIS_HOST=localhost
REDIS_PORT=16379
REDIS_DB=0
ASYNC_ENABLED=true

MINIMAX_BASE_URL=https://api.minimax.chat/v1
MINIMAX_API_KEY=sk-cp-...
```

### 4.2 `frontend/.env.local`(不可入 git)

```bash
NEXT_PUBLIC_API_URL=http://localhost:11335/api/v1
NEXT_PUBLIC_WS_URL=ws://localhost:11335/ws/web
```

---

## 5. 常用命令

### 5.1 后端

```bash
# 跑测试
cd backend && pytest

# 跑单个
pytest tests/unit/test_agent.py -v

# mypy
mypy lumen_api/ lumen_services/ lumen_models/ lumen_core/

# 启动 worker
celery -A lumen_tasks worker --loglevel=info --concurrency=4

# 启动 beat(retention / schedule)
celery -A lumen_tasks beat --loglevel=info
```

### 5.2 前端

```bash
cd frontend

# 跑测试
npm run test:unit

# 跑单个
npx vitest run __tests__/chat/

# type check
npx tsc --noEmit

# 启动
npm run dev
```

### 5.3 DB

```bash
# 备份
docker exec lumen-platform-mysql \
  mysqldump -uroot -prootpassword --single-transaction \
  ai_platform > backup_$(date +%Y%m%d).sql

# 恢复
docker exec -i lumen-platform-mysql \
  mysql -uroot -prootpassword ai_platform < backup_20260806.sql

# 看进程
docker exec lumen-platform-mysql \
  mysql -uroot -prootpassword -e "SHOW PROCESSLIST"
```

### 5.4 容器

```bash
# 重启单个
docker compose restart ollama

# 看 log
docker compose logs -f mysql

# 重建
docker compose up -d --build backend
```

---

## 6. 调试技巧

### 6.1 后端

```python
# 在 lumen_core/config.py 确认 DEBUG=true
DEBUG = True

# 加断点
import pdb; pdb.set_trace()

# SQL echo
echo=True  # engine.create_engine(..., echo=True)
```

**fastapi devtools**:`http://localhost:11335/docs` 看所有端点。

### 6.2 前端

```ts
// Chrome DevTools → Sources → 加 breakpoint
// console.log(...)
// React DevTools → 看组件 hierarchy
```

### 6.3 数据库

```sql
-- 当前 active query
SELECT id, user, db, command, time, state, LEFT(info, 200)
FROM information_schema.processlist
WHERE command != 'Sleep' ORDER BY time DESC;

-- 慢查询
SHOW VARIABLES LIKE 'slow_query%';
```

---

## 7. 常见问题

### 7.1 端口被占

```bash
# Windows
netstat -ano | grep :11335
taskkill /PID <pid> /F

# Linux
lsof -i :11335
kill -9 <pid>
```

### 7.2 Ollama 11434 冲突

机子上已有 `ragpandora-ollama` 实例?

```bash
# 改 docker-compose.yml
ports:
  - "11435:11434"  # 改 11435
```

然后 `OLLAMA_API_BASE=http://localhost:11435`。

### 7.3 ES 启动慢

- 给 ES 至少 1G 内存
- `docker stats` 看实际占用

### 7.4 uvicorn zombie

[详细](../troubleshooting/uvicorn-zombie.md)。

**症状**:接口返空数据,端口 LISTENING,日志无错误。
**诊断**:
```bash
netstat -ano | grep :11335
# 看 PID 是不是变了
```
**修法**:杀旧 worker(`Stop-Process -Id <pid>`)。

### 7.5 MySQL MCP 连错库

```
mcp__ai_platform_docker_mysql__mysql_query
```
必须用 `ai_platform_docker_mysql`,不是 `mcp_server_mysql`。详见 [data-recovery.md §0](../troubleshooting/data-recovery.md)。

### 7.6 测试 fixture 污染 dev DB

复用 setup session 看不到 API 提交的数据(MySQL InnoDB REPEATABLE READ),teardown 必须**新开** `SessionLocal()`。详见 [data-recovery.md](../troubleshooting/data-recovery.md)。

### 7.7 NULL timestamp 报错

`ValidationError: created_at — Input should be a valid datetime`

**修法**:跑 `python backend/scripts/backfill_null_timestamps.py`(详见 [data-recovery.md §3.1](../troubleshooting/data-recovery.md))。

---

## 8. 性能优化 dev 配置

### 8.1 后端

```bash
# 内存
ulimit -n 65535  # 文件句柄上限

# 关闭 debug
DEBUG=false
```

### 8.2 前端

```json
// frontend/package.json
"dev": "NODE_OPTIONS='--max-old-space-size=4096' next dev -p 11334"
```

### 8.3 Ollama 预热

```bash
curl http://localhost:11434/api/generate \
  -d '{"model":"qwen2.5:7b","prompt":"hi","stream":false}'
```

---

## 9. 完整 .env 模板

**backend/.env**(dev):
```bash
DATABASE_URL=mysql+pymysql://root:rootpassword@localhost:3307/ai_platform
SECRET_KEY=dev-secret-key-change-in-production
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30

EXTERNAL_JWT_SECRET=external-dev-only-change-in-production-please
EXTERNAL_TOKEN_TTL_SECONDS=1800

ES_HOST=localhost
ES_PORT=9200
ES_INDEX_PREFIX=knowledge
ES_ENABLED=true

REDIS_HOST=localhost
REDIS_PORT=16379
REDIS_DB=0
ASYNC_ENABLED=true

Ollama
OLLAMA_API_BASE=http://localhost:11434
OLLAMA_EMBEDDING_MODEL=nomic-embed-text
OLLAMA_CHAT_MODEL=qwen2.5:7b

Retrieval
RETRIEVAL_VECTOR_WEIGHT=0.5
RETRIEVAL_BM25_WEIGHT=0.5
RERANK_ENABLED=true
RERANK_TYPE=auto
RERANK_TOP_N=20
BM25_USE_JIEBA=true

Llm
MINIMAX_BASE_URL=https://api.minimax.chat/v1
MINIMAX_API_KEY=sk-cp-...

Wx
WX_PUBLISHER_REAL_CLIENT_ENABLED=false
WX_PUBLISHER_FERNET_KEY=dev-only-fernet-key-do-not-use-in-prod-32b

# Storage (M38.1). Default backend is local; flip STORAGE_BACKEND=s3 to
# point KB uploads at MinIO/S3. S3 vars are only required when s3.
STORAGE_BACKEND=local
STORAGE_LOCAL_ROOT=./data
# STORAGE_LOCAL_USE_LEGACY_ROOT=false  # 设为 true 时回落到 ./storage
S3_ENDPOINT=http://localhost:9000
S3_REGION=us-east-1
S3_BUCKET=lumen-kb
S3_ACCESS_KEY=minioadmin
S3_SECRET_KEY=minioadmin
S3_USE_SSL=false
S3_PATH_STYLE=true
S3_PRESIGNED_URL_EXPIRY=600
```

**frontend/.env.local**:
```bash
NEXT_PUBLIC_API_URL=http://localhost:11335/api/v1
NEXT_PUBLIC_WS_URL=ws://localhost:11335/ws/web
```

---

## 10. 验证一切就绪

跑这个 smoke test:

```bash
# 1. 后端健康
curl http://localhost:11335/

# 2. 登录
curl -X POST http://localhost:11335/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@example.com","password":"admin"}'

# 3. 列出 agent
curl http://localhost:11335/api/v1/agents \
  -H "Authorization: Bearer <token>"

# 4. 前端
curl http://localhost:11334/

# 5. Ollama
curl http://localhost:11434/api/version

# 6. ES
curl http://localhost:9200/_cluster/health
```

全部返 200 / 正常数据 → dev 环境 OK!

---

**相关文档**
- [项目铁律](../../CLAUDE.md)
- [环境配置参考](../reference/environment-config.md)
- [排错速查](../troubleshooting/common-errors.md)
- [部署文档](deploy.md)

**维护者**:全栈架构师
**最近更新**:2026-08-06
