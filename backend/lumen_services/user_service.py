from typing import List, Optional
from sqlalchemy.orm import Session
from lumen_models.user import User
from lumen_models.tenant import Tenant
from lumen_schemas.user import UserCreate, UserUpdate
from lumen_core.security import get_password_hash


class UserService:
    def list_users(self, db: Session, tenant_id: int) -> List[User]:
        return db.query(User).filter(User.tenant_id == tenant_id).all()

    def list_assignable_users(self, db: Session, tenant_id: int) -> List[User]:
        """返回同租户内「可被指派」的用户:active + 按 id 升序(便于前端默认选第一个)。

        排除 ``is_active=False`` 的账号(离职/禁用),避免客户被指派给
        一个登录不了的人。返回的字段通过 ``UserSimpleResponse`` 裁剪,
        不会泄露 is_superuser / 密码哈希等内部信息。
        """
        return (
            db.query(User)
            .filter(User.tenant_id == tenant_id, User.is_active.is_(True))
            .order_by(User.id.asc())
            .all()
        )

    def create_user(
        self, db: Session, tenant_id: int, data: UserCreate
    ) -> User:
        user = User(
            username=data.username,
            email=data.email,
            full_name=data.full_name,
            hashed_password=get_password_hash(data.password),
            tenant_id=tenant_id,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user

    def get_user(self, db: Session, user_id: int, tenant_id: int) -> Optional[User]:
        return db.query(User).filter(
            User.id == user_id,
            User.tenant_id == tenant_id
        ).first()

    def update_user(
        self, db: Session, user_id: int, tenant_id: int, data: UserUpdate
    ) -> Optional[User]:
        user = self.get_user(db, user_id, tenant_id)
        if not user:
            return None

        update_data = data.model_dump(exclude_unset=True)
        if "password" in update_data:
            update_data["hashed_password"] = get_password_hash(update_data.pop("password"))

        for field, value in update_data.items():
            setattr(user, field, value)

        db.commit()
        db.refresh(user)
        return user

    def delete_user(self, db: Session, user_id: int, tenant_id: int) -> bool:
        user = self.get_user(db, user_id, tenant_id)
        if not user:
            return False
        db.delete(user)
        db.commit()
        return True
