"""M36.2.2: Stock background-music library ORM.

Mirrors ``lumen_models.stock_asset`` (M36.2.1) — built-in BGM lives with
``tenant_id=NULL`` (visible to every tenant); tenant-uploaded BGM lives
with ``tenant_id=<owning tenant>``. The video composition service reads
``file_path`` off this table when ``background_music_path`` looks like a
pure-digit id (see ``video_compose_service._resolve_asset_to_path``).

Spec: docs/modules/video-composition.md §3.1
"""
from sqlalchemy import Column, Float, Index, Integer, String, Text

from lumen_models.base import BaseModel


class StockMusic(BaseModel):
    __tablename__ = "stock_musics"

    name = Column(String(120), nullable=False, comment="Human-readable label, e.g. 'Mellow Piano'")
    # Style category used to bucket the gallery (mirrors stock_asset
    # categories: 舒缓 / 振奋 / 戏剧 / 商务 / 氛围). Free-form string
    # so new moods can be added without a schema change.
    category = Column(String(40), nullable=False, index=True, comment="舒缓 / 振奋 / 戏剧 / 商务 / 氛围")
    description = Column(Text, nullable=True)
    # Relative to ``settings.STORAGE_DIR``, e.g. ``stock/music/mellow-piano.mp3``.
    # The video_compose service resolves this via ``STORAGE_DIR / file_path``
    # after the lookup; ``StockMusicService.get_file_abs_path`` enforces the
    # same ``relative + under STORAGE_DIR`` guard as stock_service to block
    # ``..`` escapes.
    file_path = Column(String(500), nullable=False)
    mime_type = Column(String(50), nullable=False, default="audio/mpeg")
    file_size = Column(Integer, nullable=False, default=0)
    duration_seconds = Column(Float, nullable=False, default=30.0, comment="Track length in seconds")
    # Where the BGM came from. Built-in tracks are MIDI-synthesized at seed
    # time; ``uploaded`` is reserved for future tenant upload support.
    source = Column(String(20), nullable=False, default="builtin", comment="builtin | uploaded")
    # NULL = global builtin visible to every tenant (mirrors StockAsset).
    tenant_id = Column(Integer, nullable=True, index=True, comment="NULL = global builtin")

    __table_args__ = (
        Index("ix_stock_musics_category_created", "category", "created_at"),
    )
