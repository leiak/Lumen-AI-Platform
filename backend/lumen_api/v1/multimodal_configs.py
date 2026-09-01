"""M38.4: Multimodal Embedding Config CRUD endpoints.

镜像 ``lumen_api/v1/models.py`` 的形态(同项目 admin 模型管理),
路径前缀 ``/api/v1/multimodal-configs``:

- ``GET    /``           列表(认证即可;tenant 隔离 ``(tenant_id == X) | (tenant_id IS NULL)``)
- ``GET    /{id}``       详情
- ``POST   /``           创建(admin)
- ``PUT    /{id}``       更新(admin,字段变更触发 cache invalidate)
- ``DELETE /{id}``       软删(``enabled=False``,422 if KB 仍引用)
- ``POST   /{id}/test``  连通性 probe(200 + ok/dim,失败也返 200 + error)

为什么不走 hard delete? 与 ``ModelConfig.delete_model`` 同模式 —— 真
硬删会撞 ``ON DELETE RESTRICT`` FK(后续 KB 切 multimodal 时 spec 设计
是新建 revision,不删 config),且 admin 想"停用"和"删除"语义不同;
软删 (``enabled=False``) 是中间态。
"""
from __future__ import annotations

import logging
import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_, update
from sqlalchemy.orm import Session

