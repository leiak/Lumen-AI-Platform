"""Tests for SkillMarketplace detail endpoint + content field exposure.

Covers:
  - GET /skills/market/{id} returns full content
  - GET /skills/market/  (list) includes content per item
  - GET /skills/market/installed includes content per item
  - GET /skills/market/{id} 404 for missing skill
  - GET /skills/market/{id} requires auth (401)
  - GET /skills/market/{id}/install returns 405 (route ordering)
  - GET /skills/market/categories still works
  - content=NULL row is handled gracefully
  - is_installed flag correctly reflects tenant state
"""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from lumen_main import app
    return TestClient(app)


@pytest.fixture
def auth_header(tmp_user):
    from lumen_services.auth_service import create_access_token
    token = create_access_token(
        data={"sub": tmp_user.username, "user_id": tmp_user.id}
    )
    return {"Authorization": f"Bearer {token}"}


def _make_marketplace_skill(db, *, name="test-skill", category="code",
                            content="You are a test skill.", version="1.0.0",
                            is_verified=1, downloads=0, rating="4.5"):
    from lumen_models.skill_marketplace import SkillMarketplace
    s = SkillMarketplace(
        name=name, category=category, description=f"desc for {name}",
        content=content, version=version, provider="TestOrg",
        downloads=downloads, rating=rating, is_verified=is_verified,
    )
    db.add(s); db.commit(); db.refresh(s)
    return s


def test_list_marketplace_includes_content(client, auth_header, tmp_user):
    """list endpoint exposes content field on every item."""
    from lumen_core.database import SessionLocal
    from lumen_models.skill_marketplace import SkillMarketplace
    db = SessionLocal()
    created_ids = []
    try:
        s1 = _make_marketplace_skill(db, name="l1", content="prompt A")
        s2 = _make_marketplace_skill(db, name="l2", content="prompt B")
        created_ids = [s1.id, s2.id]

        # Page through the entire listing — the dev DB accumulates
        # pre-existing marketplace skills from other test runs (e.g.
        # 'doubler-*' / 'list-prompt-m17-x' / 'del-in-use-m17') that
        # can push our fixture rows past page_size=10. Walk all
        # pages so we find l1 / l2 regardless of how much noise is
        # already in the table.
        all_items: list = []
        page = 1
        page_size = 50  # bigger than the 5+ skills we expect in dev
        while True:
            r = client.get(
                f"/api/v1/skills/market/?page={page}&page_size={page_size}",
                headers=auth_header,
            )
            assert r.status_code == 200
            items = r.json()["data"]
            all_items.extend(items)
            if len(items) < page_size:
                break
            page += 1

        by_name = {it["name"]: it for it in all_items}
        assert "l1" in by_name, (
            f"l1 not found in any page; got names: {sorted(by_name)}"
        )
        assert "l2" in by_name
        assert by_name["l1"]["content"] == "prompt A"
        assert by_name["l2"]["content"] == "prompt B"
    finally:
        # Cleanup so a re-run starts clean and we don't leak rows
        # into the dev DB (which the next test_list_marketplace
        # call would see, causing future flake).
        if created_ids:
            db.query(SkillMarketplace).filter(
                SkillMarketplace.id.in_(created_ids)
            ).delete(synchronize_session=False)
            db.commit()
        db.close()


def test_installed_list_includes_content(client, auth_header, tmp_user):
    """installed list endpoint also exposes content per item."""
    from lumen_core.database import SessionLocal
    from lumen_models.skill_marketplace import InstalledSkill
    db = SessionLocal()
    created_ms = None
    created_inst = None
    try:
        ms = _make_marketplace_skill(db, name="i1", content="installed-prompt")
        created_ms = ms
        # Manually create an InstalledSkill row to make the skill show up
        # in the installed list. (We don't exercise the install endpoint here
        # because that path is already covered elsewhere.)
        installed = InstalledSkill(
            tenant_id=tmp_user.tenant_id,
            marketplace_skill_id=ms.id,
            status="active",
        )
        db.add(installed); db.commit()
        created_inst = installed

        # Page through — the dev DB accumulates pre-existing
        # 'del-in-use-*' / 'doubler-*' / 'test-prompt-*' / 'test-script-*'
        # / 'test-http-*' skills from other tests. Walking all pages
        # ensures we find our 'i1' regardless of how much noise is
        # already in the table.
        all_items: list = []
        page = 1
        page_size = 50
        while True:
            r = client.get(
                f"/api/v1/skills/market/installed?page={page}&page_size={page_size}",
                headers=auth_header,
            )
            assert r.status_code == 200
            items = r.json()["data"]
            all_items.extend(items)
            if len(items) < page_size:
                break
            page += 1
        names = [it["name"] for it in all_items]
        assert "i1" in names, f"i1 not found in any page; got {names}"
        item = next(it for it in all_items if it["name"] == "i1")
        assert item["content"] == "installed-prompt"
    finally:
        if created_inst is not None:
            db.delete(created_inst); db.commit()
        if created_ms is not None:
            db.delete(created_ms); db.commit()
        db.close()


