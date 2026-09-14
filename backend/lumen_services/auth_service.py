from typing import Optional
from sqlalchemy.orm import Session
from lumen_models.user import User
from lumen_models.tenant import Tenant
from lumen_core.security import verify_password, create_access_token
from lumen_core.tenant import TenantContext


class AuthService:
    @staticmethod
    def authenticate_user(db: Session, username: str, password: str) -> Optional[User]:
        # ORDER BY id ASC 让多账号时稳定选最小 id —— pytest fixture
        # 残留 / 多次 init_dev_db 跑可能产生多条同 username 行(例:admin),
        # 不指定排序的话 .first() 在不同 query plan 下返回不同行,撞到
        # hash 不全的那条就 500(passlib.exc.UnknownHashError)。
        # 2026-09-14 实际故障:dev DB 有 id=1 (hashed_password='x' 占位
        # 行) + id=12 (真 admin),未指定排序时随机命中 id=1 → login 500。
        user = (
            db.query(User)
            .filter(User.username == username)
            .order_by(User.id.asc())
            .first()
        )
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
