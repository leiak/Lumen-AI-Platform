"""M35: Playbook Pydantic schemas."""
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class PlaybookBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = Field(default=None, max_length=2000)
    yaml_content: str = Field(..., min_length=1)
    scope: List[str] = Field(default_factory=lambda: ["image", "tts"])


class PlaybookCreate(PlaybookBase):
    pass


class PlaybookUpdate(BaseModel):
    description: Optional[str] = Field(default=None, max_length=2000)
    yaml_content: Optional[str] = Field(default=None, min_length=1)
    scope: Optional[List[str]] = None


class PlaybookRead(PlaybookBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: int
    style_tokens: Optional[Dict[str, Any]] = None
    is_builtin: bool
    created_by: Optional[int] = None
    created_at: datetime
    updated_at: datetime


class PlaybookListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: Optional[str]
    scope: Optional[List[str]]
    is_builtin: bool
    created_at: datetime
    updated_at: datetime
