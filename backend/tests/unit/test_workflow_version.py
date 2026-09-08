"""M30b 2.0 (2026-09-07) — workflow version history service + endpoint.

The 2.0 schema adds ``workflow_versions`` with a unique
``(workflow_id, version)`` index and a JSON ``definition_snapshot``.
These tests cover the read path: ``list_versions`` (newest first) and
``get_version`` (tenant-scoped). 2.1 will add the "保存即 version +1"
write trigger; 2.0 ships read-only.
"""
import uuid
from datetime import datetime

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


# ---- 2.1 B.1 (2026-09-08): "保存即 version +1" write trigger tests ------------
#
# These cover the new write-side behavior shipped in 2.1: every successful
# PUT /workflows/{id} writes a new ``WorkflowVersion`` row + bumps
# ``workflow.version`` by 1. ``bootstrap_workflow_versions()`` is the
# one-shot baseline seeder for pre-2.1 workflows.


def test_update_workflow_bumps_version_and_writes_row():
    """PUT workflow → workflow.version += 1 + new WorkflowVersion row
    carrying the PRE-update definition as ``definition_snapshot``.
    """
    from lumen_schemas.workflow import WorkflowUpdate, WorkflowDefinition, WorkflowNode, WorkflowEdge
    from lumen_services.workflow_service import WorkflowService

    db = SessionLocal()
    _ensure_tenant(db)
    # Use create_workflow so the workflow starts at version=1 + has a
    # baseline row (mirrors how the API wires it up).
    svc = WorkflowService()
    initial = svc.create_workflow(
        db,
        tenant_id=1,
        data=_make_workflow_create_payload(
            name="b1_trigger_one",
            definition_dict={"nodes": [{"id": "a", "type": "input", "config": {"x": 1}}], "edges": []},
        ),
    )
    wf_id = initial.id
    assert initial.version == 1
    try:
        # Update the definition — trigger must bump version to 2 and
        # snapshot the PRE-update definition.
        new_def_dict = {"nodes": [{"id": "a", "type": "input", "config": {"x": 99}}], "edges": []}
        result = svc.update_workflow(
            db,
            wf_id,
            tenant_id=1,
            data=WorkflowUpdate(
                definition=WorkflowDefinition.model_validate(new_def_dict),
                change_summary="bump x to 99",
            ),
        )
        assert result is not None
        assert result.version == 2

        rows = svc.list_versions(db, wf_id, tenant_id=1)
        assert len(rows) == 2
        # Newest first
        latest = rows[0]
        assert latest.version == 2
        # The snapshot of v=2 captures the PRE-update state, which is
        # the original definition (x=1), not the new one (x=99).
        assert latest.definition_snapshot["nodes"][0]["config"]["x"] == 1
        assert latest.change_summary == "bump x to 99"
        # The v=1 baseline row still exists from create_workflow.
        assert rows[1].version == 1
        assert rows[1].change_summary == "Initial version"
    finally:
        _cleanup(db, wf_id)


def test_update_workflow_records_actor_user_id():
    """``actor_user_id`` kwarg flows through to ``WorkflowVersion.created_by_user_id``."""
    from lumen_schemas.workflow import WorkflowUpdate
    from lumen_services.workflow_service import WorkflowService

    db = SessionLocal()
    _ensure_tenant(db)
    svc = WorkflowService()
    wf = svc.create_workflow(
        db,
        tenant_id=1,
        data=_make_workflow_create_payload(name="b1_trigger_actor"),
    )
    try:
        # Patch current_user.id by passing actor_user_id=42 directly.
        # The router does this in production; the service signature is
        # kw-only so it's an explicit decision.
        svc.update_workflow(
            db,
            wf.id,
            tenant_id=1,
            data=WorkflowUpdate(name="b1_trigger_actor_renamed"),
            actor_user_id=42,
            change_summary="renamed by user 42",
        )
        rows = svc.list_versions(db, wf.id, tenant_id=1)
        assert rows[0].created_by_user_id == 42
        assert rows[0].change_summary == "renamed by user 42"
    finally:
        _cleanup(db, wf.id)


