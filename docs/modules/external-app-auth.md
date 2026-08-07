# 模块:外部应用鉴权(Embeddable Chat Widget)

> 第三方网站嵌入的聊天挂件怎么"安全地"调我们的对话 API。
> 文档讲透 widget 怎么注册、怎么换 token、怎么挡恶意调用、暴露哪些端点。

---

## 1. 产品定位

**Embeddable Chat Widget 是什么?**

- 第三方网站(客户的官网、商城)用几行 `<script>` 嵌入我们的聊天能力
- 我们的对话 API **不能直接暴露**给公网(密钥会泄漏、限流失效)
- 中间层:第三方先换一次性 JWT,bearer token 调 `/api/v1/external/...`

**和"内部 API"什么不同?**

| 维度 | 内部 API | 外部 API |
|------|---------|---------|
| 鉴权 | JWT(用户登录) | JWT(应用凭证) |
| 隔离 | `current_user` | `ExternalApp` + `allowed_origins` |
| 限流 | 用户级 | **应用级** + origin 白名单 |
| 资源范围 | 整个平台 | 只能调该 app `allowed_agent_ids` / `allowed_team_ids` 里的 Agent |
| 接入 | 前端登录后 | **第三方域名下 `<script>` 加载** |

**业务场景?**

- 客户的电商网站想接入我们的 AI 客服
- 客户 SaaS 平台想给自己的用户提供智能问答,但不希望自己训练
- 微信生态外的网页客服(公众号助手是另一种,见 [wx-publisher](wx-publisher.md))

**一句话**:让"第三方域名"也能用我们的对话能力,但**不交出我们的核心密钥**。

---

## 2. 功能清单

| 功能 | 描述 |
|------|------|
| ExternalApp CRUD | 管理员创建/查看/更新/删除/重新生成秘钥 |
| App Key + Secret | 公开 key + bcrypt 哈希的 secret;secret **只在创建时返回一次** |
| Origin 白名单 | 每个 app 配允许的域名,精确或单层通配 |
| Scope 控制 | 逗号分隔的 scope 串,widget 只能调对应端点 |
| Token 颁发 | `POST /external/auth/token` 用 (app_key, Origin) 换 JWT |
| Visitor 持久化 | 浏览器 UUID 落库,跨会话跟同一访客 |
| 限流 | 进程内滑动窗口 60s,失败返 429 + `Retry-After: 60` |
| 资源隔离 | token 内嵌 `allowed_agent_ids` / `allowed_team_ids`,后端二次校验 |
| 多租户隔离 | 全程 `tenant_id` 过滤,跨租户 404(不暴露存在性) |
| 用量统计 | 7 天活跃访客、累计对话数、`last_used_at` |

---

## 3. 数据模型

### 3.1 external_apps

```python
# backend/lumen_models/external_app.py

class ExternalApp(BaseModel):
    __tablename__ = "external_apps"

    tenant_id: int                # → tenants.id,索引
    name: str                     # 内部显示名
    app_key: str                  # 公开,前端可见,8~64 字符
    app_secret_hash: str          # bcrypt;不在任何 API 响应里出现
    allowed_origins: list[str]    # JSON;精确或 "https://*.example.com"
    allowed_agent_ids: list[int]  # JSON;widget 只能用这些 Agent
    allowed_team_ids: list[int]   # JSON;同上,Team
    scopes: str                   # "chat:stream,chat:upload,conv:read"
    rate_limit_per_min: int       # 默认 60
    is_active: bool               # 软切换
    description: str | None
    created_by: int               # → users.id
    last_used_at: datetime | None
```

**索引**:
- `(tenant_id, is_active)` — 列表过滤
- `(tenant_id, created_at)` — 排序

### 3.2 external_visitors

```python
class ExternalVisitor(BaseModel):
    __tablename__ = "external_visitors"

    app_id: int                          # → external_apps.id
    visitor_id: str                      # 浏览器 UUID(localStorage)
    display_name: str | None
    visitor_metadata: dict | None
    first_seen_at: datetime
    last_seen_at: datetime

    __table_args__ = (
        UniqueConstraint("app_id", "visitor_id", name="uq_external_visitors_app_visitor"),
    )
```

