"""M37.2 — Eval Run + Result ORM models.

两张表:`eval_runs` (一次评测运行) + `eval_run_results` (单条 item 的
检索/答案指标 + judge 详情)。

设计要点:

- ``status`` 用 ``String(20)`` 而非 MySQL ENUM,跟 video/text2sql/wx_publisher
  一致 —— 加状态值零 ALTER,只需 docstring 记录取值集合。
- 所有 JSON 列(comment)标了 schema 概要,LLM 端 / API 端靠 Pydantic 校验。
- FK ``run_id → eval_runs.id ON DELETE CASCADE`` + ``item_id → eval_dataset_items.id
  ON DELETE CASCADE`` —— 删 run 顺手清 results,删 dataset 清 runs + results。
- ``trace_id``(VARCHAR(36))关联 EmbeddingCallLog / LLMCallLog 的 trace,便于
  M37.3 dashboard 跳转到 trace 页。
- ``llm_judge_calls`` 存 ``[{metric, score, reasoning, llm_call_log_id}, ...]``
  供审计 + 二次分析(比如 faithfulness=0 时回看 reasoning)。
- ``embedding_call_log_ids`` JSON list[int] 关联本条 item 检索期间的
  EmbeddingCallLog 行 id,同理供 audit。

Spec: docs-internal/superpowers/specs/m37-rag-evaluation.md §4.2
Plan: docs-internal/superpowers/plans/m37-plan.md CP3 T8
"""
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    JSON,
)
from sqlalchemy.orm import relationship

from .base import BaseModel


# M37.2 status 取值集合(写在 ORM docstring 里,避免反复查 spec):
#   pending    —— run 已创建,worker 还没 pickup
#   running    —— worker 正在跑
#   completed  —— 全部 item 完成,metrics_json + report_markdown 已生成
#   failed     —— 跑崩了,error_message 里有 root cause
#   cancelled  —— 用户主动 cancel
EVAL_RUN_STATUSES = ("pending", "running", "completed", "failed", "cancelled")


class EvalRun(BaseModel):
    """一次评测运行的元数据 + 进度 + 聚合结果。

    跨表关系:
    - ``dataset`` 反向引到 EvalDataset
    - ``results`` 一对多 EvalRunResult(run 删除时 CASCADE 清 results)

    ``metrics_json``(整体聚合)+ ``report_markdown``(≤ 50KB 人类可读报告)
    在所有 result 写完后由 report.py 一次性生成。
    """

    __tablename__ = "eval_runs"

    dataset_id = Column(
        Integer,
        ForeignKey("eval_datasets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="绑定的 eval_datasets.id;dataset 删除时 CASCADE 清 run + results",
    )

    # 完整评测配置(JSON):{
    #   search_weights: {title, important_kw, question_kw, text},
    #   top_k: int,
    #   rerank: bool,
    #   rerank_top_n: int,
    #   embedding_model_config_id: int,
    #   judge_model_config_id: int,
    #   chunking_strategy: str,
    #   judge_metrics: List[str],   # ["faithfulness", "answer_relevancy"]
    #   name: str,                  # 用户起的 run 别名
    #   ...
    # }
    config_json = Column(
        JSON,
        nullable=False,
        comment="评测参数全集(JSON),含 search_weights / top_k / rerank / judge model 等",
    )

    status = Column(
        String(20),
        nullable=False,
        default="pending",
        comment="pending / running / completed / failed / cancelled",
    )

    # 进度字段:total_items 在启动时一次性写入 dataset 的 item 数,
    # completed_items 每跑完 1 条 +1,前端轮询看进度
    total_items = Column(Integer, nullable=False, default=0)
    completed_items = Column(Integer, nullable=False, default=0)

    # 整体聚合指标(JSON),格式见 spec §4.2 示例:
    #   {retrieval: {...}, answer: {...}, by_category: {...}, by_difficulty: {...}}
    metrics_json = Column(
        JSON,
        nullable=True,
        comment="整体聚合指标;所有 results 写完后由 report.py 一次性生成",
    )

    # 自动生成的 Markdown 报告(≤ 50KB),dashboard 直接渲染
    report_markdown = Column(
        Text,
        nullable=True,
        comment="自动生成的 Markdown 报告,≤ 50KB;dashboard 直接渲染",
    )

    error_message = Column(
        Text,
        nullable=True,
        comment="status=failed 时的 root cause,前端展示",
    )

    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)

    created_by = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        comment="触发此 run 的 user id;user 删了保留 run(SET NULL)",
    )

    # 关联 EmbeddingCallLog / LLMCallLog 的 trace_id,便于 dashboard 跳转
    trace_id = Column(
        String(36),
        nullable=True,
        index=True,
        comment="关联 LLMCallLog/EmbeddingCallLog 的 trace_id",
    )

    # 关系
    dataset = relationship("EvalDataset", backref="runs")
    results = relationship(
        "EvalRunResult",
        backref="run",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        Index("idx_eval_run_ds_time", "dataset_id", "created_at"),
        Index("idx_eval_run_status_time", "status", "created_at"),
    )


