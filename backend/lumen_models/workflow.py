from sqlalchemy import Column, String, Text, Integer, ForeignKey, JSON, DateTime, Index, Boolean
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from lumen_models.base import BaseModel


class Workflow(BaseModel):
    __tablename__ = "workflows"

    name = Column(String(100), nullable=False)
    description = Column(Text)
    definition = Column(JSON, nullable=False)  # DAG definition
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    is_active = Column(Boolean, default=True)

    tenant = relationship("Tenant", backref="workflows")
    runs = relationship("WorkflowRun", back_populates="workflow", cascade="all, delete-orphan")


class WorkflowRun(BaseModel):
    __tablename__ = "workflow_runs"

    workflow_id = Column(Integer, ForeignKey("workflows.id"), nullable=False, index=True)
    status = Column(String(20), default="pending")  # pending, running, completed, failed, cancelled
    # "manual" = POST /workflows/{id}/run or /execute, "scheduled" = cron fire.
    # server_default backfills existing rows created before the column was
    # added (see app.core.database.ensure_workflow_runs_trigger_source).
    trigger_source = Column(String(20), nullable=False, default="manual", server_default="manual")
    input_data = Column(JSON)
    output_data = Column(JSON)
    error_message = Column(Text)
    started_at = Column(DateTime, server_default=func.now())
    finished_at = Column(DateTime, nullable=True)

    workflow = relationship("Workflow", back_populates="runs")
    node_runs = relationship("WorkflowNodeRun", back_populates="run", cascade="all, delete-orphan")
    # M30b-d follow-up (2026-06-19): ``LLMCallLog`` / ``EmbeddingCallLog`` 是 M27
    # ship 的 LLM / embedding 调用级日志,每个 row 用 ``workflow_run_id`` 软链回
    # ``WorkflowRun``。DB 层 FK 没 ON DELETE CASCADE,MCP 禁 DDL 无法直接改 schema
    # (CLAUDE.md §1);改走 ORM 层 cascade,在 ``WorkflowService.delete_workflow``
    # 触发 ``db.delete(workflow)`` 时,SQLAlchemy 先 DELETE FROM llm_call_logs
    # WHERE workflow_run_id IN (...) 再删 WorkflowRun,避开 FK 1451。
    # 关键: ``passive_deletes=False``(默认)— 显式声明,让 SQLAlchemy 主动发 SQL
    # 删子记录。之前用 ``passive_deletes=True`` 告诉 SA "DB 已配 cascade,别管",
    # 但实际 DB 没配,结果 SA 啥也不发,FK 1451 立刻撞上。
    llm_call_logs = relationship(
        "LLMCallLog",
        primaryjoin="WorkflowRun.id == foreign(LLMCallLog.workflow_run_id)",
        cascade="all, delete-orphan",
        passive_deletes=False,
    )
    embedding_call_logs = relationship(
        "EmbeddingCallLog",
        primaryjoin="WorkflowRun.id == foreign(EmbeddingCallLog.workflow_run_id)",
        cascade="all, delete-orphan",
        passive_deletes=False,
    )


class WorkflowNodeRun(BaseModel):
    """Tracks execution status of individual nodes within a workflow run"""
    __tablename__ = "workflow_node_runs"

    run_id = Column(Integer, ForeignKey("workflow_runs.id"), nullable=False, index=True)
    node_id = Column(String(100), nullable=False)  # Node ID from DAG definition
    node_type = Column(String(50), nullable=False)  # input, agent, condition, parallel, output
    status = Column(String(20), default="pending")  # pending, running, completed, failed, skipped
    input_data = Column(JSON)
    output_data = Column(JSON)
    error_message = Column(Text)
    started_at = Column(DateTime, server_default=func.now())
    finished_at = Column(DateTime, nullable=True)
    execution_order = Column(Integer, nullable=True)  # Order in which node was executed

    run = relationship("WorkflowRun", back_populates="node_runs")

    __table_args__ = (
        Index("idx_node_run_run_node", "run_id", "node_id", unique=True),
    )

    def __repr__(self):
        return f"<WorkflowNodeRun(run_id={self.run_id}, node_id={self.node_id}, status={self.status})>"


class WorkflowSchedule(BaseModel):
    """Stores scheduled execution configurations for workflows"""
    __tablename__ = "workflow_schedules"

    workflow_id = Column(Integer, ForeignKey("workflows.id"), nullable=False, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    cron_expression = Column(String(100), nullable=False)  # e.g., "0 9 * * *" for daily at 9am
    input_data = Column(JSON, nullable=True)  # Optional fixed input for scheduled runs
    is_active = Column(Boolean, default=True)
    last_run_at = Column(DateTime, nullable=True)
    next_run_at = Column(DateTime, nullable=True)

    workflow = relationship("Workflow", backref="schedules")

    __table_args__ = (
        Index("idx_schedule_workflow_active", "workflow_id", "is_active"),
    )
