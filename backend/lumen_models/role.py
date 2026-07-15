from sqlalchemy import Column, String, Text, Integer, Boolean, ForeignKey, Table
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

    name = Column(String(50), nullable=False, unique=True)
    description = Column(String(200))
    is_active = Column(Boolean, default=True)

    # Many-to-many with permissions
    permissions = relationship("Permission", secondary="role_permissions", back_populates="roles")

# Role-Permission association table
role_permissions = Table(
    "role_permissions",
    BaseModel.metadata,
    Column("role_id", Integer, ForeignKey("roles.id"), primary_key=True),
    Column("permission_id", Integer, ForeignKey("permissions.id"), primary_key=True),
)
