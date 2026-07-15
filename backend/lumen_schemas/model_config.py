from pydantic import BaseModel, Field, ConfigDict, field_validator
from typing import Optional, Any
from datetime import datetime


class ModelConfigBase(BaseModel):
    """Base schema with protected_namespaces disabled to allow model_type/model_name"""
    model_config = {"protected_namespaces": ()}

    name: str = Field(..., description="Config name")
    model_type: str = Field(..., description="ollama/openai/anthropic/zhipu/minimax")
    model_name: str = Field(..., description="Model name like qwen2.5, gpt-4o")
    base_url: Optional[str] = Field(None, description="API base URL")
    api_key: Optional[str] = Field(None, description="API key")
    api_version: Optional[str] = Field(None, description="API version")
    temperature: float = Field(0.7, ge=0, le=2, description="Default temperature")
    max_tokens: int = Field(4096, gt=0, description="Max output tokens")
    timeout: int = Field(120, gt=0, description="Request timeout")
    is_default: bool = Field(False, description="Is default model")
    is_chat: bool = Field(True, description="Usable as a chat model")
    is_embedding: bool = Field(False, description="Usable as an embedding model")
    is_image_generation: bool = Field(False, description="Usable as an image generation model")
    is_tts: bool = Field(False, description="M35: Usable as a TTS (text-to-speech) model")
    is_subtitle_generation: bool = Field(False, description="M35: Usable as a subtitle generation model")
    is_video: bool = Field(False, description="M36: Usable as a video generation model (Kling/Sora/Veo future)")
    description: Optional[str] = Field(None, description="Model description")

    # Legacy rows inserted before the ORM `default=False` was applied (or
    # rows written via raw SQL scripts like `scripts/init_dev_db.py`) can
    # have `is_default = NULL` in MySQL. Pydantic's strict bool validator
    # rejects None, which made `GET /models/` return 500 and the admin
    # page render empty. Coerce None → False here so the response stays
    # `bool`-typed (frontend types are unaffected) and existing API
    # contracts hold. `is_default = False` means "not the default
    # model", which is semantically what a NULL already expressed.
    @field_validator("is_default", mode="before")
    @classmethod
    def _coerce_is_default(cls, v: Any) -> Any:
        return False if v is None else v


class ModelConfigCreate(ModelConfigBase):
    pass


class ModelConfigUpdate(BaseModel):
    model_config = {"protected_namespaces": ()}

    name: Optional[str] = None
    model_type: Optional[str] = None
    model_name: Optional[str] = None
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    api_version: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    timeout: Optional[int] = None
    is_default: Optional[bool] = None
    is_active: Optional[bool] = None
    is_chat: Optional[bool] = None
    is_embedding: Optional[bool] = None
    is_image_generation: Optional[bool] = None
    is_tts: Optional[bool] = None
    is_subtitle_generation: Optional[bool] = None
    is_video: Optional[bool] = None
    description: Optional[str] = None


class ModelConfigResponse(ModelConfigBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    is_active: bool
    tenant_id: Optional[int]
    created_at: datetime
    updated_at: datetime
