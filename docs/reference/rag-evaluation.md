# RAG 评测体系(M37)

> Reference — 信息查阅型文档。想知道「某个指标怎么算」「某个 endpoint 收什么参数」查这里。
> 想动手跑一次评测,直接看本文末尾的「快速上手」。

RAG 评测体系解决一个具体问题:改了 `chunk_size`、换了 embedding 模型、调了
`search_weights` 之后,**检索到底变好了还是变差了**?靠人工翻几个 query 看
感觉不可靠,所以固化成 golden dataset + 可重复的指标 run。

组成:

| 模块 | 位置 |
|------|------|
| 评测集(golden dataset)管理 | `/dashboard/eval/datasets` |
| 评测运行 + 报告 | `/dashboard/eval/runs/[id]` |
| 后端 API | `/api/v1/eval/datasets/*` + `/api/v1/eval/runs/*` |
| 评测循环 | `backend/lumen_services/eval/runner.py` |
| CLI 直跑 | `backend/scripts/run_rag_eval.py` |
| Celery task | `backend/lumen_tasks/eval_tasks.py`(task 名 `run_rag_eval`) |

---

## 1. 数据模型

两张表,parent / child 关系。

### `eval_datasets` — 评测集

| 字段 | 说明 |
|------|------|
| `kb_id` | 绑定的知识库。**建后不可改** —— 换 KB 等于换了被测对象,历史 run 会失去可比性 |
| `tenant_id` | `NULL` 表示 **builtin**(全租户可见,只读);非空则只有该租户可见 |
| `name` | 同一 tenant 下唯一 |
| `source` | `manual` / `imported` / `synthetic` |
| `is_active` | `1` / `0`,停用的不在下拉里出现 |

### `eval_dataset_items` — 评测集条目

| 字段 | 说明 |
|------|------|
| `query` | 必填,被评测的问题 |
| `expected_doc_ids` | JSON 数组,期望被检索命中的 `documents.id`。**检索指标全靠它**,空数组表示期望检索不到(out_of_scope) |
| `expected_answer` | 参考答案,人工 review 用;当前不参与自动打分 |
| `answer_keywords` | JSON 数组,喂给 `keyword_hit_rate` 做 substring 匹配 |
| `category` | `factual` / `reasoning` / `multi_hop` / `keyword_heavy` / `out_of_scope`,报告按此分桶 |
| `difficulty` | `easy` / `medium` / `hard`,报告按此分桶 |
| `notes` | 维护者备注 |

### `eval_runs` / `eval_run_results` — 一次评测 + 每条 item 的明细

`eval_runs` 存 `config_json`(见 §3)、`status`、`total_items` /
`completed_items`(前端轮询进度)、`metrics_json`(聚合指标)、
`report_markdown`(Markdown 报告)、`trace_id`。

`status` 取值:`pending` → `running` → `completed` / `failed` / `cancelled`。

`eval_run_results` 一行一条 item:`retrieved_doc_ids`、`retrieval_scores`、
`retrieved_contexts`(每条截断到 200 字)、`answer`、`retrieval_metrics`、
`answer_metrics`、`llm_judge_calls`、`latency_ms`、`error_message`。

---

## 2. 指标

### 2.1 检索指标(纯规则,不花钱)

设 `retrieved` 为按相关度降序的 doc id 列表,`expected` 为 `expected_doc_ids`。

| 指标 | 含义 |
|------|------|
| `hit_at_5` / `hit_at_10` | 前 K 个结果里是否至少命中一个 expected;命中 `1.0` 否则 `0.0` |
| `mrr` | 第一个命中结果排名的倒数(排第 1 得 `1.0`,排第 3 得 `0.333`,没命中 `0.0`) |
| `ndcg_at_10` | 归一化折损累计增益,兼顾「命中了几个」和「排得多靠前」 |
| `recall_at_10` | 前 10 个结果覆盖了 expected 里多大比例 |

`expected` 为空数组时所有检索指标返 `0.0` —— 没有目标就没有命中可言。

> 实现:`backend/lumen_services/eval/metrics.py`

### 2.2 答案指标(需要 LLM,要花钱)

前提:`config.judge_metrics` 非空 **且** `config.judge_model_config_id` 有值。
两个条件缺一个就整段跳过,`answer` / `answer_metrics` 落 `NULL` —— 纯调检索
参数时不必付 LLM 成本。

