"""
单元测试: 日志服务
"""
import pytest
import sys
import os
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))


class TestLoggingService:
    """日志服务测试"""

    def test_sanitize_data(self):
        """数据脱敏测试"""
        from lumen_services.logging_service import LoggingService

        service = LoggingService()

        # 原始数据
        data = {
            "username": "test_user",
            "password": "secret123",
            "api_key": "key123",
            "data": {"token": "abc123"}
        }

        sanitized = service._sanitize_data(data)

        # 验证敏感字段被脱敏
        assert sanitized["username"] == "test_user"
        assert sanitized["password"] == "***REDACTED***"
        assert sanitized["api_key"] == "***REDACTED***"
        assert sanitized["data"]["token"] == "***REDACTED***"

    def test_sanitize_nested_data(self):
        """嵌套数据脱敏"""
        from lumen_services.logging_service import LoggingService

        service = LoggingService()

        data = {
            "user": {
                "name": "test",
                "profile": {
                    "password": "secret"
                }
            }
        }

        sanitized = service._sanitize_data(data)
        assert sanitized["user"]["profile"]["password"] == "***REDACTED***"

    def test_sanitize_sql(self):
        """SQL脱敏测试"""
        from lumen_services.logging_service import LoggingService

        service = LoggingService()

        sql = "SELECT * FROM users WHERE id = 123 AND name = 'test'"
        sanitized = service._sanitize_sql(sql)

        # 应该脱敏具体数值
        assert "?" in sanitized or "'?'" in sanitized

    def test_sanitize_none(self):
        """None值处理"""
        from lumen_services.logging_service import LoggingService

        service = LoggingService()

        assert service._sanitize_data(None) is None
        assert service._sanitize_sql(None) is None

    def test_info_logging(self):
        """Info级别日志"""
        from lumen_services.logging_service import LoggingService

        service = LoggingService()
        # 不应抛出异常
        service.info("Test info message")
        service.info("Test with extra", extra_field="value")

    def test_warning_logging(self):
        """Warning级别日志"""
        from lumen_services.logging_service import LoggingService

        service = LoggingService()
        service.warning("Test warning message")

    def test_error_logging(self):
        """Error级别日志"""
        from lumen_services.logging_service import LoggingService

        service = LoggingService()
        service.error("Test error message")

    def test_debug_logging(self):
        """Debug级别日志"""
        from lumen_services.logging_service import LoggingService

        service = LoggingService()
        service.debug("Test debug message")


class TestAuditLogModel:
    """审计日志模型测试"""

    def test_audit_log_creation(self):
        """审计日志创建"""
        from lumen_services.logging_service import AuditLog

        log = AuditLog(
            user_id=1,
            tenant_id=1,
            username="test_user",
            action="CREATE",
            resource_type="document",
            resource_id="123",
            status="success"
        )

        assert log.user_id == 1
        assert log.username == "test_user"
        assert log.action == "CREATE"


class TestOperationLogModel:
    """操作日志模型测试"""

    def test_operation_log_creation(self):
        """操作日志创建"""
        from lumen_services.logging_service import OperationLog

        log = OperationLog(
            tenant_id=1,
            module="knowledge",
            action="UPLOAD",
            operator="admin",
            method="POST",
            path="/api/v1/knowledge/1/documents",
            status_code=200,
            duration_ms=1500,
            level="INFO"
        )

        assert log.module == "knowledge"
        assert log.method == "POST"
        assert log.duration_ms == 1500


class TestQueryLogModel:
    """查询日志模型测试"""

    def test_query_log_creation(self):
        """查询日志创建"""
        from lumen_services.logging_service import QueryLog

        log = QueryLog(
            tenant_id=1,
            query_type="SELECT",
            table_name="users",
            duration_ms=50,
            row_count=10,
            cache_hit=0
        )

        assert log.query_type == "SELECT"
        assert log.row_count == 10
        assert log.cache_hit == 0


class TestLoggingServiceIntegration:
    """日志服务集成测试（模拟数据库）"""

    def test_log_audit_with_mock_db(self):
        """模拟数据库记录审计日志"""
        from lumen_services.logging_service import LoggingService

        service = LoggingService()

        # 模拟db
        mock_db = MagicMock()

        log = service.log_audit(
            db=mock_db,
            action="TEST",
            resource_type="test",
            user_id=1,
            tenant_id=1,
            username="test",
            status="success"
        )

        # 验证数据库操作被调用
        mock_db.add.assert_called_once()
        mock_db.commit.assert_called_once()

    def test_log_operation_with_mock_db(self):
        """模拟数据库记录操作日志"""
        from lumen_services.logging_service import LoggingService

        service = LoggingService()
        mock_db = MagicMock()

        log = service.log_operation(
            db=mock_db,
            module="test",
            action="TEST_ACTION",
            tenant_id=1
        )

        mock_db.add.assert_called_once()
        mock_db.commit.assert_called_once()

    def test_log_query_with_mock_db(self):
        """模拟数据库记录查询日志"""
        from lumen_services.logging_service import LoggingService

        service = LoggingService()
        mock_db = MagicMock()

        log = service.log_query(
            db=mock_db,
            query_type="SELECT",
            table_name="users",
            tenant_id=1
        )

        mock_db.add.assert_called_once()
        mock_db.commit.assert_called_once()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
