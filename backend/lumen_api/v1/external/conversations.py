"""Conversation CRUD for the widget.

Mirrors the *shape* of /chat/conversations/* (see app/api/v1/chat.py:84-160)
but is scoped by (external_app_id, external_visitor_id) instead of
(user_id, tenant_id). All endpoints return SingleResponse[T].
"""
from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from lumen_api.v1.deps import ExternalAppContext, get_current_external_app
from lumen_core.database import get_db
from lumen_models.agent import Agent
from lumen_models.agent_team import AgentTeam
from lumen_models.chat import Conversation, Message as MessageModel
from lumen_schemas.chat import Message
from lumen_schemas.common import SingleResponse
from lumen_schemas.external import ExternalConversationCreate, ExternalConversationResponse

router = APIRouter()


def _to_response(c: Conversation, agent_name: Optional[str], team_name: Optional[str]) -> ExternalConversationResponse:
    """Build ExternalConversationResponse explicitly.

    agent_name / team_name are *joined* columns — Pydantic's
    from_attributes would silently leave them None on the ORM row.
    See MEMORY.md "Pydantic 静默丢弃未知字段".
    """
    return ExternalConversationResponse(
        id=c.id, title=c.title or "外部对话",
        agent_id=c.agent_id, team_id=c.team_id,
        agent_name=agent_name, team_name=team_name,
        created_at=c.created_at.isoformat() if c.created_at else "",
        updated_at=c.updated_at.isoformat() if c.updated_at else "",
    )


def _verify_external_conv(conv_id: int, ctx: ExternalAppContext, db: Session) -> Conversation:
    """Return the conv if it exists AND belongs to (ctx.app_id, ctx.visitor_id).

    404 otherwise — same anti-IDOR posture as the internal verify helpers.
    See MEMORY.md "IDOR defense via 404".
    """
    c = db.query(Conversation).filter(
        Conversation.id == conv_id,
        Conversation.external_app_id == ctx.app_id,
        Conversation.external_visitor_id == ctx.visitor_id,
        Conversation.deleted_at.is_(None),
    ).first()
    if not c:
        raise HTTPException(404, "conversation not found")
    return c


@router.get("/conversations", response_model=SingleResponse[List[ExternalConversationResponse]])
async def list_conversations(
    ctx: ExternalAppContext = Depends(get_current_external_app),
    db: Session = Depends(get_db),
):
    # LEFT OUTER JOIN to pull agent_name and team_name in one query.
    # Without these joined columns, the response would have to fall back
    # to a per-row scalar lookup (N+1) or accept agent_name=None
    # (silent data loss). This mirrors the internal /chat/conversations
    # outerjoin pattern (see app/api/v1/chat.py:84-108).
    rows = db.query(Conversation, Agent.name, AgentTeam.name).outerjoin(
        Agent, Conversation.agent_id == Agent.id
    ).outerjoin(
        AgentTeam, Conversation.team_id == AgentTeam.id
    ).filter(
        Conversation.external_app_id == ctx.app_id,
        Conversation.external_visitor_id == ctx.visitor_id,
        Conversation.deleted_at.is_(None),
    ).order_by(Conversation.updated_at.desc()).all()
    return SingleResponse(data=[
        _to_response(c, agent_name, team_name)
        for (c, agent_name, team_name) in rows
    ])


@router.post("/conversations", response_model=SingleResponse[ExternalConversationResponse])
async def create_conversation(
    req: ExternalConversationCreate,
    ctx: ExternalAppContext = Depends(get_current_external_app),
    db: Session = Depends(get_db),
):
    if req.agent_id and req.agent_id not in ctx.allowed_agent_ids:
        raise HTTPException(403, "agent not in app whitelist")
    if req.team_id and req.team_id not in ctx.allowed_team_ids:
        raise HTTPException(403, "team not in app whitelist")
    c = Conversation(
        title=req.title or "外部对话",
        tenant_id=ctx.tenant_id,
        agent_id=req.agent_id, team_id=req.team_id,
        user_id=None,  # INVARIANT: external convs have no user_id
        external_app_id=ctx.app_id, external_visitor_id=ctx.visitor_id,
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    agent_name = db.query(Agent.name).filter(Agent.id == c.agent_id).scalar() if c.agent_id else None
    team_name = db.query(AgentTeam.name).filter(AgentTeam.id == c.team_id).scalar() if c.team_id else None
    return SingleResponse(data=_to_response(c, agent_name, team_name))


@router.get("/conversations/{conv_id}/messages", response_model=SingleResponse[List[Message]])
async def get_messages(
    conv_id: int,
    ctx: ExternalAppContext = Depends(get_current_external_app),
    db: Session = Depends(get_db),
):
    conv = _verify_external_conv(conv_id, ctx, db)
    msgs = db.query(MessageModel).filter(
        MessageModel.conversation_id == conv.id
    ).order_by(MessageModel.created_at.asc()).all()
    return SingleResponse(data=msgs)


@router.delete("/conversations/{conv_id}", response_model=SingleResponse[None])
async def delete_conversation(
    conv_id: int,
    ctx: ExternalAppContext = Depends(get_current_external_app),
    db: Session = Depends(get_db),
):
    """Soft-delete: set deleted_at; row preserved for future restore."""
    conv = _verify_external_conv(conv_id, ctx, db)
    conv.deleted_at = datetime.utcnow()
    db.commit()
    return SingleResponse(message="Deleted successfully")
