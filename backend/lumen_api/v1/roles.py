from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from lumen_core.database import get_db
from lumen_api.v1.auth import get_current_user
from lumen_models.user import User
from lumen_models.role import Role, Permission
from lumen_schemas.role import RoleCreate, RoleResponse

router = APIRouter(prefix="/roles", tags=["roles"])

@router.get("/", response_model=List[RoleResponse])
async def list_roles(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Admin only")

    roles = db.query(Role).all()
    return roles

@router.post("/", response_model=RoleResponse)
async def create_role(
    data: RoleCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Admin only")

    # Validate all permission IDs exist
    if data.permission_ids:
        existing_ids = {p.id for p in db.query(Permission).filter(Permission.id.in_(data.permission_ids)).all()}
        missing_ids = set(data.permission_ids) - existing_ids
        if missing_ids:
            raise HTTPException(status_code=400, detail=f"Invalid permission IDs: {missing_ids}")

    role = Role(name=data.name, description=data.description)

    if data.permission_ids:
        perms = db.query(Permission).filter(Permission.id.in_(data.permission_ids)).all()
        role.permissions = perms

    db.add(role)
    db.commit()
    db.refresh(role)
    return role

@router.get("/{role_id}", response_model=RoleResponse)
async def get_role(
    role_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Admin only")

    role = db.query(Role).filter(Role.id == role_id).first()
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    return role

@router.delete("/{role_id}")
async def delete_role(
    role_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Admin only")

    role = db.query(Role).filter(Role.id == role_id).first()
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")

    db.delete(role)
    db.commit()
    return {"message": "Role deleted"}
