# 排错:开发环境启动 / 端口 / 容器

> 本文档收录**启动阶段**的常见症状,按"症状 → 修法"组织。
> 与 [common-errors.md](common-errors.md) 的区别:common-errors 按"运行中碰到的错误类型"组织(前端 / 鉴权 / 数据库 / 模型 / KB / 工作流 / Celery / 多媒体 / Docker / 测试),本文按"启动某个服务的某一步遇到问题"组织。
> 与 [uvicorn-zombie.md](uvicorn-zombie.md) 的关系:uvicorn-zombie 是 Windows 专属的深度排错(诊断 SQL + 进程结构),本文只给快速处理命令。

---

## 0. 快速索引

| 阶段 | 症状 | 跳转 |
|------|------|------|
| 后端进程 | 11335 端口被占 / 接口返空 / 405 | [§1 后端](#1-后端) |
| 前端进程 | 11334 起不来 | [§2 前端](#2-前端) |
| 容器栈 | mysql / redis / ollama 没起来 | [§3 容器栈](#3-容器栈) |
| Celery | worker 启动 ImportError / 任务永远 queued | [§4 celery](#4-celery) |
| Ollama | 模型没拉,KB ingest 失败 | [§5 ollama](#5-ollama) |
| 数据库 | pytest 报 "Table doesn't exist" | [§6 数据库](#6-数据库) |
| Widget | dist 不存在 / 加载失败 | [§7 widget](#7-widget) |
| LangSmith | tracing 不工作 | [§8 langsmith](#8-langsmith) |
| 兜底 | 全栈重启 | [§9 兜底](#9-兜底) |

---

## 1. 后端

### 1.1 11335 端口被占,新进程启动后接口返空

**快速处理**:

1. `netstat -ano | grep :11335 | grep LISTENING` 看 PID
2. `powershell -NoProfile -Command "Stop-Process -Id <pid>"` 杀旧 worker(优先不带 `-Force`)
3. `cd backend && uvicorn lumen_main:app --host 0.0.0.0 --port 11335` 重启
4. `curl http://localhost:11335/` 确认 `{"message":"Lumen AI Platform API",...}`

> 深度诊断 / 进程结构 / MySQL MDL 孤儿连接 / 后台任务启 uvicorn 被带走 → 见 [uvicorn-zombie.md](uvicorn-zombie.md)。

### 1.2 后端启动后立即退出,log 0 字节(git bash + Windows Python 专属)

**症状**:`nohup python -u -m uvicorn ... > log 2>&1 & disown` 后 log 完全空,11335 connection refused,但 `Get-Process python` 看到 PID 还在。

**根因**:git bash on Windows + Anaconda Python 3.11 的 `nohup ... > log 2>&1 & disown` 组合会**吞掉 stdout/stderr**,进程看似启动但实际异常退出。

**修法**:用 PowerShell `Start-Process` 强制重定向:

```bash
powershell -NoProfile -Command "Start-Process -FilePath 'D:\Anaconda3\python.exe' -ArgumentList '-u','-m','uvicorn','lumen_main:app','--host','0.0.0.0','--port','11335' -RedirectStandardOutput 'D:\work-ai\0401-lingclaw-to-langchain-demo\.run-logs\uvicorn.log' -RedirectStandardError 'D:\work-ai\0401-lingclaw-to-langchain-demo\.run-logs\uvicorn.err' -WorkingDirectory 'D:\work-ai\0401-lingclaw-to-langchain-demo\backend' -PassThru | Select-Object Id"
```

### 1.3 某个 endpoint 405 Method Not Allowed

**诊断**:`curl /openapi.json` 看路由是否真的注册。

```bash
curl -s http://localhost:11335/openapi.json | python -c "import sys,json; d=json.load(sys.stdin); [print(m,p) for p in d['paths'] for m in d['paths'][p]]"
```

- **openapi 里没有** = 后端没加载新代码 = uvicorn 没 reload(僵尸 / 忘记 `--reload`)
- **openapi 里有** = 前端 URL 拼错 / 后端 redirect_slashes 触发 307(参 [common-errors §2 鉴权](common-errors.md#2-鉴权))

---

## 2. 前端

### 2.1 11334 起不来,报端口占用

```bash
netstat -ano | grep :11334 | grep LISTENING
powershell -NoProfile -Command "Stop-Process -Id <pid>"
```

Next.js dev 不会留 zombie,直接 Ctrl+C 重启即可。

### 2.2 `npm error code ENOENT` ... `package.json`

**根因**:`npm run dev` 在错的 cwd 下启动(比如 backend/),找不到 `frontend/package.json`。

**修法**:`cd frontend && npm run dev` 然后重定向日志。

---

## 3. 容器栈

### 3.1 Docker 容器重启后 mysql / redis / ollama 没起来

```bash
bash scripts/dev-up.sh   # 拉起 5 个 lumen-platform-* 容器,等 ES green/yellow,等 celery ready
bash scripts/dev-down.sh [--keep-base]   # 停服
```

### 3.2 docker compose up -d celery_worker 报 `.env.docker not found`

dev 环境**可以忽略**:celery 容器仍能用 shell 环境变量或默认配置起来,跑 `celery -A lumen_tasks.celery_app worker`。要彻底干净就补一个 `backend/.env.docker`(从 `backend/.env` 复制,把 host 名改成 docker service 名: `mysql` / `redis` / `ollama`)。

---

## 4. Celery

### 4.1 worker 启动后 ImportError "partially initialized module"

**根因**:`celery_app.py` 模块级 import `document_tasks` 形成循环。

**修法**:`Celery(..., include=["lumen_tasks.document_tasks"])` 让 Celery worker 启动时再 import 任务模块。

### 4.2 任务永远 "queued"

- **卡在 queued**:celery worker 没起来 / 没连上 Redis。
- **卡在 running**:worker 接到任务但崩了,看 `.run-logs/uvicorn.log` 或 worker stderr。
- **Lumen 文档卡 queued**:多数情况是 `lumen_tasks.document_tasks` 没被 preload,worker 接到 task 后才 import 报 ImportError。修复见 §4.1。

---

## 5. Ollama

### 5.1 模型没拉,Knowledge Base ingest 失败

```bash
docker exec lumen-platform-ollama ollama pull nomic-embed-text
docker exec lumen-platform-ollama ollama pull qwen2.5:7b
```

### 5.2 Ollama 端口冲突

同机跑多个 Ollama 时会报 `port is already allocated`。查 `docker ps --filter "name=ollama"`,停掉冲突容器,或给本项目 Ollama 换宿主机端口(改 `backend/docker-compose.yml` 的 `11434:11434`)。

---

## 6. 数据库

### 6.1 pytest 跑不通,MySQL 报错 "Table doesn't exist"

```bash
cd backend && python scripts/init_dev_db.py
```

会跑 18 个 `ensure_*()` 函数 + seed 默认 model configs / 默认 tenant / 默认 admin 用户 / 默认 MCP demo。

### 6.2 接口 500 datetime 校验失败

dev DB 旧表 `created_at` / `updated_at` 列无 `DEFAULT` 触发 Pydantic 严格 schema 拦 500。修复脚本 `backend/scripts/ensure_timestamp_defaults.py` 一次性 backfill + ALTER DEFAULT。

---

## 7. Widget

### 7.1 构建失败 / dist 不存在

```bash
cd widget && npm install && npm run build
# 输出 dist/lumen-chat.js (IIFE) + dist/lumen-chat.esm.js
```

后端 FastAPI 会 mount `widget/dist/` 到 `/static/widget/`(见 `lumen_main.py` 的 `_widget_dir` 逻辑)。

---

## 8. LangSmith

### 8.1 tracing 不工作

`backend/.env` 设 `LANGSMITH_API_KEY=...` + `LANGSMITH_TRACING=true`。项目所有 LLM 调用都过 LangChain,会自动 trace。

---

## 9. 兜底

真不行 → 跑 `bash scripts/dev-down.sh && bash scripts/dev-up.sh` 全栈重启。

---

## 10. MinIO (M38.1 follow-up, 2026-08-31)

### 10.1 一键起 MinIO

```bash
bash scripts/dev-up.sh   # 自动包含 lumen-platform-minio (端口 29000/29001)
```

验证:`docker ps --filter "name=lumen-platform-minio"` → `Up (healthy)`。

MinIO console:浏览器打开 http://localhost:29001,默认 `minioadmin` / `minioadmin` 登录。

> 端口 19000/19001 被同机 `IntelliEngine-minio` 占用,本项目用 29000/29001 避开。
> 详见 `backend/docker-compose.yml:78` 注释。

### 10.2 切后端到 S3 模式

```bash
# 1. 启 MinIO + 建 bucket(一次性)
docker exec lumen-platform-minio mc alias set local http://localhost:9000 minioadmin minioadmin
docker exec lumen-platform-minio mc mb local/lumen-dev

# 2. 把 env 写入 backend/.env(参考 backend/storage.example.env 模板)
cat >> backend/.env <<'EOF'
STORAGE_BACKEND=s3
S3_ENDPOINT=http://localhost:29000
S3_BUCKET=lumen-dev
S3_ACCESS_KEY=minioadmin
S3_SECRET_KEY=minioadmin
S3_USE_SSL=false
S3_PATH_STYLE=true
S3_REGION=us-east-1
EOF

# 3. 重启 uvicorn(singleton 启动时读 env,改完必须重启才生效)
powershell -NoProfile -Command "Stop-Process -Name python -ErrorAction SilentlyContinue"
cd backend && python -u -m uvicorn lumen_main:app --host 0.0.0.0 --port 11335

# 4. 验证
curl http://localhost:11335/api/v1/storage/health
# 期望: {"code":200,"data":{"backend":"s3","ok":true,...}}
```

### 10.3 跑 live integration test

```bash
cd backend && pytest tests/integration/test_storage_minio_live.py -v
```

session-scope fixture 探测 `localhost:29000`,**连不上自动 pytest.skip**,CI 没起 MinIO 也不会 fail。期望 5-8 passed(health / multipart / list_objects / streaming / tenant-isolation)。

### 10.4 跑压测 baseline

```bash
cd backend && python -m scripts.bench_minio \
    --doc-size 100KB --tenant-count 5 --docs-per-tenant 50 \
    --concurrency 10 --output-json /tmp/minio_bench_100kb.json
```

输出 JSON:
```json
{
  "config": {"doc_size_bytes": 102400, "tenant_count": 5, "docs_per_tenant": 50, "concurrency": 10},
  "put": {
    "single_sequential": {"p50_ms": 12.3, "p95_ms": 18.7, "p99_ms": 24.1, "ops_per_s": 81.3},
    "multi_concurrent": {"p50_ms": 45.2, "p95_ms": 89.1, "p99_ms": 120.5, "ops_per_s": 221.0}
  },
  "get": {...},
  "list": {...}
}
```

**解读**:
- `p50` = 中位数,日常操作体验
- `p95` = 95% 的操作比这个快(关注这行)
- `p99` = 长尾,异常场景
- `ops_per_s` = 吞吐量(每秒操作数)

Multipart 路径要 `doc_size >= 5 MiB` 才触发(自动路由阈值,见 `lumen_services/storage/s3_backend.py:25-29`):
```bash
python -m scripts.bench_minio --doc-size 10MB --docs-per-tenant 20 --concurrency 4
# 报告里多了 put.multipart 段,P95 通常在 200-500ms
```

### 10.5 常见问题

| 症状 | 修法 |
|------|------|
| `lumen-platform-minio` 容器起不来 | 看 `docker logs lumen-platform-minio`;多半是端口 29000/29001 被占,改 docker-compose.yml 端口映射 |
| `health` 返 `backend=local` 不是 `s3` | 没重启 uvicorn,singleton 缓存了之前的 backend;重启 11335 |
| `health` 返 `ok=false detail="error: 404"` | bucket 不存在,先去 MinIO console 建 `lumen-dev` |
| multipart 上传卡住 | 检查 `MINIO_BROWSER_REDIRECT_URL` 没冲突;容器内存限制 `mem_limit: 1g` 见 docker-compose |
| 端到端 KB 上传 PDF 失败 | 看后端 log:大概率 parsers 还在 `open(file_path)` 走本地路径,见 [architecture/storage.md §Parsers 适配](../explanation/storage.md#parsers-适配) |

### 10.6 注意事项

- **默认凭据 `minioadmin/minioadmin` 只用于 dev**。生产必须改 + 启用 MinIO KMS。
- **`STORAGE_BACKEND` 运行时切换** 不支持(工厂是 singleton,改 env 必须重启 uvicorn)。
- **`boto3` Windows registry proxy bypass** 未处理(参考 `httpx-proxy-bypass-2026-08-31.md`,production Linux `HTTPS_PROXY` 出去代理需要 follow-up)。

---

**相关文档**
- [常见错误速查(运行中错误)](common-errors.md)
- [Uvicorn zombie 排错(Windows 深度)](uvicorn-zombie.md)
- [开发环境搭建](../how-to/dev-env.md)
- [Storage 架构 + 选型决策](../explanation/storage.md)
