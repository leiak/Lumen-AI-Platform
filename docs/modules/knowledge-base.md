# 模块:知识库 RAG

> Lumen AI Platform 的核心模块 —— 知识库(Retrieval-Augmented Generation)。
> 文档讲透 KB 能做什么、文档怎么上传、检索怎么跑、混合检索怎么工作。

---

## 1. 产品定位

**知识库是什么?**
- 一组相关文档的集合 + 自动向量化 + 智能检索
- 让 AI 回答时参考"公司私有文档",而不是"凭训练记忆瞎说"
- 例:产品手册 KB → AI 答"产品 A 保修期多久"时引手册原文

**和"传 PDF 给 ChatGPT"比有什么不同?**
- 永久存,不用每次传
- 检索时只返相关段落,token 省
- 引用透明,用户能点看来源
- 跨会话共享(同一 KB 多个 Agent 都能用)

---

## 2. 功能清单

| 功能 | 描述 |
|------|------|
| KB CRUD | 创建 / 编辑 / 删除 / 启停 |
| 文档上传 | PDF / DOCX / Excel / Markdown / TXT / 图片(OCR) |
| 文档解析 | Docling + 三级 fallback |
| 智能切块 | 按段落 / 句子 / token |
| Embedding | per-KB 选 model |
| 混合检索 | FAISS + Elasticsearch + Rerank |
| 引用 | 自动提取并展示 |
| 检索配置 | per-KB top_k / score / 权重 |
| FAQ 管理 | 问答对(辅助检索) |
| 搜索权重 | 4 滑块调优 |

---

## 3. 数据模型

### 3.1 knowledge_bases
```python
class KnowledgeBase(Base):
    id: int
    name: str
    description: str
    embedding_model_config_id: int   # 该 KB 用哪个 embedding
    chunking_strategy: str          # paragraph / sentence / token
    chunk_size: int                 # 块大小(默认 500)
    chunk_overlap: int              # 块重叠(默认 50)
    is_active: bool
    tenant_id: int
```

### 3.2 documents
```python
class Document(Base):
    id: int
    kb_id: int
    name: str                       # 文件名
    file_path: str                  # 相对 storage 路径
    file_size: int
    mime_type: str
    status: str                     # pending / parsing / ready / failed
    error: str
    tenant_id: int
```

### 3.3 document_chunks
```python
class DocumentChunk(Base):
    id: int
    document_id: int
    kb_id: int
    content: str                    # 文本块
    chunk_index: int
    metadata: dict
    # embedding_vector 不在 DB(在 FAISS 索引)
```

### 3.4 关联表
- `agent_knowledge_bases` — Agent ↔ KB 多对多

### 3.5 文件
- ORM: `backend/lumen_models/knowledge.py`
- Schema: `backend/lumen_schemas/knowledge.py`
- 服务: `backend/lumen_services/knowledge_service.py`
- 路由: `backend/lumen_api/v1/knowledge.py`

---

## 3.6 Workspace + DocumentFolder(M38.2,2026-08-26 ship)

KB 之上引入两层导航结构。**只做骨架,不引入 RBAC**(留 M38.2.x v2)。

### 3.7 workspaces
```python
class Workspace(Base):
    id: int
    tenant_id: int              # 租户隔离
    name: str                   # 100 字内,unique per tenant
    knowledge_base_count: int   # 反范式冗余,trigger 维护
```

- KB 通过 `KnowledgeBase.workspace_id`(NULL-able)选挂在哪个 workspace 下
- 多个 KB 可挂同一 workspace(协作分组)
- NULL workspace_id 的 KB 视为「未分组」,`tenant root` 节点

### 3.8 document_folders
```python
class DocumentFolder(Base):
    id: int
    kb_id: int                  # 严格属于 1 个 KB(不跨 KB)
    parent_id: int | None       # 自引用,NULL = KB 根
    name: str
    order_index: int
    document_count: int         # 冗余
    tenant_id: int              # 冗余,走 KB 即可
```

- 树状(folder 可以嵌套),但仅在同一 KB 内
- Document 通过 `Document.folder_id` 关联(NULL = KB 根)
- `move_document(kb_id, doc_id, target_folder_id)` API 移动文档

### 3.9 前端导航结构
`/dashboard/knowledge` 页加入 `<WorkspaceTree>` 侧边栏(AntD DirectoryTree):

