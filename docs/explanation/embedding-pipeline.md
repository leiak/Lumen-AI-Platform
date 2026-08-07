# Embedding 流水线

> Lumen AI Platform 的 RAG(检索增强生成)是怎么把"一份 PDF 变成 LLM 能用的上下文"的。
> 文档解析 → 切块 → 向量化 → 索引 → 检索 端到端流程,适合工程师实现 / 排查时参考。

---

## 1. 整体流程图

```
┌──────────────────┐
│ 用户上传 PDF      │
│ (POST /documents) │
└────────┬─────────┘
         │ 保存文件
         ▼
┌──────────────────┐
│ storage/         │
│ knowledge_bases/ │
│ <kb_id>/         │
│ <doc_id>.pdf     │
└────────┬─────────┘
         │ 派发 Celery
         ▼
┌──────────────────┐
│ parse_document   │
│ (Docling)        │
└────────┬─────────┘
         │ 文本块
         ▼
┌──────────────────┐
│ chunker          │
│ (按段落 500字)    │
└────────┬─────────┘
         │ chunks[]
         ▼
┌──────────────────┐
│ embedding_factory│
│ (per-KB model)   │
└────────┬─────────┘
         │ vectors[]
         ▼
┌──────────────────┐
│ FAISS + ES 索引  │
│ (混合检索)        │
└────────┬─────────┘
         │
         ▼
    写入 document_chunks 表 + 索引

--- 用户提问时 ---

┌──────────────────┐
│ 用户 query        │
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ embedding 工厂    │
│ query → vector    │
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ 混合检索:        │
│ - FAISS top_k    │
│ - ES BM25 top_k  │
│ - 合并去重        │
│ - Rerank 精排    │
└────────┬─────────┘
         │ top-N chunks
         ▼
┌──────────────────┐
│ 拼到 LLM prompt   │
│ (作为上下文)       │
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ LLM 生成回答      │
│ + 引用 chunks     │
└──────────────────┘
```

---

## 2. 上传 + 解析 + 切块(后台)

### 2.1 上传
- 前端: `frontend/app/dashboard/knowledge/page.tsx` POST `/knowledge/<kb_id>/documents`
- 后端: `backend/lumen_api/v1/knowledge.py` (`create_document`)
- 保存: `storage/knowledge_bases/<kb_id>/<doc_id>.<ext>`
- 写 `documents` 行(`status=pending`)
- 派发 Celery 任务 `parse_document(doc_id)`

### 2.2 Celery 任务
- 文件: `backend/lumen_tasks/document_tasks.py`
- 任务: `parse_document(doc_id)`
- 流程:
  1. 读 documents 行
  2. 调用 `docling_parser.parse(path)`
  3. 调 `chunker.chunk(text)`
  4. 调 `embedding_factory.embed_batch(texts, model_config_id)`
  5. 写 `document_chunks` 行
  6. 写 FAISS 索引
  7. 写 ES 索引
  8. 更新 `documents.status=ready`
  9. WS 推送通知

### 2.3 Docling 解析
- 文件: `backend/lumen_tools/docling_parser.py`
- 库: `docling` (IBM 出品)
- 支持: PDF / DOCX / PPTX / XLSX / MD / HTML / 图片(OCR)
- 三级 fallback:
  1. Docling(最优)
  2. pdfplumber(PDF 专用)
  3. pypdf(基础)

### 2.4 切块
- 文件: `backend/lumen_tools/chunker.py`
- 策略:
  - `paragraph` (按段落,M 默认)
  - `sentence` (按句子)
  - `token` (按 token 数)
- 默认: 500 字符一段,重叠 50 字符
- 配置: 在 `kb_retrieval_config` JSON 里

---

## 3. 向量化

### 3.1 Embedding 工厂
- 文件: `backend/lumen_tools/embedding_factory.py`
- 工厂模式:per-KB 不同 model
- 入参: `kb_id` → 查 KB 的 `embedding_model_config_id` → 选对应 model

### 3.2 支持的 model
- **Ollama 本地**:`nomic-embed-text` (768 维,免费)
- **OpenAI**:`text-embedding-3-small` (1536 维) / `text-embedding-3-large` (3072 维)
- **其他 OpenAI 兼容**:通过 `OPENAI_BASE_URL` 配置

### 3.3 向量维度
- 写 FAISS 索引时**用真实维度**(不写死 1536)
- `kb_id` + `model_config_id` 决定 collection 名字:`kb_{kb_id}_model_{model_id}`
- 维度不一致 → 写不进去,显式报错

### 3.4 性能
- 单文本 embedding: 50~200 ms
- 批量(64 条): 2~5 秒
- 缓存:同一文本 hash 后复用(M27 优化)

---

## 4. 混合检索

### 4.1 三段式
```
query
   │
   ▼
1. Embedding: query → vector (embedding 工厂,跟 KB 同一 model)
   │
   ▼
2. 双路召回:
   ├─ FAISS: top_k=20(向量相似度)
   └─ ES: top_k=20(BM25 关键词)
   │
   ▼
3. 合并 + Rerank
   ├─ 合并去重(按 chunk_id)
   ├─ Rerank 精排: 0~1 分
   └─ 取 top_N=5(可配)
```

### 4.2 向量检索(FAISS)
- 文件: `backend/lumen_tools/vector_store_factory.py`
- 算法: `IndexFlatL2` (暴力,精确) / `IndexIVFFlat` (聚类,快)
- 内存索引,重启从 MySQL 恢复
- per-(kb_id, model_config_id) 索引

