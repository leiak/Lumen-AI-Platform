"""M36: Video composition service (DB / BackgroundTasks / Notification layer).

The actual ffmpeg wrapper — ``lumen_services.video_service.audio_mux`` /
``subtitle_burn`` / ``concat_segments`` / ``build_video_from_assets`` —
lives in ``lumen_services/video_service.py`` and is provider-agnostic
(no DB / no notifications). This file is the orchestration layer:

- :class:`VideoComposeService` is a thin class mirroring
  ``ImageGenerationService`` (M22) and ``TTSService`` (M35). Its
  ``create()`` method writes a ``GeneratedVideo`` row in ``status=pending``
  and schedules :func:`_run_composition` via FastAPI's ``BackgroundTasks``.
- :func:`_run_composition` opens a **fresh** ``SessionLocal()`` (M29
  InnoDB REPEATABLE READ lesson), calls
  ``video_service.build_video_from_assets`` synchronously, saves the mp4
  via :func:`lumen_core.storage.save_bytes` (subdir="generated_videos"),
  updates the row to ``completed`` / ``failed``, writes an
  ``llm_call_logs`` row, and pushes a notification via WS.
- :meth:`VideoComposeService.create_sync_for_workflow` is the synchronous
  path used by the ``video_compose`` workflow node (T4) — same code as
  BackgroundTasks but blocks until done, returning the final row.

Asset resolution
----------------
``VideoComposeCreate`` accepts ``audio_path`` and ``subtitle_path`` as
either local filesystem paths OR stringified id refs (``"42"`` →
``generated_audios.id=42``, ``"17"`` → ``subtitles.id=17``).
:func:`_resolve_asset_to_path` does the conversion at create time so
``_run_composition`` reads pre-resolved paths back from the row's
``params`` JSON.

``source_images`` accepts the same shape (literal paths, pure-digit
``GeneratedImage.id``, or proxy URLs ``/api/v1/image-generation/{id}/image``
and ``/api/v1/stock-assets/{id}/image``). :func:`_resolve_image_paths`
normalizes the list at create time so FFmpeg always reads pre-resolved
local paths — the proxy URLs are Bearer-protected and would 401 if
ffmpeg tried to fetch them in-process.
"""
from __future__ import annotations

import logging
import re
import time
import uuid
from datetime import datetime
from typing import Any, List, Optional, Tuple

from fastapi import BackgroundTasks
from sqlalchemy import or_
from sqlalchemy.orm import Session

from lumen_core.storage import save_bytes
from lumen_models.video import GeneratedVideo
from lumen_services import video_service as vs
from lumen_services.notification_service import NotificationService
from lumen_schemas.video import VideoComposeCreate

log = logging.getLogger(__name__)


class VideoComposeError(Exception):
    """Application-level error from ``VideoComposeService``.

    Raised when the request is invalid (empty source_images,
    unresolvable asset id, model_config_id not configured). Mapped to
    4xx by the router. Provider / FFmpeg failures are written to
    ``row.status='failed'`` + ``error_message`` instead.
    """