```
ws:root (未分组,workspace_id=NULL 的 KB)
  └ KB 「legacy」
ws:1 (研发)
  └ KB 「API 规范」
     ├ kb-root:100 根目录 (12)
     └ folder:200 v1 (5)
         └ folder:201 auth (2)
```

点击节点通过回调冒泡:
- `ws:*` → `onSelectWorkspace` + `onSelectKb(ws, null)`
- `kb:*` / `kb-root:*` → `onSelectKb(ws, kbId)`(+`onSelectFolder` for kb-root)
- `folder:*` → `onSelectFolder(ws, kbId, folderId)`

### 3.10 文件
- ORM: `backend/lumen_models/workspace.py` + `backend/lumen_models/document_folder.py`
- Schema: `backend/lumen_schemas/workspace.py` + `backend/lumen_schemas/folder.py`
- 服务: `backend/lumen_services/workspace_service.py` + `backend/lumen_services/folder_service.py`
- 路由: `backend/lumen_api/v1/workspace.py` + `backend/lumen_api/v1/folder.py`
- 前端: `frontend/components/knowledge/WorkspaceTree.tsx` + `CreateWorkspaceModal` + `CreateFolderModal` + `MoveDocumentModal`
- 页面: `frontend/app/dashboard/knowledge/page.tsx` 集成 sidebar + breadcrumb

### 3.11 向后兼容
- `KnowledgeBase.workspace_id` NULL → KB 仍在「未分组」节点可见
- `Document.folder_id` NULL → 文档仍列在 KB 根(虚节点「根目录 (N)」)
- 旧 API 路径不变;workspace / folder 是新增维度
- **不删旧 API**(无破坏性更新)

### 3.12 Workspace RBAC(M38.2.x v2,2026-08-27 ship)

M38.2 把 workspace 落库后只做导航骨架,M38.2.x v2 在它之上加 19 项 ACL 权限 + owner / admin bypass,workspace_id IS NULL 默认开放 read。

**19 项 permission 清单**:

| 维度 | 权限 |
|------|------|
| workspace | `workspace.read` / `update` / `delete` / `manage_members` / `transfer_ownership` |
| KB | `kb.read` / `create` / `update` / `delete` |
| folder | `folder.read` / `create` / `update` / `delete` / `restore` |
| document | `document.read` / `create` / `update` / `delete` / `move` |

**implication 链**(后端 `_PERM_IMPLIES` + 前端 `effectivePerms` 镜像):

```
kb.update        → kb.read → document.read
kb.delete        → kb.read → document.read
folder.update    → folder.read
document.move    → folder.read + folder.update
... (见 backend/lumen_services/permission_service.py)
```

**核心规则**:

1. **owner bypass**: `Workspace.owner_id == user.id` 自动全 19 项 perm,无须在 `workspace_member_permissions` 插 row。
2. **superuser bypass**: `User.is_superuser = true` 直接全 perm(横跨所有 workspace)。
3. **workspace_id IS NULL 默认开放**: 老数据 / 没归 workspace 的 KB,read-class(workspace/kb/folder/document.read)同 tenant 全员开放;**写操作仍要 superuser**。
4. **implication**: grant `kb.update` 自动获 `kb.read` + `document.read`(前端按钮 enable 用)。
5. **transfer_ownership 30s 防误点**: 前端 modal 倒计时 + workspace 名二次输入确认,同事务写 `AuditLog` 保原子性。

**API 端点**(`/api/v1/workspaces/{id}/members/*`):

| Method | Path | 权限 | 用途 |
|--------|------|------|------|
| GET | `/members` | `workspace.read` | 列成员 + 每人权限 |
| POST | `/members` | `workspace.manage_members` | 邀请 user(整组权限一次性 set) |
| PUT | `/members/{uid}` | `workspace.manage_members` | 改 user 权限(整组覆盖) |
| DELETE | `/members/{uid}` | `workspace.manage_members` | 移除 user(member 权限回收) |
| POST | `/transfer-ownership` | `workspace.transfer_ownership` | 转让 owner + AuditLog |
| GET | `/auth/me/workspaces` | 任意已登录 | 当前 user 在各 ws 上的 effective perm |

