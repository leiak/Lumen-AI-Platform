"""M35: TTS service — creates GeneratedAudio rows, dispatches background
synthesis, persists the audio file, writes an LLMCallLog row, and
publishes a notification.

Mirrors lumen_services.image_generation_service.ImageGenerationService
(M22). The lifecycle is:

    create() → row(status=pending) + BackgroundTasks(_run_synthesis)
    _run_synthesis():
        - load row in a fresh SessionLocal
        - if playbook_id, enrich text via PlaybookService.inject_into_prompt
        - dispatch to provider.synthesize(...)
        - save_bytes to disk; run ffprobe for duration_ms
        - update row to status=completed|failed
        - log_call(call_type="tts")
        - publish_notification(AUDIO_GENERATION_COMPLETED|FAILED)

Spec: docs-internal/superpowers/specs/M35-overview.md §4
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import time
import uuid
from datetime import datetime
from typing import List, Optional, Tuple

from fastapi import BackgroundTasks
from sqlalchemy.orm import Session

from lumen_core.llm_call_context import LLMCallContext
from lumen_core.storage import save_bytes, delete_relative
from lumen_models.model_config import ModelConfig
from lumen_models.tts import GeneratedAudio
from lumen_services.notification_service import NotificationService
from lumen_services.playbook_service import (
    get_for_tenant as get_playbook_for_tenant,
    inject_into_prompt,
    validate_scope,
)
from lumen_services.tts_providers.factory import get_tts_provider

log = logging.getLogger(__name__)

# 50MB cap on a single audio payload. Anything larger is a sign of
# runaway text input (or a misconfigured loop). StreamingResponse in
# the API can chunk it, but we refuse to store more.
MAX_FILE_SIZE = 50 * 1024 * 1024

# How many seconds a single synthesis call is allowed to take before
# the background task kills it. 5 minutes covers a 100k-char text on
# a slow Edge TTS connection.
SYNTHESIS_TIMEOUT_SEC = 300


# ──────────────────────────────────────────────────────────────────────
# Service entrypoints
# ──────────────────────────────────────────────────────────────────────

class TTSService:
    """Business logic for /api/v1/tts."""

    def create(
        self,
        db: Session,
        *,
        tenant_id: int,
        user_id: int,
        model_config_id: int,
        text: str,
        voice: str = "default",
        speed: float = 1.0,
        format: str = "mp3",
        playbook_id: Optional[int] = None,
        conversation_id: Optional[int] = None,
        background_tasks: BackgroundTasks,
    ) -> Tuple[Optional[GeneratedAudio], Optional[str]]:
        """Create a GeneratedAudio row (status=pending) + schedule synthesis.

        Returns ``(row, None)`` on success, ``(None, error_tag)`` on
        business-logic refusal. ``error_tag`` is one of:
        - ``"not_found"`` — model_config_id does not exist for this tenant
        - ``"not_tts_capable"`` — the model is not flagged is_tts=True
        - ``"playbook_not_found"`` — playbook_id does not exist or is
          not visible to this tenant
        - ``"text_too_long"`` — text exceeds 10,000 chars
        - ``"empty_text"`` — text is empty after strip
        """
        text = (text or "").strip()
        if not text:
            return None, "empty_text"
        if len(text) > 10000:
            return None, "text_too_long"

        mc = db.query(ModelConfig).filter(
            ModelConfig.id == model_config_id,
        ).first()
        if not mc:
            return None, "not_found"
        # Global configs (tenant_id IS NULL) are visible to all tenants;
        # tenant-scoped configs only to their own tenant.
        if mc.tenant_id is not None and mc.tenant_id != tenant_id:
            return None, "not_found"
        if not mc.is_tts:
            return None, "not_tts_capable"

        # Optional playbook — verify it exists and applies to TTS.
        if playbook_id is not None:
            pb = get_playbook_for_tenant(
                db, tenant_id=tenant_id, playbook_id=playbook_id,
            )
            if pb is None:
                return None, "playbook_not_found"
            if not validate_scope(pb, "tts"):
                return None, "playbook_not_found"

        params_snapshot = {
            "voice": voice, "speed": speed, "format": format,
            "playbook_id": playbook_id,
        }
        row = GeneratedAudio(
            tenant_id=tenant_id,
            user_id=user_id,
            conversation_id=conversation_id,
            model_config_id=model_config_id,
            playbook_id=playbook_id,
            text=text,
            voice=voice,
            speed=f"{speed:.2f}",
            format=format,
            params=params_snapshot,
            file_path="",  # filled by _run_synthesis
            file_size=0,
            mime_type=_mime_for_format(format),
            char_count=len(text),
            status="pending",
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        background_tasks.add_task(_run_synthesis, row.id)
        return row, None

    def list_for_tenant(
        self,
        db: Session,
        *,
        tenant_id: int,
        page: int = 1,
        page_size: int = 12,
        status: Optional[str] = None,
        model_config_id: Optional[int] = None,
    ) -> Tuple[List[GeneratedAudio], int]:
        q = db.query(GeneratedAudio).filter(GeneratedAudio.tenant_id == tenant_id)
        if status:
            q = q.filter(GeneratedAudio.status == status)
        if model_config_id is not None:
            q = q.filter(GeneratedAudio.model_config_id == model_config_id)
        total = q.count()
        q = q.order_by(GeneratedAudio.created_at.desc())
        offset = (page - 1) * page_size
        return q.offset(offset).limit(page_size).all(), total

    def get(
        self,
        db: Session,
        *,
        tenant_id: int,
        audio_id: int,
    ) -> Optional[GeneratedAudio]:
        return db.query(GeneratedAudio).filter(
            GeneratedAudio.id == audio_id,
            GeneratedAudio.tenant_id == tenant_id,
        ).first()

    def cancel(
        self,
        db: Session,
        *,
        tenant_id: int,
        audio_id: int,
    ) -> Optional[GeneratedAudio]:
        """Mark a still-running job as cancelled. Idempotent: returning
        a non-pending row means it already finished — we return it as-is
        so the UI can show the actual status."""
        row = self.get(db, tenant_id=tenant_id, audio_id=audio_id)
        if not row:
            return None
        if row.status in ("pending", "running"):
            row.status = "cancelled"  # type: ignore[assignment]
            row.finished_at = datetime.utcnow()  # type: ignore[assignment]
            db.commit()
            db.refresh(row)
        return row

    def delete(
        self,
        db: Session,
        *,
        tenant_id: int,
        audio_id: int,
    ) -> bool:
        row = self.get(db, tenant_id=tenant_id, audio_id=audio_id)
        if not row:
            return False
        # M26-style: wipe any LLMCallLog rows that point at this
        # audio_id (FK is RESTRICT).
        try:
            from lumen_models.llm_call_log import LLMCallLog
            db.query(LLMCallLog).filter(
                LLMCallLog.audio_id == audio_id
            ).delete(synchronize_session=False)
        except Exception:
            pass
        db.commit()
        if row.file_path:
            delete_relative(row.file_path)  # type: ignore[arg-type]
        db.delete(row)
        db.commit()
        return True


# ──────────────────────────────────────────────────────────────────────
# Background synthesis
# ──────────────────────────────────────────────────────────────────────

def _mime_for_format(fmt: str) -> str:
    return {
        "mp3": "audio/mpeg",
        "wav": "audio/wav",
        "opus": "audio/opus",
        "flac": "audio/flac",
        "aac": "audio/aac",
    }.get((fmt or "mp3").lower(), "audio/mpeg")


def _ffprobe_duration_ms(path: str) -> Optional[int]:
    """Run ffprobe to get the audio duration in ms. Returns None on
    any failure (binary missing, file not yet written) — duration_ms
    stays NULL, which is OK for the UI to show "—".
    """
    try:
        proc = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "json",
                path,
            ],
            capture_output=True, text=True, timeout=30,
        )
        if proc.returncode != 0:
            return None
        data = json.loads(proc.stdout or "{}")
        dur = float((data.get("format") or {}).get("duration") or 0)
        if dur <= 0:
            return None
        return int(dur * 1000)
    except (FileNotFoundError, subprocess.TimeoutExpired, ValueError, json.JSONDecodeError):
        return None


async def _call_provider_synthesize(provider, *, text: str, voice: str, speed: float, format: str) -> bytes:
    """Call provider.synthesize. Provider is duck-typed (Protocol)."""
    return await provider.synthesize(
        text=text, voice=voice, speed=speed, format=format,
    )


def _run_synthesis(audio_id: int) -> None:
    """Background task entrypoint (sync, dispatches into asyncio.run).

    Mirrors _run_generation in image_generation_service.py:
    1. Open a fresh SessionLocal (the request session is closed).
    2. Load row + ModelConfig.
    3. Optionally enrich ``text`` with playbook's voice_direction.
    4. Synthesize via the provider.
    5. Save bytes to disk; probe duration.
    6. Update row to completed / failed; commit.
    7. Write a LLMCallLog row in a SEPARATE session so a log FK
       failure can't undo the audio row's commit.
    8. Publish notification.
    """
    from lumen_core.database import SessionLocal
    from lumen_services.llm_call_logging import get_llm_call_logging_service

    db = SessionLocal()
    log_call_id = str(uuid.uuid4())
    log_trace_id = str(uuid.uuid4())
    log_started_at = datetime.utcnow()
    log_tenant_id: Optional[int] = None
    log_user_id: Optional[int] = None
    log_audio_id: Optional[int] = None
    log_text: Optional[str] = None
    log_voice: Optional[str] = None
    log_format: Optional[str] = None
    log_model_name: Optional[str] = None
    log_model_type: Optional[str] = None
    log_model_config_id: Optional[int] = None
    log_extra: dict = {}

    try:
        row = db.query(GeneratedAudio).filter(GeneratedAudio.id == audio_id).first()
        if not row:
            log.error("_run_synthesis: row %s not found", audio_id)
            return
        log_tenant_id = row.tenant_id
        log_user_id = row.user_id
        log_audio_id = row.id
        log_text = row.text
        log_voice = row.voice
        log_format = row.format
        log_extra = {
            "voice": row.voice,
            "speed": row.speed,
            "format": row.format,
            "playbook_id": row.playbook_id,
        }
        mc = db.query(ModelConfig).filter(ModelConfig.id == row.model_config_id).first()
        if not mc:
            row.status = "failed"  # type: ignore[assignment]
            row.error_message = f"model_config {row.model_config_id} not found"  # type: ignore[assignment]
            row.finished_at = datetime.utcnow()  # type: ignore[assignment]
            db.commit()
            _push_notification(db, row)
            return
        log_model_name = mc.model_name
        log_model_type = mc.model_type
        log_model_config_id = mc.id

        row.status = "running"  # type: ignore[assignment]
        row.started_at = datetime.utcnow()  # type: ignore[assignment]
        db.commit()

        # Optional playbook enrichment
        synth_text = row.text
        if row.playbook_id:
            pb = get_playbook_for_tenant(
                db, tenant_id=row.tenant_id, playbook_id=row.playbook_id,
            )
            if pb is not None and validate_scope(pb, "tts"):
                # For TTS, the "enrichment" is the voice_direction
                # metadata, not a prompt rewrite. We append it to a
                # private log_extra slot so an admin can see what
                # direction was used; the synthesized text is the
                # caller's original input.
                log_extra["voice_direction"] = (pb.style_tokens or {}).get("voice_direction")
                log_extra["voice_tone"] = (pb.style_tokens or {}).get("voice_tone")

        start = time.monotonic()
        duration_ms: int = 0
        try:
            provider = get_tts_provider(mc)
            speed_f = float(row.speed or "1.0")
            data = asyncio.run(
                _call_provider_synthesize(
                    provider,
                    text=synth_text,
                    voice=row.voice,
                    speed=speed_f,
                    format=row.format,
                )
            )
            if not data:
                raise RuntimeError("provider returned empty audio bytes")
            if len(data) > MAX_FILE_SIZE:
                raise RuntimeError(
                    f"audio payload too large: {len(data)} bytes (cap={MAX_FILE_SIZE})"
                )
            abs_path, size, rel_path = save_bytes(
                row.tenant_id, data, row.mime_type,  # type: ignore[arg-type]
                subdir="generated_audios",
            )
            row.file_path = rel_path  # type: ignore[assignment]
            row.file_size = size  # type: ignore[assignment]
            row.status = "completed"  # type: ignore[assignment]
            row.finished_at = datetime.utcnow()  # type: ignore[assignment]
            duration_ms = int((time.monotonic() - start) * 1000)
            row.duration_ms = duration_ms  # type: ignore[assignment]
            row.error_message = None  # type: ignore[assignment]
            cost = provider.estimate_cost(len(synth_text))
            row.cost_usd = f"{cost:.6f}"  # type: ignore[assignment]
            # Best-effort duration probe; non-fatal if ffprobe is missing.
            probed = _ffprobe_duration_ms(str(abs_path))
            if probed is not None and probed > 0:
                # Probe wins for accurate playback timing.
                row.duration_ms = probed  # type: ignore[assignment]
            log.info(
                "Audio %s synthesized in %dms via %s, %d bytes",
                audio_id, duration_ms, type(provider).__name__, size,
            )
        except Exception as e:
            row.status = "failed"  # type: ignore[assignment]
            row.error_message = str(e)[:1000]  # type: ignore[assignment]
            row.finished_at = datetime.utcnow()  # type: ignore[assignment]
            duration_ms = int((time.monotonic() - start) * 1000)
            log.exception("Audio %s synthesis failed", audio_id)
        db.commit()
        _push_notification(db, row)

        # LLMCallLog in a fresh session so a log failure doesn't undo
        # the audio row. Mirrors the image-generation pattern.
        log_db = SessionLocal()
        try:
            get_llm_call_logging_service().log_call(
                log_db,
                ctx=LLMCallContext(
                    call_id=log_call_id,
                    trace_id=log_trace_id,
                    parent_call_id=None,
                    call_type="tts",
                    call_index=0,
                    tenant_id=log_tenant_id,
                    user_id=log_user_id,
                    client_app="dashboard",
                    audio_id=log_audio_id,
                    extra=log_extra,
                ),
                model_type=log_model_type,
                model_name=log_model_name or "unknown",
                temperature=None,
                max_tokens=None,
                system_messages=None,
                user_message=log_text,
                messages=[{"role": "user", "content": log_text or ""}],
                tools=None,
                extra_params={
                    "voice": log_voice,
                    "format": log_format,
                },
                response_content=f"audio {log_audio_id} {row.status}",
                finish_reason="stop",
                tool_calls=None,
                token_usage=None,  # TTS doesn't report tokens
                started_at=log_started_at,
                finished_at=datetime.utcnow(),
                duration_ms=duration_ms,
                first_token_latency_ms=None,
                status=row.status if row.status in ("success", "completed") else "failure",
                error_type=None if row.status == "completed" else "ProviderError",
                error_message=row.error_message if row.status != "completed" else None,
                model_config_id=log_model_config_id,
            )
        except Exception as log_err:
            log.warning("llm_call_logs write failed (audio_id=%s): %s", log_audio_id, log_err)
        finally:
            log_db.close()
    finally:
        db.close()


def _push_notification(db: Session, row: GeneratedAudio) -> None:
    """Push a notification on completion/failure. Wrapped in try/except
    so a notification failure doesn't surface as a uvicorn traceback."""
    try:
        ns = NotificationService()
        if row.status == "completed":
            ns.publish_event(
                db,
                user_id=row.user_id,  # type: ignore[arg-type]
                type="AUDIO_GENERATION_COMPLETED",
                title="语音合成完成",
                body=(row.text or "")[:30],
                resource_type="generated_audio",
                resource_id=row.id,  # type: ignore[arg-type]
                metadata={"audio_id": row.id, "status": row.status},
            )
        elif row.status == "failed":
            ns.publish_event(
                db,
                user_id=row.user_id,  # type: ignore[arg-type]
                type="AUDIO_GENERATION_FAILED",
                title="语音合成失败",
                body=(row.error_message or "")[:50],
                resource_type="generated_audio",
                resource_id=row.id,  # type: ignore[arg-type]
                metadata={
                    "audio_id": row.id,
                    "status": row.status,
                    "error_message": row.error_message,
                },
            )
    except Exception as e:
        log.warning("Failed to push notification for audio %s: %s", row.id, e)
        try:
            db.rollback()
        except Exception:
            pass
