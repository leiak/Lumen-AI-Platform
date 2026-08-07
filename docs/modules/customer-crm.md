# 模块:客户管理(CRM)

> Lumen AI Platform 的客户档案与跟进管理(M33)。
> 文档讲透客户档案、跟进 timeline、自定义字段、AI 智能建议。

---

## 1. 产品定位

**客户管理是什么?**
- 销售视角的**客户档案 + 跟进记录**
- 每租户可自定义档案字段
- AI 基于跟进历史推荐**下次话术和时间**

**和"通用 CRM"比有什么不同?**
- 不做全生命周期(线索 → 商机 → 合同 → 回款),只做**档案 + 跟进**
- **AI 原生**:平台已有的 LLM / 记忆 / 日志能力直接复用
- 和 Agent / 知识库同库,客户信息可以喂给 AI 助手

**业务场景?**
- 销售管理自己的客户,记录每次沟通
- "这周该跟进谁"一眼看到
- 长时间没联系的客户,让 AI 想开场白
- 不同行业客户需要不同字段(教育看学段,制造看产能)→ 自定义字段

---

## 2. 功能清单

| 功能 | 描述 |
|------|------|
| 客户档案 CRUD | 基础信息 + 公司信息 + 分级 + 标签 |
| 多维过滤 | 关键字 / 等级 / 来源 / 负责人 / 行业 / 标签 / 待跟进时间 |
| 软删除 + 恢复 | `is_active` 标记,可恢复 |
| 跟进记录 timeline | 5 种跟进类型,按时间倒序 |
| 聚合字段自动同步 | `last_follow_up_at` / `next_follow_up_at` 事务内更新 |
| 待跟进列表 | 「我的待跟进」,过期显示负数天 |
| 自定义字段 | 6 种类型,每租户一份 schema |
| 字段引用保护 | 有客户在用的字段不能删 |
| 手机号脱敏 | 列表页 `138****8000` |
| AI 智能建议 | 基于最近 5 条跟进推荐话术 + 时间 |
| 负责人选择器 | 默认当前用户 |
| 多租户隔离 | `tenant_id` 全表隔离 |

---

## 3. 数据模型

### 3.1 customers(客户主表)

```python
class Customer(BaseModel):
    __tablename__ = "customers"

    tenant_id: int                # 多租户隔离
    owner_user_id: int            # 负责人(销售)—— 必填
    created_by: int

    # ---- 基础信息 ----
    name: str                     # 必填,有索引
    phone: str                    # 有索引(列表页脱敏显示)
    email: str
    wechat: str
    avatar_url: str
    gender: str                   # M / F / U
    birthday: date
    address: str

    # ---- 公司信息 ----
    company_name: str             # 有索引
    company_position: str
    industry: str                 # 有索引
    company_size: str             # 1-10 / 11-50 / 51-200 / 201-1000 / 1000+
    company_website: str

    # ---- 客户属性 ----
    level: str                    # vip / normal / potential(默认) / lost
    source: str                   # referral / website / exhibition / ad / other
    tags: list                    # JSON: List[str]
    custom_fields: dict           # JSON: Dict[str, Any],按 schema 校验
    remark: str

    # ---- 跟进时间聚合(由 follow_up_service 同步,不要手改) ----
    last_follow_up_at: datetime
    next_follow_up_at: datetime

    is_active: bool               # 软删除标记
    created_at, updated_at
```

**索引设计**(全部以 `tenant_id` 打头,保证多租户下走索引):

```python
Index("idx_customers_tenant_owner", "tenant_id", "owner_user_id")
Index("idx_customers_tenant_level", "tenant_id", "level")
Index("idx_customers_tenant_next_follow", "tenant_id", "next_follow_up_at")
Index("idx_customers_tenant_phone", "tenant_id", "phone")
Index("idx_customers_tenant_active_updated", "tenant_id", "is_active", "updated_at")
```

### 3.2 customer_follow_ups(跟进记录)

```python
class CustomerFollowUp(BaseModel):
    __tablename__ = "customer_follow_ups"

    tenant_id: int
    customer_id: int              # → customers.id ON DELETE CASCADE
    user_id: int                  # 谁跟进的

    follow_up_type: str           # phone / wechat / email / meeting / other
    content: str                  # 沟通内容(必填)
    next_step: str                # 下一步计划
    next_follow_up_at: datetime   # 约定的下次跟进时间
    ai_suggested: bool            # 是否由 AI 建议触发(采纳 AI 建议时为 True)

    created_at, updated_at

    Index("idx_follow_ups_customer_created", "customer_id", "created_at")
```

