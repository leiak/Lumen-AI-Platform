"""Embedding call-level log persistence model.

M27: per-call observability for embeddings (KB retrieval / KB ingest /
dim probe / workflow KB). Stores one row per ``embed_query`` /
``embed_documents`` invocation. Unlike ``llm_call_logs`` we do NOT
store the full embedding vector (3KB/row at 768d) — only the text
preview (200 chars) + the probed embedding dimension + bytes.

Spec: docs/superpowers/specs/2026-06-15-embedding-trace-retention.md §"数据模型"
"""
from sqlalchemy import (
    Column, Integer, String, Text, JSON, Boolean, ForeignKey, Index, DateTime,
)

from lumen_models.base import BaseModel


class EmbeddingCallLog(BaseModel):
    __tablename__ = "embedding_call_logs"

    # === 身份 ===
    call_id = Column(String(36), unique=True, nullable=False, index=True)
    parent_call_id = Column(String(36), nullable=True, index=True)
    trace_id = Column(String(36), nullable=False, index=True)
    # call_type values:
    #   kb_retrieval      - chat / widget / agent_team / workflow embed for KB retrieval
    #   kb_ingest         - reindex / document upload embed_documents path
    #   dim_probe         - factory cold-start probe (text == "dim-probe")
    #   workflow_kb       - workflow knowledge_retrieval node
    #   system.kb_ingest  - background reindex (no current_user)
    #   eval_retrieval    - M37.2 RAG 评测每次 item 的检索(extra 里有 eval_run_id)
    call_type = Column(String(64), nullable=False)
    call_index = Column(Integer, default=0, nullable=False)

    # === 租户 / 触发者 ===
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    username = Column(String(100), nullable=True)
    client_app = Column(String(50), nullable=True)

    # === 关联实体(可空) ===
    conversation_id = Column(
        Integer, ForeignKey("conversations.id"), nullable=True, index=True,
    )
    agent_id = Column(Integer, ForeignKey("agents.id"), nullable=True, index=True)
    team_id = Column(Integer, ForeignKey("agent_teams.id"), nullable=True, index=True)
    workflow_id = Column(Integer, ForeignKey("workflows.id"), nullable=True, index=True)
    workflow_run_id = Column(
        Integer, ForeignKey("workflow_runs.id"), nullable=True, index=True,
    )
    workflow_node_id = Column(String(64), nullable=True)
    knowledge_base_id = Column(
        Integer, ForeignKey("knowledge_bases.id"), nullable=True, index=True,
    )

    # === 模型 ===
    model_type = Column(String(50), nullable=True)
    model_name = Column(String(100), nullable=False)
    model_config_id = Column(
        Integer, ForeignKey("model_configs.id"), nullable=True, index=True,
    )

    # === 入参(简化版 — embed 没有 system/tools/temperature) ===
    text_preview = Column(String(200), nullable=True)  # first 200 chars
    text_chars = Column(Integer, nullable=True)
    is_batch = Column(Boolean, default=False, nullable=False)  # True for embed_documents
    batch_size = Column(Integer, nullable=True)  # number of texts in embed_documents

    # === 出参(embed 没有 token_usage) ===
    embedding_dim = Column(Integer, nullable=True)  # detected vector dim (768 / 1536 / ...)
    embedding_bytes = Column(Integer, nullable=True)  # byte count: dim * 4 (float32)

    # === 时延 / 状态 ===
    started_at = Column(DateTime, nullable=False)
    finished_at = Column(DateTime, nullable=True)
    duration_ms = Column(Integer, nullable=True)
    status = Column(String(20), default="success", index=True)
    error_type = Column(String(100), nullable=True)
    error_message = Column(Text, nullable=True)
    retry_count = Column(Integer, default=0)

    # === 元数据 ===
    request_ip = Column(String(50), nullable=True)
    user_agent = Column(String(500), nullable=True)
    # extra JSON stores {is_dim_probe: bool, top_k: int, filter_expr: str}
    extra = Column(JSON, nullable=True)

    # === M27 retention ===
    # ``archived_at`` set by ``services/retention.py`` at the soft-delete
    # cutoff. Hard delete removes the row entirely.
    archived_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("idx_ecl_tenant_time", "tenant_id", "created_at"),
        Index("idx_ecl_model_time", "model_config_id", "created_at"),
        Index("idx_ecl_kb", "knowledge_base_id", "created_at"),
        Index("idx_ecl_trace", "trace_id", "call_index"),
        Index("idx_ecl_status_time", "status", "created_at"),
        Index("idx_ecl_call_type_time", "call_type", "created_at"),
    )
