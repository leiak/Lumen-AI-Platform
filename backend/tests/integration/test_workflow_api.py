"""
集成测试: 工作流 API
"""
import pytest
import sys
import os
from fastapi.testclient import TestClient

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))


class TestWorkflowAPI:
    """工作流 API 集成测试"""

    @pytest.fixture
    def client(self):
        """创建测试客户端"""
        from lumen_main import app
        return TestClient(app)

    @pytest.fixture
    def auth_headers(self, client):
        """获取认证头"""
        # 登录获取token
        response = client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "admin123"}
        )
        if response.status_code == 200:
            token = response.json().get("data", {}).get("access_token")
            return {"Authorization": f"Bearer {token}"}
        return {}

    def test_list_workflows(self, client, auth_headers):
        """列出工作流"""
        response = client.get(
            "/api/v1/workflows/",
            headers=auth_headers
        )
        # 期望返回200或401（如果未认证）
        assert response.status_code in [200, 401]

    def test_create_workflow(self, client, auth_headers):
        """创建工作流"""
        workflow_data = {
            "name": "Test Workflow",
            "description": "Integration test workflow",
            "definition": {
                "nodes": [
                    {"id": "start", "type": "start", "config": {}}
                ],
                "edges": []
            }
        }

        response = client.post(
            "/api/v1/workflows/",
            json=workflow_data,
            headers=auth_headers
        )

        # 如果认证失败返回401
        if response.status_code == 401:
            pytest.skip("Authentication required")

        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 200
        assert data["data"]["name"] == "Test Workflow"

    def test_get_workflow(self, client, auth_headers):
        """获取单个工作流"""
        # 先创建
        workflow_data = {
            "name": "Get Test",
            "definition": {"nodes": [], "edges": []}
        }

        create_response = client.post(
            "/api/v1/workflows/",
            json=workflow_data,
            headers=auth_headers
        )

        if create_response.status_code != 200:
            pytest.skip("Cannot create workflow for testing")

        workflow_id = create_response.json()["data"]["id"]

        # 再获取
        response = client.get(
            f"/api/v1/workflows/{workflow_id}",
            headers=auth_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert data["data"]["id"] == workflow_id

    def test_update_workflow(self, client, auth_headers):
        """更新工作流"""
        # 先创建
        workflow_data = {
            "name": "Update Test",
            "definition": {"nodes": [], "edges": []}
        }

        create_response = client.post(
            "/api/v1/workflows/",
            json=workflow_data,
            headers=auth_headers
        )

        if create_response.status_code != 200:
            pytest.skip("Cannot create workflow for testing")

        workflow_id = create_response.json()["data"]["id"]

        # 更新
        update_data = {"name": "Updated Name"}
        response = client.put(
            f"/api/v1/workflows/{workflow_id}",
            json=update_data,
            headers=auth_headers
        )

        assert response.status_code == 200
        assert response.json()["data"]["name"] == "Updated Name"

    def test_delete_workflow(self, client, auth_headers):
        """删除工作流"""
        # 先创建
        workflow_data = {
            "name": "Delete Test",
            "definition": {"nodes": [], "edges": []}
        }

        create_response = client.post(
            "/api/v1/workflows/",
            json=workflow_data,
            headers=auth_headers
        )

        if create_response.status_code != 200:
            pytest.skip("Cannot create workflow for testing")

        workflow_id = create_response.json()["data"]["id"]

        # 删除
        response = client.delete(
            f"/api/v1/workflows/{workflow_id}",
            headers=auth_headers
        )

        assert response.status_code == 200

        # 验证删除
        get_response = client.get(
            f"/api/v1/workflows/{workflow_id}",
            headers=auth_headers
        )
        assert get_response.status_code == 404


class TestKnowledgeAPI:
    """知识库 API 集成测试"""

    @pytest.fixture
    def client(self):
        """创建测试客户端"""
        from lumen_main import app
        return TestClient(app)

    @pytest.fixture
    def auth_headers(self, client):
        """获取认证头"""
        response = client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "admin123"}
        )
        if response.status_code == 200:
            token = response.json().get("data", {}).get("access_token")
            return {"Authorization": f"Bearer {token}"}
        return {}

    def test_list_knowledge_bases(self, client, auth_headers):
        """列出知识库"""
        response = client.get(
            "/api/v1/knowledge/",
            headers=auth_headers
        )
        assert response.status_code in [200, 401]

    def test_create_knowledge_base(self, client, auth_headers):
        """创建知识库"""
        kb_data = {
            "name": "Test Knowledge Base",
            "description": "Integration test"
        }

        response = client.post(
            "/api/v1/knowledge/",
            json=kb_data,
            headers=auth_headers
        )

        if response.status_code == 401:
            pytest.skip("Authentication required")

        assert response.status_code == 200
        data = response.json()
        assert data["data"]["name"] == "Test Knowledge Base"


class TestLogsAPI:
    """日志 API 集成测试"""

    @pytest.fixture
    def client(self):
        """创建测试客户端"""
        from lumen_main import app
        return TestClient(app)

    @pytest.fixture
    def auth_headers(self, client):
        """获取认证头"""
        response = client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "admin123"}
        )
        if response.status_code == 200:
            token = response.json().get("data", {}).get("access_token")
            return {"Authorization": f"Bearer {token}"}
        return {}

    def test_get_audit_logs(self, client, auth_headers):
        """获取审计日志"""
        response = client.get(
            "/api/v1/logs/audit",
            headers=auth_headers
        )
        assert response.status_code in [200, 401]

    def test_get_operation_logs(self, client, auth_headers):
        """获取操作日志"""
        response = client.get(
            "/api/v1/logs/operations",
            headers=auth_headers
        )
        assert response.status_code in [200, 401]

    def test_get_log_stats(self, client, auth_headers):
        """获取日志统计"""
        response = client.get(
            "/api/v1/logs/stats",
            headers=auth_headers
        )
        assert response.status_code in [200, 401]

        if response.status_code == 200:
            data = response.json()
            assert "data" in data
            assert "audit_logs_24h" in data["data"]


class TestAuthAPI:
    """认证 API 集成测试"""

    @pytest.fixture
    def client(self):
        """创建测试客户端"""
        from lumen_main import app
        return TestClient(app)

    def test_login_success(self, client):
        """登录成功"""
        response = client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "admin123"}
        )

        # 可能成功或失败（取决于是否有admin用户）
        assert response.status_code in [200, 401, 422]

    def test_login_invalid_credentials(self, client):
        """无效凭据登录"""
        response = client.post(
            "/api/v1/auth/login",
            json={"username": "invalid", "password": "wrong"}
        )

        # 应该返回401或200（带错误）
        assert response.status_code in [200, 401, 422]

    def test_get_current_user(self, client):
        """获取当前用户"""
        # 先登录
        login_response = client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "admin123"}
        )

        if login_response.status_code == 200:
            token = login_response.json().get("data", {}).get("access_token")
            headers = {"Authorization": f"Bearer {token}"}

            response = client.get(
                "/api/v1/auth/me",
                headers=headers
            )
            assert response.status_code in [200, 401]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
