"""Tests for POST /api/v1/skills/market/batch-uninstall (M20).

Spec: docs/superpowers/specs/2026-06-11-skill-installed-page-fixes-design.md §3.1
"""
import pytest
import uuid
from unittest.mock import patch
from fastapi.testclient import TestClient


# —— Fixtures (module-level helpers, not pytest fixtures) ——

def _make_client():
    from lumen_main import app
    return TestClient(app)


def _make_auth_header(user):
    from lumen_services.auth_service import create_access_token
    token = create_access_token(
        data={"sub": user.username, "user_id": user.id}
    )
    return {"Authorization": f"Bearer {token}"}


def _make_marketplace_skill(db, *, name=None, category="code", content="x",
                            version="1.0.0", is_verified=1, downloads=0):
    from lumen_models.skill_marketplace import SkillMarketplace
    s = SkillMarketplace(
        name=name or f"mkt-{uuid.uuid4().hex[:8]}",
        category=category,
        description="d",
        content=content,
        version=version,
        provider="TestOrg",
        downloads=downloads,
        rating="4.5",
        is_verified=is_verified,
    )
    db.add(s); db.commit(); db.refresh(s)
    return s


def _make_installed(db, *, tenant_id, marketplace_skill_id, skill_id=None):
    from lumen_models.skill_marketplace import InstalledSkill
    inst = InstalledSkill(
        tenant_id=tenant_id,
        marketplace_skill_id=marketplace_skill_id,
        skill_id=skill_id,
        status="active",
    )
    db.add(inst); db.commit(); db.refresh(inst)
    return inst


def _make_tenant(db, *, code=None, name=None):
    from lumen_models.tenant import Tenant
    suffix = uuid.uuid4().hex[:8]
    t = Tenant(
        name=name or f"Test Tenant {suffix}",
        code=code or f"test-{suffix}",
        status=True,
        max_users=10,
    )
    db.add(t); db.commit(); db.refresh(t)
    return t


# —— Pytest fixtures ——

@pytest.fixture
def client():
    return _make_client()


@pytest.fixture
def auth_header(tmp_user):
    return _make_auth_header(tmp_user)


@pytest.fixture
def two_tenants_with_installs(tmp_user):
    """tmp_user is in tenant 1. Create tenant 2 + 3 InstalledSkill rows per tenant.

    Yields dict with:
      - t1_id, t2_id
      - t1_install_ids: list of InstalledSkill.id (tenant 1)
      - t2_install_ids: list of InstalledSkill.id (tenant 2)
      - mkt_ids_t1, mkt_ids_t2: list of marketplace_skill_id per tenant
    Cleanup removes the InstalledSkill, Skill, SkillMarketplace, and Tenant 2.
    """
    from lumen_core.database import SessionLocal
    db = SessionLocal()
    t1_id = tmp_user.tenant_id
    t2 = _make_tenant(db)
    t2_id = t2.id
    try:
        # 3 marketplace skills for t1, 3 for t2 (all unique)
        mkt_t1 = [_make_marketplace_skill(db) for _ in range(3)]
        mkt_t2 = [_make_marketplace_skill(db) for _ in range(3)]
        # Create InstalledSkill rows directly (skip the install endpoint)
        inst_t1 = [
            _make_installed(db, tenant_id=t1_id, marketplace_skill_id=m.id)
            for m in mkt_t1
        ]
        inst_t2 = [
            _make_installed(db, tenant_id=t2_id, marketplace_skill_id=m.id)
            for m in mkt_t2
        ]
        yield {
            "t1_id": t1_id,
            "t2_id": t2_id,
            "t1_install_ids": [i.id for i in inst_t1],
            "t2_install_ids": [i.id for i in inst_t2],
            "mkt_ids_t1": [m.id for m in mkt_t1],
            "mkt_ids_t2": [m.id for m in mkt_t2],
            "mkt_skills_t1": mkt_t1,
            "mkt_skills_t2": mkt_t2,
            "inst_t1": inst_t1,
            "inst_t2": inst_t2,
        }
    finally:
        try:
            # Delete InstalledSkill rows first (FK)
            for i in inst_t1: db.delete(i)
            for i in inst_t2: db.delete(i)
            db.commit()
            # Delete marketplace skills
            for m in mkt_t1: db.delete(m)
            for m in mkt_t2: db.delete(m)
            db.commit()
            # Delete tenant 2 (tenant 1 is the default, leave it)
            db.delete(t2)
            db.commit()
        except Exception:
            db.rollback()
        finally:
            db.close()


# —— Tests ——

