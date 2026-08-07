# 数据流

> 5 个典型业务场景的端到端数据流:LLM 调用、RAG 检索、工作流执行、图片生成、外部应用 Widget。
> 文档供工程师在排查问题时参考,也能让产品理解"用户一次点击背后发生了什么"。

---

## 1. 场景 1:用户发聊天消息 → 收到流式回答

### 1.1 流程图
```
用户(浏览器)
   │ 1. 输入"今天北京天气"
   ▼
Frontend Chat 页面
   │ 2. fetch POST /api/v1/chat/messages/stream
   │    Headers: Authorization: Bearer <token>
   │    Body: { conversation_id, message, agent_id }
   ▼
Backend FastAPI(uvicorn worker)
   │ 3. 路由 chat.py → deps.get_current_user → 解析 token
   │ 4. 调 chat_service.process_message
   │    - 查 Agent 配置(model, prompt, KBs, tools)
   │    - 查 memory(滑动窗口 / 全局)
   │    - 构造 messages
   │ 5. 调 chat_service.stream
   │    - 5 轮 tool loop:
   │      a. LangChain ChatModel(model=Agent.model)
   │         → LoggingChatModel 包装 → 写 llm_call_logs
   │      b. LLM 返回 tool_calls? → 调 Tool → 回到 a
   │      c. 直到 LLM 返回 content
   │ 6. 通过 StreamingResponse 直接返回 SSE(单 chunked 连接,边生成边写)
   ▼
Frontend Chat 页面
   │ 7. 解析 SSE 块(text/event-stream)
   │ 8. 逐字渲染到消息流
   │ 9. SSE 正常结束 / 异常断开 → 落库 messages + 更新 conversations.updated_at
   ▼
MySQL
   - 写 messages(content, role=assistant)
   - 更新 conversations.updated_at
```

### 1.2 关键代码位置
- 前端: `frontend/app/dashboard/chat/page.tsx`
- 前端 SSE parser: `frontend/lib/chat-sse-utils.ts`
- 后端路由: `backend/lumen_api/v1/chat.py`
- 后端服务: `backend/lumen_services/chat_service.py`
- LLM 包装: `backend/lumen_core/observability.py` (`LoggingChatModel`)
- 工具循环: `backend/lumen_services/agent_service.py` (5 轮 tool loop)

### 1.3 失败兜底
- LLM 401 / 403 / 超时 → 当前会话直接 5xx 给前端,无自动 fallback(`LoggingChatModel` + `create_chat_model` 没有 model 链)
- SSE 异常断开 → 前端在 `MessageBubble` 上挂"已中断,可重新生成"按钮,不自动重连
- Tool 调用失败 → 标记该 tool_call 失败,把错误信息作为 tool 消息回灌,继续下一轮;超 5 轮强制结束
- 模型层埋点(每次 LLM 调用)统一写 `llm_call_logs`,trace_id 由中间件注入,失败详情可查 `/api/v1/logs/llm-calls/{call_id}`

详见 [explanation/chat-sse-streaming.md](../explanation/chat-sse-streaming.md)。

---

## 2. 场景 2:用户上传 PDF → 知识库检索

### 2.1 上传 + 解析 + 向量化(后台)

```
用户(浏览器)
   │ 1. 进入 /dashboard/knowledge,选 KB,上传 PDF
   ▼
Frontend Knowledge 页
   │ 2. POST /api/v1/knowledge/<kb_id>/documents (multipart/form-data)
   ▼
Backend FastAPI
   │ 3. 路由 knowledge.py → knowledge_service.create_document
   │ 4. 保存文件到 storage/knowledge_bases/<kb_id>/<doc_id>.pdf
   │ 5. 创建 documents 行(status=pending)
   │ 6. 派发 Celery 任务 document_tasks.parse_document(doc_id)
   ▼
Celery worker
   │ 7. Docling 解析 PDF → 文本块
   │ 8. 切块(默认按段落 500 字)
   │ 9. per-KB embedding 工厂 → 选对应 embedding model
   │ 10. 调 embedding API(Ollama / OpenAI)→ 向量
   │ 11. 写 document_chunks 表 + FAISS 索引
   │ 12. 更新 documents.status=ready
   │ 13. WS 推送到前端通知
   ▼
Frontend
   │ 14. 收到 WS 通知 → 通知中心 + 列表刷新
```

### 2.2 检索(用户提问时)