def test_update_workflow_multiple_puts_increment_monotonically():
    """3 sequential PUTs → version goes 1 → 2 → 3 → 4 with 4 distinct snapshots."""
    from lumen_schemas.workflow import WorkflowUpdate, WorkflowDefinition
    from lumen_services.workflow_service import WorkflowService

    db = SessionLocal()
    _ensure_tenant(db)
    svc = WorkflowService()
    wf = svc.create_workflow(
        db,
        tenant_id=1,
        data=_make_workflow_create_payload(
            name="b1_multi_put",
            definition_dict={"nodes": [{"id": "x", "type": "input", "config": {"v": 0}}], "edges": []},
        ),
    )
    try:
        for i in range(1, 4):
            svc.update_workflow(
                db,
                wf.id,
                tenant_id=1,
                data=WorkflowUpdate(
                    definition=WorkflowDefinition.model_validate(
                        {"nodes": [{"id": "x", "type": "input", "config": {"v": i}}], "edges": []}
                    ),
                    change_summary=f"set v={i}",
                ),
            )
        # The local ``wf`` object is the same identity tracked by the
        # session — its ``version`` attribute is auto-flushed on commit,
        # so 3 PUTs push it from baseline 1 to 4.
        db.refresh(wf)
        assert wf.version == 4
        rows = svc.list_versions(db, wf.id, tenant_id=1)
        assert [r.version for r in rows] == [4, 3, 2, 1]
    finally:
        _cleanup(db, wf.id)


def test_update_workflow_versions_are_per_workflow_isolated():
    """Two workflows PUT independently → their version counters stay independent."""
    from lumen_schemas.workflow import WorkflowUpdate
    from lumen_services.workflow_service import WorkflowService

    db = SessionLocal()
    _ensure_tenant(db)
    svc = WorkflowService()
    wf_a = svc.create_workflow(
        db,
        tenant_id=1,
        data=_make_workflow_create_payload(name="b1_iso_a"),
    )
    wf_b = svc.create_workflow(
        db,
        tenant_id=1,
        data=_make_workflow_create_payload(name="b1_iso_b"),
    )
    try:
        svc.update_workflow(db, wf_a.id, tenant_id=1, data=WorkflowUpdate(name="b1_iso_a_v2"))
        svc.update_workflow(db, wf_a.id, tenant_id=1, data=WorkflowUpdate(name="b1_iso_a_v3"))
        svc.update_workflow(db, wf_b.id, tenant_id=1, data=WorkflowUpdate(name="b1_iso_b_v2"))
        a = svc.get_workflow(db, wf_a.id, tenant_id=1)
        b = svc.get_workflow(db, wf_b.id, tenant_id=1)
        assert a.version == 3  # baseline 1 + 2 updates
        assert b.version == 2  # baseline 1 + 1 update
    finally:
        _cleanup(db, wf_a.id, wf_b.id)


def test_bootstrap_workflow_versions_seeds_unseeded_workflows():
    """Pre-2.1 workflow (no version row, version=0) gets version=1 baseline row
    + workflow.version bumped to 1 after bootstrap runs."""
    from lumen_core.database import bootstrap_workflow_versions
    from lumen_services.workflow_service import WorkflowService

    db = SessionLocal()
    _ensure_tenant(db)
    # Build a pre-2.1 workflow: directly insert with version=0 and no
    # WorkflowVersion row. Bypass create_workflow() so the seed row is
    # NOT inserted (this simulates what a row written before 2.1
    # ship looks like).
    suffix = uuid.uuid4().hex[:8]
    wf = Workflow(
        name=f"b1_bootstrap_{suffix}",
        definition={"nodes": [{"id": "legacy", "type": "input", "config": {}}], "edges": []},
        tenant_id=1,
        is_active=True,
        version=0,  # pre-2.1 default
    )
    db.add(wf)
    db.commit()
    db.refresh(wf)
    try:
        # Confirm pre-bootstrap state: version=0, zero version rows.
        assert wf.version == 0
        assert (
            db.query(WorkflowVersion)
            .filter(WorkflowVersion.workflow_id == wf.id)
            .count()
            == 0
        )

        # Run the bootstrap helper — it must seed version=1 + bump.
        bootstrap_workflow_versions()

        # ``bootstrap_workflow_versions`` opens its own ``SessionLocal``
        # for the writes, so the outer session's identity map still
        # holds the stale ``version=0``. Re-fetch from a fresh session.
        from lumen_core.database import SessionLocal as FreshSession
        db.close()
        db = FreshSession()
        refreshed = db.get(Workflow, wf.id)
        assert refreshed.version == 1
        rows = (
            db.query(WorkflowVersion)
            .filter(WorkflowVersion.workflow_id == wf.id)
            .all()
        )
        assert len(rows) == 1
        assert rows[0].version == 1
        assert rows[0].change_summary is None  # bootstrap leaves summary blank
        # Snapshot equals the workflow's current definition.
        assert rows[0].definition_snapshot == refreshed.definition
    finally:
        _cleanup(db, wf.id)


