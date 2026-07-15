"""Admin Skill Crud + test-run endpoint (M17)."""
import logging
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from pydantic import ValidationError
from lumen_core.database import get_db
from lumen_api.v1.auth import get_current_user
from lumen_models.user import User
from lumen_models.skill_marketplace import SkillMarketplace, InstalledSkill
from lumen_schemas.skill import (
    SkillUpsertRequest, SkillTestRunRequest, SkillTestRunResult,
)
from lumen_api.v1.skill_market import SkillMarketplaceResponse
from lumen_schemas.common import SingleResponse, PaginatedResponse
from lumen_services.skill_test_runner import SkillTestRunner
from lumen_services.rate_limit import build_default_limiter

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin/skills", tags=["admin-skills"])


# M30 P1-4: distributed sliding-window rate limiter backed by Redis
# (with in-memory fallback when Redis is unreachable — same algorithm,
# per-process dict, degraded to the M17 behavior). Cross-worker
# effective because the Redis ZSET is shared.
#
# Config: 10 calls per 5 minutes per user, same as the M17 in-memory
# defaults so test behavior is unchanged for clients.
_skill_test_run_limiter = build_default_limiter(limit=10, window_seconds=300)


def _check_rate_limit(user_id: int) -> None:
    result = _skill_test_run_limiter(str(user_id))
    if not result.allowed:
        detail = "Test run rate limit: 10 calls / 5min"
        if result.degraded:
            detail += " (in-memory fallback — Redis unavailable)"
        raise HTTPException(status_code=429, detail=detail)


def _require_admin(user: User) -> None:
    if not getattr(user, "is_superuser", False):
        raise HTTPException(status_code=403, detail="Admin only")


@router.get("/", response_model=PaginatedResponse[SkillMarketplaceResponse])
async def list_all_skills(
    type: Optional[str] = Query(None),
    page: int = 1,
    page_size: int = 50,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Admin: list ALL skills (not filtered by is_verified)."""
    _require_admin(current_user)
    q = db.query(SkillMarketplace)
    if type:
        q = q.filter(SkillMarketplace.type == type)
    total = q.count()
    rows = q.offset((page - 1) * page_size).limit(page_size).all()
    return PaginatedResponse(
        data=[_to_response(r) for r in rows],
        total=total, page=page, page_size=page_size,
    )


@router.post("/", response_model=SingleResponse[SkillMarketplaceResponse])
async def create_skill(
    data: SkillUpsertRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Admin: create new skill (any of 5 types)."""
    _require_admin(current_user)
    _validate_type_config(data.type, data.type_config)
    skill = SkillMarketplace(
        name=data.name, category=data.category, type=data.type,
        description=data.description, content=data.content,
        type_config=data.type_config, version=data.version,
        provider=data.provider, is_verified=1 if data.is_verified else 0,
    )
    db.add(skill); db.commit(); db.refresh(skill)
    return SingleResponse(data=_to_response(skill))


@router.put("/{skill_id}", response_model=SingleResponse[SkillMarketplaceResponse])
async def update_skill(
    skill_id: int,
    data: SkillUpsertRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Admin: update existing skill."""
    _require_admin(current_user)
    skill = db.query(SkillMarketplace).filter(SkillMarketplace.id == skill_id).first()
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    _validate_type_config(data.type, data.type_config)
    skill.name = data.name
    skill.category = data.category
    skill.type = data.type
    skill.description = data.description
    skill.content = data.content
    skill.type_config = data.type_config
    skill.version = data.version
    skill.provider = data.provider
    skill.is_verified = 1 if data.is_verified else 0
    db.commit(); db.refresh(skill)
    return SingleResponse(data=_to_response(skill))


@router.delete("/{skill_id}", response_model=SingleResponse)
async def delete_skill(
    skill_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Admin: delete skill. Reject if installed by ≥ 1 tenant."""
    _require_admin(current_user)
    skill = db.query(SkillMarketplace).filter(SkillMarketplace.id == skill_id).first()
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    n_installed = db.query(InstalledSkill).filter(
        InstalledSkill.marketplace_skill_id == skill_id
    ).count()
    if n_installed > 0:
        raise HTTPException(
            status_code=409,
            detail=f"Skill in use by {n_installed} tenant(s); unmark is_verified to hide instead",
        )
    db.delete(skill); db.commit()
    return SingleResponse(message=f"Skill {skill_id} deleted")


@router.post("/{skill_id}/test-run", response_model=SingleResponse[SkillTestRunResult])
async def test_run_skill(
    skill_id: int,
    data: SkillTestRunRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Admin: dry-run a skill (any of 5 types). Rate-limited."""
    _require_admin(current_user)
    _check_rate_limit(current_user.id)
    skill = db.query(SkillMarketplace).filter(SkillMarketplace.id == skill_id).first()
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    result = SkillTestRunner.test_run(
        db=db, tenant_id=current_user.tenant_id, skill=skill, input_args=data.input_args,
    )
    return SingleResponse(data=result)


def _to_response(skill: SkillMarketplace) -> SkillMarketplaceResponse:
    return SkillMarketplaceResponse(
        id=skill.id, name=skill.name, category=skill.category,
        description=skill.description, content=skill.content,
        type=skill.type, type_config=skill.type_config,
        version=skill.version, provider=skill.provider,
        downloads=skill.downloads, rating=skill.rating,
        is_verified=bool(skill.is_verified),
    )


def _validate_type_config(type: str, type_config: Optional[dict]) -> None:
    """Ensure type_config matches type (Pydantic discriminator)."""
    if type == "prompt":
        return  # content used; type_config optional
    if type_config is None:
        raise HTTPException(status_code=422, detail=f"type_config required for type={type}")
    from lumen_schemas.skill import (
        ScriptTypeConfig, HttpTypeConfig,
        KnowledgeRetrievalTypeConfig, ToolTypeConfig,
    )
    cfg_map = {
        "script": ScriptTypeConfig,
        "http": HttpTypeConfig,
        "knowledge_retrieval": KnowledgeRetrievalTypeConfig,
        "tool": ToolTypeConfig,
    }
    model = cfg_map.get(type)
    if not model:
        return
    try:
        model(**type_config)
    except ValidationError as e:
        raise HTTPException(
            status_code=422,
            detail=f"type_config validation failed for type={type}: {e.errors()}",
        )