**check helper 签名**(`backend/lumen_services/permission_service.py`):

```python
class PermissionService:
    def check(db: Session, user: User, permission: str, workspace_id: int) -> bool: ...
    def load_user_workspace_permissions(db, user, ws_ids) -> dict[int, set[str]]: ...
    def require_workspace_perm(permission: str) -> Callable: ...  # FastAPI Depends
```

**chat / workflow KB RAG 集成**: agent_rag / chat_features / agent_service / workflow KB 节点全部加 `user` 入参;**user 无 kb.read 时该 KB 在检索结果里被 skip**(不 throw),spec §6.6。

**前端 useCanI 模式**:

```ts
import { useCanI } from "@/hooks/useWorkspacePermissions";

function KnowledgePage() {
  const canManage = useCanI("workspace.manage_members", selectedWorkspaceId);
  return <Button disabled={!canManage}>成员管理</Button>;
}
```

详见 `docs-internal/superpowers/specs/2026-08-27-workspace-rbac.md`(200+ 行,完整 invariant 列表 + spec §6 implication 全链)。

---

## 4. UI

### 4.1 列表
- 路径: `frontend/app/dashboard/knowledge/page.tsx`
- 表格:KB 名 / 文档数 / embedding 模型 / 状态 / 操作
- 操作:打开 / 编辑 / 删除

### 4.2 KB 详情 / 文档管理
- Tabs: 文档列表 / FAQ / 配置
- 文档列表:文件名 / 大小 / 状态 / 上传时间
- 上传:拖拽 + 进度

### 4.3 KB 配置
- Embedding 模型:`EmbeddingModelSelect` (per-KB)
- 切块策略:下拉
- 检索参数:4 滑块
- 详见 § 10

### 4.4 关键组件
- `frontend/components/knowledge/FAQTab.tsx`
- `frontend/components/agent/MultiKBSelector.tsx`(Agent 编辑用)
- `frontend/components/EmbeddingModelSelect.tsx`

---

## 5. 文档上传 + 解析(后台)

### 5.1 流程
```
用户上传 PDF
   │
   ▼
POST /knowledge/<kb_id>/documents
   │
   ▼
保存文件 → storage/knowledge_bases/<kb_id>/<doc_id>.pdf
   │
   ▼
写 documents 行(status=pending)
   │
   ▼
派发 Celery 任务 parse_document(doc_id)
   │
   ▼
Celery worker:
  1. Docling 解析(失败 → pdfplumber → pypdf 三级 fallback)
  2. chunker.chunk(text) 切块
  3. embedding_factory.embed_batch(texts) 向量化
  4. 写 document_chunks 行
  5. 写 FAISS 索引
  6. 写 ES 索引
  7. 更新 documents.status=ready
  8. WS 推通知
```

### 5.2 关键代码
- 上传: `backend/lumen_api/v1/knowledge.py::create_document`
- Celery: `backend/lumen_tasks/document_tasks.py::parse_document`
- 解析: `backend/lumen_tools/docling_parser.py`
- 切块: `backend/lumen_tools/chunker.py`
- Embedding: `backend/lumen_tools/embedding_factory.py`
- 向量库: `backend/lumen_tools/vector_store_factory.py`
- 写 ES: `backend/lumen_tools/es_search.py`

详见 [explanation/embedding-pipeline.md](../explanation/embedding-pipeline.md)。

---

## 6. 检索(查询时)

### 6.1 流程
```
用户问"产品 A 保修期"
   │
   ▼
1. embedding 工厂:query → vector(用 KB 同一模型)
   │
   ▼
2. 双路召回
   ├─ FAISS: top_k=20
   └─ ES BM25: top_k=20
   │
   ▼
3. 合并 + 去重
   │
   ▼
4. Rerank 精排(可选)
   │
   ▼
5. 取 top_n=5
   │
   ▼
6. 拼到 LLM prompt
   │
   ▼
7. LLM 生成 + 引用 chunks
```

