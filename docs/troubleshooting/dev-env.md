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
| MinIO | 端口冲突 / multipart 卡 / endpoint 504 | [§10 MinIO](#10-minio-m381-follow-up-2026-08-31) |
| OTel | Jaeger 看不到 trace / collector 端口冲突 | [§11 Jaeger + OTel Collector](#11-jaeger--otel-collector-phase-1-group-b-44-day-4-2026-09-05) |
| OTel lifecycle | 进程退出丢最后几个 span / W3C trace 链路 | [§12 OTel Lifecycle + Proxy Bypass](#12-otel-lifecycle--proxy-bypass-phase-1-group-b-44-day-5-2026-09-06) |
| OTel metrics | collector 看不到 `lumen_span_*` / span-derived 不工作 | [§13 OTel Span-derived Metrics](#13-otel-span-derived-metrics-phase-1-group-b-44-day-6-2026-09-06) |

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
- **`boto3` Windows registry proxy bypass** ✅ **Phase 1 Group B 4.4 Day 5 (2026-09-06) 已 ship**:`S3Backend._bypass_proxy_kwargs()` 默认 `S3_BYPASS_PROXY=true` 走 `proxies={}` 让 botocore 不查 Windows registry / `HTTPS_PROXY`。生产 / K8s 集群真要走代理,设 `S3_BYPASS_PROXY=false` 走 botocore auto-detect。详见 §12.3。

---

## 11. Jaeger + OTel Collector (Phase 1 Group B 4.4 Day 4, 2026-09-05)

OTel Collector + Jaeger 完整链路: backend → OTLP gRPC → Collector → jaeger / prometheus exporters。dev 默认 backend 走 console(stdout),不连 collector。要看 trace 必须切换到 otlp + 启动两个容器。

### 11.1 一键起 Jaeger + OTel Collector

```bash
cd backend && docker compose up -d lumen-platform-jaeger lumen-platform-otel-collector
```

容器起来后:
- Jaeger UI: http://localhost:16686(浏览器打开看 trace tree)
- OTel Collector health: http://localhost:13133/status(返 `{"status":"Server available"}`)
- OTel Collector /metrics: http://localhost:8889/metrics(`otelcol_*` 自监控)

### 11.2 切 backend 到 OTLP(让 span 真正流到 Jaeger)

**关键**:`backend/.env` 默认 `OTEL_EXPORTER=console`,改 `otlp` + 重启 uvicorn 才能让 trace 真正流到 collector。改 `.env` 是项目保护动作(避免 Claude 误改),手动编辑即可。

```bash
# 在 backend/.env 末尾追加或修改:
OTEL_EXPORTER=otlp
OTEL_ENDPOINT=http://localhost:4317   # otel-collector 容器 4317 → host 4317
OTEL_SAMPLE_RATIO=1.0                 # dev 默认全采;prod 可降到 0.05~0.1
```

改完**必须重启 uvicorn**(singleton 在 startup 读 env,改完不重启不生效)。

### 11.3 端到端验证

```bash
cd backend && python -m scripts.validate_otel_collector --send-test-span
```

期望输出 `3/3 passed`:
1. Jaeger services API 找到 `lumen-backend` service
2. OTel Collector /metrics 找到 `otelcol_receiver_accepted_spans` 指标
3. Prometheus targets API 找到 `otel-collector` job `Up`

### 11.4 常见问题

| 症状 | 排查 / 修法 |
|------|------|
| Jaeger UI 没 `lumen-backend` service | (a) 没改 `OTEL_EXPORTER=otlp`;(b) uvicorn 没重启;(c) OTel collector 容器没起(`docker ps --filter "name=lumen-platform-otel-collector"`) |
| Jaeger UI 有 service 但 span tree 空 | 后端没真正发请求(uvicorn 启动了但没请求)。`--send-test-span` 主动发 1 个,2 秒后刷 UI |
| Collector `/metrics` 没 `otelcol_receiver_accepted_spans` | collector 配置没生效。`docker logs lumen-platform-otel-collector` 看 config load error。改 `monitoring/otel-collector.yml` 后 `docker compose restart lumen-platform-otel-collector` 即可(config 文件是挂载,无需 force-recreate) |
| Prometheus targets `otel-collector` Down | 改完 `monitoring/prometheus.yml` 没 reload。`docker exec lumen-platform-prometheus kill -HUP 1` 或重启 prometheus 容器 |
| 后端 log 报 `ConnectionError: http://localhost:4317` | OTel Collector 容器没起,或 4317 没 expose host。`docker ps` 看容器状态 + `curl http://localhost:13133/status` 探活 |
| W3C traceparent 链路断(celery worker 看不到 uvicorn 的 trace) | Celery 容器跟 uvicorn 进程不在同一 docker network,或 `OTEL_EXPORTER=otlp` 没在 celery container env(`docker exec lumen-platform-celery-doc env | grep OTEL`) |
| 端口 16686/4317/4318/8889 冲突 | 改 `backend/docker-compose.yml` 端口映射,记得同步改 `OTEL_ENDPOINT`(同机 IntelliEngine-* 系列可能占这些端口) |
| 采样率不生效,trace 还是 100% | (a) `OTEL_SAMPLE_RATIO` 没设;(b) 设了但没重启 uvicorn;(c) 设了非数字 fallback 到 1.0,看 uvicorn log 有无 warning |

### 11.5 采样率语义速查

`OTEL_SAMPLE_RATIO=0.0` ~ `1.0`,详见 `lumen_core/otel.py:_build_sampler`:

| 值 | 行为 |
|---|------|
| `0.0` | ALWAYS_OFF,不采任何 span |
| `0.0 < ratio < 1.0` | ParentBased(TraceIdRatioBased(ratio)),父 span 决定 + 子 span 按 ratio 随机采 |
| `1.0` | ALWAYS_ON,全采 |
| 非数字 | logger.warning + fallback 1.0 |
| 未设 | 默认 1.0(dev 调试保留全量) |

**ParentBased 关键**:跨进程 trace(uvicorn → celery worker → ollama)必须尊重 upstream 的采样决定 —— 上游不采,下游也不采,否则 trace tree 断裂(只看到一半 span)。

### 11.6 注意事项

- **`docker compose restart` 不重读 `env_file`**(同 M27 easyocr / M38.1.x docker 修):改完 `backend/.env.docker.example` 必须 `docker compose up -d --force-recreate --no-deps celery_worker_doc celery_worker_ppt celery_worker_eval` 才生效。
- **otel-collector 容器内存限 512MB**(dev OOM guard):突发流量超 50% 内存(256MB)时 memory_limiter 触发 spike 拒收。生产可调大或改用 K8s HPA。
- **`OTEL_SAMPLE_RATIO` 在 dev 1.0 是设计选择**:调试阶段保留全量 trace 排查问题方便,prod 高流量场景**必须**降到 0.05~0.1,否则 collector / jaeger 内存爆炸。
- **`boto3` Windows registry proxy bypass** ✅ **Day 5 (2026-09-06) 已 ship**(详见 §12.3):`S3Backend.from_env()` 默认 `proxies={}` 让 botocore 不查 Windows registry。生产 Linux 出口代理场景设 `S3_BYPASS_PROXY=false` opt-in。

---

## 12. OTel Lifecycle + Proxy Bypass (Phase 1 Group B 4.4 Day 5, 2026-09-06)

Day 4 ship 了 collector + Jaeger + Prometheus scrape 链路。Day 5 ship 4 个 follow-up,全是 "Day 4 跑通后才暴露的运维坑":进程退出丢最后几个 span / 自研 `X-Trace-Id` header 跟 OTel W3C `traceparent` 双写冲突 / boto3 走 Windows registry 代理 / OTLP exporter 走 Linux HTTPS_PROXY 出口。

### 12.1 Shutdown flush 双保险 (uvicorn lifespan + atexit)

**问题**:`BatchSpanProcessor` 默认 5s flush 间隔,uvicorn 收 SIGTERM 立刻退出时,buffered span 直接丢。Jaeger UI 上 trace tree 总是缺最后 ~5s 的叶子 span。

**修法**(双保险):

1. **lifespan shutdown finally 块** (`lumen_main._shutdown_cleanup`):`_shutdown_cleanup` 在 scheduler.stop + celery_queue_monitor.cancel + slo_budget_calculator.cancel 之后、`engine.dispose()` 之前,调 `lumen_core.otel.force_flush(timeout_millis=5000)`。5s 对齐 OTLP gRPC exporter 默认 timeout。
2. **atexit 注册** (`lumen_main._otel_atexit_flush`):只在 `OTEL_EXPORTER` 是 OTLP exporter (非 `none` / `console`) 时注册。`console` exporter 写 stdout,pytest / uvicorn 子进程退出时 sys.stdout 已 close,SDK 内部 logger.exception 会再抛 stderr closed → 污染退出日志。OTLP 走网络 I/O,保留 atexit 价值。

**为什么不在 flush 之前 engine.dispose()**:保留 flush-then-dispose 顺序作为通用约定,后续业务 span 加 DB state 属性时不用回头改顺序。

**验证**:
```bash
# 起 collector + 切 OTLP(见 §11.2)+ 发请求 → Ctrl+C → 看 collector 最后几个 span 是否落盘
cd backend && docker compose up -d lumen-platform-otel-collector lumen-platform-jaeger
# 改 .env: OTEL_EXPORTER=otlp, 重启 uvicorn
# curl /api/v1/health 几次 → Ctrl+C uvicorn → tail docker logs lumen-platform-otel-collector
# 应该看到 otelcol_exporter_sent_spans{exporter="jaeger"} 计数含最后几个 span
```

### 12.2 `lumen_services.httpx_trace` deprecated (用 W3C traceparent)

**问题**:Day 1 ship 的 `traced_event_hooks()` / `traced_async_event_hooks()` 给 httpx client 注入自研 `X-Trace-Id` header。Day 1 同时 ship 了 `HTTPXClientInstrumentor` 自动注 W3C `traceparent` header。两套机制并存,新代码不知道用哪套。

**修法**:`lumen_services/httpx_trace.py` 全模块标 deprecated:
- 模块 docstring 顶部写 `.. deprecated::` + 指向 HTTPXClientInstrumentor
- `traced_event_hooks()` / `traced_async_event_hooks()` 各自 docstring 加 `.. deprecated::`
- 调用方 import 时 `_warned_deprecation` 模块级守门,只发一次 `DeprecationWarning`,避免 pytest -W error 炸所有调用点

**迁移**:
```python
# 旧(已 deprecated):
from lumen_services.httpx_trace import traced_event_hooks
client = httpx.Client(event_hooks=traced_event_hooks())

# 新:什么都不用做,setup_tracing() 已 instrument httpx
client = httpx.Client()  # 自动带 W3C traceparent
```

`X-Trace-Id` header 旧客户端不识别 `traceparent` 还能 join,删除 `httpx_trace` 后老 client 看不到 trace_id —— 不删,只标 deprecated。

### 12.3 boto3 / OTLP HTTPS_PROXY 防御

**问题**:
- **boto3 (S3Backend)**: Windows registry `HKCU\...\Internet Settings\ProxyServer=127.0.0.1:10793` 默认被 botocore 读,直连 `localhost:29000` (MinIO) → 走代理 → 代理对 internal IP 无路由 → `ConnectionError`。
- **OTLP gRPC exporter**: gRPC channel 自动读 `HTTPS_PROXY` / `GRPC_PROXY` env 走代理。生产 / K8s 集群 S3 endpoint 在代理后面的话,collector 看到的是代理 IP 不是 pod IP。

**修法**:

| 组件 | 函数 | 默认行为 | opt-in 代理 |
|------|------|---------|------------|
| boto3 (S3Backend) | `S3Backend._bypass_proxy_kwargs()` | 返 `{}`(botocore 不查 proxy) | `S3_BYPASS_PROXY=false` → "auto" sentinel,botocore 自己查 |
| OTLP gRPC exporter | `_build_exporter("otlp")` | 检测 `HTTPS_PROXY` env,logger.warning 提醒 | `GRPC_PROXY=""` / `HTTPS_PROXY=""` 显式 unset |

**生产 Linux 出口代理场景**: `lumen` 进程启动前:
```bash
unset HTTPS_PROXY
unset GRPC_PROXY
# 或者显式设空
GRPC_PROXY="" HTTPS_PROXY="" uvicorn lumen_main:app ...
```

### 12.4 Celery worker trace 关联验证

**踩坑**(跨进程 trace 链路最常见断点):

celery worker 跟 uvicorn 进程不在同一 docker network / env,OTLP exporter 没装,导致 worker 看不到 uvicorn 的 trace —— Jaeger UI 上 worker task span 是孤立的,parent span 为空。

**验证**:
```bash
# 1. celery 容器 env 必须有 OTEL_EXPORTER + OTEL_ENDPOINT
docker exec lumen-platform-celery-doc env | grep -E "OTEL_"

# 2. celery worker stdout 应有 "[otel] BatchSpanProcessor" 日志
docker logs lumen-platform-celery-doc 2>&1 | grep -i otel

# 3. 发个 KB 上传 → 看 Jaeger UI trace tree 应含 worker span 作为 child
# (不是孤立 root span)
```

**修法**(若 1 不通过):celery container env 没 OTEL_*,改 `backend/.env.docker.example` + `docker compose up -d --force-recreate --no-deps celery_worker_doc celery_worker_ppt celery_worker_eval` 重建。

### 12.5 常见问题

| 症状 | 排查 / 修法 |
|------|------|
| uvicorn 退出后 Jaeger UI 上 trace 缺最后 ~5s | Day 5 双保险应已 ship。验:`lumen_main._shutdown_cleanup` 有 force_flush 调用、`lumen_main._otel_atexit_flush` 已 atexit 注册(OTLP 模式下)。dev console exporter 不发最后 5s 是已知行为(写 stdout,跟 pytest 退出冲突) |
| Celery worker trace 是孤立 root span,parent 为空 | §12.4。celery 容器 OTEL env 缺失 |
| MinIO 上传 `ConnectionError: 127.0.0.1:10793` | §12.3。`S3Backend` 默认 `proxies={}` 应已 ship,验 `_bypass_proxy_kwargs() == {}`。老 uvicorn 实例可能缓存了旧 S3Backend singleton,重启 11335 |
| OTLP exporter 走代理 (Linux prod) | §12.3。unset `HTTPS_PROXY` / `GRPC_PROXY` 或显式 `=""` |

### 12.6 注意事项

- **`force_flush()` 内部已 swallow 异常**:shutdown 阶段 collector 已挂 / 网络断,`force_flush` 返 False 不抛,绝不阻断进程退出。详见 `lumen_core.otel.force_flush` docstring。
- **`HTTPXClientInstrumentor` 自动 instrument 0 配置**:setup_tracing() 内部 `_instrument_httpx()` 已调,新 httpx client 不用任何 hooks。`X-Trace-Id` 仍兼容 (TraceIdMiddleware 写 ctxvar → `get_trace_id()` 兜底)。
- **boto3 `proxies={}` 不影响 retries / signing**:botocore retries / signature_version / s3 addressing_style 全保留,只是不查 proxy。详见 `lumen_services/storage/s3_backend.py:_bypass_proxy_kwargs` docstring。

---

## 13. OTel Span-derived Metrics (Phase 1 Group B 4.4 Day 6, 2026-09-06)

Day 4 ship 了 OTel trace pipeline,Day 5 ship 了 lifecycle + proxy 防御。Day 6 把每条 span **派生**到 Prometheus —— `lumen.span.events` Counter + `lumen.span.duration` Histogram,PromQL 一秒看到 "哪个 span 在某段时间内变慢 / 报错率上升",不用再翻上千个 trace。

### 13.1 端到端启用

跟 §11.2 一样的步骤:起 collector + 切 OTLP。Day 6 没新增配置,只是 OTLP 模式下 metric 自动启动(由 `lumen_core.otel._do_setup` 级联调 `lumen_core.otel_metrics.setup_metrics()`)。

```bash
# 1. 起 collector(同 §11.1)
cd backend && docker compose up -d lumen-platform-otel-collector

# 2. 切 backend 到 OTLP + 重启 uvicorn(同 §11.2)
# backend/.env:
#   OTEL_EXPORTER=otlp
#   OTEL_ENDPOINT=http://localhost:4317
#   OTEL_SAMPLE_RATIO=1.0
# 改完重启 uvicorn

# 3. 验证:uvicorn 启动 log 应有:
# "OpenTelemetry metrics initialized: exporter=otlp endpoint=http://localhost:4317 service=lumen-backend env=dev"
```

### 13.2 验证 collector 收到 metric

```bash
# 1. OTel Collector :8889 暴露的 metric
curl -s http://localhost:8889/metrics | grep lumen_span_events_total
# 期望:lumen_span_events_total{...service_name="lumen-backend"...,span_name="chat.stream"} 1.0

# 2. Prometheus 已 scrape 到(等 1 个 scrape_interval=15s)
curl -s 'http://localhost:19090/api/v1/query?query=lumen_span_events_total' | python -m json.tool | head -30

# 3. RPS PromQL(按 span_name 看请求速率)
curl -sG 'http://localhost:19090/api/v1/query' \
  --data-urlencode 'query=sum by (span_name) (rate(lumen_span_events_total{service_name="lumen-backend"}[5m]))' \
  | python -m json.tool | head -30

# 4. P95 延迟 PromQL
curl -sG 'http://localhost:19090/api/v1/query' \
  --data-urlencode 'query=histogram_quantile(0.95, sum by (span_name, le) (rate(lumen_span_duration_seconds_bucket{service_name="lumen-backend"}[5m])))' \
  | python -m json.tool | head -30
```

### 13.3 跟 prometheus_client metric 的关系(互补,不替代)

| 维度 | prometheus_client(`lumen_core.metrics`) | OTel span-derived(`lumen_core.otel_metrics`) |
|------|------------------------------------------|--------------------------------------------|
| 数据源 | 业务代码主动 `.inc()` / `.observe()` | OTel SDK 在 `SpanProcessor.on_end` 被动观察 |
| 命名空间 | `lumen_llm_calls_total` / `lumen_embedding_duration_seconds` / `http_requests_total` | `lumen_span_events` / `lumen_span_duration` |
| 何时启用 | uvicorn 启动 + `lumen_api/middleware/prometheus.py` 装好 | `OTEL_EXPORTER=otlp/otlp_grpc/otlp_http` 时启,console / none 不启 |
| 关联能力 | 独立 PromQL,无法跟 trace_id 直接 join | 自动带 `service.name` / `trace_id` join,跟 Jaeger 同源 |
| 典型用途 | 业务 KPI(LLM 调用次数、token 用量、SLO 预算) | 延迟分布(P50/P95/P99)、未知 span 排查、跨业务路径覆盖率 |
| 总 series | < 50(prometheus_client 业务 metric + HTTP 中间件) | < 670(15 维 allowlist × 12 known span_name) |

**为什么不替换**:两类数据源不同 — prometheus_client 是业务代码累计值,OTel 是被动观察 span 终态。新加的 OTel metric 是**补充**,不是替代。`http_requests_total` 仍由 `lumen_api/middleware/prometheus.py` 维护,`lumen_llm_calls_total` 仍走 prometheus_client。

### 13.4 Cardinality 守门(防 series 爆炸)

12 维 allowlist:`span.kind` / `http.request.method` / `http.response.status_code`(5 段分类) / `llm.call_kind` / `embedding.call_kind` / `chat.status` / `llm.status` / `retrieval.backend` / `retrieval.rerank_enabled` / `retrieval.has_filter` / `workflow.status` / `workflow.node.status` / `workflow.node.type` / `db.system` / `messaging.system`。

**总 series 估算 < 670**(各 span 维度稀疏,workflow.node 最重 1×5×3×22=330,其他大多 < 50)。OTel SDK 默认 100K / Prometheus 建议 10K 都达标。

**Span name 白名单**(`_KNOWN_SPAN_NAMES`,12 个):`chat.stream` / `chat.endpoint` / `embedding.generate` / `retrieval.search` / `workflow.run` / `workflow.node` / `llm.chat` / `http.client` / `http.server` / `celery.task` / `sqlalchemy.orm` / `pymysql.connect`。**白名单外的 span_name 自动 collapse 到 `"other"`**,防止业务方拼 typo 产生 cardinality 爆增。**新增 `@traced_span(name="...")` 时必须同步扩这个 frozenset**,否则会被 collapse。

### 13.5 常见问题

| 症状 | 排查 / 修法 |
|------|------|
| Collector `:8889/metrics` 没 `lumen_span_*` | (a) 没改 `OTEL_EXPORTER=otlp`;(b) uvicorn 没重启;(c) 启动 log 没 "OpenTelemetry metrics initialized"(失败 fallback 不抛) |
| Prometheus 有 `lumen_span_*` 但全是 0 | uvicorn 启动了但没业务 span 流过。`curl /api/v1/health` 几次或发个 chat 请求,等 1 个 scrape_interval(15s) |
| `span_name="other"` 大量出现 | 业务代码用了新的 `@traced_span(name=...)` 但没扩 `_KNOWN_SPAN_NAMES`(见 `lumen_core/otel_metrics.py`)。修:加进 frozenset 重启 |
| `http.response.status_code="UNSET"` 大量出现 | span 是 client / internal 视角,没经过 FastAPI 入站,没 HTTP status。正常 — 仅 server span 该有 |
| 测试时 `force_flush` 后 metric 没新增 | `InMemoryMetricReader` 走 `force_flush` 才会触发 aggregation。Python `for-loop` 直推数据用完就被 GC,要用 `meter.force_flush()` |
| HTTPS_PROXY 警告刷屏 | 同 §12.3:unset `HTTPS_PROXY` / `GRPC_PROXY` env,或显式 `=""` |

### 13.6 注意事项

- **`PeriodicExportingMetricReader` 间隔 15s 对齐 Prometheus scrape_interval**:意味着最坏情况业务 span end 后要等 15s 才有 metric。Prometheus PromQL `rate()` / `histogram_quantile()` 默认查 5m 窗口,够用。**不要降间隔**(collector 压力大 + OTel exporter 不批量)。
- **`shutdown_on_exit=False`**:`MeterProvider` 的 daemon thread 在 Python `atexit` 时会被强杀,跟 Day 5 batch span processor 同坑(强制关闭会丢最后几个 metric)。我们走 `lumen_main._shutdown_cleanup` + `_otel_atexit_flush` 主动 `force_flush`,不依赖 daemon 兜底。
- **`force_flush(timeout_millis=5000)` 是兜底**:OTLP exporter 默认 2s timeout,5s 留 buffer 余量。atexit 阶段调一次用 `timeout_millis=3000`(短一点,atexit 进程在退出,不能阻塞太久)。
- **`Counter` / `Histogram` lazy init**(per label_tuple):OTel SDK Counter 是 per-label 实例,需要 `dict[Tuple[Tuple[str, str], ...], Counter]` 索引;每个新 (label_tuple) 第一次 `create_counter` 一次性创建,后续复用。**不会重复创建**,但 series 数要看 label cardinality。
- **新增 / 改名 span attribute**:如果加进 `_ALLOWED_LABEL_KEYS`,cardinality 影响跟现有维度等同;如果**不加**,会被静默丢弃,业务 span 的新 attribute 不会反映到 metric。决策看是否值得扩 cardinality 守门。

---

**相关文档**
- [常见错误速查(运行中错误)](common-errors.md)
- [Uvicorn zombie 排错(Windows 深度)](uvicorn-zombie.md)
- [开发环境搭建](../how-to/dev-env.md)
- [Storage 架构 + 选型决策](../explanation/storage.md)