流程是「先生成答案,再让 judge 给答案打分」:

1. **生成答案** —— 用检索到的 contexts + query 拼 prompt 调 chat 模型
   (`lumen_services/eval/answer.py`,`call_type="eval_answer"`)。
   contexts 为空时 prompt 显式引导拒答。
2. **打分**:

| 指标 | 取值 | 怎么算 |
|------|------|--------|
| `keyword_hit_rate` | `0.0` ~ `1.0` | 规则:`answer_keywords` 中有多少个以子串形式出现在答案里。大小写不敏感,纯空白关键词被忽略 |
| `faithfulness` | `0` / `1` / `2` | LLM judge:答案是否被 retrieved contexts 支撑。`2`=完全支撑,`1`=部分支撑有少量推断,`0`=捏造或大量外部知识 |
| `answer_relevancy` | `0` / `1` / `2` | LLM judge:答案是否真的回答了 query |

judge 输出走严格 Pydantic schema(`extra="forbid"`),解析失败或 LLM 调用
失败**不 raise**,统一返 `score=0` + `reasoning="judge parse failed: ..."`,
让 run 跑完剩下的 item。

答案生成失败(模型挂 / 配置被删)→ `answer=None`,judge 跳过不浪费调用,
但 `keyword_hit_rate` 仍按空答案落 `0.0`,这样报告里能区分「没跑」
(`answer_metrics=NULL`)和「跑了但没命中」(`keyword_hit_rate=0.0`)。

judge 的每次调用都写 `LLMCallLog`,`call_type="eval_judge"`,
`extra={"eval_run_id": X, "eval_metric": "faithfulness"}` —— 零 ALTER TABLE
就能从 trace 跳回 eval run。

### 2.3 聚合报告

`metrics_json` 结构:

```json
{
  "retrieval": { "hit_at_5": 0.63, "mrr": 0.51, "ndcg_at_10": 0.58, "latency_ms_p50": 820 },
  "answer": {
    "keyword_hit_rate": 0.6167,
    "faithfulness_avg": 1.5333,
    "answer_relevancy_avg": 1.7,
    "llm_judge_total_calls": 60
  },
  "by_category": { "factual": { }, "out_of_scope": { } },
  "by_difficulty": { "easy": { }, "hard": { } },
  "totals": { "items_total": 30, "items_success": 30, "items_failed": 0 }
}
```

`report_markdown` 是同一份数据的 Markdown 渲染,含 by_category /
by_difficulty 分桶表和 top failures 列表。

---

## 3. 评测 config

存在 `eval_runs.config_json`。默认值由
`backend/lumen_scripts/seed_m37_default_eval_config.py` 写进
`system_configs.eval_default_config`。

| 字段 | 说明 |
|------|------|
| `top_k` | 检索返回条数,默认 `10` |
| `rerank` | 是否走 rerank,默认 `true` |
| `search_weights` | 字段权重 `{title, important_kw, question_kw, text}`,跟 KB 检索配置同构 |
| `embedding_model_config_id` | **必须与 KB 的一致**,否则 run 直接 `failed` |
| `judge_model_config_id` | judge + 答案生成用哪个 chat 模型 |
| `judge_metrics` | `["faithfulness", "answer_relevancy"]`;设成 `[]` 则完全跳过 LLM |

> **embedding 一致性校验**:KB 的 embedding 模型在 M13 之后是建库时锁定的,
> collection 维度跟着它走。评测若用别的 embedding 模型,检索会全 0 命中而
> 且看不出原因,所以 runner 在开跑前就硬校验并让整个 run `failed`,
> `error_message` 写明两边的 id。

---

## 4. API

响应统一走 `SingleResponse[T]` / `PaginatedResponse[T]` 信封。

