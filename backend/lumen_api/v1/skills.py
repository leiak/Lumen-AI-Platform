from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Any, Dict, List
from lumen_core.database import get_db
from lumen_api.v1.auth import get_current_user
from lumen_models.user import User
from lumen_models.skill import Skill
from lumen_schemas.skill import SkillCreate, SkillUpdate, SkillResponse
from lumen_schemas.common import SingleResponse, PaginatedResponse
from lumen_services.skill_script_executor import SkillScriptExecutor

router = APIRouter(prefix="/skills", tags=["skills"])

@router.get("/", response_model=PaginatedResponse[SkillResponse])
async def list_skills(
    category: str = None,
    page: int = 1,
    page_size: int = 20,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # builtin 技能（tenant_id=NULL）平台可见；自定义技能租户可见
    query = db.query(Skill).filter(
        Skill.is_active == True,
        (Skill.is_builtin == True) | (Skill.tenant_id == current_user.tenant_id)
    )

    if category:
        query = query.filter(Skill.category == category)

    total = query.count()
    skills = query.offset((page - 1) * page_size).limit(page_size).all()

    return PaginatedResponse(
        data=skills,
        total=total,
        page=page,
        page_size=page_size
    )

@router.post("/", response_model=SingleResponse[SkillResponse])
async def create_skill(
    data: SkillCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    skill = Skill(**data.model_dump(), tenant_id=current_user.tenant_id)
    db.add(skill)
    db.commit()
    db.refresh(skill)
    return SingleResponse(data=skill)

@router.get("/{skill_id}", response_model=SingleResponse[SkillResponse])
async def get_skill(
    skill_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    skill = db.query(Skill).filter(
        Skill.id == skill_id,
        (Skill.is_builtin == True) | (Skill.tenant_id == current_user.tenant_id)
    ).first()
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    return SingleResponse(data=skill)

@router.put("/{skill_id}", response_model=SingleResponse[SkillResponse])
async def update_skill(
    skill_id: int,
    data: SkillUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    skill = db.query(Skill).filter(
        Skill.id == skill_id,
        (Skill.is_builtin == True) | (Skill.tenant_id == current_user.tenant_id)
    ).first()
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")

    if skill.is_builtin and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Cannot modify builtin skills")

    # 非内置技能且不属于当前租户，拒绝修改
    if not skill.is_builtin and skill.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=403, detail="Cannot modify another tenant's skill")

    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(skill, key, value)

    db.commit()
    db.refresh(skill)
    return SingleResponse(data=skill)

@router.delete("/{skill_id}")
async def delete_skill(
    skill_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    skill = db.query(Skill).filter(
        Skill.id == skill_id,
        (Skill.is_builtin == True) | (Skill.tenant_id == current_user.tenant_id)
    ).first()
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")

    if skill.is_builtin:
        raise HTTPException(status_code=403, detail="Cannot delete builtin skills")

    # 非内置技能且不属于当前租户，拒绝删除
    if not skill.is_builtin and skill.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=403, detail="Cannot delete another tenant's skill")

    db.delete(skill)
    db.commit()
    return SingleResponse(message="Skill deleted")


@router.post("/{skill_id}/run")
async def run_skill(
    skill_id: int,
    params: Dict[str, Any] = {},
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Execute a script-type skill and return the result.

    Only skill.type == "script" is supported. Prompt-type skills
    should be invoked through the chat flow instead.
    """
    skill = db.query(Skill).filter(
        Skill.id == skill_id,
        (Skill.is_builtin == True) | (Skill.tenant_id == current_user.tenant_id)
    ).first()
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")

    if skill.type != "script":
        raise HTTPException(status_code=400, detail=f"Skill type '{skill.type}' is not executable via /run. Use 'chat' for prompt-type skills.")

    if not skill.content:
        raise HTTPException(status_code=400, detail="Skill content is empty")

    result = SkillScriptExecutor().execute(skill.content, params)
    return SingleResponse(data=result.to_dict())