def test_batch_uninstall_all_succeed(client, auth_header, two_tenants_with_installs):
    """All 3 of caller's tenant's ids exist → succeeded_count=3, failed=[]"""
    mkt_ids_t1 = two_tenants_with_installs["mkt_ids_t1"]
    r = client.post(
        "/api/v1/skills/market/batch-uninstall",
        json={"ids": mkt_ids_t1},
        headers=auth_header,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["code"] == 200
    assert body["data"]["succeeded_count"] == 3
    assert body["data"]["failed"] == []


def test_batch_uninstall_partial_failure(client, auth_header, two_tenants_with_installs):
    """3 valid + 2 nonexistent ids → succeeded=3, failed has 2 entries with reason"""
    mkt_ids_t1 = two_tenants_with_installs["mkt_ids_t1"]
    nonexistent = [999_001, 999_002]
    payload_ids = mkt_ids_t1 + nonexistent
    r = client.post(
        "/api/v1/skills/market/batch-uninstall",
        json={"ids": payload_ids},
        headers=auth_header,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["data"]["succeeded_count"] == 3
    failed = body["data"]["failed"]
    assert len(failed) == 2
    assert {f["id"] for f in failed} == set(nonexistent)
    assert all(f["reason"] == "not installed" for f in failed)


def test_batch_uninstall_cross_tenant_isolation(client, auth_header, two_tenants_with_installs):
    """Tenant 1 caller cannot uninstall tenant 2's installs (they all fail)."""
    from lumen_core.database import SessionLocal
    from lumen_models.skill_marketplace import InstalledSkill
    mkt_ids_t2 = two_tenants_with_installs["mkt_ids_t2"]
    t2_id = two_tenants_with_installs["t2_id"]
    r = client.post(
        "/api/v1/skills/market/batch-uninstall",
        json={"ids": mkt_ids_t2},
        headers=auth_header,
    )
    assert r.status_code == 200
    body = r.json()
    # None of t2's ids belong to t1 → all fail
    assert body["data"]["succeeded_count"] == 0
    assert len(body["data"]["failed"]) == 3
    # t2's InstalledSkill rows must still be in DB
    db = SessionLocal()
    try:
        remaining_t2 = (
            db.query(InstalledSkill)
            .filter(InstalledSkill.tenant_id == t2_id)
            .count()
        )
        assert remaining_t2 == 3, f"t2's installs must NOT be deleted; found {remaining_t2}"
    finally:
        db.close()


def test_batch_uninstall_empty_ids(client, auth_header):
    """Empty ids list → succeeded=0, failed=[], 200 OK"""
    r = client.post(
        "/api/v1/skills/market/batch-uninstall",
        json={"ids": []},
        headers=auth_header,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["data"]["succeeded_count"] == 0
    assert body["data"]["failed"] == []


def test_batch_uninstall_does_not_decrement_downloads(
    client, auth_header, two_tenants_with_installs
):
    """Uninstall must NOT decrement SkillMarketplace.downloads (matches single endpoint)."""
    from lumen_core.database import SessionLocal
    from lumen_models.skill_marketplace import SkillMarketplace
    mkt_id = two_tenants_with_installs["mkt_ids_t1"][0]
    db = SessionLocal()
    try:
        before = db.query(SkillMarketplace.downloads).filter(
            SkillMarketplace.id == mkt_id
        ).scalar()
    finally:
        db.close()
    r = client.post(
        "/api/v1/skills/market/batch-uninstall",
        json={"ids": [mkt_id]},
        headers=auth_header,
    )
    assert r.status_code == 200
    db = SessionLocal()
    try:
        after = db.query(SkillMarketplace.downloads).filter(
            SkillMarketplace.id == mkt_id
        ).scalar()
    finally:
        db.close()
    assert before == after, f"downloads changed unexpectedly: {before} -> {after}"


def test_batch_uninstall_duplicate_ids_idempotent(client, auth_header, two_tenants_with_installs):
    """Duplicate ids in payload → first wins, second goes to failed (idempotent)."""
    mkt_ids_t1 = two_tenants_with_installs["mkt_ids_t1"]
    # Duplicate the first id 3 times
    payload_ids = [mkt_ids_t1[0]] * 3 + mkt_ids_t1[1:]
    r = client.post(
        "/api/v1/skills/market/batch-uninstall",
        json={"ids": payload_ids},
        headers=auth_header,
    )
    assert r.status_code == 200
    body = r.json()
    # 3 unique ids total; first instance of each wins, the 2 duplicates
    # land in failed (because the row was already deleted by the first loop iteration)
    assert body["data"]["succeeded_count"] == 3
    failed = body["data"]["failed"]
    assert len(failed) == 2
    assert all(f["id"] == mkt_ids_t1[0] and f["reason"] == "not installed" for f in failed)