### 评测集 `/api/v1/eval/datasets`

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` | 列表,支持 `kb_id` / `page` / `page_size`;含 builtin |
| POST | `/` | 创建,`tenant_id` 由后端从当前用户推导 |
| GET | `/{dataset_id}` | 详情(比列表多 `description` + `created_by`) |
| PUT | `/{dataset_id}` | 部分更新;`kb_id` 不可改 |
| DELETE | `/{dataset_id}` | 级联删除 items |
| GET | `/{dataset_id}/items` | item 分页列表 |
| POST | `/{dataset_id}/items` | 加一条 item |
| PATCH | `/{dataset_id}/items/{item_id}` | 编辑单条,PATCH 语义(后端 `exclude_none=True`,只覆盖传了的字段) |
| POST | `/{dataset_id}/items/bulk-import` | 批量导入 |
| DELETE | `/{dataset_id}/items/{item_id}` | 删单条 |

**bulk-import 是整批 200 OK**,不是全或无:响应
`{imported_count, failed_count, partial_errors: [{row_index, error}]}`,
`row_index` 与请求 `rows` 下标一致,前端据此高亮错误行。

### 评测运行 `/api/v1/eval/runs`

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` | run 列表 |
| POST | `/` | 创建 run 并投递 Celery task,立即返回(`status=pending`) |
| GET | `/{run_id}` | 详情,含每条 item 的 results;前端靠轮询它看进度 |
| POST | `/{run_id}/cancel` | 取消;runner 在每条 item 前检查,检测到即退出 |
| POST | `/compare` | 传两个 run id,返回逐指标 delta + winner |

**租户隔离**:非 builtin 的 dataset / run 只有所属租户能读写;builtin
dataset(`tenant_id IS NULL`)所有租户可读但不可改。

---

## 5. 执行语义

- **per-item commit**:每条 item 跑完立刻写一行 `eval_run_results` 并
  commit。进程崩了重跑同一个 run 会跳过已完成的 item 继续跑,不从头来。
- **单条失败不拖垮整 run**:item 级异常写一行带 `error_message` 的 result,
  检索指标全 `0.0`,然后继续下一条。
- **幂等**:`status` 已是 `completed` / `failed` / `cancelled` 的 run 再调
  `run_eval()` 直接返回 —— 防止 Celery 重试或用户重复点击把进度归零。
- **进度节流**:`completed_items` 每 10% 才 UPDATE 一次,避免写放大。

---

## 6. 快速上手

### 建评测集

UI:`/dashboard/eval/datasets` → 新建 → 选 KB → 逐条加 item 或用「批量导入」
贴 JSON。

或者跑 seed 脚本,直接得到一个 30 条的 builtin demo 集(5 类 × 6 条,
含 `expected_answer` + `answer_keywords`):

```bash
cd backend && python -m lumen_scripts.seed_eval_dataset_default
```

### 跑评测

UI:评测集列表点「跑这个评测集」→ 自动跳到 run 详情页看实时进度。

CLI 直跑(不依赖 Celery worker,改完检索参数想立刻看 hit@5 时最方便):

```bash
cd backend && python scripts/run_rag_eval.py \
    --dataset-id 57 \
    --config-json /path/to/config.json
```

`--config-json` 省略则读 `system_configs.eval_default_config`。

### 只看检索、不花 LLM 钱

config 里把 `judge_metrics` 设成 `[]`:

```json
{ "top_k": 10, "rerank": false, "judge_metrics": [] }
```

答案生成和 judge 会被整段跳过,只算 hit@K / MRR / NDCG / recall。

---

## 7. 排错

| 症状 | 原因 |
|------|------|
| run 一直 `pending` | Celery worker 没起,或没加载 `run_rag_eval` task。`docker logs lumen-platform-celery` 看是不是 `KeyError: 'run_rag_eval'`,是则 `docker restart lumen-platform-celery` |
| run `failed`,error 提到 `embedding_model_config_id 不匹配` | config 里的 embedding 模型跟 KB 锁定的不是同一个,改 config 或别传该字段(会自动跟 KB) |
| 检索指标全 `0.0` | 多半是 `expected_doc_ids` 填的 doc 根本不在这个 KB 里,或压根没填 |
| `faithfulness` 全 `0` 且 reasoning 是 `judge parse failed` | judge 模型输出不是合法 JSON。换个更强的 judge 模型,小模型(如 0.5b)经常包不住 JSON 格式 |
| `llm_judge_total_calls` 是 `0` | `judge_metrics` 是空数组,或 `judge_model_config_id` 没配 |

---

## 相关

- 后端响应信封契约:`CLAUDE.md` §2
- 指标算法参考 [RAGAS](https://docs.ragas.io/) —— 本实现自写以保持代码风格一致,不依赖该库
