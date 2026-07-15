"""M35: Subtitle Pydantic schemas."""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class SubtitleCreate(BaseModel):
    script: str = Field(..., min_length=1, max_length=10000)
    total_duration_ms: int = Field(..., ge=1000, le=24 * 60 * 60 * 1000)
    language: str = Field(default="zh-CN", max_length=10)
    tts_job_id: Optional[int] = None


class SubtitleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: int
    user_id: int
    tts_job_id: Optional[int]
    source_type: str
    language: str
    format: str
    content: str
    cue_count: int
    duration_ms: int
    char_count: int
    created_at: datetime


class SubtitleListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    language: str
    cue_count: int
    duration_ms: int
    char_count: int
    tts_job_id: Optional[int]
    created_at: datetime
