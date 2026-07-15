"""Pydantic schemas for AgentTeam, AgentTeamMember, and team chat."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Route policy
# ---------------------------------------------------------------------------

class RoutePolicy:
    MANAGER_DECIDES = "manager_decides"
    ROUND_ROBIN = "round_robin"
    FIRST_MATCH = "first_match"

    ALL = (MANAGER_DECIDES, ROUND_ROBIN, FIRST_MATCH)


# ---------------------------------------------------------------------------
# Member
# ---------------------------------------------------------------------------

class AgentTeamMemberBase(BaseModel):
    agent_id: int
    role: str = "worker"
    priority: int = 100
    is_active: bool = True
    config: Optional[Dict[str, Any]] = None


class AgentTeamMemberCreate(AgentTeamMemberBase):
    pass


class AgentTeamMemberUpdate(BaseModel):
    role: Optional[str] = None
    priority: Optional[int] = None
    is_active: Optional[bool] = None
    config: Optional[Dict[str, Any]] = None


class AgentTeamMemberResponse(AgentTeamMemberBase):
    id: int
    team_id: int
    created_at: datetime
    # Convenience: include the underlying agent's name/description
    agent_name: Optional[str] = None

    class Config:
        from_attributes = True


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------

class AgentTeamRouteBase(BaseModel):
    agent_id: int
    keywords: List[str] = Field(default_factory=list)
    priority: int = 100


class AgentTeamRouteCreate(AgentTeamRouteBase):
    pass


class AgentTeamRouteResponse(AgentTeamRouteBase):
    id: int
    team_id: int
    created_at: datetime

    class Config:
        from_attributes = True


# ---------------------------------------------------------------------------
# Team
# ---------------------------------------------------------------------------

class AgentTeamBase(BaseModel):
    name: str
    description: Optional[str] = None
    manager_agent_id: int
    is_active: bool = True
    route_policy: str = RoutePolicy.MANAGER_DECIDES
    aggregator_prompt: Optional[str] = None
    config: Optional[Dict[str, Any]] = None


class AgentTeamCreate(AgentTeamBase):
    # P0-5 (2026-06-20): 强制至少 1 个 member. 之前 Optional + default=[] 允许
    # 创建 0-member team, dev DB 累积 ~150 个孤儿 team (member_count=0),
    # manager_decides policy 跑起来直接 0 worker 响应. min_length=1 触发
    # Pydantic v2 422, 前端 modal 加必填提示.
    members: List[AgentTeamMemberCreate] = Field(default_factory=list, min_length=1)
    routes: Optional[List[AgentTeamRouteCreate]] = Field(default_factory=list)


class AgentTeamUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    manager_agent_id: Optional[int] = None
    is_active: Optional[bool] = None
    route_policy: Optional[str] = None
    aggregator_prompt: Optional[str] = None
    config: Optional[Dict[str, Any]] = None


class AgentTeamResponse(AgentTeamBase):
    id: int
    tenant_id: int
    created_at: datetime
    members: List[AgentTeamMemberResponse] = Field(default_factory=list)
    routes: List[AgentTeamRouteResponse] = Field(default_factory=list)

    class Config:
        from_attributes = True


class AgentTeamSummary(AgentTeamBase):
    """Lightweight shape used in paginated lists (no nested members/routes)."""

    id: int
    tenant_id: int
    created_at: datetime
    member_count: int = 0
    # P0-4 (2026-06-20): outer-joined from agents table so the frontend
    # list view can show "Manager Agent: <name>" instead of the raw FK id.
    # Optional because the FK itself is non-nullable but the join target
    # could be missing in a corrupted DB — the frontend falls back to id.
    manager_agent_name: Optional[str] = None

    class Config:
        from_attributes = True


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------

class AgentTeamChatRequest(BaseModel):
    message: str
    # Deprecated: the backend now pulls history from the DB when
    # `conversation_id` is provided. The field is kept on the schema
    # for backward compatibility (older clients still send it) but
    # the service layer ignores it once a conversation is resolved.
    history: Optional[List[Dict[str, str]]] = None
    # Optionally override the team's routing policy for this turn
    route_policy: Optional[str] = None
    # Optionally restrict the workers considered for this turn
    member_ids: Optional[List[int]] = None
    # If None, the backend creates a new conversation (title = first
    # 50 chars of the message). If set, the message is appended to
    # the existing conversation and prior history is loaded for the
    # workers.
    conversation_id: Optional[int] = None


class WorkerOutput(BaseModel):
    member_id: Optional[int] = None
    agent_id: int
    agent_name: Optional[str] = None
    role: Optional[str] = None
    response: str


class AgentTeamChatResponse(BaseModel):
    final_answer: str
    manager_reasoning: Optional[str] = None
    routing_decision: Optional[List[int]] = None  # agent_ids the manager picked
    worker_outputs: List[WorkerOutput] = Field(default_factory=list)
    policy_used: str
    team_id: int
    # Echoed back so the frontend can update its sidebar selection
    # (first turn creates a new conv, subsequent turns reuse it).
    conversation_id: int


# ---------------------------------------------------------------------------
# Conversation (team-scoped)
# ---------------------------------------------------------------------------

class AgentTeamConversationResponse(BaseModel):
    """Shape returned by GET / POST on team conversations.
    Mirrors ``schemas/chat.ConversationResponse`` but additionally
    carries ``team_id`` so the frontend can confirm which team the
    chat belongs to."""

    id: int
    title: Optional[str] = None
    team_id: Optional[int] = None
    user_id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