def test_bootstrap_workflow_versions_idempotent_on_seeded_workflow():
    """Running bootstrap twice on the same workflow doesn't write a 2nd row."""
    from lumen_core.database import bootstrap_workflow_versions
    from lumen_services.workflow_service import WorkflowService

    db = SessionLocal()
    _ensure_tenant(db)
    svc = WorkflowService()
    wf = svc.create_workflow(
        db,
        tenant_id=1,
        data=_make_workflow_create_payload(name="b1_bootstrap_idempotent"),
    )
    try:
        # create_workflow seeded version=1 baseline.
        baseline_count = (
            db.query(WorkflowVersion)
            .filter(WorkflowVersion.workflow_id == wf.id)
            .count()
        )
        assert baseline_count == 1
        # Run bootstrap — must not duplicate.
        bootstrap_workflow_versions()
        post_count = (
            db.query(WorkflowVersion)
            .filter(WorkflowVersion.workflow_id == wf.id)
            .count()
        )
        assert post_count == 1
    finally:
        _cleanup(db, wf.id)


def test_update_workflow_if_match_409_does_not_write_version_row():
    """If-Match conflict → 409 path → NO new WorkflowVersion row is written.

    This is critical for the optimistic-lock design — a failed PUT must
    not pollute the history. We exercise the service directly to assert
    the side-effect: a ``WorkflowConflictError`` is raised and
    ``workflow_versions`` count stays at the pre-PUT value.
    """
    from lumen_schemas.workflow import WorkflowUpdate
    from lumen_services.workflow_service import WorkflowService, WorkflowConflictError

    db = SessionLocal()
    _ensure_tenant(db)
    svc = WorkflowService()
    wf = svc.create_workflow(
        db,
        tenant_id=1,
        data=_make_workflow_create_payload(name="b1_conflict_no_write"),
    )
    try:
        # Stale If-Match timestamp → 409.
        stale = datetime(2000, 1, 1, 0, 0, 0)
        with pytest.raises(WorkflowConflictError):
            svc.update_workflow(
                db,
                wf.id,
                tenant_id=1,
                data=WorkflowUpdate(name="b1_conflict_no_write_v2"),
                if_match_updated_at=stale,
            )
        # Roll back the half-applied changes from the raised exception
        # (the service did ``setattr`` before raising; the commit was
        # never reached, but the session may be aborted).
        db.rollback()
        rows = svc.list_versions(db, wf.id, tenant_id=1)
        assert len(rows) == 1  # baseline only — no new row from the 409
        assert rows[0].version == 1
    finally:
        _cleanup(db, wf.id)


# ---- fixture helpers (write trigger tests) ----------------------------------

def _make_workflow_create_payload(name: str, definition_dict: dict | None = None):
    """Build a ``WorkflowCreate`` instance — extracted to a helper so the
    trigger tests stay readable.
    """
    from lumen_schemas.workflow import WorkflowCreate, WorkflowDefinition

    if definition_dict is None:
        definition_dict = {
            "nodes": [{"id": "n", "type": "input", "config": {}}],
            "edges": [],
        }
    return WorkflowCreate(
        name=name,
        description=None,
        definition=WorkflowDefinition.model_validate(definition_dict),
    )
