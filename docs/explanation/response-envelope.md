# 响应信封

> Lumen AI Platform 所有 HTTP API 返回的**统一响应格式**。
> 这是一个横切所有模块的契约,前端读 `body.code === 200` + `body.data`。
> 文档解释为什么这么设计 + 怎么用。

---

## 1. 背景

### 1.1 传统 REST API 的痛点
- 有的 endpoint 返回裸 dict
- 有的返回 ORM 对象(Pydantic 不一致)
- 有的嵌套 `data` 有的不嵌套
- 前端要写一堆 `if (response.success) { response.data... }`

### 1.2 Lumen 的解决方案
**所有 endpoint 强制返回信封**,后端用 Pydantic `response_model=SingleResponse[T]` 装饰,前端统一读:
```ts
const res = await api.get(...)
const body = res.data  // 信封
if (body.code === 200) {
  const item = body.data  // 真实数据
}
```

---

## 2. 信封定义

### 2.1 `SingleResponse[T]`
- 文件:`backend/lumen_schemas/common.py`
- 用途:单项返回(create / get / update / delete)
- 字段:

```python
class SingleResponse(BaseModel, Generic[T]):
    code: int          # 业务码,200 = 成功
    message: str       # 提示信息(双语,例: "已保存 / Saved")
    data: T | None     # 真实数据
```

### 2.2 `PaginatedResponse[T]`
- 用途:列表返回(list)
- 字段:

```python
class PaginatedResponse(BaseModel, Generic[T]):
    code: int          # 200 = 成功
    message: str       # 提示
    data: list[T]      # 数据列表
    total: int         # 总数
    page: int          # 当前页(从 1 开始)
    page_size: int     # 每页大小
```

---

## 3. 业务码约定

| 码 | 含义 | HTTP Status |
|----|------|------------|
| **200** | 成功 | 200 |
| **201** | 创建成功 | 201 |
| **400** | 参数错误 | 400 |
| **401** | 未登录 | 401 |
| **403** | 权限不足 | 403 |
| **404** | 资源不存在 | 404 |
| **409** | 资源冲突 | 409 |
| **422** | Pydantic 校验失败 | 422 |
| **429** | 限流 | 429 |
| **500** | 内部错误 | 500 |
| **502** | 上游服务错误 | 502 |
| **503** | 服务暂不可用 | 503 |

**特别约定**:
- `code === 200` = 成功(其他都算失败,即使 HTTP 200)
- `code === 4xx/5xx` = 失败,`data` 通常为 `null`

---

## 4. 后端使用

### 4.1 路由装饰
```python
from lumen_schemas.common import SingleResponse, PaginatedResponse
from lumen_schemas.agent import AgentRead

@router.get("/{agent_id}", response_model=SingleResponse[AgentRead])
def get_agent(agent_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    agent = db.query(Agent).filter(Agent.id == agent_id, Agent.tenant_id == current_user.tenant_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent 不存在 / Not found")
    return {"code": 200, "message": "查询成功 / OK", "data": agent}  # ORM 对象会被 Pydantic 序列化
```