```
用户(浏览器)
   │ 1. 在 Chat 输入"产品 A 保修期多久"
   ▼
Backend Chat
   │ 2. 查 Agent.knowledge_bases → 关联 KBs
   │ 3. 调 knowledge_service.retrieve(kb_ids, query)
   │    a. embedding 工厂(per-KB 锁定 ModelConfig): query → 向量
   │    b. FAISS 搜索 top_k(M28 默认 10)
   │    c. BM25 关键字加权(M28 `search_weights`:title / important_kw / question_kw / text 4 维)
   │    d. FAISS + BM25 加权融合,可选 Rerank 精排
   │    e. 取 top-N(默认 top_k=10,rerank_top_n=5)
   │ 4. 把 chunks 拼到 LLM prompt
   │ 5. 调 LLM 生成回答
   │ 6. 流式返回 + 引用 chunks(Citations 组件)
```

### 2.3 关键代码位置
- 上传: `backend/lumen_api/v1/knowledge.py` (POST /documents)
- Celery: `backend/lumen_tasks/document_tasks.py` (parse_document)
- 解析: `backend/lumen_tools/docling_parser.py`
- 切块: `backend/lumen_tools/chunker.py`
- Embedding 工厂: `backend/lumen_tools/embedding_factory.py`
- 向量库: `backend/lumen_tools/vector_store_factory.py`
- Rerank: `backend/lumen_tools/rerank.py`
- 检索: `backend/lumen_services/knowledge_service.py` (retrieve)

### 2.4 失败兜底
- Docling 解析失败 → 自动 fallback 到 pdfplumber → pypdf 三级
- Embedding 超时 → 重试 3 次 + 退避
- 向量库搜索 0 结果 → 不阻塞 LLM,仅不返回引用

详见 [explanation/embedding-pipeline.md](../explanation/embedding-pipeline.md) 和 [modules/knowledge-base.md](../modules/knowledge-base.md)。

---

## 3. 场景 3:用户在工作流设计器 → 触发工作流

### 3.1 流程图

```
用户(浏览器)
   │ 1. /dashboard/workflow/designer
   │ 2. 拖拽节点 + 连线 + 配置
   │ 3. 点"保存"
   ▼
Frontend
   │ 4. POST /api/v1/workflows (create_workflow)
   │    Body: { name, nodes, edges, config }
   ▼
Backend
   │ 5. workflow_service.create_workflow
   │    - 校验节点配置
   │    - 写 workflows + workflow_nodes + workflow_edges
   │ 6. 返回 workflow_id
   ▼
用户继续编辑或"运行"
   │ 7. POST /api/v1/workflows/{id}/runs
   │    Body: { inputs }
   ▼
Backend
   │ 8. workflow_service.run_workflow
   │    a. 构造 LangGraph StateGraph
   │    b. 编译 graph
   │    c. 创建 workflow_runs 行(status=running)
   │    d. 后台跑 graph
   │    e. 每个节点执行前/后:
   │       - 写 workflow_node_runs BFS 落库
   │       - 错误时按 error_strategy 处理
   │    f. 全部完成 → workflow_runs.status=success
   │ 9. 返回 run_id + 节点级 BFS 日志链接
   ▼
Frontend
   │ 10. 跳到 /dashboard/workflow?run_id=...
   │ 11. 拉 GET /api/v1/workflow-runs/{id} 看节点级日志
   │ 12. WS 推送进度更新(可选)
```

### 3.2 节点类型
详见 [modules/workflow-nodes.md](../modules/workflow-nodes.md)。

### 3.3 错误处理基础设施
- `error_strategy`: `abort` / `ignore` / `fallback_value`(取自 `explanation/error-retry-timeout.md`)
- `retry_config`: max_attempts + backoff
- `timeout`: per-node seconds

详见 [explanation/error-retry-timeout.md](../explanation/error-retry-timeout.md)。

### 3.4 关键代码位置
- 前端设计器: `frontend/app/dashboard/workflows/[id]/designer/page.tsx`
- 后端路由: `backend/lumen_api/v1/workflow.py`
- 工作流执行器: `backend/lumen_services/workflow_executor.py`
- LangGraph 集成: `backend/lumen_tools/langgraph_*.py`

---

## 4. 场景 4:用户生成图片 → 后台任务 → WS 通知

### 4.1 流程图