**唯一性是 per-app 而不是全局** — 同一 UUID 可在不同 widget 复用。

### 3.3 文件清单

| 层 | 文件 |
|----|------|
| ORM | `backend/lumen_models/external_app.py` |
| 服务 | `backend/lumen_services/external_auth_service.py` |
| 公共路由 | `backend/lumen_api/v1/external/auth.py` |
| 公共路由 | `backend/lumen_api/v1/external/agents.py` |
| 公共路由 | `backend/lumen_api/v1/external/chat.py` |
| 公共路由 | `backend/lumen_api/v1/external/conversations.py` |
| 公共路由 | `backend/lumen_api/v1/external/upload.py` |
| 管理路由 | `backend/lumen_api/v1/external_apps.py` |
| 前端管理 | `frontend/app/dashboard/settings/external-apps/` |
| Widget 组件 | `widget/src/` |

---

## 4. 核心流程

### 4.1 颁发 Token

```python
# backend/lumen_services/external_auth_service.py

def create_external_token(payload: dict, *, ttl_seconds: int | None = None) -> str:
    body = dict(payload)
    body["iss"] = "external-app"          # ← 关键:与内部 JWT 区分
    body["exp"] = int(time.time()) + (ttl_seconds or settings.EXTERNAL_TOKEN_TTL_SECONDS)
    return jwt.encode(body, EXTERNAL_JWT_SECRET, algorithm=ALGORITHM)
```

**和内部 JWT 区别**:
- `iss = "external-app"`(内部 JWT 没有这个字段,或者值不同)
- **单独的 secret** `EXTERNAL_JWT_SECRET`(防止一个泄漏连锁)
- **短 TTL**:默认 1800 秒(30 分钟),浏览器要定期续

### 4.2 `/external/auth/token` 完整流程

```
POST /api/v1/external/auth/token
Body: { app_key, visitor_id }
Header: Origin: https://shop.example.com
        ↓
1. Pydantic 校验(app_key 8-64, visitor_id 8-64)
        ↓
2. SELECT ExternalApp WHERE app_key = ? AND is_active = 1
        ↓
3. service.match_origin(Origin, app.allowed_origins)
   - 不匹配 → 403 origin not allowed
        ↓
4. service.check_rate_limit(app_id, "token", limit_per_min)
   - 超限 → 429 + Retry-After: 60
   (限流检查在 upsert 之前 — 防止 429 也写入 visitor)
        ↓
5. service.upsert_visitor(app_id, visitor_uuid)
   - SELECT FOR UPDATE → 拿到行 → last_seen_at = NOW
   - 不存在 → INSERT → flush (id 分配)
        ↓
6. UPDATE ExternalApp.last_used_at = NOW + COMMIT
        ↓
7. sign JWT:
   { app_id, tenant_id, visitor_id, allowed_agent_ids,
     allowed_team_ids, scopes, exp, iss="external-app" }
        ↓
8. resolve allowed_agents / allowed_teams 显示概要
        ↓
9. 返回 SingleResponse[TokenResponse]
```

### 4.3 Widget 调用流程

```js
// widget 内部示意
async function ensureToken() {
  if (token && token.exp > Date.now()/1000 - 60) return token;
  const res = await fetch(`${API}/api/v1/external/auth/token`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ app_key, visitor_id: getOrCreateVisitorId() }),
  });
  const { data } = await res.json();
  token = data;
  return token;
}

async function sendMessage(text) {
  await ensureToken();
  const res = await fetch(`${API}/api/v1/external/chat/stream`, {
    method: "POST",
    headers: {
      "Authorization": `Bearer ${token.token}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ agent_id: 12, message: text, conversation_id }),
  });
  // ... 读 SSE 流
}
```

---

## 5. 安全设计

### 5.1 Origin 匹配(`match_origin`)

**支持两种模式**:
- 精确: `https://shop.example.com`
- 单层通配: `https://*.example.com` — 匹配 `https://shop.example.com`,**不**匹配 `example.com` 或 `a.b.example.com`

**实现**:
```python
for pat in allowed:
    if "*" in pat:
        # 转义所有元字符,把 \* 替换为 [^.]+ (至少一个非点字符)
        regex = "^" + re.escape(pat).replace(r"\*", "[^.]+") + "$"
        if re.match(regex, origin):
            return True
    else:
        if origin == pat:
            return True
```

