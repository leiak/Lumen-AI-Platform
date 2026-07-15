"""M35: TTS Pydantic schemas."""
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


AudioFormat = Literal["mp3", "wav", "opus", "flac", "aac"]


class TTSJobCreate(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    model_config_id: int
    text: str = Field(..., min_length=1, max_length=10000)
    voice: str = Field(default="default", max_length=100)
    speed: float = Field(default=1.0, ge=0.25, le=4.0)
    format: AudioFormat = "mp3"
    playbook_id: Optional[int] = None
    conversation_id: Optional[int] = None


class TTSJobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())

    id: int
    tenant_id: int
    user_id: int
    conversation_id: Optional[int]
    model_config_id: int
    playbook_id: Optional[int]
    text: str
    voice: str
    speed: str
    format: str
    status: str
    file_path: str
    file_size: int
    mime_type: str
    duration_ms: Optional[int]
    char_count: int
    cost_usd: Optional[str]
    error_message: Optional[str]
    started_at: Optional[datetime]
    finished_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime


class TTSJobListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())

    id: int
    model_config_id: int
    voice: str
    format: str
    status: str
    text_preview: str
    duration_ms: Optional[int]
    char_count: int
    created_at: datetime


class TTSVoiceItem(BaseModel):
    id: str
    name: str
    language: str
    gender: str
