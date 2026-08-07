# 认证与 RBAC

> Lumen AI Platform 的认证、授权、CORS 设计。
> 文档供工程师实现新模块时参考,产品理解权限边界。

---

## 1. 认证机制

### 1.1 OAuth2 Password Grant + JWT
- 协议: OAuth2 Password Grant Flow
- 形式: 用户名 + 密码 → 拿 access_token (JWT)
- 库: `python-jose` 签发 / 验证
- 密码哈希: PassLib + bcrypt
- 有效期: access_token 24 小时(默认,可配置)

### 1.2 端点
- `POST /api/v1/auth/login` — 用户名密码登录
  - Body: `application/x-www-form-urlencoded` (OAuth2 标准)
  - 响应: `{"code": 200, "data": {"access_token": "...", "token_type": "bearer", "user": {...}}}`
- `GET /api/v1/auth/me` — 当前用户信息(需 Bearer)

### 1.3 JWT Payload
```json
{
  "sub": "1",          // user_id
  "tenant_id": 1,      // 租户 ID
  "is_superuser": false,
  "username": "admin",
  "exp": 1735689600
}
```

### 1.4 关键代码
- 路由: `backend/lumen_api/v1/auth.py`
- 服务: `backend/lumen_services/auth_service.py`
- 核心: `backend/lumen_core/auth.py`
  - `create_access_token(data, expires_delta)`
  - `verify_token(token)`
  - `get_current_user(token, db)` — 路由依赖

### 1.5 前端
- 存储: `localStorage.setItem("access_token", token)`
- **key 必须是 `"access_token"`**(不是 `"token"`)
- 拦截器: `services/auth.ts` 401 → 清 token + 跳 `/login`
- WS: `?token=...` query(浏览器 WS 没法设 header)

---

## 2. 外部应用认证(M2M)

### 2.1 场景
第三方网站嵌入 `<lumen-chat>`,用 `app_key` + `app_secret` 换 JWT。

### 2.2 流程
```
1. Widget POST /api/v1/external/token
   Headers: X-App-Key, X-App-Secret, Origin
2. 后端 external_app_service.issue_jwt
   - 校验 app_key + app_secret
   - 校验 Origin 白名单
   - 签 JWT(tenant_id, external_app_id, agent_id, exp=24h)
3. Widget 缓存 token,后续请求 Authorization: Bearer <external_jwt>
```

### 2.3 关键代码
- 路由: `backend/lumen_api/v1/external_app.py` (`/external/token`)
- 服务: `backend/lumen_services/external_app_service.py` (`issue_jwt`)
- 依赖: `backend/lumen_api/deps.py` (`get_current_external_app`)

详见 [modules/external-app-auth.md](../modules/external-app-auth.md)。

---

## 3. RBAC 角色权限

### 3.1 数据模型
```
roles (N) ──< role_permissions >── (N) permissions
users (N) ──< user_roles >── (N) roles
```

### 3.2 关键字段
- `roles.id`, `roles.name`, `roles.is_active`
- `permissions.id`, `permissions.name`, `permissions.resource`, `permissions.action`
- `user_roles.user_id`, `user_roles.role_id`
- `role_permissions.role_id`, `user_permissions.permission_id`(部分实现)

### 3.3 Permission 格式
- `resource.action`
- 例:
  - `knowledge.create`
  - `knowledge.read`
  - `knowledge.update`
  - `knowledge.delete`
  - `agent.create` / `agent.read` / `agent.update` / `agent.delete`
  - `workflow.*`
  - `chat.*`
  - `user.*`
  - `role.*`
  - `system.*`(仅超管)

### 3.4 内置角色

| 角色 | 权限 | 适用 |
|------|------|------|
| `super_admin` | 所有权限(跨租户) | 平台运营 |
| `tenant_admin` | 租户内所有权限 | 租户管理员 |
| `developer` | 创建/编辑 Agent / Workflow / KB | 开发者 |
| `operator` | 浏览 + 日常使用 | 业务运营 |
| `viewer` | 只读 | 访客 / 客户 |

### 3.5 装饰器
```python
# lumen_api/v1/agent.py
from lumen_api.v1.deps import require_permission

@router.post("/", response_model=SingleResponse[AgentRead])
def create_agent(
    payload: AgentCreate,
    current_user: User = Depends(get_current_user),
    _: None = Depends(require_permission("agent.create"))
):
    ...
```

### 3.6 前端
- 菜单按 role 隐藏
- 按钮按 permission 显隐(用 `<Authorized permission="agent.create">` 包装)
- 暂未实现完整 UI 级 RBAC,后端为权威

---

## 4. CORS

### 4.1 设计
- `DynamicCORSMiddleware`(M27 加固)
- 动态检查 Origin 白名单
- 替代硬编码 `CORSMiddleware`

### 4.2 关键代码
- `backend/lumen_main.py:172-179` 注册
- `backend/lumen_core/middleware/dynamic_cors.py` 实现

### 4.3 白名单
- 默认:`http://localhost:11334`(dev 前端)
- 默认:`http://localhost:11335`(后端)
- 配置:`backend/.env` 中 `CORS_ALLOWED_ORIGINS`(逗号分隔)

