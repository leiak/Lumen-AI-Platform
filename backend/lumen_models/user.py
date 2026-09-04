from sqlalchemy import Column, Computed, String, Boolean, Integer, ForeignKey
from sqlalchemy.orm import relationship
from lumen_models.base import BaseModel


class User(BaseModel):
    __tablename__ = "users"

    username = Column(String(50), nullable=False, index=True)
    email = Column(String(100), nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    full_name = Column(String(100))
    is_active = Column(Boolean, default=True)
    is_superuser = Column(Boolean, default=False)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)

    # Phase 1 Group A 3.4 (2026-09-04): VIRTUAL GENERATED 列,active 行 = 原值,
    # 软删行 = NULL,UNIQUE(ix_users_email / ix_users_username) on dedup 列 —
    # MySQL UNIQUE 对多 NULL 不视为冲突,实现"软删后 email / username 可复用"。
    # ``persisted=False`` 对应 VIRTUAL(不落盘,read 时 MySQL 现算)。
    users_dedup_email = Column(
        String(255),
        Computed(
            "CASE WHEN is_active = 1 THEN email ELSE NULL END",
            persisted=False,
        ),
        nullable=True,
    )
    users_dedup_username = Column(
        String(50),
        Computed(
            "CASE WHEN is_active = 1 THEN username ELSE NULL END",
            persisted=False,
        ),
        nullable=True,
    )

    tenant = relationship("Tenant", backref="users")
