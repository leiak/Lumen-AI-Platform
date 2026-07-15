"""集成测试: Knowledge 路由

M21: 删 KB 但被 agent 引用 → 422 + agent_count。
M28: 422 detail 还带 blocking_agents / blocking_documents / truncated,
    让前端能告诉用户「先解绑哪个 agent / 删哪个文档」,不只给一个冷数字。
"""
import pytest
import sys
import os
import uuid
from fastapi.testclient import TestClient

# Add parent directory to path so ``app.*`` imports resolve
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))


class TestKnowledgeRouter:
    """Knowledge API 集成测试"""

    @pytest.fixture
    def client(self):
        """创建测试客户端"""
        from lumen_main import app
        return TestClient(app)

    @pytest.fixture
    def auth_headers(self, client):
        """获取认证头(沿用项目默认 admin/admin123)
        注意:登录端点用 OAuth2PasswordRequestForm,必须用 form data 不能用 JSON。
        """
        from fastapi.testclient import TestClient
        response = client.post(
            "/api/v1/auth/login",
            data={"username": "admin", "password": "admin123"},
        )
        if response.status_code == 200:
            token = response.json().get("data", {}).get("access_token")
            return {"Authorization": f"Bearer {token}"}
        return {}

    @pytest.fixture
    def db_session(self):
        """M21: 直连 DB session(创建 KB + agent + 绑定 + 验证用)。"""
        from lumen_core.database import SessionLocal
        session = SessionLocal()
        try:
            yield session
        finally:
            # rollback 兜底:test 跑挂时残留的 pending change 不会污染 dev DB
            session.rollback()
            session.close()

    def test_delete_kb_referenced_by_agent_returns_422(self, client, auth_headers, db_session):
        """M21: 删 KB 但被 agent 引用 → 422 + agent_count。"""
        from lumen_models.knowledge import KnowledgeBase
        from lumen_models.agent import Agent, AgentKnowledgeBase

        # 拿一个真实的 embedding_model_config_id (FK 必须存在)
        from lumen_models.model_config import ModelConfig
        mc = (
            db_session.query(ModelConfig)
            .filter(ModelConfig.is_active == 1, ModelConfig.is_embedding == 1)
            .order_by(ModelConfig.id)
            .first()
        )
        assert mc is not None, "dev DB 至少需要一个 is_embedding=1 的 ModelConfig"

        kb = KnowledgeBase(
            name=f"m21-ref-kb-{uuid.uuid4().hex[:8]}",
            description="M21 422 test",
            tenant_id=1,
            status="active",
            embedding_model_config_id=mc.id,
        )
        db_session.add(kb)
        db_session.flush()

        agent = Agent(
            name=f"m21-ref-agent-{uuid.uuid4().hex[:8]}",
            prompt_template="test",
            model_name="gpt-4o",
            temperature=0,
            tenant_id=1,
        )
        db_session.add(agent)
        db_session.flush()
        agent.knowledge_bases.append(AgentKnowledgeBase(knowledge_base_id=kb.id))
        db_session.commit()

        kb_id = kb.id
        agent_id = agent.id
        try:
            res = client.delete(f"/api/v1/knowledge/{kb_id}", headers=auth_headers)
            assert res.status_code == 422, (
                f"expected 422 (referenced by agent), got {res.status_code} {res.text}"
            )
            body = res.json()
            # FastAPI 把 HTTPException 的 dict detail 放进 body["detail"]。
            detail = body.get("detail", {})
            if isinstance(detail, dict):
                assert detail.get("agent_count") == 1, (
                    f"expected agent_count=1, got {detail.get('agent_count')!r}; full detail={detail}"
                )
                # 文档数 0 (测试只造了 agent binding)
                assert detail.get("document_count") == 0
                # M28: blocking_agents 应含这条 binding 的 agent
                # (用 agent_id 比对,而不是 name —— name 可能因 uuid 唯一但 test 间不该撞)
                assert isinstance(detail.get("blocking_agents"), list)
                assert len(detail["blocking_agents"]) == 1
                assert detail["blocking_agents"][0]["id"] == agent_id
                assert detail["blocking_agents"][0]["name"] == agent.name
                # 文档没造,blocking_documents 应为空列表
                assert detail.get("blocking_documents") == []
                # 没超过 cap,truncated 应为 False
                assert detail.get("truncated") is False
            else:
                # 退路:有些版本的 FastAPI 会把 dict 包成 list/dict
                assert "1" in str(detail), (
                    f"expected '1' in detail str, got {detail!r}"
                )
        finally:
            # 清理:先解绑 agent_kb,再删 agent,再强删 KB。
            # 即使 test 失败,也要保证 dev DB 干净。
            from lumen_core.database import SessionLocal
            cleanup = SessionLocal()
            try:
                # 删绑定
                cleanup.query(AgentKnowledgeBase).filter_by(agent_id=agent_id).delete()
                # 删 agent
                cleanup.query(Agent).filter_by(id=agent_id).delete()
                # 强删 KB(用 delete 跳过 KB 内部 cascade 逻辑)
                cleanup.query(KnowledgeBase).filter_by(id=kb_id).delete()
                cleanup.commit()
            except Exception:
                cleanup.rollback()
            finally:
                cleanup.close()

    def test_delete_kb_with_documents_returns_422_with_doc_list(
        self, client, auth_headers, db_session
    ):
        """M28: 删 KB 但挂着 document → 422 + blocking_documents 列出 filename。"""
        from lumen_models.knowledge import KnowledgeBase, Document
        from lumen_models.model_config import ModelConfig

        mc = (
            db_session.query(ModelConfig)
            .filter(ModelConfig.is_active == 1, ModelConfig.is_embedding == 1)
            .order_by(ModelConfig.id)
            .first()
        )
        assert mc is not None, "dev DB 至少需要一个 is_embedding=1 的 ModelConfig"

        kb = KnowledgeBase(
            name=f"m28-doc-kb-{uuid.uuid4().hex[:8]}",
            description="M28 doc-blocker 422 test",
            tenant_id=1,
            status="active",
            embedding_model_config_id=mc.id,
        )
        db_session.add(kb)
        db_session.flush()

        # 挂两个 document,验证 blocking_documents 含两个
        doc1 = Document(
            filename=f"sample1-{uuid.uuid4().hex[:6]}.txt",
            file_path="/tmp/sample1.txt",
            status="completed",
            knowledge_base_id=kb.id,
        )
        doc2 = Document(
            filename=f"sample2-{uuid.uuid4().hex[:6]}.txt",
            file_path="/tmp/sample2.txt",
            status="queued",
            knowledge_base_id=kb.id,
        )
        db_session.add_all([doc1, doc2])
        db_session.commit()

        kb_id = kb.id
        doc1_id, doc2_id = doc1.id, doc2.id
        try:
            res = client.delete(f"/api/v1/knowledge/{kb_id}", headers=auth_headers)
            assert res.status_code == 422, (
                f"expected 422 (referenced by documents), got {res.status_code} {res.text}"
            )
            detail = res.json().get("detail", {})
            assert isinstance(detail, dict), f"expected dict detail, got {detail!r}"
            assert detail.get("agent_count") == 0
            assert detail.get("document_count") == 2
            # blocking_documents 应含两条,按 id 升序
            docs_list = detail.get("blocking_documents", [])
            assert len(docs_list) == 2
            assert docs_list[0]["id"] == doc1_id
            assert docs_list[0]["filename"] == doc1.filename
            assert docs_list[1]["id"] == doc2_id
            assert docs_list[1]["filename"] == doc2.filename
            # 没 agent 引用 → blocking_agents 应为空
            assert detail.get("blocking_agents") == []
            assert detail.get("truncated") is False
        finally:
            from lumen_core.database import SessionLocal
            cleanup = SessionLocal()
            try:
                # 删 docs,再强删 KB。KB 的 422 在 route 层就抛了,
                # service.delete_knowledge_base 内的 doc_count guard 不会跑,
                # 但 ORM cascade 行为依赖 cascade 配置——保险起见手动删 docs。
                cleanup.query(Document).filter_by(knowledge_base_id=kb_id).delete()
                cleanup.query(KnowledgeBase).filter_by(id=kb_id).delete()
                cleanup.commit()
            except Exception:
                cleanup.rollback()
            finally:
                cleanup.close()
