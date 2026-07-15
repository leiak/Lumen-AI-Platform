"""HTTP routes for AgentTeam (multi-agent collaboration)."""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from lumen_api.v1.auth import get_current_user
from lumen_core.database import get_db
from lumen_models.chat import Conversation
from lumen_models.user import User
from lumen_schemas.agent_team import (
    AgentTeamChatRequest,
    AgentTeamChatResponse,
    AgentTeamConversationResponse,
    AgentTeamCreate,
    AgentTeamMemberCreate,
    AgentTeamMemberResponse,
    AgentTeamResponse,
    AgentTeamSummary,
    AgentTeamUpdate,
)
from lumen_schemas.chat import Message
from lumen_schemas.common import PaginatedResponse, SingleResponse
from lumen_services.agents import TeamService

router = APIRouter(prefix="/agent-teams", tags=["agent-teams"])


# ---------------------------------------------------------------------------
# Conversation helpers
# ---------------------------------------------------------------------------

class TeamConversationCreate(BaseModel):
    """Body for POST /agent-teams/{team_id}/conversations.

    Title is optional; the chat endpoint will overwrite it with the
    first 50 chars of the user message if it's still the placeholder
    (mirroring the single-agent chat pattern in api/v1/chat.py:204).
    """

    title: Optional[str] = None


def _verify_team(team_id: int, current_user: User, db: Session) -> None:
    """Confirm the team exists within the caller's tenant. Keeps the
    conv endpoints DRY without re-asserting tenant checks everywhere.
    """
    from lumen_models.agent_team import AgentTeam

    exists = (
        db.query(AgentTeam.id)
        .filter(AgentTeam.id == team_id, AgentTeam.tenant_id == current_user.tenant_id)
        .first()
    )
    if not exists:
        raise HTTPException(status_code=404, detail="Team not found")


def verify_team_conversation(
    team_id: int,
    conv_id: int,
    current_user: User,
    db: Session,
) -> Conversation:
    """Return the team conversation if it exists AND belongs to the
    caller's tenant/user/team and is not soft-deleted. 404 otherwise.

    Parallel of ``api/v1/memory.verify_conversation`` but additionally
    filters ``team_id`` so a conv attached to a different team can
    never leak through (e.g. cross-team IDOR).
    """
    conv = (
        db.query(Conversation)
        .filter(
            Conversation.id == conv_id,
            Conversation.team_id == team_id,
            Conversation.user_id == current_user.id,
            Conversation.tenant_id == current_user.tenant_id,
            Conversation.deleted_at.is_(None),
        )
        .first()
    )
    if not conv:
        raise HTTPException(status_code=404, detail="Team conversation not found")
    return conv


