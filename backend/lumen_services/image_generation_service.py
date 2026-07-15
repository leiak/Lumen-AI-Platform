"""Image generation service. Spec: §7"""
import io
import logging
import time
import uuid
from typing import List, Optional, Tuple

from fastapi import BackgroundTasks
from PIL import Image
from sqlalchemy.orm import Session

from lumen_core.llm_call_context import LLMCallContext, set_call_context, reset_call_context
from lumen_core.storage import save_bytes, delete_relative
from lumen_models.image_generation import GeneratedImage
from lumen_models.model_config import ModelConfig
from lumen_services.image_providers.factory import get_image_provider
from lumen_services.notification_service import NotificationService

log = logging.getLogger(__name__)

THUMBNAIL_SIZE = (256, 256)
THUMBNAIL_QUALITY = 80


def _make_thumbnail(image_bytes: bytes) -> Optional[bytes]:
    """Generate a 256x256 JPEG thumbnail. Returns None on failure (logged)."""
    try:
        from PIL import ImageOps
        img = Image.open(io.BytesIO(image_bytes))
        img.verify()  # quick validation
        img = Image.open(io.BytesIO(image_bytes))  # re-open after verify
        # limit huge images
        img.thumbnail(THUMBNAIL_SIZE, Image.Resampling.LANCZOS)
        # pad to exact square (white background)
        img = ImageOps.pad(img, THUMBNAIL_SIZE, color=(255, 255, 255), centering=(0.5, 0.5))  # type: ignore[assignment]
        if img.mode != "RGB":
            img = img.convert("RGB")  # type: ignore[assignment]
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=THUMBNAIL_QUALITY, optimize=True)
        return buf.getvalue()
    except Exception as e:
        log.warning("Failed to make thumbnail: %s", e)
        return None


