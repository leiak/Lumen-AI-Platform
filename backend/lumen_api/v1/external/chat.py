"""POST /api/v1/external/chat/stream — SSE stream for the widget.

This is the mirror of /chat/stream but bound to an ExternalApp +
ExternalVisitor instead of a User. The auth dep (``get_current_external_app``)
resolves the ExternalAppContext.
"""
import json
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from lumen_api.v1.deps import ExternalAppContext, get_current_external_app
from lumen_core.database import get_db
from lumen_models.chat import Conversation
from lumen_schemas.external import ExternalChatRequest
from lumen_services import external_auth_service as auth_svc  # monkey-patch compat
from lumen_services.chat_service import ChatService

router = APIRouter()


def _get_or_create_external_conversation(
    db: Session, ctx: ExternalAppContext,
    conv_id: int | None, agent_id: int | None, team_id: int | None,
) -> Conversation:
    if conv_id is not None:
        c = db.get(Conversation, conv_id)
        if c and c.external_app_id == ctx.app_id and c.external_visitor_id == ctx.visitor_id:
            return c
        raise HTTPException(status_code=404, detail="conversation not found")
    c = Conversation(
        title="外部对话", tenant_id=ctx.tenant_id,
        agent_id=agent_id, team_id=team_id,
        user_id=None,  # INVARIANT: external chats have no user_id
        external_app_id=ctx.app_id, external_visitor_id=ctx.visitor_id,
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


@router.post("/chat/stream")
async def chat_stream(
    req: ExternalChatRequest,
    ctx: ExternalAppContext = Depends(get_current_external_app),
    db: Session = Depends(get_db),
):
    # Whitelist gate
    if req.agent_id and req.agent_id not in ctx.allowed_agent_ids:
        raise HTTPException(403, "agent not in app whitelist")
    if req.team_id and req.team_id not in ctx.allowed_team_ids:
        raise HTTPException(403, "team not in app whitelist")
    if req.agent_id and req.team_id:
        raise HTTPException(400, "agent_id and team_id are mutually exclusive")
    if not req.agent_id and not req.team_id:
        if ctx.allowed_agent_ids:
            req.agent_id = ctx.allowed_agent_ids[0]
        elif ctx.allowed_team_ids:
            req.team_id = ctx.allowed_team_ids[0]
        else:
            raise HTTPException(400, "no agent or team configured for this app")

    # Module-level access for monkey-patch compatibility (see
    # test_external_chat_stream_e2e pattern). Direct import would bind
    # the name at import time and make pytest's setattr a silent no-op.
    if not auth_svc.check_rate_limit(app_id=ctx.app_id, endpoint_class="chat", limit_per_min=60):
        raise HTTPException(429, "rate limited")

    conv = _get_or_create_external_conversation(db, ctx, req.conversation_id, req.agent_id, req.team_id)
    req.conversation_id = conv.id  # ensure downstream has it

    service = ChatService()
    return StreamingResponse(
        service.stream_for_external(ctx, req),
        media_type="text/event-stream",
    )