> **这是唯一一张带 `ON DELETE CASCADE` 的表** —— 删客户时跟进记录自动清理,不用手工按序删。

### 3.3 customer_field_definitions(自定义字段定义)

```python
class CustomerFieldDefinition(BaseModel):
    __tablename__ = "customer_field_definitions"

    tenant_id: int
    field_key: str                # 字段 key,存进 customers.custom_fields 的键
    field_label: str              # 显示名
    field_type: str               # text / number / date / select / multiselect / textarea
    options: list                 # select / multiselect 的选项;其他类型为 NULL
    required: bool
    order_index: int              # 表单排序
    is_active: bool
    created_by: int

    UniqueConstraint("tenant_id", "field_key")   # 同租户下 key 唯一
    Index("idx_customer_fields_tenant_active", "tenant_id", "is_active", "order_index")
```

**设计要点**:字段**定义**在这张表,字段**值**存在 `customers.custom_fields` 的 JSON 里。
好处:加字段不用 ALTER TABLE。代价:JSON 里的值不能建索引,复杂查询要靠 `JSON_CONTAINS`。

### 3.4 文件清单

| 层 | 文件 |
|----|------|
| ORM | `backend/lumen_models/customer.py` |
| Schema | `backend/lumen_schemas/customer.py` |
| 客户服务 | `backend/lumen_services/customer/customer_service.py` |
| 跟进服务 | `backend/lumen_services/customer/follow_up_service.py` |
| 字段服务 | `backend/lumen_services/customer/field_service.py` |
| AI 建议 | `backend/lumen_services/customer/ai_advisor.py` |
| 路由 | `backend/lumen_api/v1/customer.py`(两个 router) |
| 前端列表 | `frontend/app/dashboard/customer/page.tsx` |
| 前端详情 | `frontend/app/dashboard/customer/[id]/page.tsx` |
| 前端字段配置 | `frontend/app/dashboard/customer/settings/page.tsx` |

---

## 4. API 清单

### 4.1 客户档案(`/api/v1/customers`)

| Method | Path | 说明 |
|--------|------|------|
| GET | `/customers` | 多维过滤分页列表 |
| POST | `/customers` | 创建客户(201) |
| GET | `/customers/upcoming-follow-ups` | 我的待跟进(按 `next_follow_up_at` 升序) |
| GET | `/customers/{id}` | 详情 |
| PUT | `/customers/{id}` | 更新 |
| DELETE | `/customers/{id}` | **软删除**(204) |
| POST | `/customers/{id}/restore` | 恢复软删 |

**列表过滤参数**:

| 参数 | 类型 | 行为 |
|------|------|------|
| `keyword` | str | 模糊匹配 name / phone / email / company_name(**OR**) |
| `levels` | list | 多选,`IN` |
| `sources` | list | 多选,`IN` |
| `owner_user_id` | int | 负责人精确匹配 |
| `industry` | str | 精确匹配 |
| `tags` | list | 多 tag **AND**(`JSON_CONTAINS`) |
| `next_follow_up_before` | datetime | `next_follow_up_at <` 此日期 |
| `is_active` | bool | 默认 `True`,过滤软删 |
| `sort` | str | `created_at_desc` / `last_follow_up_at_desc` / `next_follow_up_at_asc` / `level_asc` |

> 注意 `keyword` 是 **OR**,`tags` 是 **AND** —— 这个不对称是有意的:关键字搜索要宽,标签筛选要窄。

### 4.2 跟进记录

| Method | Path | 说明 |
|--------|------|------|
| GET | `/customers/{id}/follow-ups` | timeline(`created_at` 倒序,分页) |
| POST | `/customers/{id}/follow-ups` | 新增跟进(201) |
| PUT | `/customers/{id}/follow-ups/{fid}` | 更新跟进 |
| DELETE | `/customers/{id}/follow-ups/{fid}` | **物理删除**(204) |

> 三个写操作**都会在同一事务内同步 `customers` 的聚合字段**。见 §5.1。

