"""PUT /api/v1/agents/{id}/model — admin-only 模型切换 endpoint。

Dev 复现: agent 引用的 model_name 对应的 ModelConfig row API key 死了
(例:MiniMax 401 → workflow Agent 节点 60s 超时),admin 需要快速切到
另一个 active 的 ModelConfig 恢复流程。Endpoint 通过 model_config_id 或
model_name 任一字段反查 + 校验 active + base_url + api_key 完备后才写入。

测试覆盖:
  1. happy path (model_config_id) — admin 切到 active 配置,200 + changed=True
  2. happy path (model_name 字符串) — 反查命中,200 + changed=True
  3. agent not found — 404
  4. model_config not found — 404
  5. model_config is_active=False — 422 (防止切到禁用配置)
  6. 互斥 (model_config_id + model_name) — 422 (AgentUpdateModel 校验)
  7. 都空 — 422
  8. 非 admin → 403 (require_admin 拦截)
  9. 不真正改 DB 时 (new == old) — changed=False,不 commit 副作用

执行模式: pytest 默认 fixture 链(client / db_session / tmp_user 已 is_superuser)
足够覆盖大部分 case;非 admin 用例直接 new 一个 User row 注入 override。
"""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from lumen_main import app
    return TestClient(app)


@pytest.fixture
def db_session():
    """Provide a SessionLocal() that's auto-closed after the test."""
    from lumen_core.database import SessionLocal
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _override_with(user):
    """Inject current_user 走 dependency_overrides。返回 teardown 函数。"""
    from lumen_api.v1.auth import get_current_user, require_admin
    from lumen_main import app

    def _stub():
        return user
    app.dependency_overrides[get_current_user] = _stub
    # require_admin 也得 override,不然它内部调 get_current_user 会被 auth 守门
    # (oauth2_scheme 把 Authorization header 当 form 给 strip 掉 → 401)
    app.dependency_overrides[require_admin] = _stub

    def _teardown():
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(require_admin, None)
    return _teardown


