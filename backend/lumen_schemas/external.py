"""Pydantic schemas for the public ``/api/v1/external/*`` namespace."""
from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, Field

# Re-use the existing AttachmentRef / UploadResult from chat.py so the
# widget can speak the same wire format as the internal chat upload.
from lumen_schemas.chat import AttachmentRef, UploadResult  # noqa: F401


class TokenRequest(BaseModel):
    """Body for POST /external/auth/token.

    The widget populates ``visitor_id`` from localStorage (UUID v4
    string, 8-64 chars to reject obviously-malformed values).
    """
    app_key: str = Field(min_length=8, max_length=64)
    visitor_id: str = Field(min_length=8, max_length=64)


class TokenResponse(BaseModel):
    """Response to a successful token issue.

    ``allowed_agents`` / ``allowed_teams`` are returned here so the
    widget doesn't have to make a second round-trip to /external/agents
    just to render the agent switcher.
    """
    token: str
    expires_in: int
    allowed_agents: list[ExternalAgentSummary]
    allowed_teams: list[ExternalAgentSummary]
    visitor_id: int  # echoes the DB row id (not the UUID)


class ExternalChatRequest(BaseModel):
    """Body for POST /external/chat/stream.

    ``agent_id`` and ``team_id`` are mutually exclusive (server returns
    400 if both supplied). Either may be omitted — the server falls
    back to the first whitelisted agent/team of the app.
    """
    message: str = Field(min_length=1, max_length=8000)
    agent_id: Optional[int] = None
    team_id: Optional[int] = None
    conversation_id: Optional[int] = None
    attachments: Optional[list[AttachmentRef]] = None


class ExternalConversationCreate(BaseModel):
    title: Optional[str] = None
    agent_id: Optional[int] = None
    team_id: Optional[int] = None


class ExternalConversationResponse(BaseModel):
    id: int
    title: str
    agent_id: Optional[int] = None
    team_id: Optional[int] = None
    agent_name: Optional[str] = None
    team_name: Optional[str] = None
    created_at: str
    updated_at: str


class ExternalAgentKBRef(BaseModel):
    """Subset of a KB used in the external widget token / agents list.
    Mirrors the internal AgentResponse.knowledge_bases entry shape so the
    widget can render a KB badge without a second round-trip.
    """
    id: int
    name: str
    status: str = "active"  # "active" | "inactive" | "deleted"


class ExternalAgentSummary(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    type: str = "agent"  # "agent" | "team"
    # M21: knowledge bases bound to the agent (empty list if none). Only
    # populated for type=="agent"; teams are not currently KB-bound in
    # the same way.
    knowledge_bases: list[ExternalAgentKBRef] = []
