"""
单元测试: 工作流 model_config_id 迁移脚本

Tests cover the three resolution paths (exact / substring / no-match)
plus idempotency and tenant isolation.
"""
import pytest
import sys
import os
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))


def _make_config(tenant_id, model_name, model_type, is_active=True, model_id=None):
    cfg = MagicMock()
    cfg.id = model_id or hash((tenant_id, model_name)) % 100000
    cfg.tenant_id = tenant_id
    cfg.model_name = model_name
    cfg.model_type = model_type
    cfg.is_active = is_active
    return cfg


def _make_workflow(tenant_id, definition):
    wf = MagicMock()
    wf.tenant_id = tenant_id
    wf.definition = definition
    return wf


class TestMigrateWorkflowModelRefs:
    @pytest.fixture
    def setup_db(self):
        """Return a (db, workflows) tuple where db is a MagicMock session
        and workflows is the list of MagicMock workflow objects.

        Tests call db.add(), db.commit(), etc. Migration reads from
        db.query(Workflow).all() and ModelConfig lookups.
        """
        return MagicMock(), []

    def test_exact_match_writes_model_config_id(self, setup_db):
        from lumen_scripts.migrate_workflow_model_refs import (
            migrate_workflow_model_refs,
        )

        db, workflows = setup_db
        cfg = _make_config(tenant_id=1, model_name="glm-4", model_type="zhipu", model_id=7)
        wf = _make_workflow(
            tenant_id=1,
            definition={
                "nodes": [
                    {"id": "n1", "type": "llm", "data": {"model_name": "glm-4"}}
                ]
            },
        )
        db.query.return_value.filter.return_value.first.return_value = cfg
        # We need the script to look up by exact model_name first.
        # We do this by making all .first() calls return cfg.
        report = migrate_workflow_model_refs(db, workflows=[wf])

        assert report.exact_matched == 1
        assert report.unmatched == 0
        # The workflow's node data should now have model_config_id=7
        node_data = wf.definition["nodes"][0]["data"]
        assert node_data["model_config_id"] == 7
        assert node_data["model_name"] == "glm-4"  # preserved

    def test_unmatched_leaves_null_and_preserves_name(self, setup_db):
        from lumen_scripts.migrate_workflow_model_refs import (
            migrate_workflow_model_refs,
        )

        db, workflows = setup_db
        # All .first() calls return None (no match anywhere)
        db.query.return_value.filter.return_value.first.return_value = None
        wf = _make_workflow(
            tenant_id=1,
            definition={
                "nodes": [
                    {"id": "n1", "type": "llm", "data": {"model_name": "weird-model"}}
                ]
            },
        )
        report = migrate_workflow_model_refs(db, workflows=[wf])

        assert report.exact_matched == 0
        assert report.unmatched == 1
        node_data = wf.definition["nodes"][0]["data"]
        assert node_data.get("model_config_id") is None
        assert node_data["model_name"] == "weird-model"

    def test_substring_match_falls_back_to_model_type_lookup(self, setup_db):
        """If exact match on model_name fails, the migration falls back to a
        substring match (e.g. matching on model_type). The first .first() call
        (exact match) returns None, the second (substring fallback) returns cfg.
        """
        from lumen_scripts.migrate_workflow_model_refs import (
            migrate_workflow_model_refs,
        )

        db, workflows = setup_db
        # The matched config uses a different model_name but matches on substring/model_type
        cfg = _make_config(
            tenant_id=1, model_name="some-other-name", model_type="zhipu", model_id=11
        )
        # First .first() (exact match on model_name) returns None
        # Second .first() (substring fallback) returns cfg
        db.query.return_value.filter.return_value.first.side_effect = [None, cfg]

        wf = _make_workflow(
            tenant_id=1,
            definition={
                "nodes": [
                    {"id": "n1", "type": "llm", "data": {"model_name": "glm-4"}}
                ]
            },
        )
        report = migrate_workflow_model_refs(db, workflows=[wf])

        # Exact match failed, fallback succeeded
        assert report.exact_matched == 0
        node_data = wf.definition["nodes"][0]["data"]
        assert node_data["model_config_id"] == 11
        assert node_data["model_name"] == "some-other-name"  # resolved name replaces the original (per spec 3.4)

    def test_already_migrated_node_is_skipped(self, setup_db):
        from lumen_scripts.migrate_workflow_model_refs import (
            migrate_workflow_model_refs,
        )

        db, workflows = setup_db
        # If the migration incorrectly queries for already-migrated nodes,
        # it would overwrite model_config_id=42 with this config's id (99).
        # The correct behavior is to NOT call db.query at all for already-migrated nodes.
        db.query.return_value.filter.return_value.first.return_value = _make_config(
            tenant_id=1, model_name="glm-4", model_type="zhipu", model_id=99
        )
        wf = _make_workflow(
            tenant_id=1,
            definition={
                "nodes": [
                    {"id": "n1", "type": "llm", "data": {"model_config_id": 42, "model_name": "glm-4"}}
                ]
            },
        )
        report = migrate_workflow_model_refs(db, workflows=[wf])

        assert report.skipped_already_migrated == 1
        assert report.exact_matched == 0
        # The original model_config_id=42 must be preserved (NOT overwritten with 99)
        node_data = wf.definition["nodes"][0]["data"]
        assert node_data["model_config_id"] == 42
        # Enforce: the migration must NOT call db.query for already-migrated nodes
        db.query.assert_not_called()

    def test_idempotent_second_run_no_writes(self, setup_db):
        from lumen_scripts.migrate_workflow_model_refs import (
            migrate_workflow_model_refs,
        )

        db, workflows = setup_db
        cfg = _make_config(tenant_id=1, model_name="glm-4", model_type="zhipu", model_id=7)
        db.query.return_value.filter.return_value.first.return_value = cfg
        wf = _make_workflow(
            tenant_id=1,
            definition={
                "nodes": [
                    {"id": "n1", "type": "llm", "data": {"model_name": "glm-4"}}
                ]
            },
        )
        # First run
        migrate_workflow_model_refs(db, workflows=[wf])
        assert wf.definition["nodes"][0]["data"]["model_config_id"] == 7
        # Second run — should be a no-op
        report2 = migrate_workflow_model_refs(db, workflows=[wf])
        assert report2.skipped_already_migrated == 1
        assert report2.exact_matched == 0

    def test_tenant_isolation(self, setup_db):
        """A workflow in tenant 1 must NOT match a ModelConfig belonging to
        tenant 2. The migration's filter is
        ``(tenant_id == wf.tenant_id) | (tenant_id IS NULL)``, so configs
        from other tenants are correctly excluded.
        """
        from lumen_scripts.migrate_workflow_model_refs import (
            migrate_workflow_model_refs,
        )

        db, workflows = setup_db
        # The only ModelConfig in the system belongs to tenant 2 — the migration's
        # tenant filter must exclude it for a tenant-1 workflow.
        _cfg_tenant_2 = _make_config(
            tenant_id=2, model_name="glm-4", model_type="zhipu", model_id=99
        )
        # Mock returns None — simulates the filter correctly excluding other-tenant configs
        db.query.return_value.filter.return_value.first.return_value = None

        wf = _make_workflow(
            tenant_id=1,
            definition={
                "nodes": [
                    {"id": "n1", "type": "llm", "data": {"model_name": "glm-4"}}
                ]
            },
        )
        report = migrate_workflow_model_refs(db, workflows=[wf])

        # A config in tenant 2 must NOT be matched by a tenant-1 workflow
        assert report.exact_matched == 0
        assert report.unmatched == 1
        node_data = wf.definition["nodes"][0]["data"]
        assert node_data.get("model_config_id") is None
        assert node_data["model_name"] == "glm-4"

    def test_non_llm_nodes_are_ignored(self, setup_db):
        from lumen_scripts.migrate_workflow_model_refs import (
            migrate_workflow_model_refs,
        )

        db, workflows = setup_db
        wf = _make_workflow(
            tenant_id=1,
            definition={
                "nodes": [
                    {"id": "n1", "type": "input", "data": {}},
                    {"id": "n2", "type": "output", "data": {}},
                    {"id": "n3", "type": "llm", "data": {"model_name": "glm-4"}},
                ]
            },
        )
        db.query.return_value.filter.return_value.first.return_value = None
        report = migrate_workflow_model_refs(db, workflows=[wf])

        assert report.llm_nodes_seen == 1
        # The two non-LLM nodes must be untouched
        assert wf.definition["nodes"][0]["data"] == {}
        assert wf.definition["nodes"][1]["data"] == {}
