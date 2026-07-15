"""集成测试: Agent 路由的 PUT /agents/{id} is_active 切换

回归测试:确保只传 is_active 字段时,后端能正确翻转并保持其它字段不变。
"""
import pytest
import sys
import os
import uuid
from fastapi.testclient import TestClient

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))


class TestAgentRouter:
    """Agent API 集成测试"""

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
        response = client.post(
            "/api/v1/auth/login",
            data={"username": "admin", "password": "admin123"}
        )
        if response.status_code == 200:
            token = response.json().get("data", {}).get("access_token")
            return {"Authorization": f"Bearer {token}"}
        return {}

    @pytest.fixture
    def sample_agent(self, client, auth_headers):
        """创建一个测试 agent,测试结束后清理"""
        agent_data = {
            "name": f"test_agent_toggle_{uuid.uuid4().hex[:8]}",
            "description": "for is_active toggle test",
            "prompt_template": "You are a test assistant. {input}",
            "model_name": "gpt-4o",
            "temperature": 0,
        }
        resp = client.post("/api/v1/agents/", json=agent_data, headers=auth_headers)
        assert resp.status_code == 200
        agent = resp.json()["data"]
        yield agent
        # 清理:接受 200 (删了) 和 404 (已经被前一次失败 run 删了)。
        del_resp = client.delete(f"/api/v1/agents/{agent['id']}", headers=auth_headers)
        assert del_resp.status_code in (200, 404), f"cleanup failed: {del_resp.status_code} {del_resp.text}"

    def test_update_agent_toggle_is_active(self, client, auth_headers, sample_agent):
        """PUT /agents/{id} 单独改 is_active,其它字段保持"""
        agent_id = sample_agent["id"]
        original_name = sample_agent["name"]
        original_prompt = sample_agent["prompt_template"]

        # 关闭
        resp = client.put(
            f"/api/v1/agents/{agent_id}",
            json={"is_active": False},
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["code"] == 200
        assert body["data"]["is_active"] is False
        # 其它字段保持
        assert body["data"]["name"] == original_name
        assert body["data"]["prompt_template"] == original_prompt

        # 再打开
        resp = client.put(
            f"/api/v1/agents/{agent_id}",
            json={"is_active": True},
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["data"]["is_active"] is True
        assert body["data"]["name"] == original_name
        assert body["data"]["prompt_template"] == original_prompt

    @pytest.fixture
    def db_session(self):
        """M21: 直连 DB session(查 existing KB + 验证 bindings 用)。"""
        from lumen_core.database import SessionLocal
        session = SessionLocal()
        try:
            yield session
        finally:
            # rollback 兜底:test 跑挂时残留的 pending change 不会污染 dev DB
            session.rollback()
            session.close()

    def _existing_kbs(self, db_session, n):
        """M21 helper: 直接查 dev DB 上已存在的 n 个 KB,避免在 pytest
        上下文里新建 KB(新建的 KB 在 SQLAlchemy session + FastAPI TestClient
        + MySQL REPEATABLE READ 三方交互下不可靠,见 plan §Important notes #8)。
        """
        from lumen_models.knowledge import KnowledgeBase as KBModel
        return (
            db_session.query(KBModel)
            .filter(KBModel.tenant_id == 1, KBModel.status == "active")
            .order_by(KBModel.id)
            .limit(n)
            .all()
        )

    def test_create_agent_with_knowledge_base_ids(self, client, auth_headers, db_session):
        """M21: POST /agents/ 带 knowledge_base_ids → AgentResponse.knowledge_bases 有 2 个。"""
        kbs = self._existing_kbs(db_session, 2)
        assert len(kbs) >= 2, f"dev DB 至少需要 2 个 active KB,实际 {len(kbs)}"

        payload = {
            "name": f"agent-with-kbs-{uuid.uuid4().hex[:8]}",
            "prompt_template": "test",
            "model_name": "gpt-4o",
            "temperature": 0,
            "knowledge_base_ids": [kbs[0].id, kbs[1].id],
        }
        res = client.post("/api/v1/agents/", json=payload, headers=auth_headers)
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["code"] == 200
        assert len(body["data"]["knowledge_bases"]) == 2
        assert body["data"]["kb_retrieval_config"] == {"top_k": 3, "rrf_k": 30}

        # 清理 agent
        agent_id = body["data"]["id"]
        client.delete(f"/api/v1/agents/{agent_id}", headers=auth_headers)

    def test_update_agent_kb_diff(self, client, auth_headers, db_session):
        """M21: 创建绑 [k1, k2],update 发 [k2, k3] → 1 删,1 增,1 保留。"""
        kbs = self._existing_kbs(db_session, 3)
        assert len(kbs) >= 3, f"dev DB 至少需要 3 个 active KB,实际 {len(kbs)}"

        # 创建绑 [k1, k2]
        payload = {
            "name": f"agent-diff-{uuid.uuid4().hex[:8]}",
            "prompt_template": "test",
            "model_name": "gpt-4o",
            "temperature": 0,
            "knowledge_base_ids": [kbs[0].id, kbs[1].id],
        }
        res = client.post("/api/v1/agents/", json=payload, headers=auth_headers)
        assert res.status_code == 200, res.text
        agent_id = res.json()["data"]["id"]

        # update 改成 [k2, k3]
        update_payload = {"knowledge_base_ids": [kbs[1].id, kbs[2].id]}
        res = client.put(f"/api/v1/agents/{agent_id}", json=update_payload, headers=auth_headers)
        assert res.status_code == 200, res.text
        body = res.json()
        kb_ids = {kb["id"] for kb in body["data"]["knowledge_bases"]}
        assert kb_ids == {kbs[1].id, kbs[2].id}

        # 验证 DB: k1 已删,k2 仍在,k3 新增
        from lumen_core.database import SessionLocal
        verify_db = SessionLocal()
        try:
            from lumen_models.agent import AgentKnowledgeBase
            bindings = (
                verify_db.query(AgentKnowledgeBase)
                .filter_by(agent_id=agent_id)
                .all()
            )
            binding_kb_ids = {b.knowledge_base_id for b in bindings}
        finally:
            verify_db.close()
        assert binding_kb_ids == {kbs[1].id, kbs[2].id}

        # 清理
        client.delete(f"/api/v1/agents/{agent_id}", headers=auth_headers)

    def test_list_agents_handles_null_temperature(self, client, auth_headers):
        """GET /agents/ 必须能返回 temperature=NULL 的历史数据,不能 500。

        回归 bug:早期创建的 agent 走的是没强制 temperature 的路径,
        DB 里留下 temperature=NULL 的行(id 505-508 "客服调度 Manager"
        等)。AgentResponse.temperature 原本声明为 ``int``(非 Optional),
        Pydantic model_validate 拒绝 None → 整个 list endpoint 500 →
        前端 fetchAgents 静默吞掉 → chat 页 dropdown 只剩"默认"选项,
        看不到任何可切换的 Agent。
        修法:AgentBase.temperature 改成 ``Optional[int] = 0``。
        """
        from sqlalchemy import text

        from lumen_core.database import SessionLocal
        from lumen_models.agent import Agent

        db = SessionLocal()
        agent = None
        try:
            # 直接 ORM insert 拿到 id。注意:SQLAlchemy 的
            # ``Column(Integer, default=0)`` 在 flush 时会把 None 转成 0,
            # 所以光 set temperature=None 不够,必须用 raw SQL 强制写 NULL
            # 才能复现早期那 4 行真实脏数据的状态。
            agent = Agent(
                name=f"null_temp_agent_{uuid.uuid4().hex[:8]}",
                prompt_template="p",
                model_name="qwen2.5:7b",
                tenant_id=1,
                is_active=True,
            )
            db.add(agent)
            db.commit()
            db.refresh(agent)
            null_temp_id = agent.id
            # raw UPDATE 把 temperature 强制置 NULL,模拟历史脏数据
            db.execute(
                text("UPDATE agents SET temperature = NULL WHERE id = :id"),
                {"id": null_temp_id},
            )
            db.commit()
        finally:
            db.close()

        try:
            # 触发 list endpoint。修复前会 500(ValidationError),
            # 修复后必须 200 且这条 agent 出现在 data[] 里。
            # page_size 故意给大(tenant 1 的 agents 表是 dev DB
            # 共享,累积到 2000+ 行,默认 10 不够;新插入的 NULL-temp
            # agent ID 总是最大,list endpoint 没 order_by 按 ID ASC
            # 排,新行落到 page_size 之外会被截断),page_size=5000
            # 覆盖当前 dev DB 上限(2026-06-14 实测 2165 行),确保
            # NULL-temp agent 落在 [0:page_size] 切片里。
            resp = client.get(
                "/api/v1/agents/?page=1&page_size=5000",
                headers=auth_headers,
            )
            assert resp.status_code == 200, (
                f"list endpoint 500 on NULL temperature: {resp.text}"
            )
            body = resp.json()
            assert body["code"] == 200
            ids = [a["id"] for a in body["data"]]
            assert null_temp_id in ids, (
                f"NULL-temp agent {null_temp_id} 应该在列表里,"
                f"total={body['total']}, data len={len(body['data'])},"
                f"first ids={ids[:5]}..."
            )
            null_temp_row = next(a for a in body["data"] if a["id"] == null_temp_id)
            # 修复后 Pydantic 接受 None,JSON 序列化成 null
            assert null_temp_row["temperature"] is None
        finally:
            db = SessionLocal()
            try:
                row = db.query(Agent).filter(Agent.id == null_temp_id).first()
                if row is not None:
                    db.delete(row)
                    db.commit()
            except Exception:
                db.rollback()
            finally:
                db.close()
