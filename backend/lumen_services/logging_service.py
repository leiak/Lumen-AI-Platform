"""
日志服务 - 操作日志、审计日志、查询日志
"""
import logging
import json
from datetime import datetime
from typing import Optional, List, Dict, Any
from enum import Enum
from sqlalchemy import Column, String, Text, Integer, ForeignKey, JSON, DateTime, Index
from sqlalchemy.orm import Session
from lumen_models.base import BaseModel
from lumen_core.database import Base


class LogLevel(str, Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class OperationType(str, Enum):
    CREATE = "CREATE"
    READ = "READ"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
    LOGIN = "LOGIN"
    LOGOUT = "LOGOUT"
    EXECUTE = "EXECUTE"
    API_CALL = "API_CALL"


class AuditLog(BaseModel):
    """审计日志表"""
    __tablename__ = "audit_logs"

    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=True, index=True)
    username = Column(String(100), nullable=True)
    action = Column(String(50), nullable=False)  # 操作类型
    resource_type = Column(String(50), nullable=True)  # 资源类型
    resource_id = Column(String(100), nullable=True)  # 资源ID
    details = Column(JSON, nullable=True)  # 详细信息
    ip_address = Column(String(50), nullable=True)
    user_agent = Column(String(500), nullable=True)
    status = Column(String(20), default="success")  # success, failure
    error_message = Column(Text, nullable=True)
    duration_ms = Column(Integer, nullable=True)  # 操作耗时（毫秒）

    __table_args__ = (
        Index("idx_audit_user_time", "user_id", "created_at"),
        Index("idx_audit_tenant_time", "tenant_id", "created_at"),
        Index("idx_audit_action_time", "action", "created_at"),
    )


class OperationLog(BaseModel):
    """操作日志表 - 记录系统操作"""
    __tablename__ = "operation_logs"

    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=True, index=True)
    module = Column(String(50), nullable=False)  # 模块
    action = Column(String(50), nullable=False)  # 动作
    operator = Column(String(100), nullable=True)  # 操作者
    target = Column(String(200), nullable=True)  # 操作对象
    method = Column(String(20), nullable=True)  # HTTP方法
    path = Column(String(500), nullable=True)  # 请求路径
    request_data = Column(JSON, nullable=True)  # 请求数据
    response_data = Column(JSON, nullable=True)  # 响应数据
    status_code = Column(Integer, nullable=True)  # HTTP状态码
    duration_ms = Column(Integer, nullable=True)  # 耗时
    level = Column(String(20), default="INFO")  # 日志级别

    __table_args__ = (
        Index("idx_oplog_tenant_time", "tenant_id", "created_at"),
        Index("idx_oplog_module", "module", "created_at"),
    )


class QueryLog(BaseModel):
    """查询日志表 - 记录数据库查询"""
    __tablename__ = "query_logs"

    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=True, index=True)
    query_type = Column(String(50), nullable=False)  # 查询类型
    table_name = Column(String(100), nullable=True)  # 表名
    query_sql = Column(Text, nullable=True)  # SQL语句（脱敏）
    query_params = Column(JSON, nullable=True)  # 查询参数
    duration_ms = Column(Integer, nullable=True)  # 查询耗时
    row_count = Column(Integer, nullable=True)  # 返回行数
    cache_hit = Column(Integer, default=0)  # 是否命中缓存

    __table_args__ = (
        Index("idx_querylog_tenant_time", "tenant_id", "created_at"),
        Index("idx_querylog_type", "query_type", "created_at"),
    )