**安全属性**(测试覆盖):
| 输入 | 模式 | 期望 |
|------|------|------|
| `https://shop.example.com` | `https://*.example.com` | ✅ 允许 |
| `https://example.com` | `https://*.example.com` | ❌ 拒绝(必须有一个子域) |
| `https://example.com.attacker.com` | `https://*.example.com` | ❌ 拒绝(后缀攻击) |
| `shop.example.com`(无 scheme) | `https://*.example.com` | ❌ 拒绝(scheme 必须匹配) |
| `""`(空 allowed) | (任意) | ❌ 拒绝(empty allowlist 不允许) |

### 5.2 Origin 兜底 Referer 的风险

```python
origin = request.headers.get("origin") or request.headers.get("referer", "")
```

**当前实现**:优先读 `Origin`,缺失时退回 `Referer`。

**已知软肋**:
- `Referer` 可被攻击者控制(redirect / 第三方脚本)
- 我们的匹配是基于 "host 部分",**偶然**能挡住一些攻击
- TODO(security):后续 spec 改版要砍掉 fallback,或换成正经 CORS preflight

**缓解**:目前 `allowed_origins` **默认要求填具体域名**,管理员配 `*` 时有警告。

### 5.3 限流(进程内滑动窗口)

```python
_lock = threading.Lock()
_buckets: dict[tuple[int, str], deque[float]] = {}

def check_rate_limit(*, app_id: int, endpoint_class: str, limit_per_min: int) -> bool:
    now = time.monotonic()
    cutoff = now - 60.0
    key = (app_id, endpoint_class)
    with _lock:
        bucket = _buckets.setdefault(key, deque())
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        if len(bucket) >= limit_per_min:
            return False
        bucket.append(now)
        return True
```

**关键设计**:
- 进程内:换实例时单台实例的限流独立(横向扩容 = 限流放宽 N 倍)
- 滑动窗口:精确率比固定窗口好(临近 60s 不会瞬时翻倍)
- 锁隔离:threading.Lock 保护 `deque`,thread-safe
- 桶 key 是 `(app_id, endpoint_class)` — 不同端点独立计数

**多实例现状(已知局限)**:
```
单实例:60 req / 60s / (app, endpoint_class)
4 实例:实际可能 240 req / 60s / (app, endpoint_class)
```
**升级路径**:Redis `INCR` + `EXPIRE` 或 Lua 脚本,见 §8.1。

### 5.4 资源隔离

Token 内嵌 `allowed_agent_ids` / `allowed_team_ids`。后端二次校验:

```python
# 简化示意
if request.agent_id not in token_payload["allowed_agent_ids"]:
    raise HTTPException(403, "agent not allowed for this app")
```

**含义**:即使 widget 拿到了合法 token,也只能调 `allowed_*_ids` 里的 Agent/Team。**后端不信前端**。

### 5.5 内部 JWT 隔离

```python
# backend/lumen_core/config.py
EXTERNAL_JWT_SECRET: str = "change-me-in-prod"  # 必须改
ALGORITHM: str = "HS256"
EXTERNAL_TOKEN_TTL_SECONDS: int = 1800         # 30 分钟
```

**启动时强校验**:若 `EXTERNAL_JWT_SECRET` 还是默认值,启动日志会 warn。这是**未实现的安全保障**(TODO)。

### 5.6 Secret 哈希 + 不在响应里返回

```python
# 创建时
secret_plain = _gen_app_secret()              # 明文,一次性返回
app_secret_hash = get_password_hash(secret_plain)  # bcrypt 落库

# 后续 GET /external-apps/{id} → 只返回 app_key,没有 secret
```

**重置密钥**:`POST /external-apps/{id}/regenerate-secret` 会重新生成,新明文**只返回这一次**。

---

## 6. REST API

### 6.1 公共路由(`/api/v1/external/*`)

这些**不要 JWT,只接受 external token**(`Authorization: Bearer <external_token>`)。

