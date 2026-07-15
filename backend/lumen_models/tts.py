"""M35: Generated audio (TTS) persistence model.

Mirrors lumen_models.image_generation (M22) — background task writes the row
with status=pending, then a separate background dispatch updates it to
running → completed/failed and writes the audio bytes to disk.

Spec: docs-internal/superpowers/specs/M35-overview.md
"""
from sqlalchemy import (
    Column, Integer, String, Text, JSON, ForeignKey, Index, DateTime,
)
from lumen_models.base import BaseModel


class GeneratedAudio(BaseModel):
    __tablename__ = "generated_audios"

    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    # Optional link back to a chat conversation that triggered the request
    conversation_id = Column(Integer, ForeignKey("conversations.id"), nullable=True, index=True)
    # The TTS-capable ModelConfig that produced (or is producing) the audio
    model_config_id = Column(
        Integer,
        ForeignKey("model_configs.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    # Optional playbook that enriched the input (style direction, voice tone)
    playbook_id = Column(Integer, ForeignKey("playbooks.id"), nullable=True, index=True)

    text = Column(Text, nullable=False)
    voice = Column(String(100), nullable=False, default="default")
    speed = Column(String(10), nullable=False, default="1.0")
    format = Column(String(10), nullable=False, default="mp3")
    params = Column(JSON, nullable=True)

    file_path = Column(String(500), nullable=False, default="")
    file_size = Column(Integer, nullable=False, default=0)
    mime_type = Column(String(50), nullable=False, default="audio/mpeg")
    duration_ms = Column(Integer, nullable=True)
    char_count = Column(Integer, nullable=False, default=0)
    cost_usd = Column(String(20), nullable=True)

    status = Column(String(20), nullable=False, default="pending")
    # pending / running / completed / failed / cancelled
    error_message = Column(Text, nullable=True)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index(
            "ix_gen_audios_tenant_status_created",
            "tenant_id", "status", "created_at",
        ),
    )
