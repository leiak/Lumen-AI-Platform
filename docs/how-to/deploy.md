# How-to:部署到生产

> 把 Lumen AI Platform 部署到生产环境。
> 覆盖 Docker 部署、生产 ENV、调优、监控。

---

## 1. 部署方式

| 方式 | 适用 |
|------|------|
| **Docker Compose 单机** | 中小规模,1 台 |
| **Kubernetes** | 大规模,多副本 |
| **手动(传统服务器)** | 特殊环境,不推荐 |

**当前文档重点**:Docker Compose 单机。

---

## 2. 部署前清单

### 2.1 硬件

**最小配置**:
- 4 核 CPU
- 16 GB RAM
- 100 GB SSD

**推荐配置**:
- 8 核 CPU
- 32 GB RAM
- 500 GB SSD

**估算**:
- LLM 调用日志:每月 1-10 GB(取决于调用量)
- 文档/媒体:每月 1-100 GB(取决于业务)
- FAISS 索引:每 1 万 chunk ≈ 30 MB

### 2.2 系统

- Linux(推荐 Ubuntu 22.04 / Debian 12)
- Docker 24+
- Docker Compose v2
- 开放端口:80, 443, 11335(可选)

### 2.3 域名 + SSL

- 域名指向服务器 IP
- Let's Encrypt + certbot 或自有证书
- 反向代理(Nginx / Caddy)

---

## 3. 部署步骤

### 3.1 拉代码

```bash
git clone https://github.com/your-org/lumen-platform.git
cd lumen-platform
git checkout <release-tag>
```

### 3.2 准备 .env.prod

```bash
cp backend/.env backend/.env.prod
# 改以下:
SECRET_KEY=$(openssl rand -hex 32)
EXTERNAL_JWT_SECRET=$(openssl rand -hex 32)
WX_PUBLISHER_FERNET_KEY=$(python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")

DATABASE_URL=mysql+pymysql://app:STRONG_PASSWORD@mysql.internal:3306/ai_platform
DEBUG=false
WX_PUBLISHER_REAL_CLIENT_ENABLED=true
ASYNC_ENABLED=true
```

### 3.3 docker-compose.prod.yml

```yaml
version: '3.8'

services:
  mysql:
    image: mysql:8.0
    restart: always
    environment:
      MYSQL_ROOT_PASSWORD: ${MYSQL_ROOT_PASSWORD}
      MYSQL_DATABASE: ai_platform
    volumes:
      - mysql_data:/var/lib/mysql
    healthcheck:
      test: ["CMD", "mysqladmin", "ping", "-h", "localhost"]
      interval: 5s
      timeout: 5s
      retries: 10

  redis:
    image: redis:7-alpine
    restart: always
    volumes:
      - redis_data:/data

  ollama:
    image: ollama/ollama:latest
    restart: always
    volumes:
      - ollama_data:/root/.ollama
    deploy:
      resources:
        reservations:
          devices:
            - capabilities: [gpu]

  elasticsearch:
    image: elasticsearch:8.11.0
    restart: always
    environment:
      - discovery.type=single-node
      - xpack.security.enabled=false
      - ES_JAVA_OPTS=-Xms2g -Xmx2g
    volumes:
      - es_data:/usr/share/elasticsearch/data

  backend:
    build: ./backend
    restart: always
    env_file: ./backend/.env.prod
    depends_on:
      mysql: { condition: service_healthy }
      redis: { condition: service_started }
      ollama: { condition: service_started }
    command: uvicorn lumen_main:app --host 0.0.0.0 --port 11335 --workers 4
    volumes:
      - storage_data:/app/storage
    ports:
      - "127.0.0.1:11335:11335"

  celery_worker:
    build: ./backend
    restart: always
    env_file: ./backend/.env.prod
    depends_on:
      - backend
    command: celery -A lumen_tasks worker --concurrency=8 --loglevel=info

  celery_beat:
    build: ./backend
    restart: always
    env_file: ./backend/.env.prod
    depends_on:
      - backend
    command: celery -A lumen_tasks beat --loglevel=info

  frontend:
    build: ./frontend
    restart: always
    depends_on:
      - backend
    ports:
      - "127.0.0.1:3000:3000"

  nginx:
    image: nginx:alpine
    restart: always
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf:ro
      - ./certs:/etc/nginx/certs:ro
    depends_on:
      - backend
      - frontend

volumes:
  mysql_data:
  redis_data:
  ollama_data:
  es_data:
  storage_data:
```

### 3.4 启动

```bash
docker compose -f docker-compose.prod.yml up -d
docker compose -f docker-compose.prod.yml logs -f backend
```

**注意**:首次启动会跑迁移,等 30 秒。

### 3.5 验证

```bash
curl https://yourdomain.com/api/v1/auth/login -X POST \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@example.com","password":"admin"}'
```

---

## 4. Nginx 配置