### 4.3 关键词检索(ES)
- 文件: `backend/lumen_tools/es_search.py`
- 算法: BM25
- 索引:`kb_chunks_<kb_id>`
- 字段:`content`(text,分词)+ `metadata`(keyword)

### 4.4 Rerank
- 文件: `backend/lumen_tools/rerank.py`
- 库: `sentence-transformers` (cross-encoder)
- 模型: `BAAI/bge-reranker-v2-m3` 或类似
- 输入: query + top-20 chunks
- 输出: 0~1 分
- 性能: 50 chunks / 1 秒

### 4.5 检索配置
- 每个 KB 可独立配置:
  - `top_k` (默认 20,召回数)
  - `top_n` (默认 5,送 LLM)
  - `score_threshold` (默认 0.5,过滤低分)
  - `vector_weight` / `keyword_weight` (M28 加,4 滑块)

---

## 5. 引用与可追溯

### 5.1 Citations 字段
- LLM 回答后,前 N 个 chunks 作为 `citations` 返回
- 前端 `components/chat/Citations.tsx` 渲染

### 5.2 Chunk 字段
```python
class DocumentChunk(BaseModel):
    id: int
    document_id: int
    kb_id: int
    content: str
    chunk_index: int
    metadata: dict
    embedding_vector: list[float]  # 实际存 FAISS
```

### 5.3 追溯
- 引用 → `chunk.id` → `document.id` → 跳到文档详情
- 文档详情 → 高亮显示该 chunk

---

## 6. 失败兜底

### 6.1 Docling 解析失败
- 自动 fallback pdfplumber → pypdf
- 三级都失败 → `documents.status=failed` + 通知

### 6.2 Embedding 超时
- 重试 3 次 + 指数退避
- 单条失败 → 跳过该条,继续其他
- 全失败 → `documents.status=failed` + 通知

### 6.3 向量检索 0 结果
- 不阻塞 LLM,仅不返回引用
- LLM 仅靠 prompt 回答(可能幻觉)

### 6.4 ES 不可达
- 降级为纯向量检索(FAISS)
- 性能下降但可用

### 6.5 Rerank 失败
- 跳过 Rerank,直接返回 top-N
- 精度下降但不影响功能

---

## 7. 性能数据(参考)

| 阶段 | 耗时(1 文档 / 50 页) |
|------|---------------------|
| Docling 解析 | 5~15 秒 |
| 切块 | < 0.1 秒 |
| Embedding(50 chunks) | 1~3 秒 |
| 写 FAISS + ES | 0.5 秒 |
| **合计** | **8~20 秒** |

| 检索阶段 | 耗时(查询) |
|---------|-----------|
| Embedding(query) | 50~200 ms |
| FAISS top-20 | 5~10 ms |
| ES BM25 top-20 | 20~50 ms |
| 合并 + Rerank | 200~500 ms |
| **合计** | **300~800 ms** |

---

## 8. 监控

### 8.1 关键指标
- 文档解析成功率
- Embedding 平均耗时
- 检索召回率(@5,@10,@20)
- 检索 P95 延迟

### 8.2 看板
- 暂未集成到 RAG 评测(M37 有)
- 用 LLM 调用日志 + 慢查询告警

### 8.3 告警
- 单文档解析 > 60 秒
- 检索延迟 > 2 秒
- ES / FAISS 不可达

---

## 9. 升级与扩展

### 9.1 增加新 embedding provider
- 步骤:
  1. `lumen_tools/embedding_providers/<new>.py` 实现接口
  2. `lumen_core/model_providers.py` 注册
  3. 写测试
- 例:加 Cohere / Voyage

### 9.2 换 Rerank 模型
- 步骤:
  1. 改 `lumen_tools/rerank.py` 加载新模型
  2. 跑 RAG 评测(M37)对比

### 9.3 增量索引
- 当前:全量重索引(删旧 + 加新)
- 计划:增量索引(只加新 chunk)
- 适用:大 KB 频繁更新

---

## 10. 常见误区

### 10.1 维度不匹配
- 错误:同一 KB 切了 Ollama 768 维,又用 OpenAI 1536 维
- 解决:KB 创建时锁定 `embedding_model_config_id`,**不再改**

### 10.2 切块太碎
- 错误:每 50 字一段,语义割裂
- 解决:按段落(默认 500),长段落重叠 50

### 10.3 检索太多
- 错误:top_n=20 全送 LLM,token 爆
- 解决:Rerank 精排到 5

### 10.4 不去重
- 错误:FAISS 和 ES 召回 20 + 20,实际只有 25 个独立
- 解决:按 chunk_id 去重

### 10.5 忽略 metadata 过滤
- 错误:在多租户 KB 下,跨租户检索
- 解决:FAISS 和 ES 都强制 `kb_id` filter

---

## 11. 与开源方案的对比

| 维度 | Lumen | LangChain RAG | Dify RAG | LlamaIndex |
|------|-------|---------------|----------|------------|
| 文档解析 | Docling + 三级 fallback | 用户选 | Unstructured | LlamaParse |
| 切块 | 段落 / 句子 / token | RecursiveCharacter | 自带 | SentenceSplitter |
| Embedding | per-KB | 全局 | 全局 | per-index |
| 向量库 | FAISS | Chroma / Pinecone | PG / Weaviate | 自带 |
| 混合检索 | FAISS + ES + Rerank | FAISS + BM25 (需组合) | ES + 向量 | 多种 |
| 评测 | M37 RAG 评估 | 需自建 | 内置 | 内置 |

---

**维护者**:全栈架构师 + AI 工程师
**最近更新**:2026-08-06
