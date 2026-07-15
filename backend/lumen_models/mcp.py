from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, JSON, Index
from sqlalchemy.sql import func
from lumen_models.base import Base


class MCPServer(Base):
    """MCP Server configuration stored in database"""
    __tablename__ = "mcp_servers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    url = Column(String(500), nullable=False)
    auth_token = Column(String(500), nullable=True)  # Encrypted
    status = Column(String(20), default="disconnected")  # connected, disconnected, error
    capabilities = Column(JSON, nullable=True)  # Server capabilities
    config = Column(JSON, nullable=True)  # Additional config
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("idx_mcp_tenant_name", "tenant_id", "name", unique=True),
    )

    def __repr__(self):
        return f"<MCPServer(id={self.id}, name={self.name}, status={self.status})>"


class MCPTool(Base):
    """MCP Tool definition stored in database"""
    __tablename__ = "mcp_tools"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    server_id = Column(Integer, ForeignKey("mcp_servers.id"), nullable=False)
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    input_schema = Column(JSON, nullable=False)  # JSON Schema for tool input
    output_schema = Column(JSON, nullable=True)  # JSON Schema for tool output
    is_enabled = Column(Integer, default=1)  # 1= enabled, 0=disabled
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("idx_mcp_tool_tenant_server", "tenant_id", "server_id"),
        Index("idx_mcp_tool_name", "tenant_id", "name", unique=True),
    )

    def __repr__(self):
        return f"<MCPTool(id={self.id}, name={self.name})>"


class MCPToolExecution(Base):
    """MCP Tool execution log for debugging and analytics"""
    __tablename__ = "mcp_tool_executions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    tool_id = Column(Integer, ForeignKey("mcp_tools.id"), nullable=False)
    server_id = Column(Integer, ForeignKey("mcp_servers.id"), nullable=False)
    input_data = Column(JSON, nullable=False)
    output_data = Column(JSON, nullable=True)
    error = Column(Text, nullable=True)
    status = Column(String(20), default="pending")  # pending, success, error
    execution_time_ms = Column(Integer, nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("idx_mcp_exec_tenant_tool", "tenant_id", "tool_id"),
        Index("idx_mcp_exec_created", "created_at"),
    )

    def __repr__(self):
        return f"<MCPToolExecution(id={self.id}, tool_id={self.tool_id}, status={self.status})>"