```
用户(浏览器)
   │ 1. /dashboard/image-generation
   │ 2. 输入 prompt "夏日儿童插画"
   │ 3. 选 provider (OpenAI / Stability / Ollama / Stub)
   │ 4. 选 Playbook(Agent / 系统级绑定的视觉/语音风格 token → 注入 prompt)
   │ 5. 点"生成"
   ▼
Frontend
   │ 6. POST /api/v1/image-generations/(带尾斜杠)
   ▼
Backend
   │ 7. image_generation_service.create
   │    - 写 image_generations 行(status=pending)
   │    - 派发 Celery 任务 image_gen_tasks.generate_image_task(img_id)
   │ 8. 返回 img_id
   ▼
Celery worker
   │ 9. 注入 Playbook 视觉 token → 最终 prompt
   │ 10. 调 provider(OpenAI / Stability / Ollama / Stub)
   │ 11. 下载生成图 → 存 storage/generated_images/<tenant>/<date>/<id>.png
   │ 12. Pillow 生成缩略图
   │ 13. 写 image_generations(status=success, file_path, thumbnail_path)
   │ 14. WS 推送到前端通知
   ▼
Frontend
   │ 15. 收到 WS 通知 → 列表自动刷新
   │ 16. 用户点图片 → DetailModal 显示大图(Bearer auth fetch + blob)
```

### 4.2 关键代码位置
- 前端: `frontend/app/dashboard/image-generation/page.tsx`
- 后端路由: `backend/lumen_api/v1/image_generation.py`
- Celery: `backend/lumen_tasks/image_gen_tasks.py`
- Provider: `backend/lumen_tools/image_providers/{openai,stability,ollama,stub}.py`
- Playbook 注入: `backend/lumen_tools/playbook_renderer.py`
- WS 通知: `backend/lumen_api/v1/notification.py` + 前端 `services/realtime.ts`

### 4.3 失败兜底
- Provider 401 / 403 → 自动切换到 Stub
- Provider 超时 → 重试 2 次
- 下载图片失败 → 标记 image_generations.status=failed + 通知

详见 [modules/image-generation.md](../modules/image-generation.md)。

---

## 5. 场景 5:第三方网站嵌入 Widget → 用户聊天

### 5.1 流程图

```
访客(浏览器)
   │ 1. 打开客户网站
   │ 2. 加载 <lumen-chat server="..." app-key="...">
   ▼
Widget(Lit 3)
   │ 3. core/auth.ts: fetch_token(app_key) → POST /api/v1/external/auth/token
   │ 4. 后端 external_auth_service.create_external_token(iss="external-app", ttl=1800s)
   │    - 查 external_apps(app_key)
   │    - 校验 Origin 白名单
   │    - 签 JWT(tenant_id, app_id, agent_id, exp=24h)
   │ 5. Widget 缓存 token(临期自动 refresh)
   │ 6. 访客输入"我的订单 #12345 什么时候发货"
   ▼
Widget
   │ 7. core/api.ts: streamChat(token, message)
   │    - POST /api/v1/external/chat/stream
   │    - Authorization: Bearer <external_jwt>
   ▼
Backend
   │ 8. 路由 external_app.py → deps.get_current_external_app
   │    - 验 JWT → 拿 external_app_id
   │    - 校验 Origin 白名单 + Agent 白名单
   │ 9. 调 chat_service.stream
   │    - 选 Agent(external_apps.agent_id)
   │    - 5 轮 tool loop(Tool 可调 MCP / HTTP / ERP)
   │ 10. SSE 流式返回
   ▼
Widget
   │ 11. 解析 SSE → 逐字渲染
```

### 5.2 关键代码位置
- Widget: `widget/src/LumenChat.ts`
- Widget 认证: `widget/src/core/auth.ts`
- Widget API: `widget/src/core/api.ts`
- 后端: `backend/lumen_api/v1/external/{auth,chat,agents,conversations,upload}.py`(不见 Swagger)
- JWT 签发: `backend/lumen_services/external_auth_service.py` (`create_external_token`)
- 鉴权依赖: `backend/lumen_api/v1/deps.py::get_current_external_app`(验 iss + DB 重新查 app.is_active)

### 5.3 安全设计
- `app_key` 仅用于首次换 JWT,`app_secret` 明文仅创建时返回一次,后续只显示 masked(`mask_app_secret`)
- JWT 短有效期(30 分钟,`EXTERNAL_TOKEN_TTL_SECONDS=1800`),临期自动 refresh
- Origin 白名单(`*.example.com` 单层通配,`re.escape` + `\*` → `[^.]+`,**不**匹配裸域或反向攻击后缀)
- Agent / Team 双层白名单防越权;`app.is_active` 由 DB 实时校验,禁用即 kill switch 返 401
- 进程内滑动窗口限流(60s / 60 次,默认 `rate_limit_per_min`),多实例需升 Redis

