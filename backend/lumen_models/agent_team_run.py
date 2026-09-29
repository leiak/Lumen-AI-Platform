"""AgentRun ORM — one full lifecycle of a team-chat invocation.

每条 AgentRun 串起 checkpoint、messages、HiTL 决策,是 M39 多 agent 协作
升级后的主线实体;Conversation 退化为"用户视角的同一对话",T1.6 会给
Conversation 加 `last_run_id` FK 反指回这里。

设计见 docs-internal/superpowers/specs/2026-09-29-multi-agent-team-upgrade-design.md §3.1。
"""
from sqlalchemy import (
    Column,
    String,
    Text,
    Integer,
    ForeignKey,
    JSON,
    DateTime,
    Index,
)
from lumen_models.base import BaseModel


class AgentRunStatus:
    """AgentRun 生命周期状态枚举(字符串值,与 DB 列对齐)。

    状态机转换:
      running → awaiting_plan / awaiting_result / completed / failed / cancelled
      awaiting_plan → running(用户提交 plan)/ cancelled
      awaiting_result → running(用户确认 result)/ cancelled
      completed / failed / cancelled 为终态
    """
    RUNNING = "running"
    AWAITING_PLAN = "awaiting_plan"
    AWAITING_RESULT = "awaiting_result"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    ALL = (RUNNING, AWAITING_PLAN, AWAITING_RESULT, COMPLETED, FAILED, CANCELLED)


class AgentRun(BaseModel):
    __tablename__ = "agent_team_runs"

    team_id = Column(Integer, ForeignKey("agent_teams.id"), nullable=False)
    conversation_id = Column(Integer, ForeignKey("conversations.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    # LangGraph thread_id:同一用户同一对话复用同一 thread,run 之间共享 checkpoint namespace
    thread_id = Column(String(128), nullable=False)
    # LangGraph checkpoint namespace,空串表示默认 namespace
    checkpoint_ns = Column(String(128), nullable=False, default="")
    status = Column(String(32), nullable=False, default=AgentRunStatus.RUNNING)
    # HiTL 中断时挂载的 payload(plan 草稿 / result 候选),resume 时读回
    interrupt_payload = Column(JSON, nullable=True)
    final_answer = Column(Text, nullable=True)
    # 自由 metadata(run 级别 token 用量之外的元信息,如 plan_version / model_used)
    msg_metadata = Column(JSON, nullable=True)
    # 最近一次 checkpoint id,用于 resume 时快速定位
    latest_checkpoint_id = Column(String(64), nullable=True)
    # HiTL 中断起始时刻,UI 展示"等待用户审批已 X 秒"
    awaiting_since_at = Column(DateTime, nullable=True)
    # 累计 token 用量(run 级,覆盖所有 node)
    token_count = Column(Integer, nullable=False, default=0)
    # run 总耗时(毫秒),completed 时填写
    latency_ms = Column(Integer, nullable=False, default=0)
    error_message = Column(Text, nullable=True)

    __table_args__ = (
        # 按 (tenant_id, thread_id) 高频查同一线程的所有 run(resume 场景)
        Index("idx_run_thread", "tenant_id", "thread_id"),
        # 按团队 + 状态 + 时间查 run 列表(dashboard / 监控)
        Index("idx_run_team_status", "team_id", "status", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<AgentRun(id={self.id}, thread_id={self.thread_id!r}, status={self.status!r})>"
