from sqlalchemy import Column, String, Text, Integer, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from datetime import datetime
from lumen_models.base import BaseModel
# 提前 import agent_team_run 让 AgentRun Table 注册到 Base.metadata,
# 否则 Conversation.last_run_id / Message.run_id 的 ForeignKey 字符串
# 在 query compile 时 NoReferencedTableError。T1.5 没在 lumen_main.py
# 注册这个 model,这里手动补;M39 T1.7 Alembic 收口后可以挪到 lumen_main。
from lumen_models.agent_team_run import AgentRun  # noqa: F401  # 仅用于 FK 解析

class Conversation(BaseModel):
    __tablename__ = "conversations"

    title = Column(String(200))
    # user_id is now nullable to accommodate EXTERNAL chats
    # (see ExternalChat spec § 4.3). Internal flows always set it;
    # external flows leave it NULL and fill external_app_id +
    # external_visitor_id instead. The service layer enforces the
    # mutual-exclusion invariant (internal: user_id NOT NULL AND both
    # external_*_id IS NULL; external: user_id IS NULL AND both
    # external_*_id NOT NULL).
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    agent_id = Column(Integer, ForeignKey("agents.id"))
    team_id = Column(Integer, ForeignKey("agent_teams.id"), nullable=True, index=True)
    external_app_id = Column(Integer, ForeignKey("external_apps.id"), nullable=True, index=True)
    external_visitor_id = Column(Integer, ForeignKey("external_visitors.id"), nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    deleted_at = Column(DateTime, nullable=True)  # soft-delete timestamp; None = active
    # 关联最近一次 team run,NULL = 单 Agent 旧对话;chat UI 用于展示 "last run" 状态/时间跳转/计数
    last_run_id = Column(Integer, ForeignKey("agent_team_runs.id"), nullable=True)

    messages = relationship("Message", back_populates="conversation", cascade="all, delete-orphan")

class Message(BaseModel):
    __tablename__ = "messages"

    conversation_id = Column(Integer, ForeignKey("conversations.id"), nullable=False)
    role = Column(String(20), nullable=False)  # user, assistant, system
    content = Column(Text, nullable=False)
    msg_metadata = Column(Text)  # JSON string
    # 关联产生本条 message 的 team run,NULL = 单 Agent 旧消息;用于 time-travel 拉取某次 run 的全部消息
    run_id = Column(Integer, ForeignKey("agent_team_runs.id"), nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    conversation = relationship("Conversation", back_populates="messages")
