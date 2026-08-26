# 环境配置参考

> Lumen AI Platform 全部 ENV 变量 + 配置文件路径 + 部署必改项。
> 文档讲透每个 env 是什么、默认值、生产怎么改。

---

## 1. ENV 加载机制

**Pydantic Settings** 自动从以下位置读取(按优先级):
1. 进程环境变量
2. `.env.{APP_ENV}`(如 `.env.local`)
3. `.env`(项目根或 backend/)

文件位置优先级:
- `backend/.env.local`(本地覆盖,不入 git)
- `backend/.env`(默认)

**载入类**:
```python
# backend/lumen_core/config.py
class Settings(BaseSettings):
    DATABASE_URL: str = ...
    SECRET_KEY: str = ...
    # ...
    class Config:
        env_file = ".env"
```

**使用**:
```python
from lumen_core.config import settings
print(settings.DATABASE_URL)
```

---

## 2. 核心配置

### 2.1 应用

| ENV | 默认 | 说明 |
|-----|------|------|
| `APP_NAME` | `Lumen AI Platform` | 显示名 |
| `DEBUG` | `True` | dev=True / prod=False |

### 2.2 数据库

| ENV | 默认 | 说明 |
|-----|------|------|
| `DATABASE_URL` | `mysql+pymysql://ai_user:ai_password@localhost:3306/ai_platform` | SQLAlchemy URL |

**生产推荐**:
```bash
DATABASE_URL=mysql+pymysql://app:STRONG_PASSWORD@mysql.internal:3306/ai_platform?charset=utf8mb4
```

### 2.3 JWT

| ENV | 默认 | 说明 |
|-----|------|------|
| `SECRET_KEY` | `your-secret-key-change-in-production` | 内部用户 JWT 签名 |
| `ALGORITHM` | `HS256` | |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `30` | 访问令牌 TTL |

**生产必改**:
```bash
SECRET_KEY=$(openssl rand -hex 32)
```

### 2.4 External JWT(Widget)

| ENV | 默认 | 说明 |
|-----|------|------|
| `EXTERNAL_JWT_SECRET` | `external-dev-only-change-in-production-please` | Widget JWT 签名,**独立**于 SECRET_KEY |
| `EXTERNAL_TOKEN_TTL_SECONDS` | `1800` | 30 分钟,故意短 |

**为什么独立**:
- 第三方泄漏不影响内部 JWT
- 内部泄漏不影响 widget 鉴权

**生产必改**:
```bash
EXTERNAL_JWT_SECRET=$(openssl rand -hex 32)
```

**启动时校验**:`DEBUG=False` 时,如果还是默认值,启动会 fail(TODO,目前仅 warn)。

### 2.5 广播密钥

| ENV | 默认 | 说明 |
|-----|------|------|
| `BROADCAST_INTERNAL_SECRET` | `""` | 跨进程广播时 honour `target_user_id` 的共享密钥 |

**当前约束**:空 = 所有客户端都收到,看似可以,但**真实场景都是空**(Electron 兼容默认)。

---

## 3. LLM / 模型

### 3.1 Ollama

| ENV | 默认 | 说明 |
|-----|------|------|
| `OLLAMA_API_BASE` | `http://localhost:11434` | |
| `OLLAMA_EMBEDDING_MODEL` | `nomic-embed-text` | 768 维 |
| `OLLAMA_CHAT_MODEL` | `qwen2.5:7b` | 默认 chat |

**生产推荐**:换成云端 provider,通过 `model_configs` 表配置。

### 3.2 MiniMax API(可选)

| ENV | 默认 | 说明 |
|-----|------|------|
| `MINIMAX_BASE_URL` | `https://api.minimax.chat/v1` | |
| `MINIMAX_API_KEY` | `None` | 启动时填 |

### 3.3 OAuth2

| ENV | 默认 | 说明 |
|-----|------|------|
| `OAUTH2_CLIENT_ID` | `None` | |
| `OAUTH2_CLIENT_SECRET` | `None` | |

---

## 4. RAG 检索

### 4.1 向量 vs 关键词

| ENV | 默认 | 说明 |
|-----|------|------|
| `RETRIEVAL_VECTOR_WEIGHT` | `0.5` | RRF 混合权重 |
| `RETRIEVAL_BM25_WEIGHT` | `0.5` | |
| `RERANK_ENABLED` | `True` | 是否再排 |
| `RERANK_TYPE` | `auto` | `auto` / `jina` / `llm` / `noop` |
| `RERANK_MODEL` | `None` | `auto` 时自动选 |
| `RERANK_TOP_N` | `20` | 候选数(再排后取 top K) |
| `BM25_USE_JIEBA` | `True` | 中文分词 |

### 4.2 FAISS

| ENV | 默认 | 说明 |
|-----|------|------|
| `FAISS_INDEX_PATH` | `./data/faiss/knowledge_base` | 索引本地路径 |

### 4.3 Elasticsearch