### 4.3 AI 智能建议

| Method | Path | 说明 |
|--------|------|------|
| POST | `/customers/{id}/ai/suggest` | 生成话术 + 推荐时间(同步,5~15 秒) |

### 4.4 自定义字段(`/api/v1/customer-fields`)

| Method | Path | 说明 |
|--------|------|------|
| GET | `/customer-fields` | 字段定义列表 |
| POST | `/customer-fields` | 新增字段定义 |
| PUT | `/customer-fields/{id}` | 更新字段定义 |
| DELETE | `/customer-fields/{id}` | 删字段定义(204,有引用时拒绝) |

---

## 5. 关键能力详解

### 5.1 跟进聚合字段的事务同步

**问题**:`customers.last_follow_up_at` / `next_follow_up_at` 是**冗余字段**(可以从 `customer_follow_ups` 算出来)。为什么要冗余?

**因为列表页要按"下次跟进时间"排序和过滤。**如果每次都 JOIN 子查询算,列表接口会很慢。

**代价**:必须保证一致性。所以跟进的**增 / 改 / 删都在同一事务内**调 `_refresh_customer_aggregates`:

```python
# backend/lumen_services/customer/follow_up_service.py

def _refresh_customer_aggregates(db: Session, customer_id: int) -> None:
    """重算 customer 的 last_follow_up_at / next_follow_up_at。

    在跟进的 create / update / delete 事务内调用,保证冗余字段不漂移。
    """
    # last = 最新一条跟进的 created_at
    # next = 所有跟进里 next_follow_up_at 的最小未来值
    ...
```

**重点**:是**重算**,不是增量更新。删掉最新一条跟进后,`last_follow_up_at` 要回退到上一条 —— 增量更新做不到这个。

### 5.2 手机号脱敏

列表页显示脱敏号码,详情页显示完整(有权限时)。

```python
def mask_phone(phone: Optional[str]) -> Optional[str]:
    """中间 4 位打 *。

    13800138000        → 138****8000
    +86 138 0013 8000  → +86 138****8000   (保留国际前缀)
    短号 (<7 位)        → 原样返回
    """
```

**边界处理**:
- 空 → `None`
- 长度 < 7 → 原样(座机短号打星没意义)
- 11 位纯数字 → 标准大陆手机号规则
- 更长 → 取最后 11 位处理,前缀原样保留
- 都不匹配 → 原样返回(fallback,不丢数据)

### 5.3 自定义字段校验

6 种字段类型,每种有独立校验规则:

| 类型 | Python 类型 | 约束 |
|------|-------------|------|
| `text` | `str` | ≤ 200 字符 |
| `textarea` | `str` | ≤ 2000 字符 |
| `number` | `int` / `float` | **显式排除 `bool`** |
| `date` | `str` | 必须 `YYYY-MM-DD` |
| `select` | `str` | 必须在 `options` 里 |
| `multiselect` | `list` | 每一项都必须在 `options` 里 |

```python
elif field_type == "number":
    # bool 是 int 的子类,不先排除的话 True 会被当成合法数字
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise FieldValidationError(...)
```

> `isinstance(True, int) == True` 是 Python 的经典坑。不排除的话,前端传 `true` 会被存成数字 1。

`required=True` 时 `None` 报错;`required=False` 时 `None` 直接放行。

### 5.4 字段引用保护

删字段定义前先查有没有客户在用:

```python
def _is_field_referenced(db: Session, tenant_id: int, field_key: str) -> bool:
    """该 tenant 下是否有 customer 的 custom_fields 里带这个 key。"""
```

有引用 → 拒绝删除,提示"被 N 个客户使用"。

**为什么**:`custom_fields` 是 JSON,删了定义后那些值会变成孤儿数据 —— 显示不出来又删不掉。

**想删怎么办**:先把 `is_active` 设 `False`(软下线,不再出现在表单里),等数据清理完再物理删。

### 5.5 AI 智能建议

**输入**:客户画像 + 最近 5 条跟进历史(可配 `history_limit`)+ 可选的本次关注点。

**Prompt 结构**:

```python
SYSTEM_PROMPT = """你是一位销售顾问,擅长基于客户画像和跟进历史,推荐下次跟进的沟通话术和时间。

你的回复必须严格遵循 JSON 格式,不要包含任何其他文字或 markdown 标记:
{
  "suggested_message": "话术正文,200-300 字,自然不套路,贴合客户行业和当前阶段",
  "suggested_next_follow_up_at": "ISO 8601 datetime,推荐的下次跟进时间",
  "reasoning": "推荐依据,50-100 字,说明为什么这个时间和话术"
}
"""

USER_PROMPT = """# 客户档案
姓名: {name}
公司: {company_name} - {company_position}
等级: {level}
来源: {source}
标签: {tags}
自定义字段: {custom_fields}
备注: {remark}

# 最近跟进历史(最多 {history_limit} 条,时间倒序)
{follow_up_history}

# 本次关注点(可选)
{focus_line}
...
"""
```

**输出**:

| 字段 | 说明 |
|------|------|
| `suggested_message` | 话术正文,200~300 字 |
| `suggested_next_follow_up_at` | ISO 8601 时间 |
| `reasoning` | 推荐依据,50~100 字 |

**工程细节**:
- 同步返回,耗时 5~15 秒(前端要显示 loading)
- 走 `create_chat_model` + `LLMCallContext`,**自动登记到 `llm_call_logs`**
- `call_type = "customer.ai_suggest"` —— 可在 `/dashboard/logs/llm-calls` 按这个过滤,单独看 CRM 的模型开销
- 支持传 `model_config_id` 指定用哪个模型,不传则用默认

**采纳建议**:用户点「采纳」→ 创建跟进记录时 `ai_suggested=True`。
这个标记的价值:**后续可以统计 AI 建议的采纳率**,判断这个功能到底有没有用。

### 5.6 软删除 vs 物理删除

| 对象 | 删除方式 | 原因 |
|------|----------|------|
| 客户 | **软删除**(`is_active=False`) | 误删可恢复;跟进历史有审计价值 |
| 跟进记录 | **物理删除** | 记错了就是要删掉 |
| 字段定义 | 物理删除(有引用时拒绝) | 见 §5.4 |

客户软删后:
- 默认列表查不到(`is_active=True` 过滤)
- `POST /customers/{id}/restore` 可恢复
- 跟进记录不动(客户恢复后 timeline 还在)

### 5.7 待跟进列表

```
GET /customers/upcoming-follow-ups?days=7&owner_user_id=<me>
```

- 按 `next_follow_up_at` **升序**(最急的在最上面)
- **过期的也显示**,`days_until_due` 为负数
- 默认看未来 7 天

> 过期的不隐藏是有意设计 —— 隐藏等于鼓励拖延。负数天数在 UI 上标红,视觉上就是催办。

---

## 6. UI

### 6.1 客户列表

- 路径: `frontend/app/dashboard/customer/page.tsx`
- 表格列:姓名 / 公司 / 等级(Tag)/ 负责人 / 手机(脱敏)/ 上次跟进 / 下次跟进 / 操作
- 筛选栏:关键字 / 等级(多选)/ 来源(多选)/ 负责人 / 行业 / 标签
- 排序:创建时间 / 上次跟进 / 下次跟进 / 等级

### 6.2 客户详情

- 路径: `frontend/app/dashboard/customer/[id]/page.tsx`
- 左侧:档案信息(含自定义字段,按 `order_index` 排)
- 右侧:跟进 timeline(倒序)
- 顶部按钮:「新增跟进」/「AI 建议」/「编辑」/「删除」

### 6.3 字段配置

- 路径: `frontend/app/dashboard/customer/settings/page.tsx`
- 字段定义列表,可拖拽排序(改 `order_index`)
- 新增字段:key / label / 类型 / 选项 / 必填
- 删除时如有引用,弹提示

### 6.4 负责人选择器

- 组件: `OwnerUserSelect`
- **默认选中当前用户**(销售建客户 99% 是给自己建)
- 数据源: `GET /api/v1/users/assignable`(公共端点,返回简化的 `UserSimpleResponse`)

> 之前这里是个 `InputNumber` 让用户手填 user_id —— 典型的"后端字段直接暴露给前端"的反面教材。

---

## 7. 与其他模块的关系

### 7.1 与 LLM 调用日志
AI 建议走 `LLMCallContext`,自动落 `llm_call_logs`,`call_type="customer.ai_suggest"`。
详见 [LLM 调用日志](llm-call-logs.md)。