详见 [modules/external-app-auth.md](../modules/external-app-auth.md)。

---

## 6. 场景 6:用户跑一次 RAG 评测(M37)

### 6.1 流程图
```
用户(浏览器)
   │ 1. /dashboard/eval/datasets/{id} → 点"启动 Run"
   ▼
Frontend
   │ 2. POST /api/v1/eval/runs { dataset_id, config: { top_k, rerank, search_weights, judge_metrics, embedding_model_config_id, judge_model_config_id } }
   ▼
Backend
   │ 3. eval_run_service.create_run → 校验 config.embedding_model_config_id == kb.embedding_model_config_id(否则 dim 不匹配)
   │ 4. 写 eval_runs 行(status=pending) + trace_id(uuid4)
   │ 5. Celery .delay() 派 lumen_tasks/eval_tasks.run_rag_eval(run_id)
   ▼
Celery worker(独立容器)
   │ 6. EvalRunner.run_eval(db, run_id):
   │    a. 取 dataset.items(eval_dataset_items) + retrieval_pipeline(kb_id, model_config_id)
   │    b. 跳过已写过的 item_id(续跑幂等)
   │    c. 每 item:
   │       i.  EmbeddingCallContext(call_type="eval_retrieval") → pipeline.search(query, top_k, rerank, search_weights)
   │       ii. 算 hit_at_5/10 / mrr / ndcg_at_10 / recall_at_10
   │       iii.若 judge_metrics 非空 → AnswerGenerator(call_type="eval_answer") → JudgeClient(call_type="eval_judge")
   │       iv. INSERT eval_run_results + commit(per-item,崩了能续)
   │       v.  每 10% 写一次 completed_items(进度节流)
   │       vi. 每 item 边界 _is_cancelled() 检测
   │    d. _finalize → report.generate_report → 写 metrics_json + report_markdown(≤ 50KB)+ status=completed
   │    e. 顶层异常 → status=failed + error_message,永不 raise(spec §"runner 永不 raise")
   │ 7. NotificationService.publish_event → WS 推 EVAL_RUN_COMPLETED / FAILED
   ▼
Frontend
   │ 8. /dashboard/eval/runs/{id} 看到进度 / 详情 / 对比
```

### 6.2 关键代码位置
- 前端:`frontend/app/dashboard/eval/{datasets,runs/[id]}/page.tsx` + `components/eval/{RunProgressBar,TrendLineChart,MetricsRadar}.tsx`
- 后端路由:`backend/lumen_api/v1/eval_{datasets,runs}.py`
- Runner:`backend/lumen_services/eval/{runner,metrics,judge,answer,compare,report}.py`
- Celery 任务:`backend/lumen_tasks/eval_tasks.py`(`run_rag_eval`,顶部 `# noqa: F401` preload lumen_models + retrieval,防止 ModuleNotFoundError)
- 数据模型:`backend/lumen_models/{eval_dataset,eval_run}.py`

### 6.3 失败兜底
- embedding dim 不匹配 → 422,**不**进 Celery(spec §"KB 一致性硬约束")
- Celery 任务崩 → run status=failed,err 写在 error_message,前端轮询能看见;后续可手动 `POST /api/v1/eval/runs/{id}/cancel`
- 续跑:再次 `POST /api/v1/eval/runs` 同一个 dataset,会跳过 `eval_run_results` 已写过的 item
- Judge LLM 解析失败 → score=0 + reasoning="judge parse failed: ..." 兜底,不 raise

详见 [modules/rag-evaluation.md](../modules/rag-evaluation.md)。

---

## 7. 场景 7:用户用 Text2SQL 智能问数(M33)

### 7.1 同步路径