### 6.2 关键代码
```python
# backend/lumen_services/knowledge_service.py
async def retrieve(
    self,
    query: str,
    kb_ids: list[int],
    config: dict,
    tenant_id: int,
) -> list[Chunk]:
    # 1. Embedding
    query_vector = await self.embedding_factory.embed(query, kb_id=kb_ids[0])

    # 2. 双路召回
    faiss_results = await self.vector_store.search(kb_ids, query_vector, top_k=20)
    es_results = await self.es_search.search(kb_ids, query, top_k=20)

    # 3. 合并 + 去重
    merged = merge_and_dedup(faiss_results, es_results)

    # 4. Rerank
    reranked = await self.rerank.rerank(query, merged, top_n=5)

    return reranked
```

---

## 7. 关键能力详解

### 7.1 Per-KB Embedding(M13)
- 1 个 KB 锁 1 个 embedding model
- 创建 KB 时选,后续不能改(改会破坏索引)
- 改 → 必须重建索引

### 7.2 切块策略
- **paragraph**(默认):按段落分,适合文档
- **sentence**:按句子分,适合对话
- **token**:按 token 数,适合长文

### 7.3 检索参数(per-KB)
- `top_k`: 召回数(默认 20)
- `top_n`: 送 LLM 数(默认 5)
- `score_threshold`: 过滤低分(默认 0.5)
- 详见 § 10

### 7.4 Rerank(M16)
- 用 `BAAI/bge-reranker-v2-m3` 或类似
- 输入:query + top-20 chunks
- 输出:0~1 分,排序

### 7.5 FAQ(M19)
- 问答对(独立于文档)
- 检索时也走 FAQ 匹配
- 适合:已知固定问题

### 7.6 搜索权重(M28)
- 4 滑块,0~1
  - 向量权重
  - 关键词权重
  - Rerank 权重
  - FAQ 权重
- 实时调,看效果

---

## 8. 性能

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

## 9. 边界与不做

### 9.1 当前
- ✅ 文档上传 + 解析 + 切块 + 向量化
- ✅ 混合检索(FAISS + ES)
- ✅ Rerank 精排
- ✅ Per-KB Embedding
- ✅ 引用展示
- ✅ FAQ
- ✅ 4 滑块

### 9.2 不做
- ❌ 文档版本管理(覆盖即生效)
- ❌ 跨 KB 联合检索(每个检索独立)
- ❌ 自动同步外部数据源(暂不接飞书 / 语雀)

---

## 10. 检索配置详解

### 10.1 Per-Agent 检索
- Agent 可为每个 KB 设不同参数
- `agent.kb_retrieval_config`:
  ```json
  {
    "kb_<id>_top_k": 5,
    "kb_<id>_score_threshold": 0.5
  }
  ```

### 10.2 Per-KB 全局
- `kb_retrieval_config`:
  - `top_k`(默认 20)
  - `top_n`(默认 5)
  - `vector_weight` / `keyword_weight`(M28 加,4 滑块)

### 10.3 4 滑块
- **向量权重** 0~1(默认 0.7)
- **关键词权重** 0~1(默认 0.3)
- **Rerank 权重** 0~1(默认 0.5)
- **FAQ 权重** 0~1(默认 0.3)

---

## 11. 升级路径

### 短期
- 📋 文档版本管理
- 📋 文档标签 / 分类
- 📋 自动同步(飞书 / 语雀)

### 中期
- 📋 跨 KB 联合检索
- 📋 文档级权限
- 📋 检索质量自动评估

### 长期
- 📋 多模态 KB(图 / 音 / 视频)
- 📋 自动摘要(摘要文档)
- 📋 AI 主动学习(从反馈学)

---

## 12. 排错

| 症状 | 原因 | 修法 |
|------|------|------|
| 文档解析失败 | 格式不支持 / 损坏 | 试 PDF / 看错误日志 |
| 检索 0 结果 | KB 没数据 / 关键词太偏 | 上传文档 / 改 query |
| 检索不准 | top_k 小 / 没 Rerank | 调参 / 开 Rerank |
| 维度不匹配 | KB 换 embedding model | 重建索引 |
| ES 不可达 | ES 容器挂 | 重启 ES |
| FAISS 慢 | 索引太大 | 减少文档 / 用 IVF |
| 引用不显示 | score_threshold 太严 | 调低 |

详见 [troubleshooting/common-errors.md](../troubleshooting/common-errors.md)。

---

**维护者**:全栈架构师
**最近更新**:2026-08-27(M38.2.x v2 ship:Workspace RBAC 19 perm + owner/admin bypass + chat/workflow KB graceful skip)
