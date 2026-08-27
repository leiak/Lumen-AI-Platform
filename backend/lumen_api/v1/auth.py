from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from lumen_core.database import get_db
from lumen_core.security import decode_access_token
from lumen_schemas.user import TokenResponse
from lumen_schemas.common import SingleResponse
from lumen_schemas.user import UserResponse
from lumen_services.auth_service import AuthService
from typing import Optional

router = APIRouter(prefix="/auth", tags=["auth"])
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
) -> UserResponse:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    payload = decode_access_token(token)
    if payload is None:
        raise credentials_exception
    username: str = payload.get("sub")
    if username is None:
        raise credentials_exception
    from lumen_models.user import User
    user = db.query(User).filter(User.username == username).first()
    if user is None:
        raise credentials_exception
    return user


@router.post("/login", response_model=SingleResponse[TokenResponse])
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
):
    user = AuthService.authenticate_user(db, form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = AuthService.create_token(user)
    return SingleResponse(data=TokenResponse(access_token=token, token_type="bearer"))


@router.get("/me", response_model=SingleResponse[UserResponse])
async def get_me(current_user = Depends(get_current_user)):
    return SingleResponse(data=UserResponse.model_validate(current_user))


# M38.2.x v2: 列当前 user 在当前 tenant 内「有 workspace.read 或
# is_superuser 或 is_owner」的所有 workspace。sidebar 默认接这里
# (替代 ``GET /workspaces``,后者是 admin 全集,前端不友好)。
@router.get("/me/workspaces")
async def get_me_workspaces(
    current_user: "User" = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """当前 user 能看见的 workspace 列表(sidebar 入口)。

    行为:
    - ``is_superuser`` → 返 tenant 下全部 workspace
    - 否则 → 返 ``WorkspaceMemberPermission`` grant 过 + owner + ``
      tenant_id IS NULL`` legacy 默认开的 workspace
    """
    from lumen_models.workspace import Workspace
    from lumen_models.workspace_member_permission import WorkspaceMemberPermission
    from lumen_services.permission_service import (
        PermissionService,
        _workspace_member_perms,
    )

    q = db.query(Workspace).filter(Workspace.tenant_id == current_user.tenant_id)
    rows = q.order_by(Workspace.created_at.asc(), Workspace.id.asc()).all()
    if not rows:
        return {"items": [], "total": 0}

    # 一次性 pre-load grant 行
    direct = _workspace_member_perms(db, current_user, [w.id for w in rows])
    owner_ids = {
        int(w.id) for w in rows if w.owner_id == current_user.id
    }

    is_admin = bool(getattr(current_user, "is_superuser", False))
    visible = []
    svc = PermissionService()
    for ws in rows:
        if is_admin or int(ws.id) in owner_ids:
            visible.append(ws)
            continue
        # 检查 effective perm 是否含 workspace.read
        if svc.check(db, current_user, "workspace.read", ws.id):
            visible.append(ws)
    return {
        "items": [
            {
                "id": w.id,
                "name": w.name,
                "description": w.description,
                "icon": w.icon,
                "color": w.color,
                "owner_id": w.owner_id,
            }
            for w in visible
        ],
        "total": len(visible),
    }


def require_admin(current_user: "User" = Depends(get_current_user)) -> "User":
    """仅 superuser + active 可访问,非管理员返回 403"""
    if not getattr(current_user, "is_superuser", False) or not getattr(current_user, "is_active", True):
        raise HTTPException(status_code=403, detail="仅管理员可访问")
    return current_user
