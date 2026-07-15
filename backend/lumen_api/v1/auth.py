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


def require_admin(current_user: "User" = Depends(get_current_user)) -> "User":
    """仅 superuser + active 可访问,非管理员返回 403"""
    if not getattr(current_user, "is_superuser", False) or not getattr(current_user, "is_active", True):
        raise HTTPException(status_code=403, detail="仅管理员可访问")
    return current_user
