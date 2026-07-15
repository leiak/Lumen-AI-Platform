from sqlalchemy import Column, String, Text, Integer, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime
from lumen_models.base import BaseModel


class Skill(BaseModel):
    __tablename__ = "skills"

    name = Column(String(100), nullable=False, unique=True)
    description = Column(Text)
    category = Column(String(50))  # e.g., "web", "data", "code", "chat"
    content = Column(Text)  # The actual skill prompt or code
    # prompt = LLM 调用（渲染 template 后送 LLM）
    # script = Python 脚本（SkillScriptExecutor 执行）
    type = Column(String(20), default="prompt")  # "prompt" | "script"
    is_builtin = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    version = Column(String(20), default="1.0.0")
    # tenant_id = NULL  → 内置技能，平台可见，各租户只能读不能写
    # tenant_id = N     → 租户 N 的自定义技能，只有 N 能读写
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
