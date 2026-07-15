from sqlalchemy import Column, String, Text, Integer, ForeignKey, JSON, Boolean
from sqlalchemy.orm import relationship
from lumen_models.base import BaseModel


class Agent(BaseModel):
    __tablename__ = "agents"

    name = Column(String(100), nullable=False)
    description = Column(Text)
    prompt_template = Column(Text, nullable=False)
    model_name = Column(String(50), default="gpt-4o")
    temperature = Column(Integer, default=0)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    is_active = Column(Boolean, default=True)
    config = Column(JSON)  # Additional config like max_tokens, system prompt
    # M21: KB 检索配置 (JSON, 启动迁移默认 {"top_k": 3, "rrf_k": 30})
    kb_retrieval_config = Column(JSON, nullable=True)

    # --- Memory policy (Task 8) ---
    # Which truncation / summarization strategy the runner applies to the
    # chat history before sending it to the LLM. Valid values:
    #   "none" | "sliding_window" | "token_limit" | "semantic_compression"
    memory_policy = Column(String(32), nullable=False, default="sliding_window")
    # For sliding_window: keep the last N turns.
    memory_window_size = Column(Integer, nullable=False, default=20)
    # For token_limit: drop the oldest messages until the total token count
    # (approx, using len(content)//4) is <= this value.
    memory_max_tokens = Column(Integer, nullable=False, default=4000)
    # If true and policy is semantic_compression, the runner will try to
    # summarize older messages into a single condensed "memory" message
    # before the window. (Falls back to sliding window if no chat model
    # is reachable.)
    memory_compression = Column(Boolean, nullable=False, default=False)

    # --- Tool choice (Task 8) ---
    # Which subset of the agent's configured tools is exposed to the LLM
    # on a given turn. Valid values:
    #   "auto" | "required" | "none" | "specific"
    tool_choice = Column(String(32), nullable=False, default="auto")
    # When tool_choice == "required", force the LLM to invoke a tool on
    # every turn. (Implemented as a hint in the system prompt for now,
    # since not all chat models support native tool_choice='required'.)
    tool_choice_required = Column(Boolean, nullable=False, default=False)
    # When tool_choice == "specific", restrict to this list of tool names.
    # Stored as a JSON array of strings.
    allowed_tools = Column(JSON)

    tenant = relationship("Tenant", backref="agents")
    tools = relationship("AgentTool", back_populates="agent", cascade="all, delete-orphan")
    knowledge_bases = relationship("AgentKnowledgeBase", back_populates="agent", cascade="all, delete-orphan")


class AgentTool(BaseModel):
    __tablename__ = "agent_tools"

    agent_id = Column(Integer, ForeignKey("agents.id"), nullable=False, index=True)
    tool_name = Column(String(100), nullable=False)
    tool_config = Column(JSON)

    agent = relationship("Agent", back_populates="tools")


class AgentKnowledgeBase(BaseModel):
    __tablename__ = "agent_knowledge_bases"

    agent_id = Column(Integer, ForeignKey("agents.id"), nullable=False, index=True)
    knowledge_base_id = Column(Integer, ForeignKey("knowledge_bases.id"), nullable=False, index=True)

    agent = relationship("Agent", back_populates="knowledge_bases")
    knowledge_base = relationship("KnowledgeBase")
