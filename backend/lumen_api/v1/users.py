from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from lumen_core.database import get_db
from lumen_api.v1.auth import get_current_user
from lumen_models.user import User
from lumen_schemas.user import UserCreate, UserUpdate, UserResponse, UserSimpleResponse
from lumen_schemas.common import SingleResponse, PaginatedResponse
from lumen_services.user_service import UserService

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/assignable", response_model=PaginatedResponse[UserSimpleResponse])
async def list_assignable_users(
    page: int = 1,
    page_size: int = 50,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """返回当前租户内可被指派为负责人的 active 用户列表(简化字段)。

    与 ``GET /users/`` 的差别:那个 endpoint 需要 ``is_superuser`` 权限,
    给「用户管理」页用;这个 endpoint 只要鉴权即可,给「客户 owner 选
    用户」之类的下拉用 — 销售把自己名下的客户转给同租户同事是日常
    需求,不应该卡 superuser。
    """
    if not current_user.is_active:
        raise HTTPException(status_code=403, detail="Inactive user")

    service = UserService()
    users = service.list_assignable_users(db, current_user.tenant_id)
    total = len(users)
    start = (page - 1) * page_size
    end = start + page_size
    return PaginatedResponse(
        data=[UserSimpleResponse.model_validate(u) for u in users[start:end]],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/", response_model=PaginatedResponse[UserResponse])
async def list_users(
    page: int = 1,
    page_size: int = 10,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Not enough permissions")

    service = UserService()
    users = service.list_users(db, current_user.tenant_id)
    total = len(users)
    start = (page - 1) * page_size
    end = start + page_size
    return PaginatedResponse(
        data=[UserResponse.model_validate(u) for u in users[start:end]],
        total=total,
        page=page,
        page_size=page_size
    )


@router.post("/", response_model=SingleResponse[UserResponse])
async def create_user(
    data: UserCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Not enough permissions")

    service = UserService()
    user = service.create_user(db, current_user.tenant_id, data)
    return SingleResponse(data=UserResponse.model_validate(user))


@router.get("/{user_id}", response_model=SingleResponse[UserResponse])
async def get_user(
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if current_user.id != user_id and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Not enough permissions")

    service = UserService()
    user = service.get_user(db, user_id, current_user.tenant_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return SingleResponse(data=UserResponse.model_validate(user))


@router.put("/{user_id}", response_model=SingleResponse[UserResponse])
async def update_user(
    user_id: int,
    data: UserUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if current_user.id != user_id and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Not enough permissions")

    service = UserService()
    user = service.update_user(db, user_id, current_user.tenant_id, data)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return SingleResponse(data=UserResponse.model_validate(user))


@router.delete("/{user_id}")
async def delete_user(
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Not enough permissions")

    service = UserService()
    success = service.delete_user(db, user_id, current_user.tenant_id)
    if not success:
        raise HTTPException(status_code=404, detail="User not found")
    return SingleResponse(message="Deleted successfully")