| Method | Path | 用途 |
|--------|------|------|
| POST | `/auth/token` | 颁发 token(用 app_key + Origin) |
| GET | `/agents` | 列出该 app 允许的 Agent 概要 |
| POST | `/chat/stream` | 发消息 + 接收 SSE 流式响应 |
| GET | `/conversations` | 列 widget 内对话 |
| POST | `/conversations` | 新建对话 |
| GET | `/conversations/{id}/messages` | 拉历史消息 |
| DELETE | `/conversations/{id}` | 删对话 |
| POST | `/chat/upload` | 文件上传(图片/PDF) |

### 6.2 管理路由(`/api/v1/external-apps/*`)

需要登录 + `is_superuser`(管理员)。

| Method | Path | 说明 |
|--------|------|------|
| GET | `/external-apps` | 列表(分页 + search) |
| POST | `/external-apps` | 创建,**返回 `app_secret_plain`** |
| GET | `/external-apps/{id}` | 详情 |
| PATCH | `/external-apps/{id}` | 更新 |
| DELETE | `/external-apps/{id}` | 删(有 active 对话则 409) |
| POST | `/external-apps/{id}/regenerate-secret` | 重置密钥 |
| GET | `/external-apps/{id}/usage` | 用量(7 天活跃访客、对话数) |

---

## 7. 关键设计决策

### 7.1 Token 用 module,不用 named import

```python
# ✅ 对
from lumen_services import external_auth_service as auth_svc
auth_svc.check_rate_limit(...)

# ❌ 错
from lumen_services.external_auth_service import check_rate_limit
check_rate_limit(...)
```

**为什么**:用 named import 时,函数名在 import 时就被绑定,后续 `monkey-patch` 改 `auth_svc.check_rate_limit` 不影响路由里的引用。**测试要做"超过限流"路径就必须用 module 形式**。

详见 [常见错误 §X.X](../troubleshooting/common-errors.md)。

### 7.2 限流在 upsert 之前

```python
# ✅ 当前顺序
check_rate_limit(...)       # 1. 先限流
upsert_visitor(db, ...)     # 2. 后写入

# ❌ 反过来
upsert_visitor(db, ...)     # 拒绝的请求也写了 visitor 表,污染数据
check_rate_limit(...)
```

**为什么**:恶意请求拿 429 后,**不应该**在 `external_visitors` 表留下痕迹(否则访客数会虚高,影响 `usage` 统计的准确性)。

### 7.3 跨租户返 404

```python
a = db.get(ExternalApp, app_id)
if not a or a.tenant_id != current_user.tenant_id:
    raise HTTPException(404, "not found")
```

**为什么**:返 403 会泄露 "这个 id 存在" 的信息,攻击者可枚举。返 404 是 "对当前用户来说不存在"。

### 7.4 Origin 兜底 Referer

```python
origin = request.headers.get("origin") or request.headers.get("referer", "")
```

**当前行为**:浏览器跨域 fetch 总会带 `Origin`;`Referer` 只在跳转时才有。
**风险**:`Referer` 容易被攻击者控制;但 `match_origin` 仍然按 host 匹配,所以**意外**过滤了一些攻击,但**不是**安全设计。

**TODO**(写在模块 docstring):改成正经 CORS preflight,或砍掉 fallback。

### 7.5 修饰符 `app_secret_hash` 不出现

```python
# 已通过 Pydantic schema 的 model_config(BLACKLIST_PROPERTIES)实现
# 任何含 app_secret_hash 的子响应都会被自动剥掉
```

---

## 8. 已知局限

### 8.1 多实例失效

进程内 `_buckets` 是 **per-process**。横向扩容 = 实际限流放宽 N 倍。

**升级路径**:Redis `INCR` + `EXPIRE` 或 Lua 脚本做滑动窗口。

### 8.2 没有审计日志

`usage` 端点返回 `token_issues_7d: 0` —— **没记录**。要审计"谁在什么时候调了 token"目前无数据。

**升级**:加 `external_token_audit` 表或对接现有 `audit_logs`。

### 8.3 Origin 兜底 Referer

见 §7.4。

### 8.4 Secret 默认值

`EXTERNAL_JWT_SECRET` 默认 `change-me-in-prod`。忘了改的环境会有匿名 token 风险。**启动时应该有 fail** 而非 warn。

### 8.5 没有 token revoke

