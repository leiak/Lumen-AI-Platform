from sqlalchemy import Column, Computed, String, Text, Integer, Boolean, ForeignKey, Table
from sqlalchemy.orm import relationship
from lumen_models.base import BaseModel

# Permission table
class Permission(BaseModel):
    __tablename__ = "permissions"

    name = Column(String(50), nullable=False, unique=True)
    resource = Column(String(50))  # e.g., "knowledge", "workflow", "user"
    action = Column(String(50))   # e.g., "create", "read", "update", "delete"

    # Many-to-many with roles
    roles = relationship("Role", secondary="role_permissions", back_populates="permissions")

# Role table
class Role(BaseModel):
    __tablename__ = "roles"

    name = Column(String(50), nullable=False)
    description = Column(String(200))
    is_active = Column(Boolean, default=True)

    # Phase 1 Group A 3.4 (2026-09-04):VIRTUAL GENERATED 列,active 行 =
    # 原 name,弱删行(``is_active=0``)= NULL;让 ``name`` UNIQUE 落在
    # dedup 列上,实现"弱删后 role name 可复用"。
    # 同步去掉 ``unique=True`` —— DB 端 UNIQUE 已迁到 dedup 列,原 name
    # 列本身不需要重复 UNIQUE 约束。
    roles_dedup_key = Column(
        String(50),
        Computed(
            "CASE WHEN is_active = 1 THEN name ELSE NULL END",
            persisted=False,
        ),
        nullable=True,
        comment="Phase 1 3.4 dedup key for soft-delete UNIQUE",
    )

    # Many-to-many with permissions
    permissions = relationship("Permission", secondary="role_permissions", back_populates="roles")

# Role-Permission association table
role_permissions = Table(
    "role_permissions",
    BaseModel.metadata,
    Column("role_id", Integer, ForeignKey("roles.id"), primary_key=True),
    Column("permission_id", Integer, ForeignKey("permissions.id"), primary_key=True),
)