def _to_response(team) -> AgentTeamResponse:
    return AgentTeamResponse(
        id=team.id,
        name=team.name,
        description=team.description,
        manager_agent_id=team.manager_agent_id,
        is_active=team.is_active,
        route_policy=team.route_policy or "manager_decides",
        aggregator_prompt=team.aggregator_prompt,
        config=team.config,
        tenant_id=team.tenant_id,
        created_at=team.created_at,
        members=[
            AgentTeamMemberResponse(
                id=m.id,
                team_id=m.team_id,
                agent_id=m.agent_id,
                role=m.role or "worker",
                priority=m.priority or 100,
                is_active=m.is_active,
                config=m.config,
                created_at=m.created_at,
                agent_name=m.agent.name if m.agent else None,
            )
            for m in (team.members or [])
        ],
        routes=[
            # routes not loaded by default; keep empty list for response shape
        ],
    )


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------
@router.get("/", response_model=PaginatedResponse[AgentTeamSummary])
async def list_teams(
    page: int = 1,
    page_size: int = 10,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    service = TeamService()
    items, total = service.list_teams(
        db, current_user.tenant_id, page=page, page_size=page_size
    )
    return PaginatedResponse(
        data=items,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("/", response_model=SingleResponse[AgentTeamResponse])
async def create_team(
    data: AgentTeamCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    service = TeamService()
    try:
        team = service.create_team(db, current_user.tenant_id, data, current_user)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return SingleResponse(data=_to_response(team))


@router.get("/{team_id}", response_model=SingleResponse[AgentTeamResponse])
async def get_team(
    team_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    service = TeamService()
    team = service.get_team(db, team_id, current_user.tenant_id)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    return SingleResponse(data=_to_response(team))


@router.put("/{team_id}", response_model=SingleResponse[AgentTeamResponse])
async def update_team(
    team_id: int,
    data: AgentTeamUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    service = TeamService()
    try:
        team = service.update_team(db, team_id, current_user.tenant_id, data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    return SingleResponse(data=_to_response(team))


@router.delete("/{team_id}")
async def delete_team(
    team_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    service = TeamService()
    ok = service.delete_team(db, team_id, current_user.tenant_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Team not found")
    return SingleResponse(message="Deleted successfully")


# ---------------------------------------------------------------------------
# Members
# ---------------------------------------------------------------------------
@router.post(
    "/{team_id}/members",
    response_model=SingleResponse[AgentTeamMemberResponse],
)
async def add_member(
    team_id: int,
    data: AgentTeamMemberCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    service = TeamService()
    try:
        member = service.add_member(db, team_id, current_user.tenant_id, data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not member:
        raise HTTPException(status_code=404, detail="Team not found")
    # Hydrate agent_name for the response
    return SingleResponse(
        data=AgentTeamMemberResponse(
            id=member.id,
            team_id=member.team_id,
            agent_id=member.agent_id,
            role=member.role or "worker",
            priority=member.priority or 100,
            is_active=member.is_active,
            config=member.config,
            created_at=member.created_at,
            agent_name=member.agent.name if member.agent else None,
        )
    )


@router.delete("/{team_id}/members/{member_id}")
async def remove_member(
    team_id: int,
    member_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    service = TeamService()
    ok = service.remove_member(
        db, team_id, member_id, current_user.tenant_id
    )
    if not ok:
        raise HTTPException(status_code=404, detail="Team or member not found")
    return SingleResponse(message="Member removed")


# ---------------------------------------------------------------------------
# Chat (run)
# ---------------------------------------------------------------------------
@router.post("/{team_id}/chat", response_model=SingleResponse[AgentTeamChatResponse])
async def team_chat(
    team_id: int,
    data: AgentTeamChatRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    service = TeamService()
    try:
        result = service.chat(
            db, team_id, current_user.tenant_id, data, current_user.id
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {e}")
    return SingleResponse(data=result)


# ---------------------------------------------------------------------------
# SSE stream endpoint (M26: graph.astream — see
# docs/superpowers/specs/2026-06-14-agent-team-sse-astream-design.md)
# ---------------------------------------------------------------------------

def _node_to_sse_payload(node_name: str, state_delta: dict, trace_id: str) -> dict:
    """Project a graph node's state delta to the SSE payload for the
    corresponding event. The frontend uses this to render the fold section
    for this step.

    Keep keys small + serializable; never include the whole state
    (would include ``workers_by_id`` etc, too large for SSE frames).
    """
    base = {"step": node_name, "trace_id": trace_id}
    if node_name == "load_context":
        return {
            **base,
            "conversation_id": state_delta.get("conversation", {}).get("id"),
            "workers_count": len(state_delta.get("workers_by_id", {})),
        }
    if node_name == "decide_routing":
        return {
            **base,
            "policy": state_delta.get("policy"),
            "chosen_count": len(state_delta.get("chosen_member_ids", [])),
            "manager_reasoning": state_delta.get("manager_reasoning"),
        }
    if node_name == "run_worker":
        outputs = state_delta.get("worker_outputs", [])
        if outputs:
            wo = outputs[0]
            response = wo.get("response", "")
            return {
                **base,
                "member_id": wo.get("member_id"),
                "agent_id": wo.get("agent_id"),
                "agent_name": wo.get("agent_name"),
                "response_preview": response[:200],
            }
        return {**base, "error": "run_worker emitted no outputs"}
    if node_name == "aggregate":
        return {
            **base,
            "final_answer_preview": (state_delta.get("final_answer") or "")[:200],
        }
    if node_name == "persist":
        return {
            **base,
            "conversation_id": state_delta.get("conversation_id"),
            "routing_decision": state_delta.get("routing_decision"),
            "final_answer": state_delta.get("final_answer"),
        }
    return {**base, "delta_keys": list(state_delta.keys())}


@router.post("/{team_id}/chat/stream")
async def team_chat_stream(
    team_id: int,
    data: AgentTeamChatRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """SSE stream of the multi-agent run. Each node completion becomes
    a typed SSE event so the frontend can fold/expand each step.

    Behaviour mirrors ``POST /chat/stream`` for single-agent:
      - Same ``AgentTeamChatRequest`` body
      - Same conversation_id resolve + user_msg persist + msg_metadata JSON
        (all delegated to graph nodes; same code path as the non-stream
        endpoint via ``graph.astream`` instead of ``graph.invoke``)
      - SSE event schema: ``event: <node_name>`` + ``data: {step, ...delta, trace_id}``
      - Final ``event: done`` carries ``final_answer`` + ``conversation_id``
      - On error, ``event: error`` then close (no 500 raise)

    See docs/superpowers/specs/2026-06-14-agent-team-sse-astream-design.md
    for full design rationale.
    """
    async def generate():
        from lumen_services.agents.state_graph import build_team_graph

        trace_id = str(uuid.uuid4())
        try:
            graph = build_team_graph()
            initial_state: dict = {
                "team_id": team_id,
                "tenant_id": current_user.tenant_id,
                "user_id": current_user.id,
                "user_message": data.message,
                "request_conversation_id": data.conversation_id,
                "request_member_ids": list(data.member_ids) if data.member_ids else None,
                "request_route_policy": data.route_policy,
            }
            config = {
                "configurable": {
                    "db": db,
                    "trace_id": trace_id,
                    "root_call_id": trace_id,
                },
            }
            seen_conversation_id: Optional[int] = None
            seen_final_answer: Optional[str] = None

            # astream with stream_mode="updates" yields
            # ``{<node_name>: <state_delta>}`` after each node completes.
            # We wrap each event in an SSE envelope so the frontend can
            # ``addEventListener(<node_name>, ...)`` directly.
            async for chunk in graph.astream(
                initial_state, config=config, stream_mode="updates",
            ):
                for node_name, state_delta in chunk.items():
                    if node_name == "__interrupt__":
                        continue
                    if node_name == "load_context":
                        seen_conversation_id = (
                            state_delta.get("conversation", {}).get("id")
                        )
                    if node_name in ("aggregate", "persist"):
                        seen_final_answer = state_delta.get("final_answer")
                    payload = _node_to_sse_payload(node_name, state_delta, trace_id)
                    yield (
                        f"event: {node_name}\n"
                        f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                    )

            done_payload = {
                "step": "done",
                "conversation_id": seen_conversation_id,
                "final_answer": seen_final_answer,
                "trace_id": trace_id,
            }
            yield (
                f"event: done\n"
                f"data: {json.dumps(done_payload, ensure_ascii=False)}\n\n"
            )
        except Exception as e:
            err_payload = {
                "step": "error",
                "error": f"{type(e).__name__}: {e}",
                "trace_id": trace_id,
            }
            yield (
                f"event: error\n"
                f"data: {json.dumps(err_payload, ensure_ascii=False)}\n\n"
            )

    return StreamingResponse(generate(), media_type="text/event-stream")


# ---------------------------------------------------------------------------
# Team conversations (history)
# ---------------------------------------------------------------------------
# These mirror the single-agent conversation endpoints in api/v1/chat.py
# (list/create/messages/delete) but are scoped to a specific team — the
# verify_team_conversation helper enforces the team binding on every read.

@router.get(
    "/{team_id}/conversations",
    response_model=SingleResponse[List[AgentTeamConversationResponse]],
)
async def list_team_conversations(
    team_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _verify_team(team_id, current_user, db)
    convs = (
        db.query(Conversation)
        .filter(
            Conversation.team_id == team_id,
            Conversation.user_id == current_user.id,
            Conversation.tenant_id == current_user.tenant_id,
            Conversation.deleted_at.is_(None),
        )
        .order_by(Conversation.updated_at.desc())
        .all()
    )
    return SingleResponse(data=convs)


@router.post(
    "/{team_id}/conversations",
    response_model=SingleResponse[AgentTeamConversationResponse],
)
async def create_team_conversation(
    team_id: int,
    data: TeamConversationCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _verify_team(team_id, current_user, db)
    conv = Conversation(
        title=data.title or "新对话",
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
        team_id=team_id,
    )
    db.add(conv)
    db.commit()
    db.refresh(conv)
    return SingleResponse(data=conv)


@router.get(
    "/{team_id}/conversations/{conv_id}/messages",
    response_model=SingleResponse[List[Message]],
)
async def get_team_conversation_messages(
    team_id: int,
    conv_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from lumen_models.chat import Message as MessageModel

    verify_team_conversation(team_id, conv_id, current_user, db)
    msgs = (
        db.query(MessageModel)
        .filter(MessageModel.conversation_id == conv_id)
        .order_by(MessageModel.created_at.asc())
        .all()
    )
    return SingleResponse(data=msgs)


@router.delete(
    "/{team_id}/conversations/{conv_id}",
    response_model=SingleResponse[None],
)
async def delete_team_conversation(
    team_id: int,
    conv_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Soft-delete a team conversation. Sets ``deleted_at``; the row
    is preserved for a future restore feature (parallel of
    /api/v1/chat/conversations/{id})."""
    conv = verify_team_conversation(team_id, conv_id, current_user, db)
    conv.deleted_at = datetime.utcnow()
    db.commit()
    return SingleResponse(message="Deleted successfully")
