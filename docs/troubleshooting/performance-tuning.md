# 排错:性能调优

> 哪里慢、怎么量、怎么改。
> 按"用户可感知的慢"从上到下排。

---

## 1. 性能基线

先知道"正常"是什么样,才知道什么算慢。

| 场景 | 正常耗时 | 慢的信号 |
|------|----------|----------|
| 首字延迟(chat 流式) | 0.5~2 秒 | > 5 秒 |
| 单轮完整回答(无检索) | 2~8 秒 | > 20 秒 |
| 单轮完整回答(带 RAG) | 3~12 秒 | > 30 秒 |
| KB 检索(top 5) | 100~400 ms | > 2 秒 |
| 文档解析(10 页 PDF) | 5~30 秒 | > 2 分钟 |
| 文档向量化(100 chunk) | 10~40 秒 | > 3 分钟 |
| 工作流执行(10 节点) | 5~30 秒 | > 2 分钟 |
| 图片生成(Stability) | 5~15 秒 | > 60 秒 |
| TTS(500 字) | 3~10 秒 | > 30 秒 |
| 视频合成(1 分钟成片) | 30~60 秒 | > 5 分钟 |
| list API(分页 20 条) | 30~150 ms | > 1 秒 |

---

## 2. 先量再改

### 2.1 后端已有的观测手段

**LLM 调用日志**(`llm_call_logs` 表)记录了每次模型调用的耗时和 token:

```sql
SELECT
  model_name,
  COUNT(*)              AS calls,
  AVG(duration_ms)      AS avg_ms,
  MAX(duration_ms)      AS max_ms,
  AVG(total_tokens)     AS avg_tokens
FROM llm_call_logs
WHERE created_at > NOW() - INTERVAL 1 DAY
GROUP BY model_name
ORDER BY avg_ms DESC;
```

**embedding 调用日志**(`embedding_call_logs`)同理。

**工作流节点级耗时**(`workflow_node_runs`):

```sql
SELECT node_type,
       COUNT(*) AS runs,
       AVG(duration_ms) AS avg_ms,
       MAX(duration_ms) AS max_ms
FROM workflow_node_runs
WHERE created_at > NOW() - INTERVAL 1 DAY
GROUP BY node_type
ORDER BY avg_ms DESC;
```

**trace_id 串联**:一次请求的所有 LLM / embedding / 节点调用共享一个 `trace_id`,按它查能拉出完整链路。

详见 [可观测性](../explanation/observability.md)。

### 2.2 前端

Chrome DevTools → Network 面板,重点看:
- **TTFB**(首字节)→ 后端慢
- **Content Download** 很长 → 响应体太大(分页没生效?)
- 大量重复请求 → useEffect 依赖数组写错

### 2.3 数据库

```sql
-- 慢查询(需要先开 slow_query_log)
SHOW VARIABLES LIKE 'slow_query%';

-- 当前正在跑的长查询
SELECT id, user, db, command, time, state, LEFT(info, 300)
FROM information_schema.processlist
WHERE command != 'Sleep' AND time > 2
ORDER BY time DESC;
```

---

## 3. 对话慢

### 3.1 首字延迟高

**排查顺序**:

| 怀疑点 | 怎么验 | 修法 |
|--------|--------|------|
| 模型本身慢 | 直接 curl provider,看裸调用耗时 | 换模型 / 换 provider |
| 检索前置太久 | 看 `embedding_call_logs` 的 duration | 见 §4 |
| 记忆注入太多 | 看注入后的 prompt token 数 | 调小 `memory_window_size` |
| 技能注入太多 | prompt 里技能描述占了几千 token | 减少绑定的技能数 |
| 工具定义太多 | 每个工具的 JSON schema 都进 prompt | 精简工具绑定 |

**Ollama 特有**:第一次调用某模型要**加载权重到显存**,可能 10~30 秒。之后就快了。

```bash
# 预热
curl http://localhost:11434/api/generate -d '{"model":"qwen2.5:7b","prompt":"hi","stream":false}'
```

保持模型常驻:

```bash
curl http://localhost:11434/api/generate -d '{"model":"qwen2.5:7b","keep_alive":"24h"}'
```

### 3.2 流式输出卡顿

**检查**:
- SSE 是不是被中间代理缓冲了 → nginx 要设 `proxy_buffering off`
- 后端有没有 `await` 让出事件循环 → 同步阻塞会卡住整个 worker

### 3.3 多轮后越来越慢

**根因**:上下文线性增长,每轮 prompt 越来越长。

**修法**:改记忆策略。

