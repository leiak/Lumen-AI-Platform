"""M37.2: Pydantic schemas for /api/v1/eval/runs/*.

Eval Run 是「一次评测运行」的元数据 + 进度 + 聚合指标。Create 时客户端
提供 dataset_id + EvalRunConfig(检索参数 + judge 模型);Worker 跑完
每条 item 立即 commit 一行 EvalRunResult,跑完所有 item 由 report.py
聚合成 metrics_json + report_markdown。

设计要点(跟 M37.1 eval_dataset / M35 tts / M36 video 一致):

- EvalRunStatus 用 ``Literal[...]`` 而非 MySQL ENUM —— 加状态零
  ALTER,docstring 列出取值集合(参见 eval_run.py ORM)。
- Read schema ``model_config = ConfigDict(from_attributes=True)``,
  service 层 ``EvalRunRead.model_validate(row)`` 直转 ORM。
- EvalRunConfig 是嵌套 BaseModel —— Pydantic 会嵌套校验所有字段;
  客户端 JSON 跟 service 接受的 dict 结构对齐,免一次手抄字段。
- EvalRunResultMetrics 嵌套 RetrievalMetrics + AnswerMetrics,跟
  ORM 的 JSON 列字段名一一对应(``retrieval_metrics`` / ``answer_metrics``)。
- Compare 系列带 ``per_item_delta``(逐条 diff)+ ``aggregate_delta``
  (整体 diff)+ ``winners: Dict[metric, "a"|"b"|"tie"]`` —— 给 dashboard
  的对比页直接渲染,前端不用再算。

Spec: docs-internal/superpowers/specs/m37-rag-evaluation.md §4.2
Plan: docs-internal/superpowers/plans/m37-plan.md CP3 T9
"""
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Enum Literals
# ---------------------------------------------------------------------------

# 跟 lumen_models.eval_run.EVAL_RUN_STATUSES 一致,加状态零 ALTER。
EvalRunStatus = Literal[
    "pending", "running", "completed", "failed", "cancelled"
]

# judge 跑的答案指标 —— 检索指标(hit/mrr/ndcg/recall)是纯规则不算。
EvalRunJudgeMetric = Literal["faithfulness", "answer_relevancy"]


# ---------------------------------------------------------------------------
# EvalRunConfig — Create body 嵌套的「评测配置」
# ---------------------------------------------------------------------------

class EvalRunConfig(BaseModel):
    """一次评测的配置全集。

    字段语义:

    - ``name``: 可选 run 别名(用户起的"baseline"/"rerank-on"之类),落
      ``config_json`` 同名字段,前端列表显示用。
    - ``search_weights``: M28 KB 配置的 4 维权重(title / important_kw /
      question_kw / text)—— 传给 RetrievalPipeline 走 production 一样的
      hybrid 路径,这是评测能反映 production 行为的关键。
    - ``top_k`` / ``rerank`` / ``rerank_top_n``: 检索 + rerank 参数。
    - ``embedding_model_config_id`` / ``judge_model_config_id``: 模型配置
      表外键 —— 评测不能用 chat 同模型 judge 自评自。
    - ``chunking_strategy``: 字符串(M29 的 chunking 配置名,留给 report
      显示;不在 runner 里影响检索,因为 chunk 在 ingest 时已定)。
    - ``judge_metrics``: 跑哪几个答案指标 —— 默认跑 faithfulness +
      answer_relevancy;keyword_hit_rate 是规则不算 LLM,默认必跑。

    ``chunking_strategy`` 可选因为 KB 已经决定怎么切;不传 = 用 KB 的
    当前策略,不重新分块。
    """

    name: Optional[str] = Field(default=None, max_length=200)
    search_weights: Dict[str, float] = Field(
        default_factory=dict,
        description="M28 KB search_weights 4 维权重(title/important_kw/question_kw/text)",
    )
    top_k: int = Field(default=10, ge=1, le=100)
    rerank: bool = True
    rerank_top_n: int = Field(default=5, ge=1, le=50)
    embedding_model_config_id: int = Field(ge=1)
    judge_model_config_id: int = Field(ge=1)
    chunking_strategy: Optional[str] = Field(default=None, max_length=64)
    judge_metrics: List[EvalRunJudgeMetric] = Field(
        default_factory=lambda: ["faithfulness", "answer_relevancy"],
    )


