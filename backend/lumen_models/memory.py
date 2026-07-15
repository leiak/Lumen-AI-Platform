from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Index
from sqlalchemy.sql import func
from lumen_models.base import Base


class ConversationMemory(Base):
    """Conversation memory stored in database for persistence"""
    __tablename__ = "conversation_memories"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    conversation_id = Column(Integer, nullable=False, index=True)
    role = Column(String(20), nullable=False)  # "user" or "assistant"
    content = Column(Text, nullable=False)
    meta_data = Column(Text, nullable=True)  # JSON string for additional data
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("idx_tenant_conversation", "tenant_id", "conversation_id"),
        Index("idx_conversation_created", "conversation_id", "created_at"),
    )

    def __repr__(self):
        return f"<ConversationMemory(id={self.id}, conversation_id={self.conversation_id}, role={self.role})>"


class GlobalMemory(Base):
    """Global memory for agent-wide context"""
    __tablename__ = "global_memories"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    # M15: source conversation; NULL for legacy rows written before the column
    # existed. The UI uses it to dim/filter entries from the currently
    # selected conversation in /dashboard/memory's global context panel.
    # Composite index in __table_args__ covers tenant-scoped lookups.
    conversation_id = Column(Integer, nullable=True)
    role = Column(String(20), nullable=False)  # "user" or "assistant"
    content = Column(Text, nullable=False)
    meta_data = Column(Text, nullable=True)  # JSON string
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("idx_global_tenant_created", "tenant_id", "created_at"),
        Index("idx_global_tenant_conv_created", "tenant_id", "conversation_id", "created_at"),
    )

    def __repr__(self):
        return f"<GlobalMemory(id={self.id}, tenant_id={self.tenant_id}, conv_id={self.conversation_id}, role={self.role})>"
