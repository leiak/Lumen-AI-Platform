"""LLM call-level log persistence model.

M26: per-call observability for chat / widget / agent_team / workflow /
image_generation. Stores one row per LLM invocation, including the full
input messages list, the full response, and tool-call round details.

Spec: docs/superpowers/specs/2026-06-14-llm-call-logging-design.md §"数据模型"
"""
from sqlalchemy import (
    Column, Integer, String, Text, JSON, Float, ForeignKey, Index, DateTime,
)
from sqlalchemy.sql import func

from lumen_models.base import BaseModel


class LLMCallLog(BaseModel):
    __tablename__ = "llm_call_logs"

    # === 身份 ===
    call_id = Column(String(36), unique=True, nullable=False, index=True)
    parent_call_id = Column(String(36), nullable=True, index=True)
    trace_id = Column(String(36), nullable=False, index=True)
    # call_type values:
    #   chat              - 普通 chat / widget chat stream
    #   agent_team        - AgentTeam manager_decision / member reply
    #   workflow.llm      - Workflow LLM 节点
    #   workflow.classifier - Workflow Question Classifier 节点
    #   workflow.extractor - Workflow Parameter Extractor 节点
    #   image_generation  - M22 图像生成 prompt
    #   eval_judge        - M37.2 RAG 评测 judge(extra 里有 eval_run_id / eval_metric)
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
    message_id = Column(Integer, ForeignKey("messages.id"), nullable=True, index=True)
    agent_id = Column(Integer, ForeignKey("agents.id"), nullable=True, index=True)
    team_id = Column(Integer, ForeignKey("agent_teams.id"), nullable=True, index=True)
    team_member_id = Column(Integer, nullable=True)
    workflow_id = Column(Integer, ForeignKey("workflows.id"), nullable=True, index=True)
    workflow_run_id = Column(
        Integer, ForeignKey("workflow_runs.id"), nullable=True, index=True,
    )
    workflow_node_id = Column(String(64), nullable=True)
    image_id = Column(
        Integer, ForeignKey("generated_images.id"), nullable=True, index=True,
    )

    # === 模型 ===
    model_type = Column(String(50), nullable=True)
    model_name = Column(String(100), nullable=False)
    model_config_id = Column(
        Integer, ForeignKey("model_configs.id"), nullable=True, index=True,
    )
    temperature = Column(Float, nullable=True)
    max_tokens = Column(Integer, nullable=True)

    # === 入参(完整存) ===
    system_messages = Column(JSON, nullable=True)
    user_message = Column(Text, nullable=True)
    messages = Column(JSON, nullable=True)
    tools = Column(JSON, nullable=True)
    extra_params = Column(JSON, nullable=True)
    input_chars = Column(Integer, nullable=True)
    input_tokens_estimate = Column(Integer, nullable=True)

    # === 出参(完整存) ===
    response_content = Column(Text, nullable=True)
    finish_reason = Column(String(50), nullable=True)
    tool_calls = Column(JSON, nullable=True)
    output_chars = Column(Integer, nullable=True)
    output_tokens_estimate = Column(Integer, nullable=True)

    # === 用量 / 时延 / 状态 ===
    token_usage = Column(JSON, nullable=True)
    started_at = Column(DateTime, nullable=False)
    finished_at = Column(DateTime, nullable=True)
    duration_ms = Column(Integer, nullable=True)
    first_token_latency_ms = Column(Integer, nullable=True)
    status = Column(String(20), default="success", index=True)
    error_type = Column(String(100), nullable=True)
    error_message = Column(Text, nullable=True)
    retry_count = Column(Integer, default=0)

    # === 元数据 ===
    request_ip = Column(String(50), nullable=True)
    user_agent = Column(String(500), nullable=True)
    extra = Column(JSON, nullable=True)

    # === M27 retention ===
    # ``archived_at`` set by ``services/retention.py`` when a row hits
    # the soft-delete cutoff (default 90 days). Hard delete (default
    # 180 days) removes the row entirely. List queries filter
    # ``archived_at IS NULL`` by default.
    archived_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("idx_lcl_tenant_time", "tenant_id", "created_at"),
        Index("idx_lcl_module_time", "call_type", "created_at"),
        Index("idx_lcl_model_time", "model_name", "created_at"),
        Index("idx_lcl_conv_time", "conversation_id", "created_at"),
        Index("idx_lcl_workflow", "workflow_id", "workflow_run_id"),
        Index("idx_lcl_trace", "trace_id", "call_index"),
        Index("idx_lcl_status_time", "status", "created_at"),
    )