def test_get_marketplace_skill_returns_200_with_content(client, auth_header, tmp_user):
    """GET /{id} returns full content for a known skill."""
    from lumen_core.database import SessionLocal
    db = SessionLocal()
    created_ms = None
    try:
        ms = _make_marketplace_skill(
            db, name="detail-target", content="You are a code optimization expert."
        )
        created_ms = ms
        r = client.get(f"/api/v1/skills/market/{ms.id}", headers=auth_header)
        assert r.status_code == 200
        body = r.json()
        assert body["code"] == 200
        item = body["data"]
        assert item["id"] == ms.id
        assert item["name"] == "detail-target"
        assert item["content"] == "You are a code optimization expert."
        assert item["is_installed"] is False
        assert item["skill_id"] is None
    finally:
        if created_ms is not None:
            db.delete(created_ms); db.commit()
        db.close()


def test_get_marketplace_skill_not_installed_flag(client, auth_header, tmp_user):
    """Uninstalled skill: detail returns is_installed=False and skill_id=None."""
    from lumen_core.database import SessionLocal
    db = SessionLocal()
    created_ms = None
    try:
        ms = _make_marketplace_skill(db, name="not-installed-uniq", content="x")
        created_ms = ms
        r = client.get(f"/api/v1/skills/market/{ms.id}", headers=auth_header)
        assert r.status_code == 200
        item = r.json()["data"]
        assert item["is_installed"] is False
        assert item["skill_id"] is None
    finally:
        if created_ms is not None:
            db.delete(created_ms); db.commit()
        db.close()


def test_get_marketplace_skill_installed_flag(client, auth_header, tmp_user):
    """After install, GET /{id} reports is_installed=True and skill_id set."""
    from lumen_core.database import SessionLocal
    from lumen_models.skill_marketplace import InstalledSkill
    from lumen_models.skill import Skill
    import uuid
    db = SessionLocal()
    created_ms = None
    created_sk = None
    created_inst = None
    try:
        # Use unique name to avoid UNIQUE constraint collision on skills.name
        suffix = uuid.uuid4().hex[:8]
        ms = _make_marketplace_skill(db, name=f"to-install-{suffix}", content="c")
        created_ms = ms
        sk = Skill(
            name=f"to-install-{suffix}_skill",
            description="x", category="code", content="c",
            is_builtin=False, is_active=True, version="1.0.0",
        )
        db.add(sk); db.commit(); db.refresh(sk)
        created_sk = sk
        installed = InstalledSkill(
            tenant_id=tmp_user.tenant_id,
            marketplace_skill_id=ms.id,
            skill_id=sk.id,
            status="active",
        )
        db.add(installed); db.commit()
        created_inst = installed

        r = client.get(f"/api/v1/skills/market/{ms.id}", headers=auth_header)
        assert r.status_code == 200
        item = r.json()["data"]
        assert item["is_installed"] is True
        assert item["skill_id"] == sk.id
    finally:
        if created_inst is not None:
            db.delete(created_inst); db.commit()
        if created_sk is not None:
            db.delete(created_sk); db.commit()
        if created_ms is not None:
            db.delete(created_ms); db.commit()
        db.close()


def test_get_marketplace_skill_404(client, auth_header, tmp_user):
    """GET /{id} for non-existent skill returns 404."""
    r = client.get("/api/v1/skills/market/9999999", headers=auth_header)
    assert r.status_code == 404
    assert "not found" in r.json()["detail"].lower()


def test_get_marketplace_skill_requires_auth(client, tmp_user):
    """GET /{id} without auth header returns 401."""
    r = client.get("/api/v1/skills/market/1")
    assert r.status_code == 401


def test_skill_with_null_content_returns_null(client, auth_header, tmp_user):
    """A marketplace row with content=NULL returns content=null, not 500."""
    from lumen_core.database import SessionLocal
    from sqlalchemy import text
    db = SessionLocal()
    created_ms = None
    try:
        ms = _make_marketplace_skill(db, name="null-content-uniq", content="placeholder")
        created_ms = ms
        # Manually null out content to simulate a legacy / hand-inserted row
        db.execute(text(
            "UPDATE skill_marketplace SET content = NULL WHERE id = :id"
        ), {"id": ms.id})
        db.commit()

        r = client.get(f"/api/v1/skills/market/{ms.id}", headers=auth_header)
        assert r.status_code == 200
        assert r.json()["data"]["content"] is None
    finally:
        if created_ms is not None:
            db.delete(created_ms); db.commit()
        db.close()


def test_get_install_path_returns_405(client, auth_header, tmp_user):
    """GET /{id}/install returns 405 (method not allowed), not 404.

    Verifies the new GET /{skill_id} route does not shadow POST /{id}/install
    — FastAPI matches by method first, then by path-segment count, so a GET
    on a POST-only path should yield 405.
    """
    r = client.get("/api/v1/skills/market/1/install", headers=auth_header)
    assert r.status_code == 405


def test_get_categories_path_unaffected(client, auth_header, tmp_user):
    """GET /categories still works (literal path not shadowed by /{skill_id})."""
    r = client.get("/api/v1/skills/market/categories", headers=auth_header)
    assert r.status_code == 200
    assert r.json()["code"] == 200
    assert isinstance(r.json()["data"], list)
