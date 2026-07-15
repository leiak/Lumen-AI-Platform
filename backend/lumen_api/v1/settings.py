from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from lumen_core.database import get_db
from lumen_api.v1.auth import get_current_user
from lumen_models.user import User
from lumen_models.model_config import ModelConfig
from lumen_schemas.settings import (
    SystemSettingsResponse, SystemSettingsUpdate,
    SecuritySettingsResponse, SecuritySettingsUpdate
)
from lumen_schemas.common import SingleResponse
from lumen_services.settings_service import SettingsService

router = APIRouter(prefix="/settings", tags=["settings"])


def _first_default_model_id(db: Session, tenant_id: int, *, capability: str) -> int | None:
    """Pick the first active model for the tenant that has the given
    capability (``is_chat`` or ``is_embedding``) and is marked
    ``is_default=True``. Tenant scope mirrors
    ``api/v1/models.py:43-46`` — tenant-owned rows plus global
    ``tenant_id IS NULL`` rows are visible.

    Used as the M31 fallback when the ``system_settings`` table has no
    row yet — replaces the prior hard-coded string defaults
    (``"qwen2.5:7b"`` / ``"nomic-embed-text"``) that no longer match
    the new integer-FK column type.
    """
    if capability == "is_chat":
        flag = ModelConfig.is_chat
    elif capability == "is_embedding":
        flag = ModelConfig.is_embedding
    else:
        raise ValueError(f"Unknown capability: {capability!r}")
    row = (
        db.query(ModelConfig.id)
        .filter(
            (ModelConfig.tenant_id == tenant_id) | (ModelConfig.tenant_id.is_(None)),
            ModelConfig.is_active.is_(True),
            flag.is_(True),
        )
        .order_by(ModelConfig.is_default.desc(), ModelConfig.id.asc())
        .first()
    )
    return row[0] if row else None


@router.get("/", response_model=SingleResponse[SystemSettingsResponse])
async def get_settings(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    service = SettingsService()
    settings = service.get_system_settings(db, current_user.tenant_id)
    if not settings:
        tenant_id = current_user.tenant_id
        default_chat_id = _first_default_model_id(db, tenant_id, capability="is_chat")
        default_embed_id = _first_default_model_id(db, tenant_id, capability="is_embedding")
        return SingleResponse(
            data=SystemSettingsResponse(
                system_name="Lumen AI Platform",
                system_description="基于 LangChain + React 的智能中台平台",
                default_model=default_chat_id,
                embedding_model=default_embed_id,
                chat_history_days=30
            )
        )
    return SingleResponse(data=SystemSettingsResponse.model_validate(settings))

@router.put("/", response_model=SingleResponse[SystemSettingsResponse])
async def update_settings(
    data: SystemSettingsUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    service = SettingsService()
    settings = service.update_system_settings(db, current_user.tenant_id, data)
    return SingleResponse(data=SystemSettingsResponse.model_validate(settings))

@router.get("/security", response_model=SingleResponse[SecuritySettingsResponse])
async def get_security_settings(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    service = SettingsService()
    settings = service.get_security_settings(db, current_user.tenant_id)
    if not settings:
        return SingleResponse(data=SecuritySettingsResponse())
    return SingleResponse(data=SecuritySettingsResponse.model_validate(settings))

@router.put("/security", response_model=SingleResponse[SecuritySettingsResponse])
async def update_security_settings(
    data: SecuritySettingsUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    service = SettingsService()
    settings = service.update_security_settings(db, current_user.tenant_id, data)
    return SingleResponse(data=SecuritySettingsResponse.model_validate(settings))