```nginx
upstream backend {
    server backend:11335;
}

upstream frontend {
    server frontend:3000;
}

server {
    listen 80;
    server_name yourdomain.com;
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name yourdomain.com;

    ssl_certificate /etc/nginx/certs/fullchain.pem;
    ssl_certificate_key /etc/nginx/certs/privkey.pem;

    # SSE 流式 — 不要缓冲
    proxy_buffering off;
    proxy_read_timeout 600s;

    # WebSocket
    map $http_upgrade $connection_upgrade {
        default upgrade;
        '' close;
    }

    # 后端
    location /api/ {
        proxy_pass http://backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /ws/ {
        proxy_pass http://backend;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;
        proxy_set_header Host $host;
    }

    # 前端
    location / {
        proxy_pass http://frontend;
        proxy_set_header Host $host;
    }
}
```

---

## 5. 数据库迁移

### 5.1 自动迁移

启动时 `lumen_core/database.py` 跑 `ensure_*` 幂等函数:
- `ensure_conversations_table`
- `ensure_knowledge_bases_table`
- `ensure_documents_table`
- ...

**注意**:DDL 阻塞;如果有孤儿连接(MDL),启动会卡住。[详细](../troubleshooting/data-recovery.md)。

### 5.2 手动迁移

```bash
docker exec -it lumen-platform-mysql mysql -uroot -p ai_platform
```

### 5.3 备份

```bash
# 加到 crontab
0 3 * * * /path/to/backup.sh
```

`backup.sh`:
```bash
#!/bin/bash
docker exec lumen-platform-mysql \
  mysqldump -uroot -prootpassword --single-transaction --routines --triggers \
  ai_platform > /backup/ai_platform_$(date +\%Y\%m\%d_\%H\%M\%S).sql
find /backup -name "*.sql" -mtime +7 -delete
```

详细见 [data-recovery.md §1](../troubleshooting/data-recovery.md)。

---

## 6. 监控 / 告警

### 6.1 健康检查

```bash
# 加到 nginx / k8s
curl -f http://localhost:11335/ || exit 1
```

### 6.2 监控指标

**推荐 Prometheus + Grafana**:
- 后端进程 CPU / 内存
- MySQL connections / slow queries
- Redis 内存
- ES 堆内存
- LLM 调用速率 / 失败率

**Lumen 自身**:
- `GET /api/v1/logs/llm-calls/stats` — LLM 调用统计
- `GET /api/v1/dashboard/stats` — 平台统计

### 6.3 日志

```bash
# Docker 日志
docker compose logs -f backend --tail 100

# 同步到 ELK / Loki
```

### 6.4 告警

**关键 SLO**:
- API 5xx > 1% → 告警
- LLM 失败率 > 5% → 告警
- 文档处理堆积 > 100 → 告警
- 磁盘 > 80% → 告警

---

## 7. 性能调优

### 7.1 后端 worker 数量

```bash
# 经验: CPU 核数
command: uvicorn lumen_main:app --workers 4
```

**小心**:
- 每个 worker 独立占内存(2-4 GB)
- 进程内 `_buckets`(限流)独立 → 多 worker 实际限流放宽 N 倍

### 7.2 Celery

```bash
# worker 并发
command: celery -A lumen_tasks worker --concurrency=8

# 设每个任务的超时
```

### 7.3 MySQL

```sql
-- innodb_buffer_pool_size = 内存的 50-70%
SET GLOBAL innodb_buffer_pool_size = 8 * 1024 * 1024 * 1024;

-- max_connections
SET GLOBAL max_connections = 200;

-- 慢查询
SET GLOBAL slow_query_log = 'ON';
SET GLOBAL long_query_time = 2;
```

### 7.4 Redis

```bash
# maxmemory
maxmemory 4gb
maxmemory-policy allkeys-lru
```

### 7.5 ES

```bash
# 堆内存
ES_JAVA_OPTS=-Xms4g -Xmx4g
```

### 7.6 前端

```bash
# build
npm run build
npm run start  # next start
```

---

## 8. 横向扩容

### 8.1 瓶颈判断

| 瓶颈 | 解决 |
|------|------|
| MySQL 连接打满 | 加 PgBouncer / ProxySQL |
| 后端 CPU | 加 worker 实例 |
| Ollama 慢 | 加 GPU / 换云端 LLM |
| ES 慢 | 加 ES 节点 / 换 OpenSearch |
| Storage IO | 换 SSD / 挂载分布式存储 |

### 8.2 多实例部署

```yaml
backend:
  deploy:
    replicas: 3
```

**注意**:
- 限流:进程内 → 多实例失效。升级到 Redis
- WebSocket 连接表:进程内 → 多实例广播失效。升级到 Redis pub/sub
- LLM 日志:每个调用都写 DB,没影响
- 任务调度:celery beat 必须 **单实例**

### 8.3 升级路径

