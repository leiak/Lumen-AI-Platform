"""M30b 2.0 (2026-09-07) — workflow version history service + endpoint.

The 2.0 schema adds ``workflow_versions`` with a unique
``(workflow_id, version)`` index and a JSON ``definition_snapshot``.
These tests cover the read path: ``list_versions`` (newest first) and
``get_version`` (tenant-scoped). 2.1 will add the "保存即 version +1"
write trigger; 2.0 ships read-only.
"""
import uuid

import pytest
from fastapi.testclient import TestClient

from lumen_core.database import SessionLocal
from lumen_models.workflow import Workflow, WorkflowVersion
from lumen_models.tenant import Tenant  # noqa: F401  # ensure Tenant mapped
from lumen_models.user import User  # noqa: F401
from lumen_services.auth_service import create_access_token


# ---- fixture helpers ---------------------------------------------------------

def _ensure_tenant(db) -> None:
    """Re-uses the tmp_user / first-test-of-suite pattern from conftest."""
    if db.query(Tenant).filter(Tenant.id == 1).first() is None:
        db.add(Tenant(id=1, name="Default Tenant", code="default"))
        db.commit()


def _make_workflow(db, tenant_id: int = 1) -> int:
    suffix = uuid.uuid4().hex[:8]
    wf = Workflow(
        name=f"m30b_version_{suffix}",
        definition={
            "nodes": [
                {"id": "in", "type": "input", "config": {"version": "1"}},
                {"id": "out", "type": "output", "config": {"version": "1", "field": "in.x"}},
            ],
            "edges": [
                {"id": "e1", "source": "in", "target": "out", "sourceHandle": "default"},
            ],
        },
        tenant_id=tenant_id,
        is_active=True,
    )
    db.add(wf)
    db.commit()
    db.refresh(wf)
    return wf.id


def _make_version(db, workflow_id: int, version: int, definition: dict | None = None) -> int:
    suffix = uuid.uuid4().hex[:8]
    row = WorkflowVersion(
        workflow_id=workflow_id,
        version=version,
        definition_snapshot=definition or {
            "nodes": [{"id": f"n_{version}", "type": "input", "config": {"v": version}}],
            "edges": [],
        },
        change_summary=f"bootstrap v{version}_{suffix}",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row.id


def _cleanup(db, *workflow_ids: int) -> None:
    from sqlalchemy import text
    for wid in workflow_ids:
        try:
            db.execute(text("DELETE FROM workflow_versions WHERE workflow_id = :wid"), {"wid": wid})
            db.commit()
        except Exception:  # noqa: BLE001
            db.rollback()
        try:
            db.query(Workflow).filter(Workflow.id == wid).delete()
            db.commit()
        except Exception:  # noqa: BLE001
            db.rollback()


# ---- service tests -----------------------------------------------------------

def test_list_versions_returns_empty_when_no_rows():
    from lumen_services.workflow_service import WorkflowService

    db = SessionLocal()
    _ensure_tenant(db)
    wf_id = _make_workflow(db)
    try:
        svc = WorkflowService()
        rows = svc.list_versions(db, wf_id, tenant_id=1)
        assert rows == []
    finally:
        _cleanup(db, wf_id)


def test_list_versions_returns_newest_first():
    from lumen_services.workflow_service import WorkflowService

    db = SessionLocal()
    _ensure_tenant(db)
    wf_id = _make_workflow(db)
    try:
        _make_version(db, wf_id, version=1)
        _make_version(db, wf_id, version=2)
        _make_version(db, wf_id, version=3)
        svc = WorkflowService()
        rows = svc.list_versions(db, wf_id, tenant_id=1)
        assert [r.version for r in rows] == [3, 2, 1]
    finally:
        _cleanup(db, wf_id)


def test_list_versions_unknown_workflow_returns_empty():
    from lumen_services.workflow_service import WorkflowService

    db = SessionLocal()
    svc = WorkflowService()
    assert svc.list_versions(db, 999999, tenant_id=1) == []


def test_list_versions_cross_tenant_returns_empty():
    """Tenant isolation: a version row belongs to its parent workflow's
    tenant. A user from another tenant must see an empty list, not the
    other tenant's rows.
    """
    from lumen_services.workflow_service import WorkflowService

    db = SessionLocal()
    _ensure_tenant(db)
    wf_id = _make_workflow(db, tenant_id=1)
    try:
        _make_version(db, wf_id, version=1)
        svc = WorkflowService()
        # pretend we're tenant 2 — should be hidden
        rows = svc.list_versions(db, wf_id, tenant_id=2)
        assert rows == []
    finally:
        _cleanup(db, wf_id)


def test_get_version_returns_snapshot():
    from lumen_services.workflow_service import WorkflowService

    db = SessionLocal()
    _ensure_tenant(db)
    wf_id = _make_workflow(db)
    try:
        version_id = _make_version(
            db,
            wf_id,
            version=1,
            definition={"nodes": [{"id": "x", "type": "input", "config": {"v": 1}}], "edges": []},
        )
        svc = WorkflowService()
        row = svc.get_version(db, wf_id, version_id, tenant_id=1)
        assert row is not None
        assert row.version == 1
        assert row.definition_snapshot["nodes"][0]["id"] == "x"
    finally:
        _cleanup(db, wf_id)


def test_get_version_unknown_returns_none():
    from lumen_services.workflow_service import WorkflowService

    db = SessionLocal()
    _ensure_tenant(db)
    wf_id = _make_workflow(db)
    try:
        svc = WorkflowService()
        assert svc.get_version(db, wf_id, 999999, tenant_id=1) is None
    finally:
        _cleanup(db, wf_id)


def test_get_version_cross_tenant_returns_none():
    from lumen_services.workflow_service import WorkflowService

    db = SessionLocal()
    _ensure_tenant(db)
    wf_id = _make_workflow(db, tenant_id=1)
    try:
        version_id = _make_version(db, wf_id, version=1)
        svc = WorkflowService()
        assert svc.get_version(db, wf_id, version_id, tenant_id=2) is None
    finally:
        _cleanup(db, wf_id)


def test_version_unique_constraint():
    """Re-inserting a (workflow_id, version) row must violate the unique
    index. This is a guard against future code accidentally creating
    duplicate versions.
    """
    db = SessionLocal()
    _ensure_tenant(db)
    wf_id = _make_workflow(db)
    try:
        _make_version(db, wf_id, version=1)
        from sqlalchemy.exc import IntegrityError
        with pytest.raises(IntegrityError):
            _make_version(db, wf_id, version=1)
            db.commit()
        db.rollback()
    finally:
        _cleanup(db, wf_id)
