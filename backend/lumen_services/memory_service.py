from typing import Dict, List, Optional, Any
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import desc
import json

from lumen_models.memory import ConversationMemory, GlobalMemory


class MemoryService:
    """Service for managing agent memories with database persistence"""

    def __init__(self, db: Session = None):
        self.db = db

    def add_message(
        self,
        conversation_id: int,
        role: str,
        content: str,
        tenant_id: int = None,
        metadata: Dict[str, Any] = None,
        db: Session = None
    ):
        """Add a message to conversation memory (legacy interface)"""
        if not tenant_id:
            raise ValueError("tenant_id is required for add_message")
        if db is None:
            db = self.db
        if db is None:
            raise ValueError("db session is required")
        return self.add_conversation_memory(
            db=db,
            conversation_id=conversation_id,
            tenant_id=tenant_id,
            role=role,
            content=content,
            metadata=metadata
        )

    def get_conversation_memory(
        self,
        db: Session,
        conversation_id: int,
        tenant_id: int,
        limit: Optional[int] = None
    ) -> List[Dict]:
        """Get conversation memory from database"""
        query = db.query(ConversationMemory).filter(
            ConversationMemory.conversation_id == conversation_id,
            ConversationMemory.tenant_id == tenant_id
        ).order_by(desc(ConversationMemory.created_at))

        if limit:
            query = query.limit(limit)

        memories = query.all()
        # Return in chronological order
        return [
            {
                "role": m.role,
                "content": m.content,
                "metadata": json.loads(m.meta_data) if m.meta_data else {},
                "timestamp": m.created_at.isoformat()
            }
            for m in reversed(memories)
        ]

    def add_conversation_memory(
        self,
        db: Session,
        conversation_id: int,
        tenant_id: int,
        role: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> ConversationMemory:
        """Add a message to conversation memory"""
        memory = ConversationMemory(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            role=role,
            content=content,
            meta_data=json.dumps(metadata) if metadata else None
        )
        db.add(memory)
        db.commit()
        db.refresh(memory)
        return memory

    def search_conversation_memory(
        self,
        db: Session,
        conversation_id: int,
        tenant_id: int,
        query_text: str
    ) -> List[Dict]:
        """Search conversation memory by keyword"""
        memories = db.query(ConversationMemory).filter(
            ConversationMemory.conversation_id == conversation_id,
            ConversationMemory.tenant_id == tenant_id,
            ConversationMemory.content.ilike(f"%{query_text}%")
        ).order_by(desc(ConversationMemory.created_at)).all()

        return [
            {
                "role": m.role,
                "content": m.content,
                "metadata": json.loads(m.meta_data) if m.meta_data else {},
                "timestamp": m.created_at.isoformat()
            }
            for m in memories
        ]

    def clear_conversation_memory(
        self,
        db: Session,
        conversation_id: int,
        tenant_id: int
    ) -> bool:
        """Clear all memory for a conversation"""
        deleted = db.query(ConversationMemory).filter(
            ConversationMemory.conversation_id == conversation_id,
            ConversationMemory.tenant_id == tenant_id
        ).delete()
        db.commit()
        return deleted > 0

    def get_global_memory(
        self,
        db: Session,
        tenant_id: int,
        limit: Optional[int] = None
    ) -> List[Dict]:
        """Get global memory from database"""
        query = db.query(GlobalMemory).filter(
            GlobalMemory.tenant_id == tenant_id
        ).order_by(desc(GlobalMemory.created_at))

        if limit:
            query = query.limit(limit)

        memories = query.all()
        return [
            {
                "role": m.role,
                "content": m.content,
                "metadata": json.loads(m.meta_data) if m.meta_data else {},
                "timestamp": m.created_at.isoformat(),
                "conversation_id": m.conversation_id,
            }
            for m in reversed(memories)
        ]

    def add_global_memory(
        self,
        db: Session,
        tenant_id: int,
        role: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
        conversation_id: Optional[int] = None,
    ) -> GlobalMemory:
        """Add a message to global memory.

        M15: ``conversation_id`` is the source conversation when this row
        was written from the agent chat path. NULL for legacy rows and
        for any future caller that doesn't know the source.
        """
        memory = GlobalMemory(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            role=role,
            content=content,
            meta_data=json.dumps(metadata) if metadata else None
        )
        db.add(memory)
        db.commit()
        db.refresh(memory)
        return memory

    def search_global_memory(
        self,
        db: Session,
        tenant_id: int,
        query_text: str
    ) -> List[Dict]:
        """Search global memory by keyword"""
        memories = db.query(GlobalMemory).filter(
            GlobalMemory.tenant_id == tenant_id,
            GlobalMemory.content.ilike(f"%{query_text}%")
        ).order_by(desc(GlobalMemory.created_at)).all()

        return [
            {
                "role": m.role,
                "content": m.content,
                "metadata": json.loads(m.meta_data) if m.meta_data else {},
                "timestamp": m.created_at.isoformat(),
                "conversation_id": m.conversation_id,
            }
            for m in memories
        ]

    def clear_global_memory(self, db: Session, tenant_id: int) -> bool:
        """Clear all global memory for a tenant"""
        deleted = db.query(GlobalMemory).filter(
            GlobalMemory.tenant_id == tenant_id
        ).delete()
        db.commit()
        return deleted > 0

    def cap_global_memory(self, db: Session, tenant_id: int, max_entries: int = 1000) -> int:
        """Cap global memory per tenant to ``max_entries`` newest rows.

        Returns the number of rows deleted. Called after every
        ``add_global_memory`` to prevent unbounded growth when agent
        chats are wired into global memory.
        """
        total = db.query(GlobalMemory).filter(GlobalMemory.tenant_id == tenant_id).count()
        if total <= max_entries:
            return 0
        # Find the id of the (max_entries+1)-th newest row; everything
        # at or below that id is older than the cap and gets removed.
        cutoff_id = (
            db.query(GlobalMemory.id)
            .filter(GlobalMemory.tenant_id == tenant_id)
            .order_by(desc(GlobalMemory.created_at))
            .offset(max_entries)
            .limit(1)
            .scalar()
        )
        if cutoff_id is None:
            return 0
        deleted = (
            db.query(GlobalMemory)
            .filter(GlobalMemory.tenant_id == tenant_id, GlobalMemory.id <= cutoff_id)
            .delete(synchronize_session=False)
        )
        db.commit()
        return deleted


# Singleton instance for backward compatibility
memory_service = MemoryService()