JWT 签发后 30 分钟内有效;**还没实现 token 黑名单**。要"立刻下线烂 app"只能改 `is_active=False`,但已发的 token 还能用到过期。

### 8.6 单层通配

`https://*.example.com` 不匹配 `a.b.example.com`。

**业务上**:很多企业有多层 subdomain(如 `region.brand.example.com`)。**当前不支持 `**` 这种递归通配**;需要精确列出每个子域。

### 8.7 CORS 缓存失效

`get_cors_cache().invalidate()` 在创建/更新/删除 app 时调,确保新 origin 立即生效。**没管理这个缓存会导致新 origin 在刷新生效前被动静拦截。**

---

## 9. 排错

| 症状 | 原因 | 修法 |
|------|------|------|
| `403 origin not allowed` | Origin 不在白名单 | 管理员去 `/dashboard/settings/external-apps` 加 |
| `401 invalid app_key` | app_key 不存在 / `is_active=false` | 后台启用 app |
| `429 rate limited` + `Retry-After: 60` | 超限 | 等待 60 秒重试,或管理员调高 `rate_limit_per_min` |
| 限流不生效 | 多实例部署 | 升级到 Redis |
| widget 拿到 token 但 调 `/chat/stream` 403 | `allowed_agent_ids` 没包含请求的 agent_id | 管理员改 app 配置 |
| 跨租户 403 → 应是 404 | 老代码残留 | 升级到当前版本 |
| `pytest` 里限流测试不通过 | 用了 named import 导致 monkey-patch 失效 | 改 module 形式 import |
| 创建时返回 `app_secret_plain` 是空 | 路由逻辑 bug | 检查 `ExternalAppCreated` schema 字段 |
| `Last_used_at` 不更新 | `/auth/token` 没调到(可能是限流) | 看后端日志 |
| token 突然失效 | `EXTERNAL_JWT_SECRET` 改了 | 重新生成所有 app 的 token |

---

## 10. 与其他模块的关系

```
[Browser localStorage: visitor_id]
        ↓
[Widget <script src="...">]
        ↓ POST /external/auth/token
[Lumen API]
        ↓ match_origin + check_rate_limit + upsert_visitor
[JWT 签发]
        ↓
[Widget: 后续调用 /external/chat/stream]
        ↓
[Chat Service] (复用内部对话服务)
        ↓
[LLM + Knowledge Base + Skills]
        ↓
[存 ExternalConversation (Conversation.external_app_id 标记)]
```

**数据回写**:widget 产生的对话在 `conversations` 表里有 `external_app_id` 字段,管理后台可以过滤查看"哪些对话来自 widget"。

---

## 11. 边界与不做

### 11.1 当前
- ✅ App Key + Secret + Origin 白名单
- ✅ 进程内限流(Rate limit)
- ✅ Visitor 持久化
- ✅ Allowed Agent/Team 资源隔离
- ✅ Scope 字符串(逗号分隔)
- ✅ 多租户隔离
- ✅ Secret 加密 + 仅创建/重置时返回明文

### 11.2 不做
- ❌ Token 撤销列表(blacklist)
- ❌ 审计日志(谁/何时/什么端点)
- ❌ Webhook(对话结束时通知第三方)
- ❌ 跨域 widget 域名验证(只用 Origin header)
- ❌ Redis 集群限流(目前进程内)
- ❌ 多层通配 `**`
- ❌ 单点登录(SSO)集成

### 11.3 升级路径

| 阶段 | 改动 |
|------|------|
| 短期 | 加 `external_token_audit` 表 + 实际限流审计 |
| 短期 | 启动时 `EXTERNAL_JWT_SECRET` 默认值 fail-fast |
| 中期 | Redis 限流 + token 撤销 |
| 中期 | 干掉 Origin → Referer fallback,改 CORS preflight |
| 长期 | SSO(SAML / OAuth2)集成 |
| 长期 | Webhook → 第三方后端 |

---

**相关文档**
- [鉴权与 RBAC](../architecture/05-auth-rbac.md)
- [Chat](chat.md) — 内部对话流(widget 复用)
- [Agent](agent.md) — 隔离的 Agent 资源
- [CORS 缓存](../explanation/response-envelope.md) — `get_cors_cache().invalidate()`

**维护者**:全栈架构师
**最近更新**:2026-08-06