### 7.2 与用户管理
`owner_user_id` / `created_by` / 跟进的 `user_id` 都指向 `users`。
负责人下拉走 `/users/assignable`。

### 7.3 与多租户
全表 `tenant_id` 隔离,索引都以 `tenant_id` 打头。
自定义字段 schema **每租户一份** —— A 租户加的字段 B 租户看不到。

### 7.4 与 Agent(未打通)
当前客户数据**没有**自动喂给 Agent。
想让 AI 助手"知道"客户信息,需要手工做 —— 这是明确的升级方向。

---

## 8. 边界与不做

### 8.1 当前
- ✅ 客户档案 CRUD + 软删恢复
- ✅ 多维过滤 + 4 种排序
- ✅ 跟进 timeline + 聚合字段事务同步
- ✅ 6 种自定义字段 + 校验 + 引用保护
- ✅ 手机号脱敏
- ✅ AI 智能建议 + 采纳标记
- ✅ 待跟进列表

### 8.2 不做
- ❌ 商机 / 合同 / 回款(不是完整 CRM)
- ❌ 销售漏斗 / 阶段流转
- ❌ 客户去重 / 合并
- ❌ 导入导出(Excel)
- ❌ 客户公海 / 领取分配
- ❌ 数据权限细分(当前同租户内互相可见)
- ❌ 跟进提醒推送(有列表,没有主动通知)
- ❌ 客户数据自动注入 Agent 上下文

### 8.3 已知局限

| 局限 | 影响 | 缓解 |
|------|------|------|
| `custom_fields` 是 JSON | 不能建索引,复杂查询慢 | 高频过滤字段做成正式列 |
| 同租户内客户全可见 | 销售能看到同事的客户 | 前端默认按 `owner_user_id` 过滤 |
| AI 建议同步阻塞 5~15 秒 | 请求久,UX 需要 loading | 前端做好 loading + 超时提示 |
| 待跟进无主动提醒 | 靠用户主动看 | 接通知中心 |
| 聚合字段是冗余设计 | 直接改库会漂移 | 只通过 API 改跟进 |

---

## 9. 升级路径

### 短期
- 📋 跟进提醒接入 [通知中心](notification.md)
- 📋 Excel 导入 / 导出
- 📋 客户数据权限(只看自己 / 看下属 / 看全部)

### 中期
- 📋 客户去重合并
- 📋 客户公海 + 领取规则
- 📋 商机 / 阶段(轻量销售漏斗)
- 📋 客户信息注入 Agent 上下文(聊天时 AI 自动知道客户背景)

### 长期
- 📋 完整销售流程(合同 / 回款)
- 📋 AI 自动从聊天记录提取跟进要点
- 📋 客户健康度打分 / 流失预警

---

## 10. 排错

| 症状 | 原因 | 修法 |
|------|------|------|
| 待跟进列表空 | 跟进没填 `next_follow_up_at` | 补填 |
| 下次跟进时间不更新 | 直接改了库,没走 API | 只通过 API 改跟进 |
| 自定义字段值存不进去 | 类型校验失败 | 看 422 的具体字段错误 |
| `number` 字段传 true 报错 | 有意的:bool 被显式排除 | 传数字 |
| 字段删不掉 | 被客户引用 | 先 `is_active=False` 软下线 |
| AI 建议 500 | 默认模型 key 失效 | 见 [常见错误 §4.2](../troubleshooting/common-errors.md#42-默认模型-401--超时) |
| AI 建议返回不是 JSON | 模型没遵守格式 | 换更强的模型 / 加 few-shot |
| AI 建议很慢 | 同步 5~15 秒是正常的 | 前端加 loading |
| 手机号没脱敏 | 详情页本来就显示完整 | 列表页才脱敏 |
| 删了客户跟进还在 | 是软删,数据都在 | 用 restore 恢复 |
| 列表查询慢 | 按 `custom_fields` 过滤走不了索引 | 高频字段提成正式列 |

---

**相关文档**
- [用户与权限](auth-and-rbac.md)
- [LLM 调用日志](llm-call-logs.md)
- [通知中心](notification.md)
- [多租户隔离](../architecture/04-multi-tenant.md)

---

**维护者**:产品经理 + 全栈架构师
**最近更新**:2026-08-06