| 策略 | 适合 | token 表现 |
|------|------|-----------|
| `sliding_window` | 客服短对话 | 恒定 |
| `token_limit` | 中等长度 | 有上限 |
| `semantic_compression` | 长期对话 | 恒定但多一次 LLM 摘要调用 |

详见 [记忆系统](../modules/memory.md)。

---

## 4. 检索慢

### 4.1 embedding 耗时高

**本机 Ollama**:
- `nomic-embed-text` 单条 ~20~50 ms
- 批量比逐条快得多 —— 确认走的是 batch 接口

**云端 provider**:主要是网络往返。批量 + 并发。

### 4.2 向量检索耗时高

| 因素 | 影响 | 优化 |
|------|------|------|
| FAISS index 类型 | Flat 是精确但 O(n) | 数据量大时换 IVF / HNSW |
| top_k 太大 | 线性影响 | 检索 top 20,重排后取 5 |
| KB chunk 数量 | 线性影响 | 分库,别一个 KB 塞 10 万 chunk |

### 4.3 混合检索慢

BM25(ES)+ 向量是**并行**发的。如果串行了,耗时会翻倍。

**检查**:两路检索应该用 `asyncio.gather` 并发。

**ES 侧**:
```bash
curl -s "localhost:9200/_cat/indices?v"          # 看索引大小
curl -s "localhost:9200/_nodes/stats/jvm?pretty" # 看堆内存压力
```

ES 堆吃紧 → 加内存或减索引。

### 4.4 检索权重配置

KB 有 `search_weights` 配置(向量 / BM25 / 标题 / 时效 4 个滑块)。权重本身不影响性能,但**如果某一路权重为 0,可以跳过这一路的查询** —— 这是有效的优化。

---

## 5. 文档处理慢

### 5.1 解析阶段

| 文件类型 | 解析器 | 相对速度 |
|----------|--------|----------|
| txt / md | 直接读 | 极快 |
| docx | python-docx | 快 |
| pdf(文字版) | Docling | 中 |
| pdf(扫描版) | Docling + OCR | **很慢** |
| 图片 | EasyOCR | 慢 |

**OCR 是大头**。第一次跑还要下模型(en 80MB + zh 200MB)。

**优化**:
- `data/easyocr:/root/.EasyOCR` bind mount 持久化模型,避免容器重建后重下(改完必须 `docker compose down && up -d`,`restart` 不重读 volume)
- 能不 OCR 就不 OCR —— 文字版 PDF 别走 OCR 分支

### 5.2 分块 + 向量化

- chunk 太小 → chunk 数量爆炸 → embedding 调用次数爆炸
- chunk 太大 → 检索精度下降

**经验值**:500~1000 字符,overlap 10~20%。

### 5.3 并发度

Celery worker 数量决定并行处理多少文档。

```yaml
# docker-compose.yml
command: celery -A lumen_tasks worker --concurrency=4
```

concurrency 不是越大越好 —— 受限于 Ollama 的并发能力和显存。

---

## 6. 工作流慢

### 6.1 找出慢节点

```sql
SELECT node_id, node_type, duration_ms
FROM workflow_node_runs
WHERE run_id = ?
ORDER BY duration_ms DESC
LIMIT 10;
```

### 6.2 常见慢因

| 节点 | 慢因 | 优化 |
|------|------|------|
| LLM | 模型本身 / prompt 太长 | 换模型 / 精简 prompt |
| Knowledge Retrieval | 见 §4 | — |
| HTTP | 外部服务慢 | 设 timeout,别裸等 |
| Code | 死循环 / 大计算 | 设 per-node timeout |
| Agent | 内部还要跑工具循环 | 减少工具 |

### 6.3 用并行

互不依赖的分支应该并行,不要串成一条链。真并行已支持 —— 分支汇聚用 Variable Aggregator。

### 6.4 设置 timeout

每个节点支持 per-node timeout。**不设 timeout 的 HTTP 节点是定时炸弹** —— 外部服务挂了会拖死整个工作流。

详见 [错误处理与重试](../explanation/error-retry-timeout.md)。

---

## 7. 列表接口慢

### 7.1 确认走了真分页

早期有些接口是"查全表再切片"的假分页。

**判据**:数据量翻倍,耗时也翻倍 → 假分页。

**修法**:SQL 层 `LIMIT` / `OFFSET`,`COUNT(*)` 单独查。

### 7.2 N+1 查询

**症状**:列表接口耗时与行数线性相关,SQL 日志里同样的查询重复 N 次。

**修法**:`selectinload` / `joinedload` 预加载关联。

