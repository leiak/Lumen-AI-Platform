"""M35: Subtitle persistence model.

Pure-Python SRT generation result. The Subtitle.content field holds the
fully formatted SRT text (UTF-8) — served as text/plain via the API and
also downloadable. tts_job_id optionally links the subtitle back to a
GeneratedAudio row, useful for "Generate+Subtitle" composite actions.

Spec: docs-internal/superpowers/specs/M35-overview.md
"""
from sqlalchemy import Column, Integer, String, Text, ForeignKey, Index
from lumen_models.base import BaseModel


class Subtitle(BaseModel):
    __tablename__ = "subtitles"

    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    # Optional link back to the TTS job that produced the audio track
    tts_job_id = Column(
        Integer, ForeignKey("generated_audios.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )

    source_type = Column(String(20), nullable=False, default="script")
    # Currently only "script" (M35); M36 will add "audio" (Whisper path).
    language = Column(String(10), nullable=False, default="zh-CN")
    format = Column(String(10), nullable=False, default="srt")

    content = Column(Text, nullable=False)
    cue_count = Column(Integer, nullable=False, default=0)
    duration_ms = Column(Integer, nullable=False, default=0)
    char_count = Column(Integer, nullable=False, default=0)

    __table_args__ = (
        Index(
            "ix_subtitles_tenant_created",
            "tenant_id", "created_at",
        ),
    )