| ENV | 默认 | 说明 |
|-----|------|------|
| `ES_HOST` | `localhost` | |
| `ES_PORT` | `9200` | |
| `ES_INDEX_PREFIX` | `knowledge` | |
| `ES_ENABLED` | `False` | True 启用 ES 而非 FAISS |

**生产推荐 ES** + 多个 KB。

---

## 5. 异步 / Celery

| ENV | 默认 | 说明 |
|-----|------|------|
| `REDIS_HOST` | `localhost` | |
| `REDIS_PORT` | `16379` | 故意不与系统 Redis 冲突 |
| `REDIS_DB` | `0` | |
| `ASYNC_ENABLED` | `True` | False 走同步,**只在 dev 用** |

**生产 `ASYNC_ENABLED=true`**:
- celery beat 必跑(否则 retention scheduler 卡)
- 多个 worker 必起(否则并发 1)

---

## 6. 微信公众号

| ENV | 默认 | 说明 |
|-----|------|------|
| `WX_PUBLISHER_REAL_CLIENT_ENABLED` | `False` | True 才真发到微信 |
| `WX_PUBLISHER_FERNET_KEY` | `dev-only-...` | 加密 app_secret 的 Fernet key,**生产必改** |
| `WX_PUBLISHER_STORAGE_DIR` | `""` | 草稿/素材本地路径 |

**生产必改**:
```bash
WX_PUBLISHER_FERNET_KEY=$(python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
```

**`WX_PUBLISHER_REAL_CLIENT_ENABLED=False`**:
- 测试时不会真发到微信
- 防止 dev 误发

---

## 7. 存储路径

| ENV | 默认 | 解析 |
|-----|------|------|
| `IMAGE_STORAGE_DIR` | `""` | 空 → `backend/storage/generated_images/` |
| `STORAGE_DIR` | (派生) | `backend/storage/` |

**默认结构**:
```
backend/storage/
├── documents/              # 上传的原始文档
├── generated_images/       # 图片生成
├── generated_audios/       # TTS 音频
├── generated_videos/       # 视频合成
├── vector_store/           # FAISS index
├── easyocr/                # OCR 模型缓存
├── stock_assets/           # 预置素材
├── wx_publisher/           # 公众号素材
└── _tmp/                   # 临时文件(可不备份)
```

---

## 7b. M38.1 存储后端抽象

| ENV | 默认 | 说明 |
|-----|------|------|
| `STORAGE_BACKEND` | `local` | `local` = 本地盘;`s3` = S3 兼容(MinIO/R2/S3) |
| `STORAGE_LOCAL_ROOT` | `./data` | LocalBackend 根目录(KB 上传文件实际落在哪) |
| `STORAGE_LOCAL_USE_LEGACY_ROOT` | `false` | true → 回落 `./storage`(旧 IMAGE_STORAGE_DIR 形态) |
| `S3_ENDPOINT` | `""` | S3 endpoint URL(MinIO 必填,R2/AWS 可空) |
| `S3_REGION` | `us-east-1` | AWS region |
| `S3_BUCKET` | `""` | 桶名,**必填**当 `STORAGE_BACKEND=s3` |
| `S3_ACCESS_KEY` | `""` | access key,**必填**当 `STORAGE_BACKEND=s3` |
| `S3_SECRET_KEY` | `""` | secret key,**必填**当 `STORAGE_BACKEND=s3` |
| `S3_USE_SSL` | `false` | MinIO dev = false;生产 AWS = true |
| `S3_PATH_STYLE` | `true` | MinIO = true;AWS = false(virtual-hosted) |
| `S3_PRESIGNED_URL_EXPIRY` | `600` | presigned URL 过期秒数 |

**默认根 `./data`** 的原因:pre-M38.1 上传代码写 `data/uploads/<tenant>/<kb>/<filename>`,LocalBackend 落同样的相对路径,parsers 还 `open(file_path)` 直接读,零迁移。

**冷迁移**:`POST /api/v1/storage/migrate-to-s3` (admin-only) 把 `documents.asset_storage_key IS NULL` 的行从 LocalBackend 拷到 S3Backend,幂等,返 `{scanned, migrated, failed, errors}`。

详见 `docs-internal/superpowers/specs/2026-08-26-kb-storage-abstraction.md` §6。

---

## 8. 后端 .env 默认值(dev)