```python
from sqlalchemy.orm import selectinload

query = (
    db.query(Agent)
    .options(selectinload(Agent.knowledge_bases))   # 一次查完,不要 N+1
)
```

### 7.3 缺索引

高频过滤列必须有索引:

```sql
SHOW INDEX FROM conversations;

-- 常见需要索引的列
-- tenant_id, user_id, agent_id, status, created_at
```

```sql
CREATE INDEX idx_conv_tenant_created ON conversations(tenant_id, created_at);
```

> MCP 工具禁 DDL,建索引用 Python 直连(见 [常见错误 §3.3](common-errors.md#33-mcp-工具拒绝执行-ddl))。

### 7.4 深分页

`OFFSET 100000` 会让 MySQL 扫 10 万行再丢弃。

**修法**:游标分页(`WHERE id < last_id ORDER BY id DESC LIMIT 20`)。

---

## 8. 前端慢

### 8.1 dev 启动慢 / 内存爆

```js
// next.config.js —— 用 optimizePackageImports,不要 transpilePackages
experimental: {
  optimizePackageImports: ["antd", "@ant-design/icons"],
}
```

```json
"dev": "NODE_OPTIONS='--max-old-space-size=4096' next dev -p 11334"
```

### 8.2 页面首屏慢

- 大组件用 `dynamic(() => import(...), { ssr: false })` 懒加载(工作流画布、MDEditor 这类)
- 图表库、编辑器不要在 layout 里全局引

### 8.3 重复请求

**症状**:Network 面板里同一个接口发了 2 次(或更多)。

**根因**:
- React 18 StrictMode 双挂载(dev 独有,prod 没有 —— 可以忽略)
- `useEffect` 依赖数组里放了每次渲染都变的对象/函数

**修法**:依赖数组只放原始值,或用 `useCallback` / `useMemo` 稳定引用。

### 8.4 大列表卡

antd Table 开虚拟滚动,或减少 pageSize。

> 注意:Select 的虚拟滚动配自定义 `optionRender` 会出 bug,小列表要 `virtual={false}`。见 [常见错误 §1.2](common-errors.md#12-antd-select-下拉只显示-1-个选项)。

---

## 9. 数据库运维

### 9.1 定期清理日志表

`llm_call_logs` / `embedding_call_logs` / `workflow_node_runs` 增长很快。

平台有**数据保留策略**(retention)机制,配置保留天数后由 scheduler 自动清理。

手动清理:

```sql
DELETE FROM llm_call_logs WHERE created_at < NOW() - INTERVAL 90 DAY LIMIT 10000;
```

> 加 `LIMIT` 分批删,一次删几十万行会锁表。

### 9.2 消除 AUTO_INCREMENT gap

```sql
ALTER TABLE X AUTO_INCREMENT = 1;
```

InnoDB 会自动改成 `max(id)+1`。作用是消除 gap,不是归零。

### 9.3 孤儿连接

强杀进程会留下持有 MDL 的 Sleep 连接,阻塞后续 ALTER。

```sql
SELECT id, user, command, time FROM information_schema.processlist
WHERE command = 'Sleep' AND time > 300;
```

清理方法见 [uvicorn-zombie §6](uvicorn-zombie.md#6-连带坑强杀留下-mysql-mdl-孤儿连接)。

---

## 10. 优化清单(按性价比排序)

| # | 动作 | 成本 | 收益 |
|---|------|------|------|
| 1 | Ollama 模型预热 + `keep_alive` | 极低 | 首次调用 -20 秒 |
| 2 | 高频过滤列加索引 | 低 | list API 数倍 |
| 3 | 记忆策略改 sliding_window | 低 | 长对话 token 恒定 |
| 4 | 修 N+1(selectinload) | 低 | 列表接口数倍 |
| 5 | 每个 HTTP / Code 节点设 timeout | 低 | 防雪崩 |
| 6 | 定期清日志表 | 低 | DB 体积可控 |
| 7 | 工作流分支改并行 | 中 | 端到端耗时 -50% |
| 8 | 前端大组件懒加载 | 中 | 首屏 -30% |
| 9 | 检索 top20 + 重排取 5 | 中 | 精度↑ 耗时略↑ |
| 10 | FAISS 换 IVF/HNSW | 高 | 大 KB 检索数量级 |

---

**相关文档**
- [常见错误速查](common-errors.md)
- [可观测性](../explanation/observability.md)
- [Embedding 流水线](../explanation/embedding-pipeline.md)
- [错误处理与重试](../explanation/error-retry-timeout.md)

---

**维护者**:全栈架构师
**最近更新**:2026-08-06
