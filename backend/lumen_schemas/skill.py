from pydantic import BaseModel, Field, field_validator
from typing import Any, Dict, Literal, Optional
from datetime import datetime

class SkillBase(BaseModel):
    name: str
    description: Optional[str] = None
    category: Optional[str] = None
    content: Optional[str] = None
    type: str = "prompt"  # "prompt" | "script"

class SkillCreate(SkillBase):
    pass

class SkillUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    content: Optional[str] = None
    is_active: Optional[bool] = None

class SkillResponse(SkillBase):
    id: int
    type: str = "prompt"
    is_builtin: bool
    is_active: bool
    version: str
    tenant_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# M16: Skill type-specific config schemas
# Each skill type (script, http, tool, knowledge_retrieval, workflow, composite)
# has its own config schema validated via Pydantic before executor dispatch.


class ScriptTypeConfig(BaseModel):
    code: str = Field(..., min_length=1)
    runtime: str = "python-3.11"
    timeout: int = Field(30, ge=1, le=120)
    input_schema: Optional[Dict[str, Any]] = None
    output_schema: Optional[Dict[str, Any]] = None


class HttpAuth(BaseModel):
    type: Literal["bearer", "api_key", "basic"]
    credential_ref: str  # must be ${ENV_VAR}

    @field_validator("credential_ref")
    @classmethod
    def must_be_env_ref(cls, v: str) -> str:
        if not (v.startswith("${") and v.endswith("}") and len(v) > 3):
            raise ValueError("credential_ref must be in ${ENV_VAR_NAME} format")
        return v


class HttpTypeConfig(BaseModel):
    url: str
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"] = "GET"
    headers: Dict[str, str] = Field(default_factory=dict)
    body_template: Optional[str] = None
    timeout: int = Field(30, ge=1, le=120)
    auth: Optional[HttpAuth] = None


# M17 预留 schema (M16 仅在 registry 占位)
class KnowledgeRetrievalTypeConfig(BaseModel):
    kb_id: int
    top_k: int = 5
    score_threshold: float = 0.7
    query_template: str = "{{user_query}}"


class ToolTypeConfig(BaseModel):
    mcp_server: str
    tool_name: str
    param_schema: Optional[Dict[str, Any]] = None


# M33: text2sql skill config — points at a Text2SqlDataSource by name.
# The executor (Text2SqlExecutor) does the lookup; the schema validates
# the config payload.
class Text2SqlTypeConfig(BaseModel):
    data_source_name: str = "默认 ai_platform"


# M18 预留 schema
class WorkflowTypeConfig(BaseModel):
    workflow_id: int
    input_mapping: Dict[str, str] = Field(default_factory=dict)


class CompositeTypeConfig(BaseModel):
    steps: list = Field(...)  # list of {skill_id, input_mapping}


# === M17: Admin form + test-run schemas ===

class SkillUpsertRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    category: str
    type: str
    description: Optional[str] = None
    content: Optional[str] = None
    type_config: Optional[Dict[str, Any]] = None
    version: str = "1.0.0"
    provider: Optional[str] = None
    is_verified: bool = False

    @field_validator("type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        allowed = {"prompt", "script", "http", "knowledge_retrieval", "tool", "text2sql"}
        if v not in allowed:
            raise ValueError(f"Unsupported skill type: {v}. Allowed: {sorted(allowed)}")
        return v


class SkillTestRunRequest(BaseModel):
    input_args: Dict[str, Any] = Field(default_factory=dict)


class SkillTestRunResult(BaseModel):
    result: Any
    latency_ms: int
    error: Optional[str] = None
    type: str
