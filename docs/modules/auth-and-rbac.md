# 模块:认证与 RBAC

> Lumen AI Platform 的认证、用户管理、角色权限体系。
> 文档从产品视角描述能做什么,代码实现细节看 [architecture/05-auth-rbac.md](../architecture/05-auth-rbac.md)。

---

## 1. 产品定位

**为什么需要这个模块?**
- 企业部署:不能让所有人都能看 / 改所有数据
- 多部门:销售部只能看客户,研发部只能看工作流
- 合规:谁动了什么需要可追溯
- 安全:防止越权操作(改模型、改其他租户数据)

---

## 2. 功能清单

| 功能 | 描述 | 文档 |
|------|------|------|
| 登录 | 用户名密码 → JWT | 本页 § 3 |
| 当前用户 | 查自己 | 本页 § 4 |
| 用户管理 | CRUD + 启停 | 本页 § 5 |
| 角色管理 | CRUD + 权限矩阵 | 本页 § 6 |
| 权限装饰器 | 后端检查 | [architecture/05](../architecture/05-auth-rbac.md#rbac-角色权限) |
| 外部应用认证 | app_key 换 JWT | [external-app-auth](external-app-auth.md) |
| 多租户隔离 | tenant_id 强制过滤 | [architecture/04](../architecture/04-multi-tenant.md) |

---

## 3. 登录

### 3.1 用户故事
> 作为用户,我想用用户名密码登录,系统给我 token,我访问其他 API 都自动带 token。

### 3.2 流程
```
用户输入 admin / admin123
   │
   ▼
POST /api/v1/auth/login
   │
   ▼
后端: 查 users(校验密码)
   │
   ▼
签 JWT(tenant_id, is_superuser, exp=24h)
   │
   ▼
返回 { access_token, user: {...} }
   │
   ▼
前端: localStorage.setItem("access_token", token)
```

### 3.3 前端
- 路径: `frontend/app/(auth)/login/page.tsx`
- 默认账号: `admin / admin123` (demo 友好,生产必改)
- 登录成功跳 `/dashboard`

### 3.4 后端
- 路由: `POST /api/v1/auth/login`
- 入参: `application/x-www-form-urlencoded` (OAuth2 标准)
  ```
  username=admin&password=admin123
  ```
- 响应:
  ```json
  {
    "code": 200,
    "message": "登录成功 / Login successful",
    "data": {
      "access_token": "eyJhbGc...",
      "token_type": "bearer",
      "user": {
        "id": 1,
        "username": "admin",
        "email": "admin@example.com",
        "full_name": "管理员",
        "is_active": true,
        "is_superuser": true,
        "tenant_id": 1
      }
    }
  }
  ```

### 3.5 关键代码
- 路由: `backend/lumen_api/v1/auth.py`
- 服务: `backend/lumen_services/auth_service.py::authenticate_user`
- JWT 签发: `backend/lumen_core/auth.py::create_access_token`
- 密码哈希: `PassLib + bcrypt`

---

## 4. 当前用户

### 4.1 用法
- 前端右上角显示用户名
- `dashboard/layout.tsx` useEffect 拉 `/auth/me`

### 4.2 后端
- 路由: `GET /api/v1/auth/me`
- 响应: `User` 对象(无 password)

---

## 5. 用户管理

### 5.1 用户故事
> 作为租户管理员,我想给销售团队 5 个账号,每个都能登录。

### 5.2 功能
- 列出当前租户的用户
- 创建用户(用户名 / 邮箱 / 密码 / 角色)
- 修改用户(改密码 / 改角色 / 启停)
- 删除用户(级联:该用户的会话 / 记忆怎么办?)

### 5.3 UI
- 路径: `frontend/app/dashboard/system/users/page.tsx`
- 表格:用户名 / 邮箱 / 角色 / 状态 / 操作
- 操作:创建 / 编辑 / 删除 / 启停

### 5.4 后端
- 路由: `backend/lumen_api/v1/users.py`
  - `GET /api/v1/users/` — 列表
  - `GET /api/v1/users/{id}` — 详情
  - `POST /api/v1/users/` — 创建
  - `PATCH /api/v1/users/{id}` — 编辑
  - `DELETE /api/v1/users/{id}` — 删除
  - `GET /api/v1/users/assignable` — 可分配列表(给 OwnerUserSelect 用)

### 5.5 关键代码
- 服务: `backend/lumen_services/user_service.py`
- Schema: `backend/lumen_schemas/user.py`
- ORM: `backend/lumen_models/user.py`

### 5.6 业务规则
- 不能删自己
- 不能把超管降级(只剩自己)
- 用户名唯一 / 邮箱唯一
- 密码长度 ≥ 8

---

## 6. 角色管理

### 6.1 用户故事
> 作为租户管理员,我想给"销售"角色配置"只看客户 + 改客户档案"权限,这样新建销售账号时直接选"销售"角色就行。

### 6.2 内置角色
- `super_admin` — 平台超管(跨租户)
- `tenant_admin` — 租户管理员
- `developer` — 开发者
- `operator` — 业务运营
- `viewer` — 只读访客

### 6.3 自定义角色(租户级)
- 创建 / 编辑 / 删除自定义角色
- 配置:角色名 + 权限列表
- 例: "客服" 角色 → `chat.read` + `chat.create` + `customer.read` + `customer.update`

### 6.4 UI
- 路径: `frontend/app/dashboard/system/roles/page.tsx`
- 表格:角色名 / 权限数 / 用户数 / 操作
- 编辑:权限矩阵(资源 × 动作)

### 6.5 后端
- 路由: `backend/lumen_api/v1/roles.py`
- 权限 schema: `resource.action`(例: `knowledge.create`)
- 资源列表: agent / knowledge / workflow / chat / customer / user / role / system / ...

### 6.6 关键代码
- 服务: `backend/lumen_services/role_service.py`
- Schema: `backend/lumen_schemas/role.py`
- ORM: `backend/lumen_models/role.py`(roles + permissions + role_permissions + user_roles)

---

## 7. 装饰器 / 权限检查

### 7.1 后端
```python
# backend/lumen_api/v1/agent.py
from lumen_api.v1.deps import get_current_user, require_permission

@router.post("/", response_model=SingleResponse[AgentRead])
def create_agent(
    payload: AgentCreate,
    current_user: User = Depends(get_current_user),
    _: None = Depends(require_permission("agent.create"))
):
    # 自动校验:current_user 有 agent.create 权限吗?
    ...
```

### 7.2 前端(计划中)
- 暂未实现 UI 级 RBAC
- 后续加 `<Authorized permission="agent.create">` 包装

---

## 8. 边界与不做

### 8.1 当前
- ✅ OAuth2 Password Grant
- ✅ JWT 24h
- ✅ RBAC 装饰器
- ✅ 多租户隔离
- ❌ Refresh Token(待加)
- ❌ SSO / SAML(企业版待加)
- ❌ 找回密码(无 UI)

### 8.2 计划
- 📋 邀请码接受流程(M38)
- 📋 双 token + 滑动续期
- 📋 设备管理
- 📋 异常登录告警

---

## 9. 排错

| 症状 | 原因 | 修法 |
|------|------|------|
| 登录 401 | 用户名/密码错 | 校验 |
| 登录 422 | 入参格式错 | 用 x-www-form-urlencoded |
| token 401 | token 失效 / 错 | 清 localStorage 重登 |
| 权限 403 | 角色没绑该权限 | 改 role_permissions |
| 跨用户访问 404 | 多租户隔离生效 | 检查 tenant_id |
| WebSocket 4401 | token 失效 | 重新登录 |

详见 [troubleshooting/common-errors.md](../troubleshooting/common-errors.md) 和 [auth-rbac 架构](../architecture/05-auth-rbac.md)。

---

**维护者**:全栈架构师
**最近更新**:2026-08-06
