from pydantic import BaseModel, Field
from datetime import datetime
from typing import Any, Dict, List, Optional


class KBRef(BaseModel):
    """M21: KB 摘要,前端展示用。KB 物理删除后 status='deleted',name 带 (已删除) 前缀。"""
    id: int
    name: str
    status: str  # "active" | "inactive" | "deleted"


class AgentBase(BaseModel):
    name: str
    description: Optional[str] = None
    prompt_template: str
    model_name: str = "gpt-4o"
    # Optional so historical rows with temperature=NULL can still be
    # serialized (the early migration didn't enforce a default, leaving
    # a few customer-service agents in the DB with NULL — see
    # test_list_agents_handles_null_temperature).
    temperature: Optional[int] = 0
    # M21: KB 检索配置。service 层兜底默认 {"top_k": 3, "rrf_k": 30}
    kb_retrieval_config: Optional[Dict[str, Any]] = None


class AgentCreate(AgentBase):
    tool_names: Optional[List[str]] = []
    knowledge_base_ids: Optional[List[int]] = []

    # --- Memory policy (Task 8) ---
    memory_policy: Optional[str] = "sliding_window"
    memory_window_size: Optional[int] = 20
    memory_max_tokens: Optional[int] = 4000
    memory_compression: Optional[bool] = False

    # --- Tool choice (Task 8) ---
    tool_choice: Optional[str] = "auto"
    tool_choice_required: Optional[bool] = False
    allowed_tools: Optional[List[str]] = []


class AgentUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    prompt_template: Optional[str] = None
    model_name: Optional[str] = None
    temperature: Optional[int] = None
    is_active: Optional[bool] = None

    # --- Memory policy (Task 8) ---
    memory_policy: Optional[str] = None
    memory_window_size: Optional[int] = None
    memory_max_tokens: Optional[int] = None
    memory_compression: Optional[bool] = None

    # --- Tool choice (Task 8) ---
    tool_choice: Optional[str] = None
    tool_choice_required: Optional[bool] = None
    allowed_tools: Optional[List[str]] = None

    # M21: 新增 ↓
    knowledge_base_ids: Optional[List[int]] = None
    kb_retrieval_config: Optional[Dict[str, Any]] = None


class AgentResponse(AgentBase):
    id: int
    tenant_id: int
    is_active: bool
    created_at: datetime

    # --- Memory policy (Task 8) ---
    memory_policy: Optional[str] = "sliding_window"
    memory_window_size: Optional[int] = 20
    memory_max_tokens: Optional[int] = 4000
    memory_compression: Optional[bool] = False

    # --- Tool choice (Task 8) ---
    tool_choice: Optional[str] = "auto"
    tool_choice_required: Optional[bool] = False
    allowed_tools: Optional[List[str]] = []

    # M21: 新增 ↓
    knowledge_bases: List[KBRef] = Field(default_factory=list)
    # kb_retrieval_config 继承自 AgentBase

    class Config:
        from_attributes = True


class ChatMessage(BaseModel):
    role: str  # user, assistant, system
    content: str


class ChatRequest(BaseModel):
    agent_id: int
    message: str
    conversation_id: Optional[int] = None
    history: Optional[List[ChatMessage]] = []
