"""M36: Generated video persistence model.

Mirrors ``lumen_models.tts.GeneratedAudio`` (M35) and
``lumen_models.image_generation.GeneratedImage`` (M22) — backend T3
(``video_service.create``) writes the row with ``status="pending"``, then
a background dispatch (or workflow node T4) updates it to
``composing`` → ``completed`` / ``failed`` and writes the mp4 bytes to
storage.

Unlike ``GeneratedAudio`` / ``GeneratedImage`` this is a **composition**
record, not a generation record: the source assets are pre-existing
image / audio / subtitle rows referenced by id (or path JSON), and the
``model_config_id`` is optional (M36 ships no video-gen provider — only
the FFmpeg composer).

Field reference:
- source_images (JSON list[str]) — local file paths or remote URLs
  consumed by ``video_service.audio_mux``. Stored as JSON so callers
  don't have to pre-link ``generated_images`` rows in a transaction.
- source_audio_id / source_subtitle_id — FK back to existing rows so
  a workflow run that fed these in keeps provenance.
- resolution / fps — propagated to ``video_service.audio_mux`` defaults.
- duration_ms — set after composition via ``ffprobe_duration_ms``.
- status values: pending / composing / completed / failed / cancelled.

Spec: docs-internal/superpowers/specs/m36-multimodal-foundation.md
"""
from sqlalchemy import (
    Column, Integer, String, Text, JSON, ForeignKey, Index, DateTime,
    LargeBinary,
)
from lumen_models.base import BaseModel


class GeneratedVideo(BaseModel):
    __tablename__ = "generated_videos"

    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    # Optional link back to a chat conversation that triggered the request
    conversation_id = Column(
        Integer, ForeignKey("conversations.id"), nullable=True, index=True,
    )
    # Optional. video_compose (M36) doesn't require a model — the FFmpeg
    # wrapper is the engine. Reserved for future M36.1+ when video-gen
    # providers (Kling/Sora/Veo) get added.
    model_config_id = Column(
        Integer,
        ForeignKey("model_configs.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    # Optional playbook that enriched the inputs (e.g. style direction in
    # SRT captions, or palette hints for image inputs we don't generate).
    playbook_id = Column(
        Integer, ForeignKey("playbooks.id"), nullable=True, index=True,
    )
    # Optional provenance links back to existing audio / subtitle rows
    source_audio_id = Column(
        Integer, ForeignKey("generated_audios.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    source_subtitle_id = Column(
        Integer, ForeignKey("subtitles.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )

    # source_images is a JSON list[str] of file paths or remote URLs the
    # composer stitched together. We deliberately don't FK to
    # generated_images because the user may also feed in raw uploads /
    # stock footage URLs (M36.2).
    source_images = Column(JSON, nullable=True)

    # Composed metadata propagated to ffmpeg
    resolution = Column(String(20), nullable=False, default="1280x720")
    fps = Column(Integer, nullable=False, default=24)
    # Free-form knobs: audio_fade_in, audio_fade_out, subtitle_font,
    # per_image_seconds, etc. Stored as JSON so the API can echo them
    # back without a schema migration each time we add a knob.
    params = Column(JSON, nullable=True)

    # Output
    file_path = Column(String(500), nullable=False, default="")
    file_size = Column(Integer, nullable=False, default=0)
    mime_type = Column(String(50), nullable=False, default="video/mp4")
    duration_ms = Column(Integer, nullable=True)
    # 200MB hard cap — a 30s 1080p H.264 already hits ~50MB so we keep
    # headroom. We don't store the bytes inline (would blow MEDIUMBLOB).
    thumbnail = Column(LargeBinary(length=16777215), nullable=True)

    status = Column(String(20), nullable=False, default="pending")
    # pending / composing / completed / failed / cancelled
    error_message = Column(Text, nullable=True)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index(
            "ix_gen_videos_tenant_status_created",
            "tenant_id", "status", "created_at",
        ),
    )