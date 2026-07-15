from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
import httpx
from pydantic import BaseModel
from lumen_core.database import get_db
from lumen_core.model_providers import MODEL_PROVIDERS
from lumen_core.config import settings
from lumen_api.v1.auth import get_current_user, require_admin
from lumen_models.user import User
from lumen_models.model_config import ModelConfig
from lumen_schemas.model_config import (
    ModelConfigCreate, ModelConfigUpdate, ModelConfigResponse
)
from lumen_schemas.common import SingleResponse, PaginatedResponse

router = APIRouter(prefix="/models", tags=["models"])


@router.get("/", response_model=PaginatedResponse[ModelConfigResponse])
async def list_models(
    page: int = 1,
    page_size: int = 10,
    model_type: Optional[str] = None,
    is_chat: Optional[bool] = None,
    is_embedding: Optional[bool] = None,
    is_image_generation: Optional[bool] = None,
    is_tts: Optional[bool] = None,
    is_subtitle_generation: Optional[bool] = None,
    is_video: Optional[bool] = None,
    is_active: Optional[bool] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """List all model configurations for the tenant.

    Filters:
    - ``model_type``: exact match on provider.
    - ``is_chat``: True returns only chat-capable rows; False returns
      the rest. Omit to get all. The M31 ``ChatModelSelect`` component
      filters server-side using ``is_chat=True&is_active=True``.
    - ``is_embedding``: True returns only embedding-capable rows;
      False returns the rest. Omit to get all.
    - ``is_image_generation``: True returns only image-generation-
      capable rows; False returns the rest. Omit to get all.
    - ``is_tts`` (M35): True returns only TTS-capable rows; False
      returns the rest. Omit to get all.
    - ``is_subtitle_generation`` (M35): True returns only subtitle-
      capable rows; False returns the rest. Omit to get all.
    - ``is_active``: True / False / None (None = all). The
      ``EmbeddingModelSelect`` component filters server-side using
      ``is_embedding=True&is_active=True``.
    """
    # 模型配置是全局的（tenant_id=NULL），所有认证用户均可查看
    query = db.query(ModelConfig)

    if model_type:
        query = query.filter(ModelConfig.model_type == model_type)
    if is_chat is not None:
        query = query.filter(ModelConfig.is_chat == is_chat)
    if is_embedding is not None:
        query = query.filter(ModelConfig.is_embedding == is_embedding)
    if is_image_generation is not None:
        query = query.filter(ModelConfig.is_image_generation == is_image_generation)
    if is_tts is not None:
        query = query.filter(ModelConfig.is_tts == is_tts)
    if is_subtitle_generation is not None:
        query = query.filter(ModelConfig.is_subtitle_generation == is_subtitle_generation)
    if is_video is not None:
        query = query.filter(ModelConfig.is_video == is_video)
    if is_active is not None:
        query = query.filter(ModelConfig.is_active == is_active)

    total = query.count()
    start = (page - 1) * page_size
    end = start + page_size

    models = (
        query.order_by(
            ModelConfig.is_default.desc(), ModelConfig.id.desc()
        )
        .slice(start, end)
        .all()
    )

    return PaginatedResponse(
        data=[ModelConfigResponse.model_validate(m) for m in models],
        total=total,
        page=page,
        page_size=page_size
    )


@router.get("/{model_id}", response_model=SingleResponse[ModelConfigResponse])
async def get_model(
    model_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get model config by ID"""
    model = db.query(ModelConfig).filter(ModelConfig.id == model_id).first()

    if not model:
        raise HTTPException(status_code=404, detail="Model not found")

    return SingleResponse(data=ModelConfigResponse.model_validate(model))


@router.post("/", response_model=SingleResponse[ModelConfigResponse])
async def create_model(
    data: ModelConfigCreate,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Create new model configuration (admin only)."""
    # If this is set as default, unset other defaults for all tenants
    if data.is_default:
        db.query(ModelConfig).update({"is_default": False})

    # All model configs are global (tenant_id = NULL)
    model = ModelConfig(
        **data.model_dump(),
        tenant_id=None
    )
    db.add(model)
    db.commit()
    db.refresh(model)

    return SingleResponse(data=ModelConfigResponse.model_validate(model))


@router.put("/{model_id}", response_model=SingleResponse[ModelConfigResponse])
async def update_model(
    model_id: int,
    data: ModelConfigUpdate,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Update model configuration (admin only)."""
    model = db.query(ModelConfig).filter(ModelConfig.id == model_id).first()

    if not model:
        raise HTTPException(status_code=404, detail="Model not found")

    # If setting as default, unset other defaults for all tenants
    if data.is_default:
        db.query(ModelConfig).filter(ModelConfig.id != model_id).update({"is_default": False})

    update_data = data.model_dump(exclude_unset=True)
    # Invalidate the embedding cache if any field that affects the
    # constructed Embeddings instance changed. Other fields (name,
    # description, is_default, max_tokens for chat use) don't touch
    # the embedder.
    fields_that_affect_embedding = {
        "model_name", "base_url", "api_key", "is_active", "is_embedding",
    }
    needs_invalidate = any(f in update_data for f in fields_that_affect_embedding)
    for key, value in update_data.items():
        setattr(model, key, value)

    db.commit()
    db.refresh(model)

    if needs_invalidate:
        from lumen_services.embedding_factory import invalidate_cache
        invalidate_cache(model.id)

    return SingleResponse(data=ModelConfigResponse.model_validate(model))


@router.delete("/{model_id}")
async def delete_model(
    model_id: int,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Soft-delete: set is_active=False (admin only). Refused if referenced by a KB or document."""
    from lumen_models.knowledge import KnowledgeBase, Document

    model = db.query(ModelConfig).filter(ModelConfig.id == model_id).first()
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")

    # Block if any KB or document still references this config. The
    # ON DELETE RESTRICT FK would also catch a future hard-delete,
    # but we need an app-level guard because today this endpoint
    # does a soft delete (is_active=False), which the FK doesn't see.
    kb_ref = db.query(KnowledgeBase.id).filter(
        KnowledgeBase.embedding_model_config_id == model_id
    ).first()
    if kb_ref:
        raise HTTPException(
            status_code=422,
            detail="该模型被知识库引用,无法禁用。请先迁移或删除相关知识库。",
        )
    doc_ref = db.query(Document.id).filter(
        Document.embedding_model_config_id == model_id
    ).first()
    if doc_ref:
        raise HTTPException(
            status_code=422,
            detail="该模型被文档引用,无法禁用。",
        )

    model.is_active = False
    db.commit()

    from lumen_services.embedding_factory import invalidate_cache
    invalidate_cache(model_id)

    return SingleResponse(message="Model deleted successfully")


@router.get("/providers/list")
async def list_model_providers():
    """Get available model providers.

    Sourced from `app.core.model_providers.MODEL_PROVIDERS` so the
    loader (`app.services.model_loader.create_chat_model`) and the
    admin UI stay in lockstep with a single source of truth.
    """
    return SingleResponse(data=list(MODEL_PROVIDERS))


class _ImportFromOllamaBody(BaseModel):
    base_url: Optional[str] = None


@router.post("/import-from-ollama", response_model=SingleResponse[dict])
async def import_from_ollama(
    body: _ImportFromOllamaBody,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Read locally-available Ollama models and report per-model capabilities.

    The endpoint never writes to the DB; it only fetches and enriches.
    The frontend uses the result to pre-fill the bulk-create modal.
    """
    base_url = (body.base_url or settings.OLLAMA_API_BASE).rstrip("/")
    out: dict = {"base_url": base_url, "reachable": False, "models": []}

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            tags_resp = await client.get(f"{base_url}/api/tags")
            tags_resp.raise_for_status()
            tags_data = tags_resp.json()
    except Exception as e:
        out["error_message"] = f"{type(e).__name__}: {e}"
        return SingleResponse(data=out)

    out["reachable"] = True
    models_out = []
    for m in tags_data.get("models", []):
        name = m.get("name", "")
        # Try to fetch capabilities — failure is non-fatal.
        capabilities: list = []
        family: Optional[str] = None
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                show_resp = await client.post(
                    f"{base_url}/api/show", json={"name": name}
                )
                show_resp.raise_for_status()
                show_data = show_resp.json()
                capabilities = list(show_data.get("capabilities", []))
                family = (show_data.get("details") or {}).get("family")
        except Exception:
            pass

        # Check if this model is already in model_configs.
        existing = (
            db.query(ModelConfig)
            .filter(
                ModelConfig.tenant_id.is_(None),
                ModelConfig.model_type == "ollama",
                ModelConfig.model_name == name,
            )
            .first()
        )
        models_out.append({
            "name": name,
            "size": m.get("size"),
            "modified_at": m.get("modified_at"),
            "family": family,
            "capabilities": capabilities,
            "is_embedding_capable": "embedding" in capabilities,
            "is_chat_capable": "completion" in capabilities or "chat" in capabilities,
            "exists_in_db": existing is not None,
            "existing_config_id": existing.id if existing else None,
        })
    out["models"] = models_out
    return SingleResponse(data=out)


@router.post("/bulk-create", response_model=SingleResponse[dict])
async def bulk_create_models(
    rows: List[ModelConfigCreate],
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Create many ModelConfig rows in one request (admin only). Used by the Ollama
    import modal after the admin has reviewed and toggled is_chat/
    is_embedding per row.

    Per-row outcomes are reported in ``results``:
    - ``created``: new row written.
    - ``skipped``: a row already exists for
      ``(NULL, model_type, model_name)`` — the existing id is
      returned in ``existing_config_id``.
    - ``error``: an unexpected failure (e.g. DB constraint). The
      ``error`` field has a human-readable message.

    The endpoint never raises on per-row failures; it always returns
    200 with the per-row breakdown so the UI can show a partial-success
    summary.
    """
    results = []
    for row in rows:
        try:
            existing = (
                db.query(ModelConfig)
                .filter(
                    ModelConfig.tenant_id.is_(None),
                    ModelConfig.model_type == row.model_type,
                    ModelConfig.model_name == row.model_name,
                )
                .first()
            )
            if existing is not None:
                results.append({
                    "requested_model_name": row.model_name,
                    "status": "skipped",
                    "reason": "duplicate",
                    "existing_config_id": existing.id,
                })
                continue

            new_cfg = ModelConfig(
                **row.model_dump(),
                tenant_id=None,
            )
            db.add(new_cfg)
            db.flush()
            # Try to build a full response payload; fall back to a
            # minimal ``config_id``-only payload if the row isn't
            # fully populated yet (e.g. a unit test using a mock DB
            # where ``created_at`` / ``updated_at`` are still None).
            try:
                config_payload = ModelConfigResponse.model_validate(
                    new_cfg
                ).model_dump(mode="json")
            except Exception:
                config_payload = {"id": new_cfg.id}
            results.append({
                "requested_model_name": row.model_name,
                "status": "created",
                "config": config_payload,
            })
        except Exception as e:
            results.append({
                "requested_model_name": row.model_name,
                "status": "error",
                "error": f"{type(e).__name__}: {e}",
            })

    db.commit()
    return SingleResponse(data={"results": results})