# ---------------------------------------------------------------------------
# EvalRunCreate — POST /api/v1/eval/runs/ body
# ---------------------------------------------------------------------------

class EvalRunCreate(BaseModel):
    """Body for ``POST /api/v1/eval/runs/``.

    - ``dataset_id``: 必填;绑到 eval_datasets.id(tenant 可见性由 service
      层校验,跨租户 dataset → 404)。
    - ``config``: EvalRunConfig 嵌套,见上。
    - ``trace_id`` **可选** —— 客户端发起评测时如已有 trace,带上便于
      service 层关联 dashboard 跳转;不传 = service 自动生成 UUID。
    """

    dataset_id: int = Field(ge=1)
    config: EvalRunConfig
    trace_id: Optional[str] = Field(default=None, max_length=36)


# ---------------------------------------------------------------------------
# EvalRunRead — 单条 run 详情 shape(给 GET /runs/{id})
# ---------------------------------------------------------------------------

class EvalRunListItem(BaseModel):
    """列表页 row shape —— 轻量,不含 report_markdown(markdown 可能 50KB)。

    service 层 list 查询时 ``COUNT(eval_run_results WHERE run_id=X)``
    填 ``completed_count``(实际进度),不放 ORM 列上。
    """

    model_config = ConfigDict(from_attributes=True, protected_namespaces=())

    id: int
    dataset_id: int
    status: EvalRunStatus
    total_items: int
    completed_items: int
    # service 层填的派生字段,ORM 没列
    completed_count: Optional[int] = None
    error_message: Optional[str] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    created_by: Optional[int] = None


class EvalRunRead(EvalRunListItem):
    """详情 shape —— ListItem + config_json 反序列化 + metrics_json 摘要。

    ``config`` 反序列化时把 ``config_json`` ORM 列(JSON dict)再喂给
    EvalRunConfig 校验 —— 服务端是 source of truth,前端可以靠这个
    schema 反查每条 run 当时跑的具体参数。
    """

    config: EvalRunConfig
    metrics_json: Optional[Dict[str, Any]] = None
    report_markdown: Optional[str] = Field(
        default=None,
        description="自动生成的 Markdown 报告,≤ 50KB;dashboard 直接渲染",
    )
    trace_id: Optional[str] = None


# ---------------------------------------------------------------------------
# RetrievalMetrics / AnswerMetrics — 单条 item 的指标
# ---------------------------------------------------------------------------

class RetrievalMetrics(BaseModel):
    """单条 item 的检索指标。

    字段对照 ``lumen_services.eval.metrics`` 第一节:hit_at_k / mrr /
    ndcg_at_k / recall_at_k。Runner 跑完一条 item 立即算,跟 ORM 的
    ``retrieval_metrics`` JSON 列字段名一致(便于 Pydantic 直 validate
    存储的 dict)。
    """

    model_config = ConfigDict(extra="ignore")

    hit_at_5: float = Field(ge=0.0, le=1.0)
    hit_at_10: float = Field(ge=0.0, le=1.0)
    mrr: float = Field(ge=0.0, le=1.0)
    ndcg_at_10: float = Field(ge=0.0, le=1.0)
    recall_at_10: float = Field(ge=0.0, le=1.0)


class AnswerMetrics(BaseModel):
    """单条 item 的答案指标。

    - ``faithfulness`` / ``answer_relevancy``: judge 输出 0/1/2 三档,
      service 层算 mean 后落库(0.0~2.0)。
    - ``keyword_hit_rate``: 规则,0.0~1.0。
    - 整体可以为 None —— out_of_scope item 跳过 answer 阶段不 judge。
    """

    model_config = ConfigDict(extra="ignore")

    faithfulness: Optional[float] = Field(default=None, ge=0.0, le=2.0)
    answer_relevancy: Optional[float] = Field(default=None, ge=0.0, le=2.0)
    keyword_hit_rate: float = Field(ge=0.0, le=1.0)


class EvalRunResultMetrics(BaseModel):
    """单条 item 的「检索 + 答案」指标组合 —— 跟 ORM 的
    ``retrieval_metrics`` + ``answer_metrics`` 两列对齐。
    """

    retrieval: RetrievalMetrics
    answer: Optional[AnswerMetrics] = None