class VideoComposeService:
    """Business logic for ``/api/v1/videos``.

    Spec: docs-internal/superpowers/specs/m36-multimodal-foundation.md §4
    """

    # ------------------------------------------------------------------
    # Create (POST /videos/)
    # ------------------------------------------------------------------

    def create(
        self,
        db: Session,
        *,
        tenant_id: int,
        user_id: int,
        payload: VideoComposeCreate,
        background_tasks: BackgroundTasks,
    ) -> Tuple[Optional[GeneratedVideo], Optional[str]]:
        """Create a row in ``status=pending`` and schedule ``_run_composition``.

        Returns ``(row, None)`` on success or ``(None, err_tag)`` where
        ``err_tag`` is one of:
        - ``"empty_sources"``: ``payload.source_images`` is empty.
        - ``"audio_not_found"``: ``audio_path`` looked like an id and
          didn't resolve to a row in this tenant.
        - ``"subtitle_not_found"``: same for subtitle.
        - ``"music_not_found"`` (M36.2.2): ``background_music_path``
          looked like a stock_musics id and didn't resolve.
        """
        if not payload.source_images:
            return None, "empty_sources"
        try:
            resolved_images = _resolve_image_paths(
                db, tenant_id=tenant_id, paths=list(payload.source_images),
            )
            resolved_audio = _resolve_asset_to_path(
                db, tenant_id=tenant_id, kind="audio",
                value=payload.audio_path,
            )
            resolved_subtitle = _resolve_asset_to_path(
                db, tenant_id=tenant_id, kind="subtitle",
                value=payload.subtitle_path,
            )
            resolved_music = _resolve_asset_to_path(
                db, tenant_id=tenant_id, kind="music",
                value=payload.background_music_path,
            )
        except AssetNotFound as e:
            return None, e.tag

        params_snapshot: dict[str, Any] = {
            "source_images": list(resolved_images),
            "audio_path": resolved_audio,
            "subtitle_path": resolved_subtitle,
            "background_music_path": resolved_music,
            "background_music_volume": payload.background_music_volume,
            "resolution": payload.resolution,
            "fps": payload.fps,
            "audio_fade_in": payload.audio_fade_in,
            "audio_fade_out": payload.audio_fade_out,
            "subtitle_font": payload.subtitle_font,
            "per_image_seconds": payload.per_image_seconds,
        }
        row = GeneratedVideo(
            tenant_id=tenant_id,
            user_id=user_id,
            conversation_id=payload.conversation_id,
            playbook_id=payload.playbook_id,
            source_audio_id=payload.source_audio_id,
            source_subtitle_id=payload.source_subtitle_id,
            source_images=list(resolved_images),
            resolution=payload.resolution,
            fps=payload.fps,
            params=params_snapshot,
            file_path="",
            file_size=0,
            mime_type="video/mp4",
            status="pending",
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        # Schedule the actual FFmpeg composition. Inside _run_composition
        # we open a fresh SessionLocal() so the request's transaction is
        # not piggybacked.
        background_tasks.add_task(_run_composition, row.id)  # type: ignore[arg-type]
        return row, None

    # ------------------------------------------------------------------
    # Synchronous variant (used by the video_compose workflow node in T4)
    # ------------------------------------------------------------------

    def create_sync_for_workflow(
        self,
        db: Session,
        *,
        tenant_id: int,
        user_id: int,
        payload: VideoComposeCreate,
    ) -> Tuple[Optional[GeneratedVideo], Optional[str]]:
        """Same as ``create`` but runs the composition inline (blocks).

        Used by the ``video_compose`` workflow node (T4) so the workflow
        executor can wait for the mp4 to land before moving on to the
        next node. Same error tags as ``create``.
        """
        if not payload.source_images:
            return None, "empty_sources"
        try:
            resolved_images = _resolve_image_paths(
                db, tenant_id=tenant_id, paths=list(payload.source_images),
            )
            resolved_audio = _resolve_asset_to_path(
                db, tenant_id=tenant_id, kind="audio",
                value=payload.audio_path,
            )
            resolved_subtitle = _resolve_asset_to_path(
                db, tenant_id=tenant_id, kind="subtitle",
                value=payload.subtitle_path,
            )
            resolved_music = _resolve_asset_to_path(
                db, tenant_id=tenant_id, kind="music",
                value=payload.background_music_path,
            )
        except AssetNotFound as e:
            return None, e.tag

        params_snapshot: dict[str, Any] = {
            "source_images": list(resolved_images),
            "audio_path": resolved_audio,
            "subtitle_path": resolved_subtitle,
            "background_music_path": resolved_music,
            "background_music_volume": payload.background_music_volume,
            "resolution": payload.resolution,
            "fps": payload.fps,
            "audio_fade_in": payload.audio_fade_in,
            "audio_fade_out": payload.audio_fade_out,
            "subtitle_font": payload.subtitle_font,
            "per_image_seconds": payload.per_image_seconds,
        }
        row = GeneratedVideo(
            tenant_id=tenant_id,
            user_id=user_id,
            conversation_id=payload.conversation_id,
            playbook_id=payload.playbook_id,
            source_audio_id=payload.source_audio_id,
            source_subtitle_id=payload.source_subtitle_id,
            source_images=list(resolved_images),
            resolution=payload.resolution,
            fps=payload.fps,
            params=params_snapshot,
            file_path="",
            file_size=0,
            mime_type="video/mp4",
            status="pending",
        )
        db.add(row)
        db.commit()
        db.refresh(row)

        # Run inline (no BackgroundTasks). Opens its own session via
        # ``_run_composition`` semantics — see ``compose_inline``.
        try:
            compose_inline(db, row.id)
            db.refresh(row)
        except Exception as e:
            log.exception("Inline composition crashed for video %s", row.id)
            db.refresh(row)
            # compose_inline already wrote status=failed + error_message,
            # we just need to surface the err tag.
            return row, "compose_failed"
        return row, None

    # ------------------------------------------------------------------
    # Read / list / cancel
    # ------------------------------------------------------------------

    def list_for_tenant(
        self,
        db: Session,
        *,
        tenant_id: int,
        page: int = 1,
        page_size: int = 12,
        status: Optional[str] = None,
    ) -> Tuple[List[GeneratedVideo], int]:
        q = db.query(GeneratedVideo).filter(
            GeneratedVideo.tenant_id == tenant_id,
        )
        if status:
            q = q.filter(GeneratedVideo.status == status)
        total = q.count()
        q = q.order_by(GeneratedVideo.created_at.desc())
        offset = (page - 1) * page_size
        return q.offset(offset).limit(page_size).all(), total

    def get(
        self,
        db: Session,
        *,
        tenant_id: int,
        video_id: int,
    ) -> Optional[GeneratedVideo]:
        return db.query(GeneratedVideo).filter(
            GeneratedVideo.id == video_id,
            GeneratedVideo.tenant_id == tenant_id,
        ).first()

    def cancel(
        self,
        db: Session,
        *,
        tenant_id: int,
        user_id: int,  # noqa: ARG002 — reserved for future ACL
        video_id: int,
    ) -> bool:
        """Best-effort cancel: set status='cancelled' if still pending/composing.

        FFmpeg subprocesses are not killed here (no PID is tracked).
        A future enhancement would register a cancel-event and have
        ``_run_composition`` poll it between FFmpeg steps. For M36 we
        accept that the underlying compose may complete despite the row
        being marked 'cancelled' — the API will still return 200 for
        ``GET /videos/{id}/download`` once done.
        """
        row = self.get(db, tenant_id=tenant_id, video_id=video_id)
        if not row:
            return False
        if row.status not in ("pending", "composing"):
            return False
        row.status = "cancelled"  # type: ignore[assignment]
        row.finished_at = datetime.utcnow()  # type: ignore[assignment]
        db.commit()
        return True


# ======================================================================
# Asset resolution
# ======================================================================


class AssetNotFound(Exception):
    """Raised when an id-style asset reference doesn't resolve."""

    def __init__(self, tag: str):
        super().__init__(tag)
        self.tag = tag


def _resolve_asset_to_path(
    db: Session,
    *,
    tenant_id: int,
    kind: str,
    value: Optional[str],
) -> Optional[str]:
    """Translate ``value`` into a local filesystem path or return ``None``.

    - ``None`` / empty: returns ``None`` (the FFmpeg wrapper will
      synthesize silence or skip subtitle burn).
    - Pure-digit string (e.g. ``"42"``): treated as a database id and
      looked up in the appropriate table scoped to ``tenant_id``. Raises
      :class:`AssetNotFound` if the row doesn't exist.
    - Anything else: returned as-is (treated as a local filesystem path
      by ``build_video_from_assets``).
    """
    if value is None or not str(value).strip():
        return None
    s = str(value).strip()
    if not s.isdigit():
        return s  # literal path
    pk = int(s)
    if kind == "audio":
        from lumen_models.tts import GeneratedAudio
        row = (
            db.query(GeneratedAudio)
            .filter(
                GeneratedAudio.id == pk,
                GeneratedAudio.tenant_id == tenant_id,
            )
            .first()
        )
        if not row or not row.file_path:
            raise AssetNotFound("audio_not_found")
        from lumen_core.config import settings
        from pathlib import PurePosixPath
        abs_path = settings.STORAGE_DIR / PurePosixPath(row.file_path)
        return str(abs_path)
    if kind == "subtitle":
        from lumen_models.subtitle import Subtitle
        row = (
            db.query(Subtitle)
            .filter(
                Subtitle.id == pk,
                Subtitle.tenant_id == tenant_id,
            )
            .first()
        )
        if not row or not row.content:
            raise AssetNotFound("subtitle_not_found")
        # Subtitle content is stored as TEXT (the SRT body), so we have
        # to write it to a temp file the FFmpeg subtitles= filter can
        # read. The temp file lives in settings.STORAGE_DIR / "_tmp/" so
        # it's isolated from the rest of storage.
        from lumen_core.config import settings
        from pathlib import Path
        tmp_dir = settings.STORAGE_DIR / "_tmp" / "subtitles"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        ext = (row.format or "srt").lower()
        tmp_path = tmp_dir / f"subtitle_{row.id}_{uuid.uuid4().hex[:8]}.{ext}"
        tmp_path.write_text(row.content, encoding="utf-8")
        return str(tmp_path)
    if kind == "music":
        # M36.2.2: 背景音乐 lookup。``tenant_id IS NULL`` 是全局 builtin,
        # 所有租户可见(跟 stock_asset / stock_image 共享同一规则)。
        from lumen_core.config import settings
        from lumen_models.stock_music import StockMusic
        from pathlib import PurePosixPath

        row = (
            db.query(StockMusic)
            .filter(
                StockMusic.id == pk,
                or_(
                    StockMusic.tenant_id.is_(None),
                    StockMusic.tenant_id == tenant_id,
                ),
            )
            .first()
        )
        if not row or not row.file_path:
            raise AssetNotFound("music_not_found")
        abs_path = settings.STORAGE_DIR / PurePosixPath(row.file_path)
        return str(abs_path)
    raise ValueError(f"unknown asset kind: {kind!r}")


# 匹配 ``/api/v1/image-generation/{id}/image`` URL 形态(M22)。
_IMAGE_GEN_URL_RE = re.compile(r"/image-generation/(\d+)/image")
# 匹配 ``/api/v1/stock-assets/{id}/image`` URL 形态(M36.2.1)。
_STOCK_URL_RE = re.compile(r"/stock-assets/(\d+)/image")


def _resolve_image_gen_to_path(
    db: Session, *, tenant_id: int, image_id: int,
) -> Optional[str]:
    """``image-generation`` / 纯数字 id 形态图像 → 磁盘绝对路径或 None。

    找不到对应行返回 ``None``(由 caller 决定是否抛 ``AssetNotFound``)。
    """
    from lumen_core.config import settings
    from lumen_models.image_generation import GeneratedImage
    from pathlib import PurePosixPath

    row = (
        db.query(GeneratedImage)
        .filter(
            GeneratedImage.id == image_id,
            GeneratedImage.tenant_id == tenant_id,
        )
        .first()
    )
    if not row or not row.file_path:
        return None
    abs_path = settings.STORAGE_DIR / PurePosixPath(row.file_path)
    return str(abs_path)


def _resolve_stock_image_to_path(
    db: Session, *, tenant_id: int, image_id: int,
) -> Optional[str]:
    """``stock-assets`` URL 形态图像 → 磁盘绝对路径或 None。

    Stock 跟 image-generation 的可见性规则不同:``tenant_id=NULL`` 是
    全局 builtin,所有租户都能看到;非 NULL 仅该租户可见。
    """
    from lumen_core.config import settings
    from lumen_models.stock_asset import StockAsset
    from pathlib import PurePosixPath

    row = (
        db.query(StockAsset)
        .filter(
            StockAsset.id == image_id,
            or_(
                StockAsset.tenant_id.is_(None),
                StockAsset.tenant_id == tenant_id,
            ),
        )
        .first()
    )
    if not row or not row.file_path:
        return None
    abs_path = settings.STORAGE_DIR / PurePosixPath(row.file_path)
    return str(abs_path)


def _resolve_image_to_local_path(
    db: Session, tenant_id: int, value: str,
) -> Optional[str]:
    """把图像 entry 翻译成本地文件系统路径或返回 ``None``。

    支持:
    - ``/api/v1/image-generation/{id}/image`` → GeneratedImage DB lookup
    - ``/api/v1/stock-assets/{id}/image`` → StockAsset DB lookup
      (global builtin OR 当前租户)
    - ``"{id}"`` 纯数字字串 → GeneratedImage DB lookup(legacy 兼容;
      dashboard 直接粘贴 GeneratedImage id 也能用)
    - 其他 → 原样返回(当作本地路径;workflow node 预解析过的也走这条)

    找不到对应行时返回 ``None``,由 caller 决定是否抛
    :class:`AssetNotFound`("image_not_found")。
    """
    s = (value or "").strip()
    if not s:
        return None

    stock_match = _STOCK_URL_RE.search(s)
    if stock_match:
        return _resolve_stock_image_to_path(
            db, tenant_id=tenant_id, image_id=int(stock_match.group(1)),
        )

    gen_match = _IMAGE_GEN_URL_RE.search(s)
    if gen_match:
        return _resolve_image_gen_to_path(
            db, tenant_id=tenant_id, image_id=int(gen_match.group(1)),
        )

    if s.isdigit():
        return _resolve_image_gen_to_path(
            db, tenant_id=tenant_id, image_id=int(s),
        )

    # 字面路径 — 原样返回(caller 会验存在性)。
    return s


def _resolve_image_paths(
    db: Session, tenant_id: int, paths: List[str],
) -> List[str]:
    """把整张 source_images 列表解析成本地路径。

    空字符串跳过(跟 workflow node 的 `VariableTemplateParser.format`
    把空模板替换成空串的场景对齐)。任何 URL 解析不到对应行时抛
    :class:`AssetNotFound`("image_not_found")。
    """
    out: List[str] = []
    for raw in paths:
        if not raw or not str(raw).strip():
            continue
        local = _resolve_image_to_local_path(db, tenant_id, str(raw))
        if local is None:
            raise AssetNotFound("image_not_found")
        out.append(local)
    return out


# ======================================================================
# Internal composition runner (sync function, called from BackgroundTasks)
# ======================================================================


def _run_composition(video_id: int) -> None:
    """Background task entry point. Owns its own DB session.

    Loads the row, runs ``build_video_from_assets`` synchronously, saves
    the mp4, updates the row, writes llm_call_logs, pushes a notification.
    Any exception is captured onto ``row.error_message`` rather than
    raising out — uvicorn doesn't surface BackgroundTask failures well,
    and the row is the source of truth for clients anyway.
    """
    from lumen_core.database import SessionLocal

    db = SessionLocal()
    try:
        compose_inline(db, video_id)
    except Exception as e:
        log.exception("_run_composition crashed for video %s", video_id)
        try:
            row = db.get(GeneratedVideo, video_id)
            if row and row.status not in ("completed", "cancelled"):
                row.status = "failed"  # type: ignore[assignment]
                row.error_message = f"{type(e).__name__}: {e}"[:1000]  # type: ignore[assignment]
                row.finished_at = datetime.utcnow()  # type: ignore[assignment]
                db.commit()
        finally:
            db.close()
    else:
        db.close()


def compose_inline(db: Session, video_id: int) -> None:
    """The synchronous composition body — used by both BackgroundTasks
    and ``create_sync_for_workflow``. Operates on the supplied session.
    """
    from lumen_schemas.video import VideoStatus  # noqa: F401  (typing only)

    row = db.get(GeneratedVideo, video_id)
    if not row:
        log.error("compose_inline: video row %s vanished", video_id)
        return
    if row.status in ("completed", "cancelled"):
        return

    params = row.params or {}
    image_paths: List[str] = list(params.get("source_images") or [])
    audio_path: Optional[str] = params.get("audio_path")
    subtitle_path: Optional[str] = params.get("subtitle_path")
    # M36.2.2: 背景音乐已由 create / create_sync_for_workflow 在 DB
    # lookup 后预解析成本地绝对路径,这里直接透传。
    bgm_path: Optional[str] = params.get("background_music_path")
    bgm_volume: float = float(params.get("background_music_volume") or 0.3)
    resolution: str = params.get("resolution") or "1280x720"
    fps: int = int(params.get("fps") or 24)
    audio_fade_in: float = float(params.get("audio_fade_in") or 0.0)
    audio_fade_out: float = float(params.get("audio_fade_out") or 0.0)
    subtitle_font: Optional[str] = params.get("subtitle_font")
    per_image_seconds: Optional[float] = params.get("per_image_seconds")

    row.status = "composing"  # type: ignore[assignment]
    row.started_at = datetime.utcnow()  # type: ignore[assignment]
    db.commit()

    started = time.monotonic()
    try:
        data, size, duration_ms = vs.build_video_from_assets(
            image_paths=image_paths,
            audio_path=audio_path,
            subtitle_path=subtitle_path,
            bgm_path=bgm_path,
            bgm_volume=bgm_volume,
            resolution=resolution,
            fps=fps,
            audio_fade_in=audio_fade_in,
            audio_fade_out=audio_fade_out,
            subtitle_font=subtitle_font,
            per_image_seconds=per_image_seconds,
        )
        abs_path, size, rel_path = save_bytes(
            row.tenant_id,  # type: ignore[arg-type]
            data,
            row.mime_type,  # type: ignore[arg-type]
            subdir="generated_videos",
        )
        row.file_path = rel_path  # type: ignore[assignment]
        row.file_size = size  # type: ignore[assignment]
        row.duration_ms = duration_ms  # type: ignore[assignment]
        row.status = "completed"  # type: ignore[assignment]
        row.error_message = None  # type: ignore[assignment]
        duration_ms_total = int((time.monotonic() - started) * 1000)
        log.info(
            "Video %s composed in %dms (size=%d dur_ms=%d)",
            video_id, duration_ms_total, size, duration_ms,
        )
        _write_call_log(row, duration_ms=duration_ms_total, ok=True)
    except Exception as e:
        row.status = "failed"  # type: ignore[assignment]
        row.error_message = f"{type(e).__name__}: {e}"[:1000]  # type: ignore[assignment]
        log.exception("Video %s composition failed", video_id)
        _write_call_log(row, duration_ms=int((time.monotonic() - started) * 1000), ok=False)
    finally:
        row.finished_at = datetime.utcnow()  # type: ignore[assignment]
        db.commit()
        _push_notification(db, row)


def _write_call_log(row: GeneratedVideo, *, duration_ms: int, ok: bool) -> None:
    """Best-effort write to ``llm_call_logs`` so video composes are
    observable in the same dashboard surface as LLM/image/TTS calls.
    """
    try:
        from lumen_core.database import SessionLocal
        from lumen_core.llm_call_context import LLMCallContext
        from lumen_services.llm_call_logging import get_llm_call_logging_service
        log_db = SessionLocal()
        try:
            get_llm_call_logging_service().log_call(
                log_db,
                ctx=LLMCallContext(
                    call_id=str(uuid.uuid4()),
                    trace_id=str(uuid.uuid4()),
                    parent_call_id=None,
                    call_type="video_compose",
                    call_index=0,
                    tenant_id=row.tenant_id,  # type: ignore[arg-type]
                    user_id=row.user_id,  # type: ignore[arg-type]
                    client_app="dashboard",
                    image_id=None,
                    extra={
                        "video_id": row.id,
                        "resolution": row.resolution,
                        "fps": row.fps,
                        "source_image_count": len(row.source_images or []),
                        "has_audio": bool((row.params or {}).get("audio_path")),
                        "has_subtitle": bool((row.params or {}).get("subtitle_path")),
                    },
                ),
                model_type="ffmpeg",
                model_name="ffmpeg-video-composer",
                temperature=None,
                max_tokens=None,
                system_messages=None,
                user_message=f"compose video {row.id}",
                messages=[{"role": "user", "content": f"compose video {row.id}"}],
                tools=None,
                extra_params={
                    "resolution": row.resolution,
                    "fps": row.fps,
                },
                response_content=f"video {row.id} {row.status}",
                finish_reason="stop",
                tool_calls=None,
                token_usage=None,
                started_at=row.started_at or datetime.utcnow(),  # type: ignore[arg-type]
                finished_at=datetime.utcnow(),
                duration_ms=duration_ms,
                first_token_latency_ms=None,
                status="success" if ok else "failure",
                error_type=None if ok else "CompositionError",
                error_message=None if ok else (row.error_message or "composition failed"),
                model_config_id=row.model_config_id,
            )
        finally:
            log_db.close()
    except Exception as log_err:
        # Best-effort: don't fail the bg task if logging fails.
        log.warning("llm_call_logs write failed for video %s: %s", row.id, log_err)


def _push_notification(db: Session, row: GeneratedVideo) -> None:
    """Push a VIDEO_COMPOSE_COMPLETED / FAILED / CANCELLED notification."""
    try:
        ns = NotificationService()
        status_to_type = {
            "completed": ("VIDEO_COMPOSE_COMPLETED", "视频合成完成"),
            "failed": ("VIDEO_COMPOSE_FAILED", "视频合成失败"),
            "cancelled": ("VIDEO_COMPOSE_CANCELLED", "视频合成已取消"),
        }
        event_type, default_title = status_to_type.get(
            row.status or "", ("VIDEO_COMPOSE_COMPLETED", "视频合成"),
        )
        ns.publish_event(
            db,
            user_id=row.user_id,  # type: ignore[arg-type]
            type=event_type,
            title=default_title,
            body=(row.error_message or "")[:50],
            resource_type="generated_video",
            resource_id=row.id,  # type: ignore[arg-type]
            metadata={
                "video_id": row.id,
                "status": row.status,
                "duration_ms": row.duration_ms,
                "file_size": row.file_size,
                "error_message": row.error_message,
            },
        )
    except Exception as e:
        log.warning("Failed to push notification for video %s: %s", row.id, e)
        try:
            db.rollback()
        except Exception:
            pass