class ImageGenerationService:
    """Business logic for /api/v1/image-generation.

    Spec: §7
    """

    def create(
        self,
        db: Session,
        *,
        tenant_id: int,
        user_id: int,
        model_config_id: int,
        prompt: str,
        size: str = "1024x1024",
        n: int = 1,
        negative_prompt: Optional[str] = None,
        quality: Optional[str] = None,
        style: Optional[str] = None,
        extra_params: Optional[dict] = None,
        background_tasks: BackgroundTasks,
        playbook_id: Optional[int] = None,
    ) -> Tuple[List[GeneratedImage], Optional[str]]:
        """Create N rows (status=pending), schedule background generation.

        Returns (rows, batch_id or None).
        - rows == [] and second element is None → ModelConfig not found
        - rows == [] and second element is "not_image_capable" → mc.is_image_generation is False
        """
        mc = db.query(ModelConfig).filter(
            ModelConfig.id == model_config_id,
            ModelConfig.tenant_id == tenant_id,
        ).first()
        if not mc:
            return [], None  # signal not-found
        if not mc.is_image_generation:
            return [], "not_image_capable"

        batch_id = str(uuid.uuid4()) if n > 1 else None
        # M35: when a playbook_id is given, enrich the prompt with the
        # playbook's keywords + palette + avoid. The enriched prompt is
        # the one we send to the provider; the ORIGINAL prompt stays
        # on the row for traceability (so re-runs without playbook
        # produce the original).
        effective_prompt = prompt
        effective_negative = negative_prompt
        playbook_applied = None
        if playbook_id is not None:
            from lumen_services.playbook_service import (
                get_for_tenant as get_playbook_for_tenant,
                inject_into_prompt,
                validate_scope,
            )
            pb = get_playbook_for_tenant(
                db, tenant_id=tenant_id, playbook_id=playbook_id,
            )
            if pb is None or not validate_scope(pb, "image"):
                # Unknown playbook or wrong scope — surface as a 404
                # so the frontend can fall back gracefully.
                return [], "playbook_not_found"
            enriched = inject_into_prompt(pb, prompt, "image_prompt")
            if enriched != prompt:
                effective_prompt = enriched
                playbook_applied = playbook_id
            # If the playbook has an "avoid" section, append it to the
            # negative prompt (most providers support it).
            avoid = (pb.style_tokens or {}).get("avoid") or []
            if avoid and not negative_prompt:
                effective_negative = ", ".join(avoid)
            elif avoid and negative_prompt:
                effective_negative = negative_prompt + ", " + ", ".join(avoid)
        params_snapshot = {
            "prompt": prompt, "size": size, "n": n,
            "negative_prompt": negative_prompt, "quality": quality,
            "style": style, "extra_params": extra_params,
            "playbook_id": playbook_id,
        }
        rows: List[GeneratedImage] = []
        for i in range(n):
            row = GeneratedImage(
                tenant_id=tenant_id,
                user_id=user_id,
                model_config_id=model_config_id,
                batch_id=batch_id,
                prompt=effective_prompt,  # enriched prompt for provider
                negative_prompt=effective_negative,
                size=size,
                n=n,
                quality=quality,
                style=style,
                params=params_snapshot,
                file_path="",  # filled by _run_generation
                file_size=0,
                mime_type="image/png",
                status="pending",
            )
            db.add(row)
            rows.append(row)
        db.commit()
        for r in rows:
            db.refresh(r)
        # Schedule background generation for the first row (others share same params)
        if rows:
            background_tasks.add_task(_run_generation, rows[0].id)  # type: ignore[arg-type]
        return rows, batch_id

    def list_for_tenant(
        self, db: Session, *, tenant_id: int,
        page: int = 1, page_size: int = 12,
        model_config_id: Optional[int] = None,
        status: Optional[str] = None,
        prompt: Optional[str] = None,
    ) -> Tuple[List[GeneratedImage], int]:
        q = db.query(GeneratedImage).filter(GeneratedImage.tenant_id == tenant_id)
        if model_config_id is not None:
            q = q.filter(GeneratedImage.model_config_id == model_config_id)
        if status:
            q = q.filter(GeneratedImage.status == status)
        if prompt:
            q = q.filter(GeneratedImage.prompt.like(f"%{prompt}%"))
        total = q.count()
        q = q.order_by(GeneratedImage.created_at.desc())
        offset = (page - 1) * page_size
        return q.offset(offset).limit(page_size).all(), total

    def get(self, db: Session, *, tenant_id: int, image_id: int) -> Optional[GeneratedImage]:
        return db.query(GeneratedImage).filter(
            GeneratedImage.id == image_id,
            GeneratedImage.tenant_id == tenant_id,
        ).first()

    def delete(self, db: Session, *, tenant_id: int, image_id: int) -> bool:
        row = self.get(db, tenant_id=tenant_id, image_id=image_id)
        if not row:
            return False
        # M26: llm_call_logs.image_id FKs into generated_images with
        # RESTRICT semantics. Wipe the log rows for this image first so
        # the GeneratedImage DELETE below doesn't get blocked.
        from lumen_models.llm_call_log import LLMCallLog
        db.query(LLMCallLog).filter(
            LLMCallLog.image_id == image_id
        ).delete(synchronize_session=False)
        db.commit()
        delete_relative(row.file_path)  # type: ignore[arg-type]
        db.delete(row)
        db.commit()
        return True

    def regenerate(
        self, db: Session, *, tenant_id: int, user_id: int,
        image_id: int, background_tasks: BackgroundTasks,
    ) -> Optional[List[GeneratedImage]]:
        old = self.get(db, tenant_id=tenant_id, image_id=image_id)
        if not old:
            return None
        rows, _ = self.create(
            db, tenant_id=tenant_id, user_id=user_id,
            model_config_id=old.model_config_id,  # type: ignore[arg-type]
            prompt=old.prompt,  # type: ignore[arg-type]
            size=old.size,  # type: ignore[arg-type]
            n=old.n,  # type: ignore[arg-type]
            negative_prompt=old.negative_prompt,  # type: ignore[arg-type]
            quality=old.quality,  # type: ignore[arg-type]
            style=old.style,  # type: ignore[arg-type]
            extra_params=(old.params or {}).get("extra_params"),  # type: ignore[arg-type, call-overload]
            background_tasks=background_tasks,
        )
        return rows


