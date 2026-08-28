from pydantic import BaseModel, Field, field_validator, model_validator
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


class AgentUpdateModel(BaseModel):
    """Body for ``PUT /api/v1/agents/{id}/model``(admin 专用)。

    设计意图:当 agent 引用的 model_name 对应的 ModelConfig row 死了
    (例如 MiniMax API key 过期 → 401 → 节点 60s 超时,workflow designer
    LLM/Agent 节点全部卡住),admin 需要快速「切到另一个 active 的
    ModelConfig」恢复流程,不用动 prompt / KB / 其他配置。

    字段策略:
    - ``model_config_id`` **优先** —— 走 model_configs 表查 (model_name,
      is_active) 反查,确保 model_config 真实存在且启用。
    - ``model_name`` 是 fallback,允许 admin 直接写一个字符串(向后兼容
      历史 admin SQL 脚本),但 service 层仍走 _get_model_config 反查
      验证 active + base_url + api_key 完备,任一缺失 → 422。
    - 两者都给 → 422(互斥,避免 admin 误以为字段同时生效)。
    - 都不给 → 422(Pydantic min_length 校验失败)。

    ``reason`` 是 audit 用,落库到 audit_log(可选,默认 None 不写)。
    """
    model_config_id: Optional[int] = Field(default=None, ge=1)
    model_name: Optional[str] = Field(default=None, max_length=100)
    reason: Optional[str] = Field(default=None, max_length=500)

    @field_validator("model_name")
    @classmethod
    def _strip_model_name(cls, v: Optional[str]) -> Optional[str]:
        # 避免 admin 误填前后空白导致 model_name 匹配不上
        return v.strip() if v else v

    # Pydantic v2 cross-field validation:至少给一个 + 不能同时给两个。
    # 422 detail 字符串清晰,前端 unwrap 后能直接显示给 admin。
    @model_validator(mode="after")
    def _check_mutually_exclusive(self) -> "AgentUpdateModel":
        if self.model_config_id is not None and self.model_name is not None:
            raise ValueError("model_config_id 和 model_name 互斥,只能传一个")
        if self.model_config_id is None and not self.model_name:
            raise ValueError("model_config_id 或 model_name 至少传一个")
        return self


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
