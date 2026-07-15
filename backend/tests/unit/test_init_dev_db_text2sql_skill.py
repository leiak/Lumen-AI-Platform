"""M33: tests that the text2sql skill marketplace seed is wired up.

Reuses the function from init_dev_db to make sure the marketplace
row + InstalledSkill are created on a fresh dev DB.
"""
import uuid

from lumen_core.database import SessionLocal
from lumen_models.skill_marketplace import InstalledSkill, SkillMarketplace
from scripts.init_dev_db import ensure_text2sql_skill_marketplace


def test_text2sql_skill_marketplace_uses_text2sql_type():
    """The seeded SkillMarketplace row must have type='text2sql'."""
    db = SessionLocal()
    try:
        ensure_text2sql_skill_marketplace(tenant_id=1)
        mkt = (
            db.query(SkillMarketplace)
            .filter(SkillMarketplace.name == "智能问数")
            .first()
        )
        assert mkt is not None
        assert mkt.type == "text2sql"
        # Verify the InstalledSkill exists
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