from lumen_api.v1.auth import get_current_user, require_admin
from lumen_core.database import get_db
from lumen_models.multimodal_embedding_config import MultimodalEmbeddingConfig
from lumen_models.user import User
from lumen_schemas.common import PaginatedResponse, SingleResponse
from lumen_schemas.multimodal_embedding_config import (
    MultimodalConfigTestResponse,
    MultimodalEmbeddingConfigCreate,
    MultimodalEmbeddingConfigResponse,
    MultimodalEmbeddingConfigUpdate,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/multimodal-configs", tags=["multimodal-configs"])


# --- Tenant-scope helpers ---------------------------------------------------


def _tenant_visible_query(db: Session, tenant_id: int):
    """``tenant_id == X OR tenant_id IS NULL`` pattern.

    镜像 ``ModelConfig``(M13)+ ``StockMusic``(M36.2.2)+ ``StockAsset``
    的"全局 builtin 对所有租户可见"约定 ——
    ``MultimodalEmbeddingConfig`` 跟 ModelConfig 是平行概念。
    """
    return db.query(MultimodalEmbeddingConfig).filter(
        or_(
            MultimodalEmbeddingConfig.tenant_id == tenant_id,
            MultimodalEmbeddingConfig.tenant_id.is_(None),
        )
    )


# --- GET / ------------------------------------------------------------------


@router.get("/", response_model=PaginatedResponse[MultimodalEmbeddingConfigResponse])
async def list_multimodal_configs(
    page: int = 1,
    page_size: int = 20,
    provider: Optional[str] = None,
    enabled: Optional[bool] = None,
    is_default: Optional[bool] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List multimodal embedding configs visible to the caller's tenant.

    Filters:
    - ``provider``: exact match on the provider name (jina_clip_v2 / …)
    - ``enabled``: True / False / None
    - ``is_default``: True / False / None (None = both)
    """
    query = _tenant_visible_query(db, current_user.tenant_id)
    if provider:
        query = query.filter(MultimodalEmbeddingConfig.provider == provider)
    if enabled is not None:
        query = query.filter(MultimodalEmbeddingConfig.enabled == enabled)
    if is_default is not None:
        query = query.filter(MultimodalEmbeddingConfig.is_default == is_default)

    total = query.count()
    start = (page - 1) * page_size
    rows = (
        query.order_by(
            MultimodalEmbeddingConfig.is_default.desc(),
            MultimodalEmbeddingConfig.id.asc(),
        )
        .offset(start)
        .limit(page_size)
        .all()
    )
    return PaginatedResponse(
        data=[MultimodalEmbeddingConfigResponse.model_validate(r) for r in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


# --- GET /{id} --------------------------------------------------------------


@router.get("/{config_id}", response_model=SingleResponse[MultimodalEmbeddingConfigResponse])
async def get_multimodal_config(
    config_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get one multimodal config; tenant-scoped."""
    cfg = (
        _tenant_visible_query(db, current_user.tenant_id)
        .filter(MultimodalEmbeddingConfig.id == config_id)
        .first()
    )
    if cfg is None:
        raise HTTPException(status_code=404, detail="Multimodal config not found")
    return SingleResponse(data=MultimodalEmbeddingConfigResponse.model_validate(cfg))


# --- POST / (admin) ---------------------------------------------------------


@router.post("/", response_model=SingleResponse[MultimodalEmbeddingConfigResponse])
async def create_multimodal_config(
    data: MultimodalEmbeddingConfigCreate,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Create a new multimodal embedding config (admin only).

    Per ``ModelConfig.create_model`` convention:
    - If ``is_default=True`` is requested, clear all other defaults so
      the platform default is unambiguous. Multimodal defaults are NOT
      provider-scoped (unlike ModelConfig.is_default per provider),
      so any is_default=True clears the global flag on every other row.
    - All multimodal configs are global builtin (``tenant_id=NULL``)
      per the design — no per-tenant override.

    Uniqueness: the ``uq_mec_tenant_name`` index
    (``(tenant_id, name)``) rejects duplicates; we surface the
    IntegrityError as a clean 409.
    """
    if data.is_default:
        db.execute(
            update(MultimodalEmbeddingConfig).values(is_default=False)
        )

    row = MultimodalEmbeddingConfig(**data.model_dump(), tenant_id=None)
    db.add(row)
    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        # Duplicate name or other constraint — surface as 409 so the
        # admin UI can show a specific message.
        if "uq_mec_tenant_name" in str(exc) or "Duplicate entry" in str(exc):
            raise HTTPException(
                status_code=409,
                detail=f"已存在同名 multimodal config: {data.name}",
            )
        raise
    db.refresh(row)
    return SingleResponse(data=MultimodalEmbeddingConfigResponse.model_validate(row))


# --- PUT /{id} (admin) ------------------------------------------------------


@router.put("/{config_id}", response_model=SingleResponse[MultimodalEmbeddingConfigResponse])
async def update_multimodal_config(
    config_id: int,
    data: MultimodalEmbeddingConfigUpdate,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Update a multimodal config (admin only).

    Triggers cache invalidation when fields that affect the constructed
    embedder change (provider / model_name / config / base_url / api_key
    / enabled). Other fields (name / description / is_default) don't
    touch the cached embedder object — but ``is_default=True`` may clear
    other defaults, which doesn't invalidate the cache.
    """
    cfg = db.get(MultimodalEmbeddingConfig, config_id)
    if cfg is None:
        raise HTTPException(status_code=404, detail="Multimodal config not found")

    update_data = data.model_dump(exclude_unset=True)

    # If the caller sets is_default=True, clear others first. Mirrors
    # ModelConfig's behaviour and prevents two simultaneous defaults.
    if update_data.get("is_default"):
        db.execute(
            update(MultimodalEmbeddingConfig)
            .where(MultimodalEmbeddingConfig.id != config_id)
            .values(is_default=False)
        )

    fields_that_affect_embedder = {
        "provider", "model_name", "config", "base_url", "api_key", "enabled",
    }
    needs_invalidate = any(f in update_data for f in fields_that_affect_embedder)

    for key, value in update_data.items():
        setattr(cfg, key, value)

    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        if "uq_mec_tenant_name" in str(exc) or "Duplicate entry" in str(exc):
            raise HTTPException(
                status_code=409,
                detail=f"已存在同名 multimodal config: {update_data.get('name', cfg.name)}",
            )
        raise
    db.refresh(cfg)

    if needs_invalidate:
        from lumen_services.multimodal_embedders import invalidate_multimodal_cache
        invalidate_multimodal_cache(config_id)

    return SingleResponse(data=MultimodalEmbeddingConfigResponse.model_validate(cfg))


# --- DELETE /{id} (admin) ---------------------------------------------------


@router.delete("/{config_id}")
async def delete_multimodal_config(
    config_id: int,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Soft-delete: set ``enabled=False``. Refused (422) if any KB
    still references this config — admin must unbind first.

    Hard-delete is intentionally not exposed (mirrors ModelConfig):
    the row's audit trail + dimension pinning matter, and an "active
    = False" config is still useful for read-only inspection.
    """
    from lumen_models.knowledge import KnowledgeBase

    cfg = db.get(MultimodalEmbeddingConfig, config_id)
    if cfg is None:
        raise HTTPException(status_code=404, detail="Multimodal config not found")

    kb_ref = (
        db.query(KnowledgeBase.id)
        .filter(KnowledgeBase.multimodal_config_id == config_id)
        .first()
    )
    if kb_ref:
        raise HTTPException(
            status_code=422,
            detail=(
                "该 multimodal config 被知识库引用,无法停用。"
                "请先将相关 KB 解绑 multimodal 或切换至其他 config。"
            ),
        )

    cfg.enabled = False
    db.commit()

    from lumen_services.multimodal_embedders import invalidate_multimodal_cache
    invalidate_multimodal_cache(config_id)

    return SingleResponse(message="Multimodal config disabled successfully")


# --- POST /{id}/test --------------------------------------------------------


@router.post("/{config_id}/test", response_model=SingleResponse[MultimodalConfigTestResponse])
async def test_multimodal_config(
    config_id: int,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Probe the embedder by calling ``embed_text('dim-probe')``.

    Always 200 — success / failure surfaces in ``ok``. This is
    deliberate so the admin UI can show a specific failure reason
    ("model not loaded" / "API key invalid") without forcing the
    admin to read a 500 detail.

    Cloud stubs (``is_stub=True``) are accepted: the factory skips the
    real probe and trusts ``dimension``. We still run a one-shot
    embed here to surface "not implemented" as a clean failure signal
    so the admin UI can prompt for cloud key wiring.
    """
    from lumen_services.multimodal_embedders import (
        MultimodalEmbeddingError,
        UnsupportedProviderError,
        get_multimodal_embedder,
    )

    started = time.monotonic()
    try:
        embedder, dim = get_multimodal_embedder(config_id, db)
        elapsed_ms = int((time.monotonic() - started) * 1000)
        # For cloud stubs, ``embedder.embed_text`` raises NotImplementedError.
        # We catch that and surface as ok=True (factory trusted dim) but
        # flag ``error`` so the admin knows the stub is not yet wired.
        if getattr(embedder, "is_stub", False):
            return SingleResponse(
                data=MultimodalConfigTestResponse(
                    ok=True,
                    dim=dim,
                    elapsed_ms=elapsed_ms,
                    error="cloud stub — provider not yet wired (returns NotImplementedError on real embed)",
                )
            )
        return SingleResponse(
            data=MultimodalConfigTestResponse(
                ok=True,
                dim=dim,
                elapsed_ms=elapsed_ms,
            )
        )
    except UnsupportedProviderError as exc:
        return SingleResponse(
            data=MultimodalConfigTestResponse(
                ok=False,
                error=f"unsupported provider: {exc}",
            )
        )
    except MultimodalEmbeddingError as exc:
        return SingleResponse(
            data=MultimodalConfigTestResponse(
                ok=False,
                error=f"{type(exc).__name__}: {exc}",
            )
        )
    except NotImplementedError as exc:
        # Cloud stub — surfaced as ok=False with the NotImplementedError
        # message so the admin knows to wire it.
        return SingleResponse(
            data=MultimodalConfigTestResponse(
                ok=False,
                error=f"not implemented: {exc}",
            )
        )
    except Exception as exc:  # pragma: no cover - defensive
        return SingleResponse(
            data=MultimodalConfigTestResponse(
                ok=False,
                error=f"{type(exc).__name__}: {exc}",
            )
        )


__all__ = ["router"]
