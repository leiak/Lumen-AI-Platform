from sqlalchemy import Column, String, Text, Integer, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from datetime import datetime
from lumen_models.base import BaseModel

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

    messages = relationship("Message", back_populates="conversation", cascade="all, delete-orphan")

class Message(BaseModel):
    __tablename__ = "messages"

    conversation_id = Column(Integer, ForeignKey("conversations.id"), nullable=False)
    role = Column(String(20), nullable=False)  # user, assistant, system
    content = Column(Text, nullable=False)
    msg_metadata = Column(Text)  # JSON string
    created_at = Column(DateTime, default=datetime.utcnow)

    conversation = relationship("Conversation", back_populates="messages")
