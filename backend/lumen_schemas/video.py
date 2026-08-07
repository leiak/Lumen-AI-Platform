"""M36: Video composition Pydantic schemas.

Mirrors ``lumen_schemas.tts`` (M35) — separate Create / Read / ListItem
shapes so the list page can stay light while the detail page surfaces
every column on ``GeneratedVideo``.

The ``VideoComposeCreate`` payload accepts pre-resolved asset paths or
ids from upstream workflows. The router (T3) resolves id → file path
when needed and then hands the local paths to
``lumen_services.video_service.build_video_from_assets``.

Spec: docs-internal/superpowers/specs/m36-multimodal-foundation.md
"""
from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


VideoStatus = Literal["pending", "composing", "completed", "failed", "cancelled"]


class VideoComposeCreate(BaseModel):
    """Request body for ``POST /api/v1/videos``.

    All three source arrays are optional but at least one must be
    provided (the service rejects empty ``source_images``). ``audio_path``
    and ``subtitle_path`` accept either local filesystem paths OR asset
    ids (``generated_audios.id`` / ``subtitles.id``); the router resolves
    id → path when given.

    ``resolution`` must be ``"WIDTHxHEIGHT"`` (e.g. ``"1280x720"``) —
    parsed inside ``video_service.audio_mux``.
    """

    # Asset inputs — three independent "tracks" that the FFmpeg composer
    # stitches together. All optional but at least one image is required.
    source_images: List[str] = Field(
        default_factory=list,
        description=(
            "List of local image file paths. Required: at least one entry. "
            "When >1, images are evenly split across the audio (or "
            "per_image_seconds when set)."
        ),
    )
    audio_path: Optional[str] = Field(
        None,
        description=(
            "Local audio file path OR generated_audios.id (as string). "
            "None → 4s of stereo silence is synthesized so the mp4 has an "
            "audio stream."
        ),
    )
    subtitle_path: Optional[str] = Field(
        None,
        description=(
            "Local SRT/VTT path OR subtitles.id (as string). None → no "
            "subtitle burn step."
        ),
    )
    # M36.2.2: 背景音乐(BGM)。None → 没有 BGM,主轨保持纯语音。可
    # 填本地路径或 stock_musics.id(纯数字字串)。FFmpeg 用 amix 把
    # BGM 以 bgm_volume 音量混到主轨,BGM 自动循环到主轨长度。
    background_music_path: Optional[str] = Field(
        None,
        description=(
            "本地音频路径 或 stock_musics.id (整数)。None → 不加 BGM。"
        ),
    )
    background_music_volume: float = Field(
        default=0.3,
        ge=0.0,
        le=1.0,
        description=(
            "BGM 相对主轨的音量 (0.0 - 1.0)。默认 0.3,UI 暂不暴露,"
            "schema 留位以后可加滑块。"
        ),
    )
    # Convenience FK refs the workflow node fills in. Kept separate from
    # the path strings so the row can show provenance after composition.
    source_audio_id: Optional[int] = Field(
        None, description="Optional FK back to generated_audios.id",
    )
    source_subtitle_id: Optional[int] = Field(
        None, description="Optional FK back to subtitles.id",
    )
    playbook_id: Optional[int] = Field(
        None, description="Optional playbook for style direction (M36.1)",
    )
    conversation_id: Optional[int] = None

    # Composition knobs forwarded to video_service.build_video_from_assets.
    resolution: str = Field(
        default="1280x720",
        pattern=r"^\d+[xX]\d+$",
        description='Output frame size, e.g. "1280x720" or "1920x1080".',
    )
    fps: int = Field(default=24, ge=1, le=60)
    audio_fade_in: float = Field(default=0.0, ge=0.0, le=10.0)
    audio_fade_out: float = Field(default=0.0, ge=0.0, le=10.0)
    subtitle_font: Optional[str] = Field(
        None, description='Font family name, e.g. "Microsoft YaHei".',
    )
    per_image_seconds: Optional[float] = Field(
        None,
        gt=0.0,
        description=(
            "Override per-image display duration when source_images has "
            ">1 entries. Defaults to audio_dur / len(source_images)."
        ),
    )


class VideoComposeRead(BaseModel):
    """Full row representation — returned by ``GET /videos/{id}``."""

    model_config = ConfigDict(from_attributes=True, protected_namespaces=())

    id: int
    tenant_id: int
    user_id: int
    conversation_id: Optional[int]
    model_config_id: Optional[int]
    playbook_id: Optional[int]
    source_audio_id: Optional[int]
    source_subtitle_id: Optional[int]
    source_images: Optional[List[str]]
    # M36.2.2: 回显用,返回 DB row 时把背景音乐路径一起带上。
    background_music_path: Optional[str] = None
    resolution: str
    fps: int
    file_path: str
    file_size: int
    mime_type: str
    duration_ms: Optional[int]
    status: VideoStatus
    error_message: Optional[str]
    started_at: Optional[datetime]
    finished_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime


class VideoComposeListItem(BaseModel):
    """Lightweight row for the per-tenant history list."""

    model_config = ConfigDict(from_attributes=True, protected_namespaces=())

    id: int
    resolution: str
    fps: int
    file_size: int
    duration_ms: Optional[int]
    status: VideoStatus
    image_count: int = Field(
        default=0,
        description="len(source_images) at compose time, surfaced for the list UI.",
    )
    created_at: datetime


class VideoComposeDownloadResponse(BaseModel):
    """Lightweight payload returned by the API before streaming bytes."""

    id: int
    file_path: str
    file_size: int
    mime_type: str
    duration_ms: Optional[int]