def _make_user(db, *, tenant_id, is_superuser=False):
    """Create + commit a user suitable for API tests。"""
    import uuid
    from lumen_core.security import get_password_hash
    from lumen_models.user import User

    suffix = uuid.uuid4().hex[:8]
    u = User(
        username=f"agent_model_test_{suffix}",
        email=f"agent_model_{suffix}@test.local",
        hashed_password=get_password_hash("x"),
        tenant_id=tenant_id,
        is_active=True,
        is_superuser=is_superuser,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _make_agent(db, *, tenant_id, model_name):
    """Create + commit an Agent row used as endpoint target。"""
    import uuid
    from lumen_models.agent import Agent

    suffix = uuid.uuid4().hex[:8]
    a = Agent(
        name=f"agent_model_test_{suffix}",
        description=None,
        prompt_template="hi",
        model_name=model_name,
        temperature=0,
        tenant_id=tenant_id,
        is_active=True,
        memory_policy="sliding_window",
        memory_window_size=20,
        memory_max_tokens=4000,
        memory_compression=False,
        tool_choice="auto",
        tool_choice_required=False,
        allowed_tools=[],
    )
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


def _make_model_config(db, *, name, is_active=True, base_url="http://x", api_key="k"):
    """Create + commit a ModelConfig row。"""
    import uuid
    from lumen_models.model_config import ModelConfig

    suffix = uuid.uuid4().hex[:8]
    m = ModelConfig(
        name=f"model_test_{name}_{suffix}",
        model_type="ollama",
        model_name=f"model-name-{suffix}",
        base_url=base_url,
        api_key=api_key,
        temperature=0.7,
        max_tokens=4096,
        timeout=120,
        is_default=False,
        is_active=is_active,
        is_chat=True,
        is_embedding=False,
    )
    db.add(m)
    db.commit()
    db.refresh(m)
    return m


def _teardown(db, *rows):
    """Hard-delete helper,失败时 rollback 不抛(避免 teardown 抛掩盖真实失败)。"""
    for r in rows:
        try:
            db.delete(r)
            db.commit()
        except Exception:
            db.rollback()


# -------- happy paths ---------------------------------------------------------

def test_update_agent_model_by_id_happy_path(client, db_session):
    """Admin 切 agent 到 active ModelConfig → 200 + changed=True + agent.model_name 已写库。"""
    from lumen_core.database import SessionLocal

    tenant_id = 1
    target_mc = _make_model_config(db_session, name="happy", base_url="http://localhost:11434", api_key="k")
    agent = _make_agent(db_session, tenant_id=tenant_id, model_name="some-old-model")

    # admin 跑 override
    admin = _make_user(db_session, tenant_id=tenant_id, is_superuser=True)

    teardown = _override_with(admin)
    try:
        r = client.put(
            f"/api/v1/agents/{agent.id}/model",
            json={"model_config_id": target_mc.id, "reason": "test happy path"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["code"] == 200
        data = body["data"]
        assert data["changed"] is True
        assert data["old_model_name"] == "some-old-model"
        assert data["new_model_name"] == target_mc.model_name
        assert data["reason"] == "test happy path"
        # 确认 DB 真的改了
        fresh_db = SessionLocal()
        try:
            fresh = fresh_db.query(type(agent)).filter(type(agent).id == agent.id).first()
            assert fresh.model_name == target_mc.model_name
        finally:
            fresh_db.close()
    finally:
        _teardown(db_session, target_mc, agent, admin)
        teardown()


def test_update_agent_model_by_name_happy_path(client, db_session):
    """传 model_name 字符串也能反查命中 active ModelConfig → 200。"""
    from lumen_core.database import SessionLocal

    tenant_id = 1
    target_mc = _make_model_config(db_session, name="byname")
    agent = _make_agent(db_session, tenant_id=tenant_id, model_name="another-old")
    admin = _make_user(db_session, tenant_id=tenant_id, is_superuser=True)

    teardown = _override_with(admin)
    try:
        r = client.put(
            f"/api/v1/agents/{agent.id}/model",
            json={"model_name": target_mc.model_name},
        )
        assert r.status_code == 200, r.text
        body = r.json()["data"]
        assert body["changed"] is True
        assert body["new_model_name"] == target_mc.model_name
    finally:
        _teardown(db_session, target_mc, agent, admin)
        teardown()


def test_update_agent_model_no_change(client, db_session):
    """new == old → changed=False,不真正 commit 副作用。"""
    tenant_id = 1
    target_mc = _make_model_config(db_session, name="nochange")
    # agent 一开始就用 target_mc.model_name
    agent = _make_agent(db_session, tenant_id=tenant_id, model_name=target_mc.model_name)
    admin = _make_user(db_session, tenant_id=tenant_id, is_superuser=True)

    teardown = _override_with(admin)
    try:
        r = client.put(
            f"/api/v1/agents/{agent.id}/model",
            json={"model_config_id": target_mc.id},
        )
        assert r.status_code == 200, r.text
        body = r.json()["data"]
        assert body["changed"] is False
        assert body["old_model_name"] == body["new_model_name"] == target_mc.model_name
    finally:
        _teardown(db_session, target_mc, agent, admin)
        teardown()


# -------- error cases --------------------------------------------------------

def test_update_agent_model_agent_not_found(client, db_session):
    """agent 不存在 → 404 (即便 admin)。"""
    target_mc = _make_model_config(db_session, name="agent404")
    admin = _make_user(db_session, tenant_id=1, is_superuser=True)

    teardown = _override_with(admin)
    try:
        r = client.put(
            "/api/v1/agents/999999/model",
            json={"model_config_id": target_mc.id},
        )
        assert r.status_code == 404
        assert "999999" in r.json()["detail"]
    finally:
        _teardown(db_session, target_mc, admin)
        teardown()


def test_update_agent_model_config_not_found(client, db_session):
    """model_config_id 不存在 → 404。"""
    agent = _make_agent(db_session, tenant_id=1, model_name="x")
    admin = _make_user(db_session, tenant_id=1, is_superuser=True)

    teardown = _override_with(admin)
    try:
        r = client.put(
            f"/api/v1/agents/{agent.id}/model",
            json={"model_config_id": 999999},
        )
        assert r.status_code == 404
        assert "999999" in r.json()["detail"]
    finally:
        _teardown(db_session, agent, admin)
        teardown()


def test_update_agent_model_config_inactive_422(client, db_session):
    """is_active=False 的 model_config → 422,不允许切到禁用配置。"""
    target_mc = _make_model_config(db_session, name="inactive", is_active=False)
    agent = _make_agent(db_session, tenant_id=1, model_name="x")
    admin = _make_user(db_session, tenant_id=1, is_superuser=True)

    teardown = _override_with(admin)
    try:
        r = client.put(
            f"/api/v1/agents/{agent.id}/model",
            json={"model_config_id": target_mc.id},
        )
        assert r.status_code == 422
        assert "is_active=False" in r.json()["detail"] or "禁用" in r.json()["detail"]
    finally:
        _teardown(db_session, target_mc, agent, admin)
        teardown()


def test_update_agent_model_mutually_exclusive_422(client, db_session):
    """同时给 model_config_id + model_name → 422(AgentUpdateModel 互斥校验)。"""
    agent = _make_agent(db_session, tenant_id=1, model_name="x")
    admin = _make_user(db_session, tenant_id=1, is_superuser=True)

    teardown = _override_with(admin)
    try:
        r = client.put(
            f"/api/v1/agents/{agent.id}/model",
            json={"model_config_id": 1, "model_name": "qwen2.5:7b"},
        )
        assert r.status_code == 422
        detail = r.json()["detail"]
        # FastAPI 把 Pydantic 错误塞进 detail 数组
        msg = str(detail) if isinstance(detail, str) else str(detail[0].get("msg", ""))
        assert "互斥" in msg
    finally:
        _teardown(db_session, agent, admin)
        teardown()


def test_update_agent_model_empty_422(client, db_session):
    """都不传 → 422(Pydantic 至少一个校验)。"""
    agent = _make_agent(db_session, tenant_id=1, model_name="x")
    admin = _make_user(db_session, tenant_id=1, is_superuser=True)

    teardown = _override_with(admin)
    try:
        r = client.put(
            f"/api/v1/agents/{agent.id}/model",
            json={},
        )
        assert r.status_code == 422
        msg = str(r.json()["detail"][0].get("msg", ""))
        assert "至少传一个" in msg
    finally:
        _teardown(db_session, agent, admin)
        teardown()


def test_update_agent_model_non_admin_403(client, db_session):
    """非 superuser 调此 endpoint → 403(require_admin 守门)。

    注意:只 override get_current_user,不要 override require_admin,
    让 require_admin 内部真实跑 is_superuser 检查,否则会绕过 403。
    """
    from lumen_api.v1.auth import get_current_user
    from lumen_main import app

    agent = _make_agent(db_session, tenant_id=1, model_name="x")
    target_mc = _make_model_config(db_session, name="nonadmin")
    # 普通 user,is_superuser=False
    normal = _make_user(db_session, tenant_id=1, is_superuser=False)

    app.dependency_overrides[get_current_user] = lambda: normal
    try:
        r = client.put(
            f"/api/v1/agents/{agent.id}/model",
            json={"model_config_id": target_mc.id},
        )
        assert r.status_code == 403, r.text
        assert "管理员" in r.json()["detail"]
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        _teardown(db_session, agent, target_mc, normal)