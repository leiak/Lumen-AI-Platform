"""M33: tests for init_dev_db text2sql seed functions.

Spec: docs/superpowers/specs/2026-06-20-text2sql-design.md §6.2

The seed must be idempotent: re-running the script must not crash
on a duplicate key, and it must not stomp on user-customised
data sources.
"""
import uuid

from lumen_core.database import SessionLocal
from lumen_models.skill_marketplace import InstalledSkill, SkillMarketplace
from lumen_models.text2sql import Text2SqlDataSource
from scripts.init_dev_db import (
    ensure_default_text2sql_datasource,
    ensure_text2sql_skill_marketplace,
)


def test_ensure_default_text2sql_datasource_is_idempotent():
    """Calling the seed twice must not insert two rows.

    On a DB that already has a default source the seed is a no-op;
    on a fresh DB it inserts exactly one row.
    """
    db = SessionLocal()
    try:
        # Run twice — should never crash, should never duplicate.
        id1 = ensure_default_text2sql_datasource(tenant_id=1)
        id2 = ensure_default_text2sql_datasource(tenant_id=1)
        assert id1 == id2
        after = (
            db.query(Text2SqlDataSource)
            .filter(
                Text2SqlDataSource.tenant_id == 1,
                Text2SqlDataSource.name == "默认 ai_platform",
            )
            .count()
        )
        # The seed uses "name=='默认 ai_platform' AND tenant_id==1" —
        # there should be exactly ONE row per tenant (idempotent).
        assert after == 1, (
            f"Expected exactly one default source for tenant 1, "
            f"got {after}"
        )
    finally:
        db.close()


def test_ensure_text2sql_skill_marketplace_creates_marketplace_and_install():
    """The marketplace row + InstalledSkill must both be created.

    Idempotent on re-run — we don't want to error out if the
    script is re-executed.
    """
    db = SessionLocal()
    try:
        # Run twice
        ensure_text2sql_skill_marketplace(tenant_id=1)
        ensure_text2sql_skill_marketplace(tenant_id=1)
        mkt = (
            db.query(SkillMarketplace)
            .filter(SkillMarketplace.name == "智能问数")
            .first()
        )
        assert mkt is not None
        assert mkt.type == "text2sql"
        assert mkt.category == "data"
        installed = (
            db.query(InstalledSkill)
            .filter(
                InstalledSkill.marketplace_skill_id == mkt.id,
                InstalledSkill.tenant_id == 1,
            )
            .first()
        )
        assert installed is not None
        assert installed.status == "active"
    finally:
        db.close()