async def _call_provider(provider, row: GeneratedImage) -> List[bytes]:
    """Call provider.generate() with row's params."""
    return await provider.generate(
        prompt=row.prompt,  # type: ignore[arg-type]
        size=row.size,  # type: ignore[arg-type]
        n=1,
        quality=row.quality,  # type: ignore[arg-type]
        style=row.style,  # type: ignore[arg-type]
        negative_prompt=row.negative_prompt,  # type: ignore[arg-type]
        extra_params=(row.params or {}).get("extra_params"),  # type: ignore[arg-type, call-overload]
    )


def _run_generation(image_id: int) -> None:
    """Background task: load row, call provider, save to disk + DB, push notification.

    Runs as a sync function dispatched by FastAPI's BackgroundTasks. Inside
    we open a fresh DB session (the request's session is closed by now),
    and run the async provider.generate() via asyncio.run so the sync
    entrypoint can wait on it.

    M26: writes one llm_call_logs row (call_type="image_generation") with
    the model's actual response — the byte payload size, dimensions, and
    duration. Token usage is N/A (image models don't report tokens).
    """
    import asyncio
    from datetime import datetime
    from lumen_core.database import SessionLocal
    from lumen_services.llm_call_logging import get_llm_call_logging_service

    db = SessionLocal()
    log_call_id: Optional[str] = None
    log_trace_id: Optional[str] = None
    log_started_at = datetime.utcnow()
    log_tenant_id: Optional[int] = None
    log_user_id: Optional[int] = None
    log_image_id: Optional[int] = None
    log_model_name: Optional[str] = None
    log_model_type: Optional[str] = None
    log_model_config_id: Optional[int] = None
    log_prompt: Optional[str] = None
    log_size: Optional[str] = None
    log_quality: Optional[str] = None
    log_style: Optional[str] = None
    log_n: Optional[int] = None
    log_extra: dict = {}

    try:
        row = db.query(GeneratedImage).filter(GeneratedImage.id == image_id).first()
        if not row:
            log.error("_run_generation: row %s not found", image_id)
            return
        log_tenant_id = row.tenant_id
        log_user_id = row.user_id
        log_image_id = row.id
        log_prompt = row.prompt
        log_size = row.size
        log_quality = row.quality
        log_style = row.style
        log_n = row.n
        log_extra = {
            "negative_prompt": row.negative_prompt,
            "batch_id": row.batch_id,
        }
        mc = db.query(ModelConfig).filter(ModelConfig.id == row.model_config_id).first()
        if not mc:
            log_model_name = "unknown"
            row.status = "failed"  # type: ignore[assignment]
            row.error_message = f"model_config {row.model_config_id} not found"  # type: ignore[assignment]
            db.commit()
            _push_notification(db, row)
            return
        log_model_name = mc.model_name
        log_model_type = mc.model_type
        log_model_config_id = mc.id

        row.status = "generating"  # type: ignore[assignment]
        db.commit()

        start = time.monotonic()
        duration_ms: int = 0
        try:
            provider = get_image_provider(mc)
            results = asyncio.run(_call_provider(provider, row))
            if not results:
                raise RuntimeError("provider returned empty result")
            data = results[0]
            # Detect actual format from bytes BEFORE save_bytes so the file
            # extension matches content (MiniMax returns JPEG, OpenAI/Stability
            # return PNG — row.mime_type was hardcoded "image/png" at insert
            # time, which would persist the wrong extension for JPEG payloads).
            img = Image.open(io.BytesIO(data))
            # touch width/height to force lazy load
            _ = img.width, img.height
            fmt = (img.format or "PNG").lower()
            row.mime_type = f"image/{fmt}"  # type: ignore[assignment]
            row.width = img.width  # type: ignore[assignment]
            row.height = img.height  # type: ignore[assignment]
            abs_path, size, rel_path = save_bytes(row.tenant_id, data, row.mime_type)  # type: ignore[arg-type]
            thumb = _make_thumbnail(data)
            row.file_path = rel_path  # type: ignore[assignment]
            row.file_size = size  # type: ignore[assignment]
            row.thumbnail = thumb  # type: ignore[assignment]
            row.status = "completed"  # type: ignore[assignment]
            duration_ms = int((time.monotonic() - start) * 1000)
            row.duration_ms = duration_ms  # type: ignore[assignment]
            row.error_message = None  # type: ignore[assignment]
            log.info(
                "Image %s generated in %dms via %s",
                image_id, duration_ms, type(provider).__name__,
            )
        except Exception as e:
            row.status = "failed"  # type: ignore[assignment]
            row.error_message = str(e)[:1000]  # type: ignore[assignment]
            duration_ms = int((time.monotonic() - start) * 1000)
            log.exception("Image %s generation failed", image_id)
        db.commit()
        _push_notification(db, row)

        # M26: write the llm_call_logs row AFTER the DB commit so the
        # row's status / dimensions are final. The image_id FK is satisfied
        # because we already wrote the GeneratedImage row earlier in this
        # function (status=pending → completed/failed).
        #
        # We open a FRESH session here (SessionLocal()) so the image
        # generation's commit isn't tangled with the log call. If the log
        # call FK-fails (e.g. orphan image_id), the rollback is scoped
        # to the log session only — the image row stays committed and
        # DELETE /api/v1/image-generation/{id} still finds it.
        log_call_id = str(uuid.uuid4())
        log_trace_id = str(uuid.uuid4())
        log_db = SessionLocal()
        try:
            get_llm_call_logging_service().log_call(
                log_db,
                ctx=LLMCallContext(
                    call_id=log_call_id,
                    trace_id=log_trace_id,
                    parent_call_id=None,
                    call_type="image_generation",
                    call_index=0,
                    tenant_id=log_tenant_id,
                    user_id=log_user_id,
                    client_app="dashboard",
                    image_id=log_image_id,
                    extra=log_extra,
                ),
                model_type=log_model_type,
                model_name=log_model_name or "unknown",
                temperature=None,
                max_tokens=None,
                system_messages=None,
                user_message=log_prompt,
                messages=[{"role": "user", "content": log_prompt or ""}],
                tools=None,
                extra_params={
                    "size": log_size,
                    "quality": log_quality,
                    "style": log_style,
                    "n": log_n,
                },
                response_content=f"image {log_image_id} {row.status}",
                finish_reason="stop",
                tool_calls=None,
                token_usage=None,  # image models don't report tokens
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
            # Best-effort: image generation already succeeded; don't fail
            # the background task if the log call is broken. Log and move on.
            log.warning("llm_call_logs write failed (image_id=%s): %s", log_image_id, log_err)
        finally:
            log_db.close()
    finally:
        db.close()


def _push_notification(db: Session, row: GeneratedImage) -> None:
    """Persist a notification + WS broadcast. Wrapped in try/except so a
    notification failure does not bubble out of the background task and
    surface as a uvicorn traceback."""
    try:
        ns = NotificationService()
        if row.status == "completed":
            ns.publish_event(
                db,
                user_id=row.user_id,  # type: ignore[arg-type]
                type="IMAGE_GENERATION_COMPLETED",
                title="图片生成完成",
                body=row.prompt[:30],  # type: ignore[arg-type]
                resource_type="generated_image",
                resource_id=row.id,  # type: ignore[arg-type]
                metadata={"image_id": row.id, "status": row.status},
            )
        else:
            ns.publish_event(
                db,
                user_id=row.user_id,  # type: ignore[arg-type]
                type="IMAGE_GENERATION_FAILED",
                title="图片生成失败",
                body=(row.error_message or "")[:50],  # type: ignore[arg-type]
                resource_type="generated_image",
                resource_id=row.id,  # type: ignore[arg-type]
                metadata={
                    "image_id": row.id,
                    "status": row.status,
                    "error_message": row.error_message,
                },
            )
    except Exception as e:
        log.warning("Failed to push notification for image %s: %s", row.id, e)
        try:
            db.rollback()
        except Exception:
            pass