```bash
# backend/.env
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

**注意**:
- dev 模式端口 3307/16379 故意错开 3306/6379
- 部署到 prod 不会冲突

---

## 9. 前端 ENV

**前端加载 `frontend/.env.local`**(不提交)或 `frontend/.env.development` / `frontend/.env.production`。

### 9.1 Next.js 公共 ENV

| ENV | 说明 |
|-----|------|
| `NEXT_PUBLIC_API_URL` | 后端 base URL |
| `NEXT_PUBLIC_WS_URL` | WebSocket URL(`/ws/web`) |
| `NEXT_PUBLIC_FEATURE_*` | Feature flags |

### 9.2 默认 frontend/.env.local

```bash
NEXT_PUBLIC_API_URL=http://localhost:11335/api/v1
NEXT_PUBLIC_WS_URL=ws://localhost:11335/ws/web
```

### 9.3 生产

```bash
NEXT_PUBLIC_API_URL=https://app.yourdomain.com/api/v1
NEXT_PUBLIC_WS_URL=wss://app.yourdomain.com/ws/web
```

---

## 10. 部署必改(生产清单)

**生产环境必改**:

```bash
# 强随机
SECRET_KEY=$(openssl rand -hex 32)
EXTERNAL_JWT_SECRET=$(openssl rand -hex 32)
WX_PUBLISHER_FERNET_KEY=$(python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")

# 数据库
DATABASE_URL=mysql+pymysql://app:STRONG_PASSWORD@mysql.internal:3306/ai_platform

# 调试关
DEBUG=false
WX_PUBLISHER_REAL_CLIENT_ENABLED=true

# 异步开
ASYNC_ENABLED=true
```

**生产环境 NOT 改的**:

- `ALGORITHM` = `HS256`(改 RS256 要全套重写)
- `RETRIEVAL_VECTOR_WEIGHT` / `RETRIEVAL_BM25_WEIGHT` 这类**业务参数**,通过 `model_configs` / `knowledge_bases.search_weights` 调,不要走 ENV

---

## 11. 启动检查

启动时 `app.main` 会:

```python
# 应该写但还没全写(部分已实现)
def startup_checks():
    if settings.DEBUG:
        return
    # 生产模式 fail-fast
    if settings.SECRET_KEY.startswith("your-secret-key"):
        raise RuntimeError("SECRET_KEY must be changed in production")
    if settings.EXTERNAL_JWT_SECRET.startswith("external-dev-only"):
        raise RuntimeError("EXTERNAL_JWT_SECRET must be changed in production")
    if settings.WX_PUBLISHER_FERNET_KEY.startswith("dev-only"):
        raise RuntimeError("WX_PUBLISHER_FERNET_KEY must be changed in production")
    if not settings.ASYNC_ENABLED:
        log.warning("ASYNC_ENABLED is false — sync processing in prod is slow")
```

**目前状态**:部分检查有 warn,没有 fail-fast。**TODO**:上线前补齐。

---

## 12. 调试 ENV

**dev 常用**:
```bash
# 强制 reload
WATCHFILES_FORCE_POLLING=true

# 慢一点的日志
LOG_LEVEL=debug

# 关掉 ES 用 FAISS
ES_ENABLED=false

# 关掉所有异步任务
ASYNC_ENABLED=false
```

---

## 13. 配置文件路径

| 文件 | 用途 |
|------|------|
| `backend/.env` | 后端默认(可入 git) |
| `backend/.env.local` | 后端本地覆盖(不入 git) |
| `frontend/.env.local` | 前端本地(不入 git) |
| `frontend/.env.development` | 前端 dev 默认 |
| `frontend/.env.production` | 前端 prod 默认 |
| `docker-compose.yml` | 容器编排(端口、卷挂载) |
| `widget/.env` | widget(嵌入端) |

---

## 14. 配置变更影响

| 变更 | 影响 | 危险度 |
|------|------|--------|
| `SECRET_KEY` | 所有已签 JWT 失效 | ⚠️ |
| `EXTERNAL_JWT_SECRET` | 所有 widget token 失效 | ⚠️ |
| `WX_PUBLISHER_FERNET_KEY` | 公众号账号解不开 | ⚠️ |
| `DATABASE_URL` | 整个服务连不上 | 🔴 |
| `Ollama 模型名` | 检索失败 | ⚠️ |
| `RETRIEVAL_VECTOR_WEIGHT` | 检索效果变 | 🟡 |
| `ASYNC_ENABLED` 切 false | 整个异步停 | 🔴 |
| `DEBUG` 切 true | 漏错误信息 | ⚠️ |

**改 ENV → 重启 uvicorn + celery worker + beat**。

---

## 15. 鲲鱼(sidecar)配置

详见 [部署文档](../how-to/deploy.md)。

---

## 16. 排错

| 症状 | 原因 | 修法 |
|------|------|------|
| `RuntimeError: SECRET_KEY must be changed` | 没改默认值 | 设 ENV |
| `Can't connect to MySQL` | DATABASE_URL 错 | 检查 host/port/user/pass |
| `Ollama call fails` | OLLAMA_API_BASE 错 | `curl $OLLAMA_API_BASE/api/version` |
| `JWT decode failed` | SECRET_KEY 改了 | 重新登录 |
| ES 检索 0 结果 | ES 索引前缀不一致 | 检查 `ES_INDEX_PREFIX` |
| Celery 任务不发 | ASYNC_ENABLED=false | 改 true |
| 公众号报错 "Fernet key 无效" | 改了 WX_PUBLISHER_FERNET_KEY | 重新保存所有账号 |
| widget 拿到 401 | EXTERNAL_JWT_SECRET 改了 | admin 重新生成 |

---

**相关文档**
- [API 参考](api.md)
- [数据模型参考](database-schema.md)
- [部署文档](../how-to/deploy.md)
- [架构总览](../architecture/00-overview.md)

**维护者**:全栈架构师
**最近更新**:2026-08-06
