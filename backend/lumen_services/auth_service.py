from typing import Optional
from sqlalchemy.orm import Session
from lumen_models.user import User
from lumen_models.tenant import Tenant
from lumen_core.security import verify_password, create_access_token
from lumen_core.tenant import TenantContext


class AuthService:
    @staticmethod
    def authenticate_user(db: Session, username: str, password: str) -> Optional[User]:
        user = db.query(User).filter(User.username == username).first()
        if not user:
            return None
        if not verify_password(password, user.hashed_password):
            return None
        if not user.is_active:
            return None
        return user

    @staticmethod
    def create_token(user: User) -> str:
        TenantContext.set_tenant_id(user.tenant_id)
        token = create_access_token(data={"sub": user.username, "user_id": user.id})
        TenantContext.clear()
        return token

    @staticmethod
    def create_default_tenant(db: Session) -> Tenant:
        tenant = db.query(Tenant).filter(Tenant.code == "default").first()
        if not tenant:
            tenant = Tenant(name="Default Tenant", code="default")
            db.add(tenant)
            db.commit()
            db.refresh(tenant)
        return tenant
