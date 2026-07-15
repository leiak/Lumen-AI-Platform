"""Tests for admin /admin/skills API (M17)."""
import pytest
from fastapi.testclient import TestClient

from lumen_main import app


@pytest.fixture
def client():
    return TestClient(app)


def _make_skill(type: str = "prompt", type_config: dict = None, content: str = None, name: str = None):
    from lumen_core.database import SessionLocal
    from lumen_models.skill_marketplace import SkillMarketplace
    import uuid
    db = SessionLocal()
    s = SkillMarketplace(
        name=name or f"admin-test-{type}-{uuid.uuid4().hex[:6]}",
        category="code",
        content=content,
        type=type,
        type_config=type_config,
        is_verified=1,
    )
    db.add(s); db.commit(); db.refresh(s)
    db.close()
    return s


@pytest.fixture
def admin_user():
    """Create a throwaway superuser (is_superuser=True) for admin tests."""
    from lumen_core.database import SessionLocal
    from lumen_core.security import get_password_hash
    from lumen_models.user import User
    from lumen_services.auth_service import create_access_token
    import uuid
    db = SessionLocal()
    suffix = uuid.uuid4().hex[:8]
    u = User(
        username=f"admin_test_{suffix}",
        email=f"admin_{suffix}@test.local",
        hashed_password=get_password_hash("x"),
        tenant_id=1,
        is_active=True,
        is_superuser=True,
    )
    db.add(u); db.commit(); db.refresh(u)
    user_id = u.id
    db.close()
    token = create_access_token(data={"sub": u.username, "user_id": user_id})
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def regular_user():
    """Non-admin user for negative auth tests."""
    from lumen_core.database import SessionLocal
    from lumen_core.security import get_password_hash
    from lumen_models.user import User
    from lumen_services.auth_service import create_access_token
    import uuid
    db = SessionLocal()
    suffix = uuid.uuid4().hex[:8]
    u = User(
        username=f"regular_test_{suffix}",
        email=f"regular_{suffix}@test.local",
        hashed_password=get_password_hash("x"),
        tenant_id=1,
        is_active=True,
        is_superuser=False,
    )
    db.add(u); db.commit(); db.refresh(u)
    user_id = u.id
    db.close()
    token = create_access_token(data={"sub": u.username, "user_id": user_id})
    return {"Authorization": f"Bearer {token}"}


def test_admin_create_skill_prompt(client, admin_user):
    r = client.post("/api/v1/admin/skills/", json={
        "name": "test-prompt-m17", "category": "code", "type": "prompt",
        "content": "be nice", "version": "1.0.0",
    }, headers=admin_user)
    assert r.status_code == 200
    item = r.json()["data"]
    assert item["type"] == "prompt"
    assert item["content"] == "be nice"


def test_admin_create_skill_kb(client, admin_user):
    r = client.post("/api/v1/admin/skills/", json={
        "name": "test-kb-m17", "category": "code", "type": "knowledge_retrieval",
        "type_config": {"kb_id": 1, "top_k": 3, "score_threshold": 0.5,
                        "query_template": "What is {{topic}}?"},
    }, headers=admin_user)
    assert r.status_code == 200
    assert r.json()["data"]["type"] == "knowledge_retrieval"


def test_admin_create_skill_mcp(client, admin_user):
    r = client.post("/api/v1/admin/skills/", json={
        "name": "test-mcp-m17", "category": "data", "type": "tool",
        "type_config": {"mcp_server": "demo-mcp", "tool_name": "list_workflows"},
    }, headers=admin_user)
    assert r.status_code == 200
    assert r.json()["data"]["type"] == "tool"


def test_admin_create_skill_rejects_mismatched_type_config(client, admin_user):
    """type=script with type_config missing required 'code' → 422."""
    r = client.post("/api/v1/admin/skills/", json={
        "name": "bad-m17", "category": "code", "type": "script",
        "type_config": {"timeout": 5},  # missing 'code'
    }, headers=admin_user)
    assert r.status_code == 422


def test_admin_create_skill_rejects_unknown_type(client, admin_user):
    r = client.post("/api/v1/admin/skills/", json={
        "name": "bad-type-m17", "category": "code", "type": "future_type_xyz",
    }, headers=admin_user)
    assert r.status_code == 422


def test_admin_create_skill_rejects_non_admin(client, regular_user):
    r = client.post("/api/v1/admin/skills/", json={
        "name": "x", "category": "code", "type": "prompt", "content": "x",
    }, headers=regular_user)
    assert r.status_code == 403


def test_admin_list_skills_filtered_by_type(client, admin_user):
    # Create at least one script and one prompt
    s_script = _make_skill(type="script", type_config={"code": "x", "timeout": 5}, name="list-script-m17-x")
    s_prompt = _make_skill(type="prompt", content="x", name="list-prompt-m17-x")
    r = client.get("/api/v1/admin/skills/?type=script&page_size=200", headers=admin_user)
    assert r.status_code == 200
    data = r.json()["data"]
    # All returned items must be type=script
    assert all(item["type"] == "script" for item in data), \
        f"non-script leaked: {[i['type'] for i in data if i['type'] != 'script']}"
    # The new script we created must be present
    names = [item["name"] for item in data]
    assert s_script.name in names
    # The prompt we created must NOT be in the script list
    assert s_prompt.name not in names


def test_admin_update_skill(client, admin_user):
    s = _make_skill(type="prompt", content="old", name="upd-1-m17")
    r = client.put(f"/api/v1/admin/skills/{s.id}", json={
        "name": "upd-1-m17-renamed", "category": "code", "type": "prompt",
        "content": "new content", "version": "1.0.0",
    }, headers=admin_user)
    assert r.status_code == 200
    assert r.json()["data"]["name"] == "upd-1-m17-renamed"
    assert r.json()["data"]["content"] == "new content"


def test_admin_delete_skill_in_use_409(client, admin_user):
    from lumen_core.database import SessionLocal
    from lumen_models.skill_marketplace import InstalledSkill
    s = _make_skill(type="prompt", content="x", name="del-in-use-m17")
    db = SessionLocal()
    db.add(InstalledSkill(tenant_id=1, marketplace_skill_id=s.id, status="active"))
    db.commit()
    db.close()
    r = client.delete(f"/api/v1/admin/skills/{s.id}", headers=admin_user)
    assert r.status_code == 409


def test_admin_delete_skill_not_installed(client, admin_user):
    s = _make_skill(type="prompt", content="x", name="del-ok-m17")
    r = client.delete(f"/api/v1/admin/skills/{s.id}", headers=admin_user)
    assert r.status_code == 200


def test_admin_test_run_endpoint(client, admin_user):
    s = _make_skill(type="script", type_config={
        "code": "def main(x): return x * 2", "timeout": 5,
    }, name="tr-test-m17")
    r = client.post(f"/api/v1/admin/skills/{s.id}/test-run", json={
        "input_args": {"x": 7}
    }, headers=admin_user)
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["type"] == "script"
    assert data["result"] == 14
    assert data["error"] is None