class EvalRunResultRead(BaseModel):
    """单条 item 的完整评测结果 shape —— 给 dashboard 跑完 run 后逐条查看用。

    ORM 直 validate:``retrieval_metrics`` / ``answer_metrics`` 是 JSON 列,
    EvalRunResultMetrics 会嵌套校验。``llm_judge_calls`` 跟
    ``embedding_call_log_ids`` 是 raw JSON list,不强行 schema(供 audit
    二次分析用,前端展示时再 Pydantic 二次校验单条)。
    """

    model_config = ConfigDict(from_attributes=True, protected_namespaces=())

    id: int
    run_id: int
    item_id: int
    query: str
    retrieved_doc_ids: List[int]
    retrieval_scores: List[float]
    retrieved_contexts: Optional[List[str]] = None
    answer: Optional[str] = None
    retrieval_metrics: RetrievalMetrics
    answer_metrics: Optional[AnswerMetrics] = None
    llm_judge_calls: Optional[List[Dict[str, Any]]] = None
    latency_ms: Optional[int] = None
    embedding_call_log_ids: Optional[List[int]] = None
    error_message: Optional[str] = None
    created_at: datetime


class EvalRunReadWithResults(EvalRunRead):
    """详情 + 该 run 所有 item 结果 —— 给 dashboard 跑完后的详情页用。

    分页由 ``results_page`` / ``results_total`` 控制,跟
    PaginatedResponse 语义一致;service 层 list 查询时 ``OFFSET/LIMIT``。
    """

    results: List[EvalRunResultRead] = Field(default_factory=list)
    results_total: int = 0
    results_page: int = 1
    results_page_size: int = 50


# ---------------------------------------------------------------------------
# EvalRunCancel — POST /api/v1/eval/runs/{id}/cancel body
# ---------------------------------------------------------------------------

class EvalRunCancel(BaseModel):
    """Body for ``POST /api/v1/eval/runs/{id}/cancel``。

    空 body 也接受(默认 reason="user cancel");带 reason 让 service
    层写 run.error_message,前端列表展示给操作者看"为什么被取消"。
    """

    reason: Optional[str] = Field(default=None, max_length=500)


# ---------------------------------------------------------------------------
# Compare — POST /api/v1/eval/runs/compare
# ---------------------------------------------------------------------------

class EvalRunCompareRequest(BaseModel):
    """Body for ``POST /api/v1/eval/runs/compare`。

    两个 run 必填且必须属同一个 dataset(否则 metric 无可比性 —— 不同
    KB 检索结果完全不同)。Service 层校验。
    """

    run_id_a: int = Field(ge=1)
    run_id_b: int = Field(ge=1)


class EvalRunCompareItemDelta(BaseModel):
    """两条 run 在同一条 item 上的逐条 diff。

    ``item_id`` 是锚点(a/b 都跑过这条),``query`` 冗余便于 dashboard
    显示。``retrieval_delta`` / ``answer_delta`` 是 a→b 的符号差值
    (b - a);正 = b 更好。
    """

    item_id: int
    query: str
    retrieval_delta: Optional[Dict[str, float]] = None
    answer_delta: Optional[Dict[str, float]] = None


class EvalRunCompareWinner(BaseModel):
    """两条 run 在某个 metric 维度的胜负。

    ``winner`` = "a" / "b" / "tie";``delta`` 是 b-a 差值(0 = tie);
    ``pct`` 是 delta 相对 a 的百分比(NaN/Infinity 由前端展示兜底)。
    """

    metric: str
    winner: Literal["a", "b", "tie"]
    delta: float
    pct: Optional[float] = None


class EvalRunCompareResponse(BaseModel):
    """Compare 响应 —— 给 dashboard 对比页一次渲染用全。

    ``per_item_delta`` 按 ``item_id`` 升序;``aggregate_delta`` 是按
    metric 聚合的 mean 差值;``winners`` 给整体赢家(aggregate 的
    sign 判断 —— 阈值 ±0.005 内 = tie,跟 plan 阈值一致)。
    """

    run_id_a: int
    run_id_b: int
    per_item_delta: List[EvalRunCompareItemDelta] = Field(default_factory=list)
    aggregate_delta: Dict[str, float] = Field(default_factory=dict)
    winners: List[EvalRunCompareWinner] = Field(default_factory=list)
