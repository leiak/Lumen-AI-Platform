# How-to:常见问答(FAQ)

> 一线工程师踩过的坑 + 用户的疑问。
> 找不到答案再问 mentor。

---

## 1. 启动相关

### Q: 启动后端卡 `Waiting for application startup.`

**A**: MySQL MDL 阻塞。被孤儿连接占用 metadata lock。最常见的根因:`taskkill /F` 强杀过 uvicorn,SQLAlchemy 连接池没关 → 旧连接在 MySQL 那边 `Sleep` 但持 MDL。

**修法**:
```python
import pymysql
conn = pymysql.connect(host='localhost', port=3307, user='root', password='rootpassword', database='ai_platform', connect_timeout=5)
cur = conn.cursor()
cur.execute('KILL <processlist_id>')
conn.close()
```

详见 [uvicorn-zombie §6](../troubleshooting/uvicorn-zombie.md#6-连带坑强杀留下-mysql-mdl-孤儿连接)。

### Q: 端口 11335 被占

**A**:
```bash
# Windows
netstat -ano | grep :11335
taskkill /PID <pid> /F

# Linux
lsof -i :11335
kill -9 <pid>
```

**不要**改端口 — 项目硬编码 11335。真要用 fallback,起 11336,前端改 API URL。

### Q: 前端启动失败 / `npm install` 慢

**A**:
```bash
# 切镜像
npm config set registry https://registry.npmmirror.com

# 清缓存
rm -rf node_modules/.cache
npm install
```

### Q: Ollama 模型没下载

**A**:
```bash
docker exec lumen-platform-ollama ollama pull nomic-embed-text
docker exec lumen-platform-ollama ollama pull qwen2.5:7b
```

**首次下载**:
- nomic-embed-text: 274 MB
- qwen2.5:7b: 4.7 GB

---

## 2. 数据库相关

### Q: 可以用 `mcp__mcp_server_mysql__mysql_query` 吗?

**A**: **不要**。用 `mcp__ai_platform_docker_mysql__mysql_query`(项目专用)。

**根因**:通用 MCP 默认连的是远端共享 MySQL,有 29 个 schema;项目 dev 用本地 Docker MySQL `localhost:3307/ai_platform`。连错了 DELETE 会误伤别的项目。

### Q: MCP 拒绝 DDL

**A**: `mcp__ai_platform_docker_mysql__mysql_query` 限制 `ALTER TABLE` / `TRUNCATE` / `CREATE INDEX` 等 DDL。

**修法**:Python pymysql 直连:
```python
import pymysql
conn = pymysql.connect(host='localhost', port=3307, user='root',
                      password='rootpassword', database='ai_platform')
cur = conn.cursor()
cur.execute("ALTER TABLE ...")
conn.commit()
```

### Q: list API 返 `ValidationError: created_at` → 500

**A**: 早期 fixture 直插 SQL 跳过了 ORM 默认值,导致空 `created_at`。

**修法**:
```bash
cd backend && python scripts/backfill_null_timestamps.py
```

详见 [data-recovery.md §3.1](../troubleshooting/data-recovery.md#31-null-时间戳导致-list-api-500)。

### Q: dev DB 怎么清理?

**A**: 永远先备份,再按 FK 顺序删。

```bash
# 1. 备份
docker exec lumen-platform-mysql mysqldump -uroot -prootpassword --single-transaction ai_platform > backup.sql

# 2. 数
SELECT COUNT(*) FROM conversations WHERE id > 100;

# 3. 删(按 FK 顺序)
DELETE FROM messages WHERE conversation_id IN (SELECT id FROM conversations WHERE id > 100);
DELETE FROM conversations WHERE id > 100;
DELETE FROM conversations WHERE team_id > 100;
DELETE FROM agent_teams WHERE id > 100;
```

详细 [data-recovery.md §4](../troubleshooting/data-recovery.md#4-批量清理)。

### Q: NULL 时间戳是不是 bug?

**A**: 是早期 dev 流程的缺陷。**新加列必须带 `server_default=func.now() + nullable=False`**,否则又会被 Pydantic datetime 严格 schema 拦 500。

详见 [data-recovery.md §3.1](../troubleshooting/data-recovery.md#31-null-时间戳导致-list-api-500)。

---

## 3. 鉴权相关

### Q: 拿不到 JWT / 401

**A**:
```ts
const token = localStorage.getItem("access_token")  // ← "access_token", 不是 "token"
```

**后端**:
```python
from lumen_api.v1.auth import get_current_user
```

### Q: Token 怎么改 TTL?

**A**: `backend/.env` 改 `ACCESS_TOKEN_EXPIRE_MINUTES=30`。

### Q: External Token 是什么?

**A**: Widget 嵌入式聊天用的,**独立** 与内部 JWT。`ass="external-app"`,独立 secret `EXTERNAL_JWT_SECRET`。

---

## 4. 前端相关

### Q: `antd message()` 不显示

**A**: 不要用 `import { message } from "antd"` 的静态 API。在 React strict mode + Next.js App Router 客户端组件下经常不渲染。

**修法**:
```tsx
import { App } from "antd";

export default function MyComponent() {
  const { message } = App.useApp();  // ← hook,在组件里
  return <button onClick={() => message.success("已保存")}>...</button>
}
```

### Q: `<img src=...>` 加载受保护资源 401

**A**: 浏览器 `<img>` 不能加 Authorization header。

**修法**:
```ts
const res = await fetch(url, {
  headers: { Authorization: `Bearer ${token}` }
})
const blob = await res.blob()
const blobUrl = URL.createObjectURL(blob)
// <img src={blobUrl} />
// unmount 时 URL.revokeObjectURL(blobUrl)
```

### Q: TypeScript 报类型错

**A**:
```bash
# 跑 tsc
cd frontend && npx tsc --noEmit

# 自动 fix
npx tsc --noEmit --fix
```

### Q: vitest 找不到 antd Select 的下拉选项

**A**: AntD v5 默认 `virtual: true`,小列表 + 自定义 `optionRender` 出 bug。

**修法**:
```tsx
<Select virtual={false} optionRender={...} />
```

### Q: 端口 11334 启动慢

**A**:
```json
// package.json
"dev": "NODE_OPTIONS='--max-old-space-size=4096' next dev -p 11334"
```

加 `transpilePackages` → `optimizePackageImports`:
```js
experimental: {
  optimizePackageImports: ["antd", "@ant-design/icons"],
}
```

---

## 5. 后端相关

### Q: 怎么在 service 里共享 Session?

**A**: 用 `Depends(get_db)`。

```python
@router.get("/foo")
def foo(db: Session = Depends(get_db)):
    ...
```

**不要** 自己 `SessionLocal()` — 容易漏 `close()`。

### Q: FastAPI 启动时跑什么?

**A**: `lumen_core/database.py::ensure_*` 函数,幂等地建表 / 加列 / 加索引。

### Q: 反向代理 / Nginx 怎么部署?

**A**: [deploy.md](deploy.md) §4。

### Q: 怎么跑单个测试?

**A**:
```bash
cd backend && pytest tests/unit/test_agent.py::test_create_agent -v
```

### Q: mypy 报错但代码看着对

**A**: 看错的位置,大多是 `Optional` / `None` 处理。先 `type: ignore` 临时绕,后续补真类型。

**禁止** 用 `# type: ignore` 全部跳过 — review 时会被打回。

---

## 6. LLM / Embedding 相关

### Q: 怎么换 embedding 模型?

**A**: `/dashboard/system/models` → Ollama 导入 或 手动添加。

切换后**所有 KB 的 FAISS 索引要重建**:
```bash
python backend/scripts/reindex_all_kbs.py
```

### Q: LLM 调用慢

**A**: 1. 看 `llm_call_logs` 找哪步慢;2. 换模型;3. 减小 prompt;4. 预热 Ollama:

```bash
curl http://localhost:11434/api/generate \
  -d '{"model":"qwen2.5:7b","prompt":"hi","stream":false}'
```

### Q: 检索 0 结果

**A**:
1. KB 状态是 `ready`?
2. 文档处理成功?
3. Embedding 模型 vs 索引模型一致?
4. 改用 `search_weights` 调参

### Q: 怎么知道 LLM 实际收到什么?

**A**: `llm_call_logs`:
```sql
SELECT call_id, call_type, model_name, messages, response_content
FROM llm_call_logs ORDER BY created_at DESC LIMIT 10;
```

GET `/api/v1/logs/llm-calls/{call_id}` 详情。

### Q: trace_id 怎么串联?

**A**: 一次请求里所有调用共享 `trace_id`。看全链路:
```bash
GET /api/v1/logs/llm-calls/trace/{trace_id}
```

---

## 7. 工作流相关

### Q: 工作流节点运行慢

**A**:
1. `/dashboard/workflows/{id}/runs/{rid}` 看每个节点耗时
2. LLM 节点超时 → 选小模型
3. HTTP 节点超时 → 改 timeout
4. 没用 Parallel → 改

### Q: 怎么调试?

**A**: 单个节点可以测:
```python
node = MyNode(config={...})
result = await node.invoke(state, config)
```

或在前端 `/dashboard/workflows/{id}/runs/{rid}` 看每节点 outputs。

### Q: 怎么重跑?

**A**: `POST /api/v1/workflows/{id}/runs/{rid}/resume`(从断点续跑)。

### Q: 22 节点不够用

**A**: 自己加。详见 [add-new-workflow-node.md](add-new-workflow-node.md)。

---

## 8. 性能相关

### Q: list API 慢

**A**:
1. 看 SQL 是否走了索引
2. 用 `EXPLAIN` 看
3. N+1 → `selectinload`
4. 深分页 → 改游标

### Q: dev 服务器卡

**A**:
- 检查 dev DB session 数
- 看 MongoDB / Redis 是不是满了
- ES 堆内存

### Q: 内存爆

**A**:
- 加大 Node 内存:`NODE_OPTIONS='--max-old-space-size=4096'`
- 杀僵尸进程

### Q: 多实例部署

**A**: 注意:
- 进程内限流 → 多实例失效(升级 Redis)
- 进程内 WS 连接表 → 多实例推送失效(升级 Redis pub/sub)
- Celery beat 必须**单实例**

详见 [deploy.md §8](deploy.md#8-横向扩容)。

---

## 9. 部署相关

### Q: 怎么部署?

**A**: [deploy.md](deploy.md)。

### Q: 怎么备份?

**A**:
```bash
docker exec lumen-platform-mysql mysqldump -uroot -prootpassword --single-transaction --routines --triggers ai_platform > backup_$(date +%Y%m%d).sql
```

加到 crontab。

### Q: 怎么恢复?

**A**:
```bash
docker exec -i lumen-platform-mysql mysql -uroot -prootpassword ai_platform < backup.sql
```

详情 [data-recovery.md §2](../troubleshooting/data-recovery.md#2-恢复)。

---

## 10. 业务相关

### Q: 怎么加新 widget 接入方?

**A**:
1. `/dashboard/settings/external-apps` → 创建
2. 拿到 `app_key` + `app_secret`
3. 配置 `allowed_origins` (域名白名单)
4. 配置 `allowed_agent_ids` / `allowed_team_ids`
5. 给接入方 script 嵌入

### Q: 公众号发布失败

**A**:
- 看 `wx_publish_records.error_message`
- 43004 / 45009 频率 / 数量超限
- app_secret 解密失败 → 检查 Fernet key

### Q: 智能问数 SELECT 慢

**A**:
- 数据源只读账号权限最小化
- 加 WHERE 时间范围
- 网络往返时间

### Q: 客户 CRM 字段怎么加自定义?

**A**: `customer_field_definitions` 表,前端 `/dashboard/customers` 加。

6 种类型:text / number / date / select / multiselect / textarea。

---

## 11. 杂项

### Q: 注释该用英文还是中文?

**A**: 见 [CLAUDE.md §9](../../CLAUDE.md#9-沟通风格--注释语言):
- 标识符(变量名 / 类名 / 函数名)英文
- docstring 英文 1 行 + 中文详细
- 行内 `//` / `#` 中文为主

### Q: commit message 怎么写?

**A**: `feat(scope):` / `fix(scope):` / `docs:` scope 可选。一个 commit 做一件事。

### Q: 怎么 PR?

**A**: 用 `gh` CLI:
```bash
gh pr create --title "feat(workflow): 中文标题" --body "..."
```

### Q: 怎么 sync dev DB?

**A**:
```bash
docker exec lumen-platform-mysql mysqldump -uroot -prootpassword --single-transaction ai_platform > backup.sql
```

再粘贴到目标 DB。

### Q: 怎么跑 seed 脚本?

**A**:
```bash
cd backend
python lumen_scripts/seed_playbooks.py
python lumen_scripts/seed_stock_assets.py
python lumen_scripts/seed_mcp_demo.py
```

有问题的自己写覆盖 — insert ignore 就好。

### Q: 怎么找 mentor?

**A**: 找任意一个写过该模块的人,或者 GitHub issue 里 @ mention。

---

## 12. 升级路径

更多:[roadmap.md](../requirements/04-roadmap-milestones.md) 未来规划。

---

**相关文档**
- [排错速查](../troubleshooting/common-errors.md)
- [排错:性能调优](../troubleshooting/performance-tuning.md)
- [项目铁律](../../CLAUDE.md)
- [架构总览](../architecture/00-overview.md)

**维护者**:全栈架构师
**最近更新**:2026-08-06
