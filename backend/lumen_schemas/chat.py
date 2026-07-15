import json

from pydantic import BaseModel, Field, field_validator
from typing import Optional, List, Dict, Any, Literal
from datetime import datetime


class AttachmentRef(BaseModel):
    """An attachment the user uploaded alongside a chat message (V1 inline)."""

    file_id: str
    name: str
    size: int
    mime_type: str
    content_text: str


class UploadResult(BaseModel):
    """Returned by POST /chat/upload. The frontend keeps content_text in
    component state and re-sends it on the stream request as part of
    ChatRequest.attachments."""

    file_id: str
    name: str
    size: int
    mime_type: str
    content_text: str


class Message(BaseModel):
    id: int
    conversation_id: int
    role: Literal["user", "assistant", "system"]
    content: str
    metadata: Optional[Dict[str, Any]] = Field(None, validation_alias="msg_metadata")
    created_at: datetime

    class Config:
        from_attributes = True

    @field_validator("metadata", mode="before", check_fields=False)
    @classmethod
    def _decode_msg_metadata(cls, v: Any) -> Any:
        """Auto-JSON-decode ``msg_metadata`` when it's stored as a TEXT
        string in MySQL.

        Without this, ``Message.model_validate(orm_row)`` would fail on
        the response side because Pydantic does NOT auto-parse a
        ``str`` into a ``Dict``. Both ``GET /chat/conversations/{id}/
        messages`` and ``GET /agent-teams/{team_id}/conversations/
        {id}/messages`` persist msg_metadata via ``json.dumps`` in the
        write path, so we must round-trip it on the read path. None /
        dict / non-string values pass through unchanged.
        """
        if isinstance(v, str) and v:
            try:
                return json.loads(v)
            except (ValueError, TypeError):
                # Malformed JSON in DB; surface as the raw string rather
                # than 500-ing the whole list response. The frontend
                # sees a string where it expected a dict and skips the
                # metadata block.
                return v
        return v


class ConversationCreate(BaseModel):
    title: Optional[str] = None
    agent_id: Optional[int] = None


class ConversationUpdate(BaseModel):
    """Body for PATCH /chat/conversations/{id}. Pass agent_id=null to
    unbind (revert to tenant default model config). Empty body is
    semantically equivalent to passing agent_id=null (Pydantic default).
    """
    agent_id: Optional[int] = None


class ConversationResponse(BaseModel):
    id: int
    title: str
    agent_id: Optional[int]
    agent_name: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    # NOTE: ``agent_name`` is a *joined* column, not on the Conversation
    # ORM row. Endpoints that rely on ``from_attributes=True`` to bind
    # the response from an ORM instance will silently leave
    # ``agent_name=None``. Endpoints that need it MUST construct the
    # response explicitly (see ``_serialize_conversation`` in
    # ``app/api/v1/chat.py``). Pydantic does not warn on this — the
    # request side drops unknown fields and the response side drops
    # missing joined columns. See MEMORY.md "Pydantic 静默丢弃未知字段".

    class Config:
        from_attributes = True


class ChatRequest(BaseModel):
    message: str
    conversation_id: Optional[int] = None
    agent_id: Optional[int] = None
    stream: bool = True
    # —— V1 feature toggles ——
    enable_thinking: bool = False
    enable_web_search: bool = False
    attachments: Optional[List[AttachmentRef]] = None
    # —— V1 skill injection (per-message) ——
    skill_ids: Optional[List[int]] = None


class SkillRecommendationItem(BaseModel):
    """One recommended skill returned by /chat/recommend-skills."""
    skill_id: int
    marketplace_skill_id: int
    name: str
    description: Optional[str] = None
    reason: str  # 为什么推荐这个技能
    confidence: float  # 0.0-1.0
    match_type: str  # "keyword" | "llm"


class RecommendSkillsRequest(BaseModel):
    """Request body for POST /chat/recommend-skills."""
    message: str = Field(..., min_length=1, description="用户发送的消息")


class RecommendSkillsResponse(BaseModel):
    """Response for POST /chat/recommend-skills."""
    recommendations: List[SkillRecommendationItem]
