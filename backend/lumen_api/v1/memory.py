from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from lumen_core.database import get_db
from lumen_api.v1.auth import get_current_user
from lumen_models.user import User
from lumen_models.chat import Conversation
from lumen_services.memory_service import MemoryService
from lumen_schemas.common import SingleResponse
from pydantic import BaseModel

router = APIRouter(prefix="/memory", tags=["memory"])


def verify_conversation(conversation_id: int, current_user: User, db: Session):
    """Verify that the conversation belongs to the current user and tenant."""
    conv = db.query(Conversation).filter(
        Conversation.id == conversation_id,
        Conversation.user_id == current_user.id,
        Conversation.tenant_id == current_user.tenant_id
    ).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conv


class MemoryMessage(BaseModel):
    role: str
    content: str
    metadata: Optional[dict] = None
    # M15: source conversation. None for legacy rows and for any future
    # caller that doesn't know the source. The UI uses it to dim/filter
    # current-conv rows in the global context panel.
    conversation_id: Optional[int] = None


@router.get("/conversations/{conversation_id}", response_model=SingleResponse[List[MemoryMessage]])
async def get_conversation_memory(
    conversation_id: int,
    limit: int = Query(50, ge=1, le=500),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get memory history for a conversation"""
    verify_conversation(conversation_id, current_user, db)
    try:
        service = MemoryService()
        history = service.get_conversation_memory(
            db, conversation_id, current_user.tenant_id, limit
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get memory history: {str(e)}")
    return SingleResponse(data=[MemoryMessage(**h) for h in history])


@router.post("/conversations/{conversation_id}/messages", response_model=SingleResponse[dict])
async def add_memory_message(
    conversation_id: int,
    message: MemoryMessage,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Add a message to conversation memory"""
    verify_conversation(conversation_id, current_user, db)
    try:
        service = MemoryService()
        service.add_conversation_memory(
            db,
            conversation_id,
            current_user.tenant_id,
            message.role,
            message.content,
            message.metadata
        )
        # Also add to global memory (M15: thread the conv id so the
        # global context UI can distinguish "this row is from the
        # currently selected conv" from "it came from elsewhere").
        service.add_global_memory(
            db,
            current_user.tenant_id,
            message.role,
            message.content,
            message.metadata,
            conversation_id=conversation_id,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to add memory message: {str(e)}")
    return SingleResponse(data={"status": "added"})


@router.get("/conversations/{conversation_id}/search", response_model=SingleResponse[List[MemoryMessage]])
async def search_conversation_memory(
    conversation_id: int,
    query_text: str = Query(..., min_length=1),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Search memory for a conversation"""
    verify_conversation(conversation_id, current_user, db)
    try:
        service = MemoryService()
        results = service.search_conversation_memory(
            db, conversation_id, current_user.tenant_id, query_text
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to search memory: {str(e)}")
    return SingleResponse(data=[MemoryMessage(**r) for r in results])


@router.delete("/conversations/{conversation_id}", response_model=SingleResponse[dict])
async def clear_conversation_memory(
    conversation_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Clear memory for a conversation"""
    verify_conversation(conversation_id, current_user, db)
    try:
        service = MemoryService()
        service.clear_conversation_memory(db, conversation_id, current_user.tenant_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to clear memory: {str(e)}")
    return SingleResponse(data={"status": "cleared"})


@router.get("/global", response_model=SingleResponse[List[MemoryMessage]])
async def get_global_context(
    query_text: Optional[str] = None,
    limit: int = Query(100, ge=1, le=1000),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get global agent context/memory"""
    try:
        service = MemoryService()
        if query_text:
            context = service.search_global_memory(db, current_user.tenant_id, query_text)
        else:
            context = service.get_global_memory(db, current_user.tenant_id, limit)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get global context: {str(e)}")
    return SingleResponse(data=[MemoryMessage(**c) for c in context])


@router.delete("/global", response_model=SingleResponse[dict])
async def clear_global_memory(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Clear global memory for the tenant"""
    try:
        service = MemoryService()
        service.clear_global_memory(db, current_user.tenant_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to clear global memory: {str(e)}")
    return SingleResponse(data={"status": "cleared"})