class LoggingService:
    """日志服务"""

    def __init__(self):
        self.logger = logging.getLogger("app")
        self._setup_logging()

    def _setup_logging(self):
        """配置日志"""
        if not self.logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)
            self.logger.setLevel(logging.INFO)

    def log_audit(
        self,
        db: Session,
        action: str,
        resource_type: str = None,
        resource_id: str = None,
        user_id: int = None,
        tenant_id: int = None,
        username: str = None,
        details: Dict[str, Any] = None,
        ip_address: str = None,
        user_agent: str = None,
        status: str = "success",
        error_message: str = None,
        duration_ms: int = None
    ) -> AuditLog:
        """记录审计日志"""
        try:
            audit_log = AuditLog(
                user_id=user_id,
                tenant_id=tenant_id,
                username=username,
                action=action,
                resource_type=resource_type,
                resource_id=str(resource_id) if resource_id else None,
                details=details,
                ip_address=ip_address,
                user_agent=user_agent,
                status=status,
                error_message=error_message,
                duration_ms=duration_ms
            )
            db.add(audit_log)
            db.commit()
            return audit_log
        except Exception as e:
            self.logger.error(f"Failed to write audit log: {e}")
            db.rollback()
            return None

    def log_operation(
        self,
        db: Session,
        module: str,
        action: str,
        operator: str = None,
        target: str = None,
        method: str = None,
        path: str = None,
        request_data: Dict[str, Any] = None,
        response_data: Dict[str, Any] = None,
        status_code: int = None,
        duration_ms: int = None,
        level: str = "INFO",
        tenant_id: int = None
    ) -> OperationLog:
        """记录操作日志"""
        try:
            # 脱敏处理 - 移除敏感字段
            sanitized_request = self._sanitize_data(request_data)
            sanitized_response = self._sanitize_data(response_data)

            operation_log = OperationLog(
                tenant_id=tenant_id,
                module=module,
                action=action,
                operator=operator,
                target=target,
                method=method,
                path=path,
                request_data=sanitized_request,
                response_data=sanitized_response,
                status_code=status_code,
                duration_ms=duration_ms,
                level=level
            )
            db.add(operation_log)
            db.commit()
            return operation_log
        except Exception as e:
            self.logger.error(f"Failed to write operation log: {e}")
            db.rollback()
            return None

    def log_query(
        self,
        db: Session,
        query_type: str,
        table_name: str = None,
        query_sql: str = None,
        query_params: Dict[str, Any] = None,
        duration_ms: int = None,
        row_count: int = None,
        cache_hit: bool = False,
        tenant_id: int = None
    ) -> QueryLog:
        """记录查询日志"""
        try:
            # SQL脱敏
            sanitized_sql = self._sanitize_sql(query_sql)

            query_log = QueryLog(
                tenant_id=tenant_id,
                query_type=query_type,
                table_name=table_name,
                query_sql=sanitized_sql,
                query_params=query_params,
                duration_ms=duration_ms,
                row_count=row_count,
                cache_hit=1 if cache_hit else 0
            )
            db.add(query_log)
            db.commit()
            return query_log
        except Exception as e:
            self.logger.error(f"Failed to write query log: {e}")
            db.rollback()
            return None

    def _sanitize_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """脱敏处理 - 移除敏感字段"""
        if not data:
            return None

        sensitive_fields = [
            'password', 'secret', 'token', 'api_key', 'apikey',
            'access_token', 'refresh_token', 'authorization',
            'credential', 'private_key', 'ssn', 'credit_card'
        ]

        sanitized = {}
        for key, value in data.items():
            key_lower = key.lower()
            if any(s in key_lower for s in sensitive_fields):
                sanitized[key] = "***REDACTED***"
            elif isinstance(value, dict):
                sanitized[key] = self._sanitize_data(value)
            else:
                sanitized[key] = value
        return sanitized

    def _sanitize_sql(self, sql: str) -> str:
        """SQL脱敏"""
        if not sql:
            return None

        # 移除具体数值，保留结构
        import re
        # 脱敏数字值
        sql = re.sub(r'\d+', '?', sql)
        # 脱敏引号内的内容
        sql = re.sub(r"'[^']*'", "'?'", sql)
        # 限制长度
        if len(sql) > 500:
            sql = sql[:500] + "..."
        return sql

    def get_audit_logs(
        self,
        db: Session,
        tenant_id: int,
        user_id: int = None,
        action: str = None,
        start_time: datetime = None,
        end_time: datetime = None,
        limit: int = 100
    ) -> List[AuditLog]:
        """查询审计日志"""
        query = db.query(AuditLog).filter(AuditLog.tenant_id == tenant_id)

        if user_id:
            query = query.filter(AuditLog.user_id == user_id)
        if action:
            query = query.filter(AuditLog.action == action)
        if start_time:
            query = query.filter(AuditLog.created_at >= start_time)
        if end_time:
            query = query.filter(AuditLog.created_at <= end_time)

        return query.order_by(AuditLog.created_at.desc()).limit(limit).all()

    def get_operation_logs(
        self,
        db: Session,
        tenant_id: int,
        module: str = None,
        start_time: datetime = None,
        end_time: datetime = None,
        level: str = None,
        limit: int = 100
    ) -> List[OperationLog]:
        """查询操作日志"""
        query = db.query(OperationLog).filter(OperationLog.tenant_id == tenant_id)

        if module:
            query = query.filter(OperationLog.module == module)
        if level:
            query = query.filter(OperationLog.level == level)
        if start_time:
            query = query.filter(OperationLog.created_at >= start_time)
        if end_time:
            query = query.filter(OperationLog.created_at <= end_time)

        return query.order_by(OperationLog.created_at.desc()).limit(limit).all()

    def info(self, message: str, **kwargs):
        """记录Info日志"""
        self.logger.info(message, extra=kwargs)

    def warning(self, message: str, **kwargs):
        """记录Warning日志"""
        self.logger.warning(message, extra=kwargs)

    def error(self, message: str, **kwargs):
        """记录Error日志"""
        self.logger.error(message, extra=kwargs)

    def debug(self, message: str, **kwargs):
        """记录Debug日志"""
        self.logger.debug(message, extra=kwargs)


# 全局单例
_logging_service: Optional[LoggingService] = None


def get_logging_service() -> LoggingService:
    """获取日志服务单例"""
    global _logging_service
    if _logging_service is None:
        _logging_service = LoggingService()
    return _logging_service