| 阶段 | 改动 |
|------|------|
| 短期 | Uvicorn + Celery 多 worker |
| 短期 | Read replica for MySQL |
| 中期 | Redis 限流 + WebSocket pub/sub |
| 中期 | K8s 部署 |
| 长期 | 微服务拆分 |

---

## 9. 升级流程

### 9.1 滚动升级(Uvicorn)

```bash
# 1. 拉新代码
git pull
git checkout v1.1.0

# 2. 重 build
docker compose build backend

# 3. 滚动重启(无停机)
docker compose up -d --no-deps backend
```

### 9.2 数据库迁移

```bash
# 1. 备份
./backup.sh

# 2. 跑迁移
docker compose exec backend python scripts/ensure_timestamp_defaults.py

# 3. 验证
docker compose exec mysql mysql -uroot -p ai_platform -e "SHOW TABLES"
```

### 9.3 回滚

```bash
# 1. 切回上一个 tag
git checkout v1.0.0

# 2. 重启
docker compose up -d --force-recreate --no-deps backend celery_worker
```

---

## 10. 安全清单

- [ ] **改 SECRET_KEY / EXTERNAL_JWT_SECRET / WX_PUBLISHER_FERNET_KEY**
- [ ] **DEBUG=false**
- [ ] **MySQL 账号最小权限**(不允许 root 远程)
- [ ] **JWT 改成 RS256**(可选)
- [ ] **HTTPS(Let's Encrypt)**
- [ ] **限流开启**
- [ ] **CORS 严格白名单**
- [ ] **定期备份 + 恢复演练**
- [ ] **MySQL MDL 监控**
- [ ] **Firewall(只开 80/443/SSH)**
- [ ] **Fail2ban / SSH key only**
- [ ] **CORS 缓存失效路径走通**

---

## 11. 备份方案

```bash
# 1. DB 全量
docker exec lumen-platform-mysql \
  mysqldump -uroot -prootpassword --single-transaction \
  ai_platform > /backup/db_$(date +%Y%m%d).sql

# 2. Storage 增量
rsync -avz /app/storage/ /backup/storage_$(date +%Y%m%d)/

# 3. 上传到 S3
aws s3 cp /backup/ s3://your-bucket/backup/ --recursive
```

**频率**:DB 每日,Storage 每周。
**保留**:DB 30 天,Storage 季度。

---

## 12. 故障恢复

**核心 SOP**:见 [data-recovery.md](../troubleshooting/data-recovery.md)。

**常见故障**:
- DB 不可连 → 重启 Docker / 查 disk
- Ollama 慢 → 看 GPU / 查 chat model
- ES 索引丢了 → 重新创建 + 重灌
- 后端 500 → 看 log,常见是 ENV 错

---

## 13. 监控指标

### 13.1 平台操作指标

```bash
# 用户
SELECT COUNT(*) FROM users WHERE is_active = 1;

# Agent 数
SELECT COUNT(*) FROM agents WHERE tenant_id = ?;

# 今日消息
SELECT COUNT(*) FROM messages WHERE created_at > NOW() - INTERVAL 1 DAY;

# 文档处理堆积
SELECT COUNT(*) FROM documents WHERE status = 'processing' AND created_at < NOW() - INTERVAL 1 HOUR;
```

### 13.2 业务指标

```bash
# 今日 LLM 调用
SELECT COUNT(*) FROM llm_call_logs WHERE created_at > NOW() - INTERVAL 1 DAY;

# 失败率
SELECT
  COUNT(*) AS total,
  SUM(CASE WHEN status='error' THEN 1 ELSE 0 END) AS errors
FROM llm_call_logs WHERE created_at > NOW() - INTERVAL 1 DAY;

# 配额使用
SELECT
  user_id,
  COUNT(*) AS calls_today
FROM llm_call_logs
WHERE created_at > NOW() - INTERVAL 1 DAY
GROUP BY user_id
ORDER BY calls_today DESC LIMIT 10;
```

---

## 14. 排错

| 症状 | 原因 | 修法 |
|------|------|------|
| 502 Bad Gateway | 后端没起来 | `docker compose logs backend` |
| 530 Site Frozen | uvicorn zombie | 杀 worker |
| API 慢 | MySQL 慢查询 | 查 processlist |
| Ollama 慢 | 模型没加载 | `keep_alive` 预热 |
| MySQL OOM | innodb_buffer_pool 太大 | 改 config |
| Celery 任务堆积 | worker 不够 | 加 worker |
| 启动卡 `Waiting for application startup.` | MySQL MDL 阻塞 | KILL 孤儿连接 |

---

**相关文档**
- [环境配置参考](../reference/environment-config.md)
- [数据恢复](../troubleshooting/data-recovery.md)
- [性能调优](../troubleshooting/performance-tuning.md)
- [运维铁律](../troubleshooting/data-recovery.md#8-铁律)

**维护者**:全栈架构师
**最近更新**:2026-08-06