class EvalRunResult(BaseModel):
    """单条 item 的检索结果 + 答案 + 指标 + judge 调用详情。

    设计:一条 item 一行,跑完立刻写库 + commit(plan §D5 "per-item commit +
    崩了能续跑"),runner 下次启动时通过 WHERE error_message IS NULL 跳过
    已成功的行。
    """

    __tablename__ = "eval_run_results"

    run_id = Column(
        Integer,
        ForeignKey("eval_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="关联 eval_runs.id;run 删了 CASCADE 清 results",
    )
    item_id = Column(
        Integer,
        ForeignKey("eval_dataset_items.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="关联 eval_dataset_items.id;item 删了 CASCADE 清 results",
    )

    # query 冗余存 —— item 可能被改 / 删,这里保留评测当时的 query 文本
    # 供 report 渲染 + audit
    query = Column(Text, nullable=False, comment="评测当时的 query 文本(冗余)")

    # 检索明细:实际命中的 doc_ids + 每个 doc 的 score + 截断后的 chunk text
    retrieved_doc_ids = Column(
        JSON,
        nullable=False,
        comment="实际检索命中的 document id 列表(JSON list[int])",
    )
    retrieval_scores = Column(
        JSON,
        nullable=False,
        comment="每个 doc 的 score(JSON list[float]),与 retrieved_doc_ids 同序",
    )
    retrieved_contexts = Column(
        JSON,
        nullable=True,
        comment="截断后的 chunk text 列表(≤ 200 字/个),供 audit + judge faithfulness",
    )

    # RAG 生成的答案(answer 阶段调 chat),None 表示 answer 阶段崩了
    answer = Column(
        Text,
        nullable=True,
        comment="LLM 生成的最终答案(RAG 拼装);None = answer 阶段失败",
    )

    # 检索指标(JSON):{hit_at_5, hit_at_10, mrr, ndcg_at_10, recall_at_10}
    retrieval_metrics = Column(
        JSON,
        nullable=False,
        comment="检索指标:hit_at_5/10, mrr, ndcg_at_10, recall_at_10",
    )

    # 答案指标(JSON):{faithfulness, answer_relevancy, keyword_hit_rate}
    # None 表示没跑答案指标(例如 out_of_scope 类跳过 answer 阶段)
    answer_metrics = Column(
        JSON,
        nullable=True,
        comment="答案指标:faithfulness/answer_relevancy(0/1/2)+ keyword_hit_rate(0~1)",
    )

    # judge 调用详情,审计用:[{metric, score, reasoning, llm_call_log_id}, ...]
    llm_judge_calls = Column(
        JSON,
        nullable=True,
        comment="judge LLM 调用详情(供 audit / faithfulness=0 时回看 reasoning)",
    )

    latency_ms = Column(
        Integer,
        nullable=True,
        comment="单条 item 总耗时(retrieval + answer + judge),report 用 p50/p95",
    )

    # 关联本次检索期间的 EmbeddingCallLog 行 id 列表 —— 跳转 trace
    embedding_call_log_ids = Column(
        JSON,
        nullable=True,
        comment="本次检索期间的 EmbeddingCallLog 行 id 列表(跳转 trace 用)",
    )

    error_message = Column(
        Text,
        nullable=True,
        comment="单条 item 跑崩时的 root cause;run.status 仍 completed 但本行失败",
    )

    __table_args__ = (
        Index("idx_eval_result_run_item", "run_id", "item_id"),
    )