**注意**:
- 返回 `dict` 而非 ORM 对象更显式
- 抛 `HTTPException` 时,**全局错误处理器**会包装成信封
- 见 [auth-rbac § 6](../architecture/05-auth-rbac.md#错误处理)

### 4.2 错误的统一处理
```python
# lumen_core/middleware/error_handler.py
@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    return JSONResponse(
        status_code=exc.status_code,
        content={"code": exc.status_code, "message": exc.detail, "data": None}
    )
```

### 4.3 全局错误
```python
# lumen_core/middleware/error_handler.py
@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    log.exception("Unhandled exception")
    return JSONResponse(
        status_code=500,
        content={"code": 500, "message": "内部错误 / Internal Server Error", "data": None}
    )
```

### 4.4 Pydantic 校验失败
- 自动包装成 422 + `errors` 字段:
```json
{
  "code": 422,
  "message": "参数校验失败 / Validation failed",
  "data": null,
  "errors": [
    {"loc": ["body", "name"], "msg": "field required", "type": "value_error.missing"}
  ]
}
```

---

## 5. 前端使用

### 5.1 通用读取
```ts
// lib/response.ts
export function unwrap<T>(res: AxiosResponse<ApiResponse<T>>): T {
  const body = res.data
  if (body.code === 200) {
    return body.data as T
  }
  throw new ApiError(body.code, body.message, body.errors)
}
```

### 5.2 单项
```ts
// services/agent.ts
async function getAgent(id: number): Promise<Agent> {
  const res = await api.get(`/agents/${id}`)
  return unwrap<Agent>(res)  // T = Agent
}
```

### 5.3 列表
```ts
async function listAgents(params: Query): Promise<{ items: Agent[]; total: number }> {
  const res = await api.get('/agents/', { params })
  const body = res.data
  if (body.code === 200) {
    return { items: body.data, total: body.total }
  }
  throw new ApiError(body.code, body.message)
}
```

### 5.4 在 React 组件中
```tsx
const { data, isLoading, error } = useQuery(['agents'], () => agentApi.list())
// error 已经包含 message,可以直接用 antd message.error(error.message)
```

### 5.5 直接 axios 用法(非 Query)
```ts
const res = await axios.post('/agents', payload, {
  headers: { Authorization: `Bearer ${token}` }
})
const body = res.data
if (body.code === 200) {
  console.log('已保存', body.data)
} else {
  console.error(body.message)
}
```

---

## 6. 工具函数

### 6.1 前端
- `frontend/lib/response.ts` — `unwrap` / `unwrapList`
- `frontend/lib/api-error.ts` — `ApiError` 类

### 6.2 后端
- `backend/lumen_schemas/common.py` — `SingleResponse[T]` / `PaginatedResponse[T]`
- `backend/lumen_core/middleware/error_handler.py` — 统一异常处理

---

## 7. TypeScript 类型

```ts
// frontend/types/api.ts
export interface ApiResponse<T> {
  code: number
  message: string
  data: T | null
  errors?: Array<{ loc: string[]; msg: string; type: string }>
}

export interface PaginatedApiResponse<T> extends ApiResponse<T[]> {
  total: number
  page: number
  page_size: number
}
```

---

## 8. 边界情况

### 8.1 业务码 vs HTTP Status
- 业务码是权威(前端只看 `code`)
- HTTP Status 通常与 `code` 一致,但**不一定**(例:`201 Created` 也用 `code: 200`)

### 8.2 空数据
- 单项:`data: null`
- 列表:`data: []`,`total: 0`

### 8.3 大列表
- 默认 page_size: 20
- 最大 page_size: 100
- 超过建议用 cursor 分页(目前大部分接口用 offset)

### 8.4 文件下载
- 不走信封,直接返回二进制流
- 走 `Content-Type: application/octet-stream` 或 `image/png` 等
- 鉴权靠 Bearer header

### 8.5 SSE 流
- 不走信封
- `Content-Type: text/event-stream`
- 详见 [explanation/chat-sse-streaming.md](chat-sse-streaming.md)

### 8.6 WebSocket
- 不走信封
- 升级协议 + 消息自描述

---

## 9. 为什么不直接用 HTTP Status

### 9.1 业务码能区分的更多
- HTTP Status 只能 16 种
- 业务码可以无穷(如 4001 = 用户已存在,4002 = 用户名非法)

### 9.2 业务码是统一的
- HTTP 200 但业务失败 → 前端能区分
- HTTP 500 但业务成功(如异步任务启动)→ 不会误判

### 9.3 业务码更细
- 例:限流可以 429(普通)vs 4291(账号黑名单)
- 错误码可枚举,便于 i18n

---

## 10. 国际化(i18n)

### 10.1 双语 message
- 成功消息: `"已保存 / Saved"`
- 错误消息: `"参数错误 / Bad request"`
- 让中英文用户都能看懂

### 10.2 计划
- 后期按 `Accept-Language` 返回单语
- 后端 i18n 文件 `backend/lumen_core/i18n.py`

---

## 11. 破坏性变更控制

### 11.1 信封字段变更
- `code` / `message` / `data` 永远是这 3 个
- 新增字段向后兼容(如 `errors`、`trace_id`)

### 11.2 业务码变更
- 已有业务码不重新分配
- 新增业务码从 1001 起

### 11.3 弃用字段
- 用 `@deprecated` Pydantic 装饰
- 文档标 `Deprecated since Mxx`
- 保留 6 个月后移除

---

**维护者**:全栈架构师
**最近更新**:2026-08-06