### 4.4 处理流程
```
请求到达
   │
   ▼
DynamicCORSMiddleware
   │
   ├─ Origin 在白名单?
   │    ├─ 是 → 反射 Access-Control-Allow-Origin + Credentials
   │    └─ 否 → 拒绝(不放行 CORS 头)
   │
   ├─ 是 preflight (OPTIONS)?
   │    └─ 200 + 必要头
   │
   └─ 继续后续中间件 / 路由
```

### 4.5 常见误区
- 静态 `CORSMiddleware` 会"放行所有 Origin"→ XSS 风险
- 动态根据 Origin 反射 → 仍需白名单(否则任意站可调)
- Lumen 用白名单 + 反射 Origin

---

## 5. 限流

### 5.1 实现
- `backend/lumen_core/rate_limiter.py`
- 基于 Redis 滑动窗口

### 5.2 限流维度
- Per IP
- Per tenant
- Per user
- Per endpoint(如 `/auth/login` 严限)

### 5.3 默认配额
- 登录: 5 次/分钟/IP
- API 通用: 60 次/分钟/用户
- LLM 调用: 30 次/分钟/用户
- 外部应用: 1000 次/小时/app_key

### 5.4 超出限流
- 响应 429
- `message`: "请求过于频繁,请稍后再试 / Too many requests"

---

## 6. 错误处理

### 6.1 业务 4xx
- 400: 请求参数错误
- 401: 未登录 / token 失效
- 403: 权限不足
- 404: 资源不存在
- 409: 资源冲突
- 422: Pydantic 校验失败
- 429: 限流

### 6.2 系统 5xx
- 500: 内部错误
- 502: 上游服务错误(Ollama / OpenAI 不可达)
- 503: 服务暂不可用(数据库连不上)

### 6.3 响应格式
```json
{
  "code": 400,
  "message": "参数错误 / Bad request",
  "data": null,
  "errors": [...]   // 可选,详细错误
}
```

### 6.4 关键代码
- `backend/lumen_core/middleware/error_handler.py` — 统一错误处理
- 业务 message 走 i18n(`backend/lumen_core/i18n.py`)

---

## 7. WebSocket 鉴权

### 7.1 URL 鉴权
```
ws://localhost:11335/api/v1/ws/web?token=<access_token>
```

### 7.2 服务端校验
- `lumen_api/v1/websocket.py` — 解析 token
- 校验失败 → 关闭连接 + 4401 状态码

### 7.3 前端
- `services/realtime.ts` 启动时附 token
- 重连时自动带 token
- 4401 → 停止重连 + 跳登录

---

## 8. 安全设计原则

### 8.1 最小权限
- 默认用户没有 admin 权限
- 业务功能按需分配

### 8.2 失败默认拒绝
- 权限检查不通过 → 默认拒绝
- 不"自动放行"

### 8.3 显式授权
- 不依赖隐式继承
- 装饰器必须显式声明

### 8.4 审计可追溯
- 关键操作写 audit log
- LLM 调用带 user_id + tenant_id

### 8.5 不在前端藏权限
- 后端是权限权威
- 前端只是 UX 提示,真校验在后端

---

## 9. 与常见认证方案的对比

| 方案 | Lumen 选择 | 理由 |
|------|-----------|------|
| **Session + Cookie** | ❌ | 前端 SPA + 多端,Cookie 麻烦 |
| **JWT (无状态)** | ✅ | 适合 SPA / 多端 |
| **Refresh Token** | 🚧 计划中 | 提升 UX,减少重登 |
| **OAuth2 + 第三方** | 🚧 企业版 | 暂用 OAuth2 Password Grant |
| **SSO (SAML / OIDC)** | 🚧 长期 | 大客户需要 |
| **API Key (M2M)** | ✅ (app_key) | 外部应用 |
| **mTLS** | 🚧 评估 | 高安全客户 |

---

## 10. 升级路径

### 短期(1~2 月)
- Refresh Token
- 双 token (access + refresh)
- 滑动续期

### 中期(3~6 月)
- 企业 SSO(SAML 2.0)
- OIDC 第三方登录
- 设备管理(查看登录设备)

### 长期(6~12 月)
- 零信任(每次 API 调用鉴权)
- 行为分析(异常登录告警)
- mTLS

---

## 11. 排错

| 症状 | 原因 | 修法 |
|------|------|------|
| 401 但 token 有效 | 时钟漂移 | 同步服务器时间 |
| 401 但前端没跳 | 拦截器没生效 | 检查 `services/auth.ts` |
| 403 但应该有权限 | role / permission 没绑 | 检查 `user_roles` + `role_permissions` |
| 跨域报 CORS 错 | Origin 不在白名单 | 加到 `CORS_ALLOWED_ORIGINS` |
| WS 4401 | token 失效 | 清 token 重新登录 |
| 429 限流 | 配额超 | 等 1 分钟重试 |

详见 [troubleshooting/common-errors.md](../troubleshooting/common-errors.md)。

---

**维护者**:全栈架构师
**最近更新**:2026-08-06