```
用户(浏览器)
   │ 1. /dashboard/text2sql → 输入"上月销售 TOP 10 产品"
   ▼
Frontend
   │ 2. POST /api/v1/text2sql/ask { data_source_id, question, async_run: false }
   ▼
Backend
   │ 3. text2sql_service.ask → 写 text2sql_queries 行(status='generating')
   │ 4. Text2SqlEngine.ask(question, data_source):
   │    a. SchemaInspector.get_full_schema_text(隐藏 text2sql_* + alembic_version)
   │    b. Phase 1 循环 ≤3 次:
   │       i.  LLM(qwen2.5:0.5b 硬编码,temperature=0.0)→ raw SQL
   │       ii. SQLGuard.run(sql, max_rows=100, timeout_ms=5000):
   │           - parse / validate_select_only(DML/DDL/SHOW/EXPLAIN 全部黑名单)
   │           - extract_tables + validate_tables(INFORMATION_SCHEMA 存在性 + allowlist)
   │           - extract_columns + validate_columns(qual/unqual + field_allowlist)
   │           - wrap_with_limit(无 LIMIT → 追加 / LIMIT > max_rows → 改写)
   │           - inject_timeout(SELECT 后插 /*+ MAX_EXECUTION_TIME(N) */)
   │       iii. SQLExecutor.execute(rewritten_sql):max_rows+1 检测截断;err 3024 → timeout
   │    c. 成功 → Phase 2:Explanation LLM(call_type="text2sql.explain") + confidence 0~1
   │    d. 写 generated_sql / rows_json / explanation / 2 个 llm_call_id
   │ 5. _apply_result_to_row 映射 14 个字段 → status=success / rejected / failed
   │ 6. NotificationService.publish_event → WS 推 TEXT2SQL_COMPLETED / FAILED
   ▼
Frontend
   │ 7. /history/{query_id} 拉到 rows + explanation + 置信度
```

### 7.2 异步路径(`async_run=true`)
- 立即写 `status='pending'` 行 + 返 `query_id`;FastAPI `BackgroundTasks.add_task(_run_ask, ...)` 进程内调度(不是 Celery)
- 前端 polling `/history/{id}` 直到 status 非 pending

### 7.3 三道防线
1. **SQLGuard 静态校验**:拒绝 DML/DDL/SHOW/EXPLAIN + 表/列 allowlist 校验
2. **数据源配置**:连接用最小权限**只读**账号(运维层面)
3. **执行**:LIMIT 自动注入(默认 100 行)+ MySQL `MAX_EXECUTION_TIME` 5000ms

### 7.4 关键代码位置
- 前端:`frontend/app/dashboard/text2sql/page.tsx` + `components/text2sql/{index,DataSourceManager}.tsx`
- 后端:`backend/lumen_api/v1/{text2sql,text2sql_datasources}.py`
- 引擎:`backend/lumen_services/text2sql/{engine,sql_guard,sql_executor,schema_inspector,prompts,data_source_service}.py` + `text2sql_service.py`
- 数据模型:`backend/lumen_models/text2sql.py`

详见 [modules/text2sql.md](../modules/text2sql.md)。

---

## 8. 跨场景的横切关注点

### 6.1 trace_id 贯穿
- 每次 API 请求生成 trace_id(后端中间件)
- 透传到 LLM call、日志、WS 推送
- 前端 UI: trace_id 查 `/dashboard/logs/trace/[trace_id]`

### 6.2 多租户隔离
- 每个查询带 `tenant_id`(从 token 解析)
- 强制 WHERE `tenant_id = ?`
- 全局资源 `tenant_id IS NULL`(默认 model / stock assets)

### 6.3 错误统一格式
- 所有 endpoint 返回 `SingleResponse[T]` 或 `PaginatedResponse[T]`(`lumen_schemas/common.py`),前端读 `body.code === 200` + `body.data`
- 抛 `HTTPException` 由 envelope exception handler 包成 `{"code": 4xx, "message": "...", "data": null}`
- 系统 5xx 走 FastAPI 默认 handler,也是 3 字段结构(`code=500`, `data=null`)
- 业务 `message` 字段双语: `"已保存 / Saved"`(按 CLAUDE.md §9)

### 6.4 异步任务统一入口
- 长任务走 Celery(`backend/lumen_tasks/*`);短任务 / demo 用 FastAPI 进程内 BackgroundTasks(如 `text2sql/ask` async_run)
- 任务状态统一 5 态: `pending` / `running` / `success` / `failed` / `cancelled`
- 完成 / 失败通知:`NotificationService.publish_event` 先持久化(`db.commit` 在 broadcast 前),再 `electron_service.broadcast_event_sync` 推 WS `notification_created` 事件
- M37 评测按 per-item commit,崩了能续跑;M32 publish 按 `queued → uploading → uploaded → success` 阶段推进

### 6.5 文件存储
- 路径规范: `storage/{module}/{tenant_id}/{date}/{file_id}.{ext}`
- 数据库只存路径 + 元数据
- 二进制不入库

---

**维护者**:全栈架构师
**最近更新**:2026-08-07
