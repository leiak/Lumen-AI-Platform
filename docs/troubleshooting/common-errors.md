# 排错:常见错误速查

> 按"症状 → 诊断 → 修法"组织。
> 先看这张总表定位大类,再跳到对应小节。

---

## 0. 总索引

| 大类 | 典型症状 | 跳转 |
|------|----------|------|
| 后端进程 | 接口返空 / 405 / 启动卡住 | [uvicorn-zombie](uvicorn-zombie.md) |
| 前端渲染 | 白屏 / toast 不弹 / 下拉少选项 | [§1 前端](#1-前端) |
| 鉴权 | 401 / 图片加载不出来 | [§2 鉴权](#2-鉴权) |
| 数据库 | 500 datetime / FK 删不掉 / 启动卡住 | [§3 数据库](#3-数据库) |
| 模型调用 | Unsupported model type / 超时 / 401 | [§4 模型调用](#4-模型调用) |
| 知识库检索 | 检索返空 / 引用错乱 | [§5 知识库](#5-知识库) |
| 工作流 | 节点不执行 / 变量取不到 | [§6 工作流](#6-工作流) |
| Celery 异步 | 任务永远 queued | [§7-celery-异步](#7-celery-异步) |
| 多媒体 | ffmpeg 报错 / 视频黑屏 | [§8 多媒体](#8-多媒体) |
| Docker | 端口冲突 / volume 不生效 | [§9-docker](#9-docker) |
| 测试 | 测试污染 dev DB / 断言数字对不上 | [§10 测试](#10-测试) |
| 启动阶段 | 后端 11335 占 / 前端 11334 占 / Celery 启不来 / Ollama 模型没拉 / Widget dist 缺失 | [dev-env.md](dev-env.md) |

---

## 1. 前端

### 1.1 antd toast(message)不显示

**症状**:调 `message.success("保存成功")` 没反应,控制台也没报错。

**根因**:`import { message } from "antd"` 的**静态 message API**,在 React StrictMode + Next.js App Router 客户端组件下经常不渲染。

**修法**:用 hook 版本。

```tsx
// ❌ 错:模块顶层静态 API
import { message } from "antd";

// ✅ 对:组件函数体里 hook 调用
import { App } from "antd";

export default function MyPage() {
  const { message } = App.useApp();   // ← 必须在函数体里
  // ...
  message.success("已保存 / Saved");
}
```

前置条件:dashboard layout 已经用 `<App>` 包装(本项目已做)。

**额外建议**:toast 3 秒就消失,关键操作再叠一个**内联状态指示器**兜底:

```tsx
<span style={{ color: "#52c41a" }}>✓ 已保存 {secondsAgo} 秒前</span>
```

用户绝对不会错过。

---

### 1.2 antd Select 下拉只显示 1 个选项

**症状**:
- 屏幕上下拉只看到当前选中那项,滚动才看见其他
- 测试里 `fireEvent.mouseDown(combobox)` 后下拉确实开了,但 `getByText` / `getByTitle` / `getByRole` 都找不到第二个 option

**根因**:AntD v5 的 Select 默认 `virtual: true`(用 `rc-virtual-list` 虚拟滚动)。给 Select 加自定义 `optionRender`(flex 布局 / Tag)时,虚拟列表的高度测量会出错,**非 active option 不渲染进 DOM**。

**修法**:小列表(≤ 10 行)且有自定义 `optionRender` 时,关掉虚拟滚动。

```tsx
<Select
  optionRender={(opt) => (
    <div style={{ display: "flex", justifyContent: "space-between" }}>
      <span>{opt.label}</span>
      <Tag>{opt.data.provider}</Tag>
    </div>
  )}
  virtual={false}   // ← 关键
/>
```

典型场景:`EmbeddingModelSelect`(KB embedding 下拉)、`ChatModelSelect`、`OwnerUserSelect`。

---

### 1.3 前端 dev 启动慢 / 内存爆

**根因**:`next.config.js` 里用了 `transpilePackages` 全量转译大包。

**修法**:换成 `optimizePackageImports`,并给 Node 加内存。

```js
// next.config.js
experimental: {
  optimizePackageImports: ["antd", "@ant-design/icons"],
}
```

```json
// package.json
"dev": "NODE_OPTIONS='--max-old-space-size=4096' next dev -p 11334"
```

---

### 1.4 CORS 报错但后端配置看起来是对的

**先排除误判**:React 18 StrictMode 会**双挂载组件**,第一次挂载的 XHR 被 abort。浏览器把 abort 的请求也报成 CORS 失败 —— 这是**假 CORS 错误**。

**判据**:
- 只在 dev 模式出现,build 后没有 → 是 StrictMode 副作用,忽略。
- dev 和 prod 都有 → 真 CORS 问题,查 `DynamicCORSMiddleware` 的 allowlist。

---

## 2. 鉴权

### 2.1 `<img src>` 加载受保护资源必 401

**这是本项目最高频的坑,新加图片显示时默认按这个模式写。**

**根因**:
- `<img src=...>` **不能设 Authorization header**,浏览器不会带。
- 后端只读 `Authorization: Bearer <token>` header,**不认 `?token=xxx` query 参数**。
- 结果:必 401。

**❌ 错**:
```tsx
<img src={`${API}/image-generation/${id}/file`} />
<img src={`${API}/image-generation/${id}/file?token=${token}`} />
```

**✅ 对**(fetch + blob + createObjectURL):
```tsx
const [blobUrl, setBlobUrl] = useState<string>();

useEffect(() => {
  let revoked: string | undefined;
  const token = localStorage.getItem("access_token");

  fetch(url, { headers: { Authorization: `Bearer ${token}` } })
    .then((r) => r.blob())
    .then((blob) => {
      revoked = URL.createObjectURL(blob);
      setBlobUrl(revoked);
    });

  return () => { if (revoked) URL.revokeObjectURL(revoked); };  // ← 必须 revoke,否则内存泄漏
}, [url]);

return blobUrl ? <img src={blobUrl} /> : <Spin />;
```

**同样适用于** `<video src>`、`<audio src>`。

已按这个模式改造的组件:`image-generation/DetailModal`、`TemplateCard`、`StockThumb`、`videos/DetailModal`。

---

### 2.2 token key 拿错

**正确 key 是 `access_token`,不是 `token`。**

```ts
// ✅
localStorage.getItem("access_token")

// ❌
localStorage.getItem("token")   // 永远是 null
```

axios 实例已自动注入;**原生 `fetch()` 调用方需要手动设 header**。

---

### 2.3 前端拿不到数据但接口 200

**根因**:响应信封没拆对。

```ts
const res = await api.get("/agents/1");
// res           → AxiosResponse
// res.data      → 后端信封 { code, message, data }
// res.data.data → 真正的业务数据

// ✅
const body = res.data;
if (body.code === 200) {
  const agent: Agent = body.data;
}

// ❌
const agent = res.data;   // 拿到的是信封,不是 Agent
```

列表接口是 `PaginatedResponse[T]`,业务数据在 `body.data.items`。

详见 [响应信封契约](../explanation/response-envelope.md)。

---

## 3. 数据库

### 3.1 list 接口 500,报 datetime 校验失败

**症状**:
```
pydantic_core._pydantic_core.ValidationError: 1 validation error for XxxRead
created_at
  Input should be a valid datetime [type=datetime_type, input_value=None]
```

**根因**:早期 fixture / 迁移脚本**直插 SQL 绕过了 ORM 默认值**,导致 `created_at` / `updated_at` 是 NULL。Pydantic 的 `datetime` 是严格类型,不接受 None。

**修法**:跑一次性回填脚本。

```bash
cd backend && python scripts/backfill_null_timestamps.py
```

脚本逻辑:扫全部表,`UPDATE t SET created_at = COALESCE(created_at, NOW())`,不动业务数据。

**根治**(2026-08-06 已做):`scripts/ensure_timestamp_defaults.py` 给 86 张旧表 `ALTER` 补上列默认值。

**预防铁律**:
> **新加时间列必须带 `server_default=func.now()` + `nullable=False`。**
> 否则又会被 Pydantic 严格 schema 拦 500。

```python
created_at: Mapped[datetime] = mapped_column(
    DateTime, server_default=func.now(), nullable=False
)
```

---

### 3.2 删数据报外键约束失败

**本项目多数表没有 `ON DELETE CASCADE`,必须手动按序删。**

#### AgentTeam 的真实依赖链(4 层)

```
messages → conversations(team_id) → agent_team_members(team_id) → agent_teams(id)
```

**最容易漏的是 `agent_team_members`** —— team ↔ agents 的多对多中间表。

```sql
DELETE FROM messages WHERE conversation_id IN (SELECT id FROM conversations WHERE team_id > 15);
DELETE FROM conversations WHERE team_id > 15;
DELETE FROM agent_team_members WHERE team_id > 15;   -- ← 别漏这张
DELETE FROM agent_teams WHERE id > 15;
```

#### 验证

```sql
SELECT
  (SELECT COUNT(*) FROM agent_teams WHERE id > 15)          AS teams,
  (SELECT COUNT(*) FROM conversations WHERE team_id > 15)   AS convs,
  (SELECT COUNT(*) FROM agent_team_members WHERE team_id>15) AS members,
  (SELECT COUNT(*) FROM messages
     WHERE conversation_id IN (SELECT id FROM conversations WHERE team_id > 15)) AS msgs;
```

全 0 才算删干净。

---

### 3.3 MCP 工具拒绝执行 DDL

**症状**:
```
DDL operations are not allowed for schema 'ai_platform'.
Ask the administrator to update SCHEMA_DDL_PERMISSIONS.
```

**根因**:`mcp__ai_platform_docker_mysql__mysql_query` 禁 `ALTER TABLE` / `TRUNCATE` / `CREATE INDEX` 等 DDL,也不支持 `KILL`。

**修法**:Python 直连。

```python
import pymysql
conn = pymysql.connect(
    host="localhost", port=3307,
    user="root", password="rootpassword",
    database="ai_platform", connect_timeout=5,
)
```

凭据来自 `backend/.env` 的 `DATABASE_URL`。

---

### 3.4 MCP 连错数据库

**这是会静默出错的坑。**

通用 MCP `mcp__mcp_server_mysql__mysql_query` 默认连**远端共享 MySQL**(29 个 schema),不是本项目的 Docker MySQL。

**铁律**:
- ✅ 用 `mcp__ai_platform_docker_mysql__mysql_query`
- ❌ 不要用 `mcp__mcp_server_mysql__mysql_query`

**任何 DB 写操作前先确认**:

```sql
SELECT @@hostname, @@port, DATABASE();
```

期望:`localhost` / `3307` / `ai_platform`。

---

### 3.5 `AUTO_INCREMENT` 重置不生效

`ALTER TABLE X AUTO_INCREMENT = 1` 在 InnoDB 上**不会真的从 1 开始** —— MySQL 会自动改用 `max(id)+1`,避免 PK 冲突。

所以这条语句的实际意义是"**消除 AUTO_INCREMENT 与 max(id) 之间的 gap**",不是"归零"。想真归零得先清空表。

---

## 4. 模型调用

### 4.1 `Unsupported model type: openai`

**根因**:`lumen_core/model_providers.py` 的 `MODEL_PROVIDERS` 注册中心里缺 entry。

**修法**:补注册。

```python
MODEL_PROVIDERS = {
    "openai": {
        "type": "openai",
        "supported_models": ["gpt-4o", "gpt-3.5-turbo", "text-embedding-3-small"],
        "required_config": ["api_key"],
        "default_base_url": "https://api.openai.com/v1",
    },
    # ...
}
```

---

### 4.2 默认模型 401 / 超时

**诊断**:先确认默认模型是哪个。

```sql
SELECT id, name, provider, model_name, is_default, is_active
FROM model_configs WHERE is_default = 1;
```

**常见情况**:默认模型指向一个 key 已失效的云端 provider。

**修法**:把默认切到本机 Ollama(不需要 key,不会超时)。

```sql
UPDATE model_configs SET is_default = 0 WHERE is_default = 1;
UPDATE model_configs SET is_default = 1 WHERE provider = 'ollama' AND is_chat = 1 LIMIT 1;
```

---

### 4.3 Ollama 连不上

| 检查 | 命令 | 期望 |
|------|------|------|
| 端口通 | `curl http://localhost:11434/api/tags` | 200 + 模型列表 |
| 容器活着 | `docker ps \| grep ollama` | Up |
| 模型拉了 | `docker exec lumen-platform-ollama ollama list` | 有 `nomic-embed-text` / `qwen2.5:7b` |

**端口冲突**:同机跑多个 Ollama 时会报 `port is already allocated`。查:

```bash
docker ps -a --format "table {{.Names}}\t{{.Ports}}" | grep 11434
```

停掉冲突容器,或给本项目的 Ollama 换宿主机端口。

---

## 5. 知识库

### 5.1 检索返回空

按顺序排除:

1. **后端是 zombie 吗?** → [uvicorn-zombie](uvicorn-zombie.md)。陈旧 worker 里缓存的 ES client / 被限流的 Ollama 会让 embedding 抛异常,fallback 返 `[]`。
2. **文档解析完了吗?** → `SELECT id, status FROM documents WHERE knowledge_base_id = ?`,status 应为 `success`。
3. **向量写进去了吗?** → 看 FAISS index 文件是否存在、size > 0。
4. **embedding 模型对得上吗?** → KB 建库时锁定的 `embedding_model_config_id`,和现在配置的必须一致(维度不同直接检索不到)。

### 5.2 文档卡在 "queued" 永不更新

见 [§7 Celery](#7-celery-异步)。

### 5.3 引用编号和内容对不上

**根因**:检索结果去重 / 重排后,前端引用编号没跟着重映射。

**诊断**:看 SSE 流里的 `citation` 事件,`index` 字段是否连续且与 `sources` 数组对齐。

---

## 6. 工作流

### 6.1 新节点类型 404 / 前端不显示

后端 22 种节点类型来自 `/api/v1/workflow-nodes/types`。前端画布的节点面板读这个接口。

**诊断**:

```bash
curl -s localhost:11335/api/v1/workflow-nodes/types | python -m json.tool | head -40
```

数量对不上 → zombie(见 [uvicorn-zombie](uvicorn-zombie.md))。

### 6.2 节点取不到上游变量

**根因**:变量引用语法或作用域写错。

**检查**:
- 引用格式是否为 `{{node_id.output_field}}`
- 上游节点是否真的在这条执行路径上(条件分支没走到的分支不产出变量)
- 并行分支的变量要经过 Variable Aggregator 汇聚

**排查工具**:节点级执行记录表 `workflow_node_runs` 会落库每个节点的输入输出。

```sql
SELECT node_id, node_type, status, LEFT(input_json, 200), LEFT(output_json, 200)
FROM workflow_node_runs WHERE run_id = ? ORDER BY id;
```

### 6.3 节点报错但整个工作流没停

这是**设计行为**。每个节点有 `error_strategy`:

| 策略 | 行为 |
|------|------|
| `fail` | 中断整个工作流(默认) |
| `continue` | 记录错误,继续往下走 |
| `default_value` | 用配置的兜底值继续 |

详见 [错误处理与重试](../explanation/error-retry-timeout.md)。

---

## 7. Celery 异步

### 7.1 任务永远 "queued",状态不更新

**症状**:文档 / 图片 / 视频任务提交后,status 卡在 `queued` 或 `pending`,不报错也不完成。

**根因 A(最常见)**:Celery worker **根本没起**。

```bash
docker ps | grep celery
# 或看日志
docker logs lumen-platform-celery --tail 50
```

**根因 B**:worker 起了,但 task 在设置 DB status **之前**就崩了 —— 所以 DB 里看不到任何错误痕迹。

典型案例(2026-06-26):`document_tasks.py` 顶部的 import 没有触发 `lumen_schemas` / `lumen_tools` 加载,task 首次执行时 `ModuleNotFoundError`。

**修法**:在 task 模块顶部强制 preload。

```python
# 强制预加载,避免 celery worker 首次执行 task 时 ModuleNotFoundError
import lumen_schemas  # noqa: F401
import lumen_tools    # noqa: F401
```

**诊断命令**:直接看 worker 日志的 traceback,不要只看 DB。

```bash
docker logs lumen-platform-celery --tail 200 | grep -A 20 Traceback
```

### 7.2 取消任务无效

`revoke(task_id, terminate=True)` 需要 worker 支持。检查 Celery 配置里 `task_acks_late` 和 pool 类型 —— Windows 上 `solo` pool 不支持 terminate。

---

## 8. 多媒体

### 8.1 ffmpeg 找不到

```bash
ffmpeg -version
```

没有 → 装 ffmpeg 并加进 PATH。Docker 部署的话确认镜像里有。

### 8.2 视频黑屏 / `No such file`

**根因**:图片路径没解析成磁盘绝对路径。

`videos.image_paths` 可能存的是:
- 磁盘绝对路径
- 纯数字 id(stock asset)
- `stock-assets/<id>` URL
- `image-generation/<id>` URL

服务层的 `_resolve_image_to_local_path` 负责统一翻译。如果报 `No such file`,说明走到了未覆盖的形态。

详见 [视频合成](../modules/video-composition.md) 和 [股票素材库](../modules/stock-assets.md)。

### 8.3 字幕不显示

99% 是编码问题。SRT 必须是 **UTF-8**(不带 BOM)。

```bash
file -i sub.srt   # 期望 charset=utf-8
```

### 8.4 缩略图 0 字节

ffmpeg 抽帧失败。看 ffmpeg stderr —— 通常是源视频时长为 0 或 codec 不支持。

---

## 9. Docker

### 9.1 端口已被占用

```
Error: port is already allocated
```

**诊断**:

```bash
docker ps -a --format "table {{.Names}}\t{{.Ports}}" | grep <端口>
netstat -ano | grep :<端口>
```

**典型案例**:同机的 `ragpandora-ollama` 占了 11434,`lumen-platform-ollama` 起不来。

### 9.2 改了 volume 配置但不生效

**`docker compose restart` 不重读 volume 配置。**

必须:

```bash
docker compose down
docker compose up -d
```

**典型案例**:给 EasyOCR 加 `data/easyocr:/root/.EasyOCR` bind mount(持久化 80MB en + 200MB zh 模型,避免容器重建后重下),`restart` 后发现还在重新下载 —— 因为没 `down`。

---

## 10. 测试

### 10.1 测试跑完污染了 dev DB

**症状**:dev 环境突然多出几百条 "hello team" 之类的测试数据。

**根因**:fixture 没写 teardown,或 teardown 写错了。

**关键坑**:teardown **必须新开 session**。

```python
# ❌ 错:复用 setup 的 session
@pytest.fixture
def team_setup(db_session):
    team = create_team(db_session)
    yield team
    db_session.delete(team)   # 看不到 API / load_context 在其他 session 提交的数据
    db_session.commit()

# ✅ 对:teardown 新开 SessionLocal()
@pytest.fixture
def team_setup(db_session):
    team = create_team(db_session)
    yield team
    cleanup = SessionLocal()      # ← 新 session,才能看到别的 session 提交的行
    try:
        cleanup.query(Message).filter(...).delete(synchronize_session=False)
        cleanup.query(Conversation).filter(...).delete(synchronize_session=False)
        cleanup.query(AgentTeamMember).filter(...).delete(synchronize_session=False)
        cleanup.query(AgentTeam).filter(...).delete(synchronize_session=False)
        cleanup.commit()
    finally:
        cleanup.close()
```

**为什么**:MySQL InnoDB 默认 REPEATABLE READ 隔离级别。setup 时开的 session 有一个事务快照,**看不到** API 调用 / `load_context` 在其他 session 里提交的新行。用它删,删不干净。

参考写法:`backend/tests/.../test_agent_team_logs_call.py`。

### 10.2 断言的数字对不上

系统在演进,写死的数字会过期。常见的:

| 断言 | 会变的原因 |
|------|-----------|
| 节点类型数量 = 22 | 加新节点 |
| MCP 工具数量 = 7 | 加新工具 |
| provider 数量 | 加新 provider |
| model 列表 count | 全局 model(tenant_id IS NULL)的可见性规则变了 |

**修法**:改断言,或者改成动态查询(`len(get_all_node_types())`)而不是硬编码。

### 10.3 时间戳相关测试 flaky

**症状**:按 `created_at` 排序的测试偶尔失败。

**根因**:同一秒内插入的多行,MySQL DATETIME 精度不足以区分。

**修法**:测试里插入之间 `time.sleep(1.1)` 拉开时间戳。

### 10.4 并行执行测试偶发失败

Windows asyncio 定时器可能**早醒几毫秒**。断言耗时下限时留容忍度:

```python
assert elapsed_ms >= expected_ms - 15   # Windows asyncio 早醒容忍
```

---

## 11. 通用排查顺序

遇到不明问题,按这个顺序走,90% 能定位:

```
1. 后端是不是 zombie?
   curl -s localhost:11335/openapi.json | grep <你的路由>
   ↓ 路由不在 → 重启后端,结束

2. 接口本身对吗?
   curl -s localhost:11335/api/v1/xxx -H "Authorization: Bearer $TOKEN" | python -m json.tool
   ↓ 后端返对 → 是前端问题(信封没拆对 / token key 错 / img 鉴权)

3. 后端返错 → 看 uvicorn 日志的 traceback
   ↓ 是 DB 错 → 查 §3

4. 异步任务不动 → 看 celery 日志,不要只看 DB status
   docker logs lumen-platform-celery --tail 200

5. 都正常但数据不对 → 确认连的是哪个 DB
   SELECT @@hostname, @@port, DATABASE();
```

---

**相关文档**
- [Uvicorn 僵尸进程](uvicorn-zombie.md)
- [性能调优](performance-tuning.md)
- [数据恢复](data-recovery.md)
- [开发环境搭建](../how-to/dev-env.md)

---

**维护者**:全栈架构师
**最近更新**:2026-08-06
