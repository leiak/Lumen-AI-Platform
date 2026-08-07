# 端口分配

> Lumen AI Platform 的端口分配是**硬编码的**,原因写在 `CLAUDE.md` 第一条。
> 文档说明每个端口的用途、谁占用、为什么这么选。

---

## 1. 端口分配表

| 服务 | 端口 | 启动命令 | 备注 |
|------|------|---------|------|
| **前端 dev (Next.js)** | **11334** | `cd frontend && npm run dev` | Web UI |
| **后端 (uvicorn)** | **11335** | `cd backend && uvicorn lumen_main:app --port 11335` | API + Swagger `/docs` + Redoc `/redoc` |
| **Ollama** | **11434** | `ollama serve`(默认) | embedding + chat |
| **本地 MCP demo server** | **8765** | `cd backend && python run_mcp_server.py` | 6 工具 demo |

---

## 2. 为什么是这些端口(不是默认的 3000 / 8000)

### 2.1 历史原因
- 项目最初在 `localhost:8000`(后端默认) / `localhost:3000`(前端默认) 开发
- 后来因为:
  - 同机常跑 `ragpandora-ollama`(占 11434)
  - 同机常跑其他 dev 项目占 3000/8000
  - macOS Control Center 偶尔占 7000
- 决定改用**五位端口**(11334/11335/11434/8765)避免冲突

### 2.2 数字含义(非硬性)
- `1133X` = "11月33日项目" 内部代号
- `11434` = 跟 Ollama 默认一致(省事)
- `8765` = "87+65=152" 跟早期 demo 端口一致

### 2.3 实际原因
- 避免与其他 dev 项目的端口冲突
- 不会和 macOS / Windows 系统服务撞
- 容易记(`11-33-4` 跟 `11-33-5` 一对)

---

## 3. 各端口的依赖关系

```
11334 (Frontend) ────→ 11335 (Backend) ────→ 11434 (Ollama)
                              │   ├──────→ 3307 (MySQL, Docker)
                              │   ├──────→ 6379 (Redis, Docker)
                              │   └──────→ 9200 (Elasticsearch, Docker)
                              │
                              └──────→ 8765 (MCP demo, 本地)
```

- **Frontend (11334) 必依赖** Backend (11335)
- **Backend (11335) 依赖** Ollama / MySQL / Redis / ES
- **MCP demo (8765)** 是 Backend 可选的外部依赖

---

## 4. 配置

### 4.1 Backend
- `backend/.env`:
  ```
  BACKEND_PORT=11335
  ```
- `lumen_main.py` 启动时读 `BACKEND_PORT`
- `uvicorn lumen_main:app --port 11335`(推荐显式传,避免读错配置)

### 4.2 Frontend
- `frontend/.env.local`:
  ```
  NEXT_PUBLIC_API_URL=http://localhost:11335/api/v1
  ```
- `frontend/next.config.js`:
  ```js
  rewrites: () => [{
    source: '/api/:path*',
    destination: 'http://127.0.0.1:11335/api/:path*'
  }]
  ```
- `npm run dev` 启动 11334(在 `package.json` 中写死)

### 4.3 Ollama
- 默认 11434
- 不需要改

### 4.4 MCP demo
- `backend/run_mcp_server.py` 写死 8765
- 不需要改

---

## 5. Docker 端口

`backend/docker-compose.yml` 暴露的端口(对外):

| 容器 | 容器内端口 | 主机端口 | 用途 |
|------|-----------|---------|------|
| lumen-platform-mysql | 3306 | **3307** | 避开本机 MySQL 3306 |
| lumen-platform-redis | 6379 | **6379** | 直接映射 |
| lumen-platform-elasticsearch | 9200 | **9200** | 直接映射 |
| lumen-platform-ollama | 11434 | **11434** | 直接映射 |

**注意**: MySQL 主机端口是 **3307** 不是 3306(避免与本机 MySQL 冲突)。

---

## 6. 端口冲突排查

### 6.1 症状
- 启动报 `Address already in use`
- 启动报 `port is already allocated`(Docker)

### 6.2 诊断
```bash
# Linux / macOS
lsof -i :11335
netstat -tulnp | grep 11335

# Windows (PowerShell)
Get-NetTCPConnection -LocalPort 11335

# Windows (git-bash)
netstat -ano | grep 11335
```

### 6.3 修法
- 找到占用 PID → 杀掉
- 或换端口(不推荐,会破文档约定)

详见 [troubleshooting/uvicorn-zombie.md](../troubleshooting/uvicorn-zombie.md)。

---

## 7. 端口 + 子项目 + 跨域的关系

### 7.1 跨域
- `11334` (前端) 调 `11335` (后端) 是跨域
- 默认通过 `DynamicCORSMiddleware` 放行 `localhost:11334`
- 也可以走 Next.js rewrites(不跨域,前端代理)

### 7.2 推荐
- **开发**用 Next.js rewrites(`/api/*` → 11335)
  - 不跨域
  - 调试简单
  - 现有 `next.config.js` 已是这个模式
- **生产**用 Nginx 反向代理
  - 同源(`/api/*` 反代到后端)
  - 安全 + 性能

---

## 8. 监控端口

### 8.1 健康检查
- `GET http://localhost:11335/health` → 200 + 服务状态
- 包含 MySQL / Redis / Ollama / ES 健康检查

### 8.2 监控建议
- 监控 11334 / 11335 是否在 LISTENING
- 监控 11335 `/health` 返回 200
- 告警:任一服务 down 时

---

## 9. 修改端口的成本

### 9.1 不要随便改
- 改端口会破 4 处文档约定:
  1. `CLAUDE.md` § 1
  2. `README.md` 快速启动
  3. `frontend/.env.local`
  4. `frontend/next.config.js`
- 还会影响 `dev_health_check.sh` 监控脚本
- 改的成本远大于"凑合 1133X"

### 9.2 真要改的话
1. 改 `backend/.env` `BACKEND_PORT`
2. 改 `frontend/.env.local` `NEXT_PUBLIC_API_URL`
3. 改 `frontend/next.config.js` rewrites
4. 改 `backend/run_mcp_server.py`(MCP 端口)
5. 改 `Dockerfile` / `docker-compose.yml`
6. 改所有文档
7. 改 `.claude/hooks/check-dev-services.sh`
8. 改 CI / E2E 脚本

**结论**:除非有强需求(比如生产部署),否则**保持 1133X**。

---

## 10. 部署端口(生产建议)

### 10.1 反向代理方案(推荐)
```
Internet → 443/80 (Nginx)
                ├─ /         → 11334 (Frontend)
                ├─ /api/     → 11335 (Backend)
                └─ /static/  → 11334 (Widget bundle)
```

### 10.2 直连方案
```
Internet → 11334 (Frontend)
Internet → 11335 (Backend)
```

直连方案需要在防火墙暴露两个端口,生产不推荐。

---

## 11. 总结

**端口分配是项目铁律**:
- 11334 前端
- 11335 后端
- 11434 Ollama
- 8765 MCP demo
- 3307 Docker MySQL(主机端口)

**不随便改**。需要改时**先讨论**,再批量改 8 处文件。

---

**维护者**:全栈架构师
**最近更新**:2026-08-06
