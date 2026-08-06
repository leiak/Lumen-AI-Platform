"""M37.1: Eval dataset ORM for RAG evaluation suite.

A dataset is a curated list of golden queries + expected document IDs +
optional ground-truth answers, used to measure retrieval quality and answer
quality of the RAG pipeline. Each dataset is bound to exactly one KB so
that retrieval metrics are well-scoped (Hit@K / MRR only make sense when
you know which KB to search in).

Design notes:

- ``tenant_id`` is intentionally nullable. ``NULL`` marks a builtin
  dataset visible to every tenant (admin-curated baselines); a non-null
  value scopes the dataset to one tenant. Same convention as
  ``StockAsset.tenant_id`` (M36.2.1).
- ``source`` is a free-form string (``"manual"`` / ``"imported"`` /
  ``"synthetic"``) rather than a MySQL ENUM, matching project house style
  — see ``StockAsset.source`` and ``Skill.type``. The service layer
  enforces the allowed set.
- ``expected_doc_ids`` is JSON (list of int). We don't model a join
  table because the KB schema is open-ended and the user may want to
  assert partial relevance (rank a doc as "expected at rank 3" instead of
  just "expected somewhere in top-k"). The eval runner turns this list
  into the boolean relevance set used by Hit@K / MRR / NDCG.
- ``answer_keywords`` is JSON (list of str) — used by the cheap
  ``keyword_hit_rate`` answer metric. When set, the LLM judge can be
  skipped for fast regression runs.
- ``category`` / ``difficulty`` let the dashboard slice metrics
  (e.g. "reasoning hit@5 = 0.40 vs factual hit@5 = 0.95") so failures
  point to a category, not just an aggregate number.
- ``is_active`` uses Integer 0/1 (not MySQL TINYINT or Boolean) to match
  project house style — see ``StockAsset``, ``ModelConfig.is_default``.
- FK actions: CASCADE on KB / dataset so deleting a KB sweeps its
  golden queries; SET NULL on created_by so user deletion doesn't lose
  the dataset.

Spec: docs-internal/superpowers/specs/m37-rag-evaluation.md §4.1
"""
from sqlalchemy import (
    Column, Integer, String, Text, JSON, ForeignKey, Index,
)
from sqlalchemy.orm import relationship

from lumen_models.base import BaseModel


class EvalDataset(BaseModel):
    __tablename__ = "eval_datasets"

    # KB this dataset evaluates. Tenant isolation is enforced
    # via JOIN on knowledge_bases.tenant_id at the API layer
    # (mirrors the Document / FAQEntry convention).
    kb_id = Column(
        Integer,
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="关联知识库 ID,CASCADE 删除",
    )
    # NULL = 内置 / 全局可见 builtin dataset,所有租户可读
    tenant_id = Column(
        Integer,
        ForeignKey("tenants.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="NULL = 全局 builtin,数字 = 私有 tenant",
    )
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    # "manual" / "imported" / "synthetic" —— 项目惯例不用 MySQL ENUM
    source = Column(
        String(20),
        nullable=False,
        default="manual",
        comment="manual | imported | synthetic",
    )
    # 1 启用 / 0 停用 —— Integer 0/1 跟项目其它 status 字段一致
    is_active = Column(
        Integer,
        nullable=False,
        default=1,
        comment="1 启用 / 0 停用",
    )
    created_by = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        comment="NULL = 内置种子数据集",
    )

    items = relationship(
        "EvalDatasetItem",
        back_populates="dataset",
        cascade="all, delete-orphan",
    )
    kb = relationship("KnowledgeBase")

    __table_args__ = (
        Index("ix_eval_datasets_kb_active", "kb_id", "is_active"),
    )


class EvalDatasetItem(BaseModel):
    __tablename__ = "eval_dataset_items"

    dataset_id = Column(
        Integer,
        ForeignKey("eval_datasets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="父 dataset,CASCADE 删除",
    )
    query = Column(Text, nullable=False, comment="评测 query,纯文本")
    # JSON list of int: expected document IDs that should appear in
    # top-k. The runner turns this into a relevance set for retrieval
    # metrics. Empty list == "out of scope" item (answer metric only).
    expected_doc_ids = Column(
        JSON,
        nullable=False,
        comment="期望命中的 document_id 列表,JSON 数组",
    )
    expected_answer = Column(
        Text,
        nullable=True,
        comment="ground truth 答案,可选,LLM judge 用",
    )
    answer_keywords = Column(
        JSON,
        nullable=True,
        comment="期望答案关键词,JSON 字符串数组,keyword_hit_rate 用",
    )
    # "factual" / "reasoning" / "multi_hop" / "keyword_heavy" / "out_of_scope"
    category = Column(
        String(64),
        nullable=True,
        index=True,
        comment="factual | reasoning | multi_hop | keyword_heavy | out_of_scope",
    )
    # "easy" / "medium" / "hard"
    difficulty = Column(
        String(20),
        nullable=True,
        default="medium",
        comment="easy | medium | hard",
    )
    notes = Column(Text, nullable=True, comment="研发 / QA 备注")

    dataset = relationship("EvalDataset", back_populates="items")

    __table_args__ = (
        Index("ix_eval_dataset_items_ds_category", "dataset_id", "category"),
    )