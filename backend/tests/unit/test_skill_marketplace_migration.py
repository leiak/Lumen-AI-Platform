"""Tests for skill_marketplace type column migration.

M16 adds two columns: `type` (NOT NULL DEFAULT 'prompt') and
`type_config` (JSON NULL). Migration must be idempotent.
"""
import pytest
from sqlalchemy import text


def test_ensure_marketplace_type_column_creates_columns():
    """First call creates type + type_config columns."""
    from lumen_core.database import ensure_marketplace_type_column
    from lumen_core.database import engine

    ensure_marketplace_type_column()

    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE, COLUMN_DEFAULT
            FROM information_schema.COLUMNS
            WHERE table_schema = DATABASE()
              AND table_name = 'skill_marketplace'
              AND COLUMN_NAME IN ('type', 'type_config')
        """))
        cols = {row.COLUMN_NAME: row for row in result}

    assert 'type' in cols
    assert 'type_config' in cols
    # type: VARCHAR NOT NULL with default 'prompt'
    assert cols['type'].DATA_TYPE in ('varchar', 'enum')
    assert cols['type'].IS_NULLABLE == 'NO'
    assert 'prompt' in str(cols['type'].COLUMN_DEFAULT)
    # type_config: JSON nullable
    assert cols['type_config'].IS_NULLABLE == 'YES'


def test_ensure_marketplace_type_column_idempotent():
    """Running twice doesn't raise (idempotent ALTER)."""
    from lumen_core.database import ensure_marketplace_type_column
    ensure_marketplace_type_column()
    ensure_marketplace_type_column()  # second call must not raise


def test_existing_rows_default_to_prompt():
    """After ALTER, NEW rows default to type='prompt' and type_config=NULL.

    Legacy rows already inserted (with their own type) are not
    affected by the migration's default; the default only applies
    to inserts that omit the column. We test the default by
    inserting a row with the type field omitted at the SQL level
    so MySQL's column default kicks in, then asserting the
    round-trip read-back value.

    We deliberately use the SAME SessionLocal for both the INSERT
    and the read. Using `engine.begin()` here would open a
    separate connection whose transaction snapshot (MySQL
    InnoDB's default REPEATABLE READ) does not see rows written
    by the SessionLocal connection, so the follow-up query would
    return None and the test would flake. Keeping both ops on
    one session guarantees read-your-writes.
    """
    from lumen_core.database import ensure_marketplace_type_column, SessionLocal
    from lumen_models.skill_marketplace import SkillMarketplace

    ensure_marketplace_type_column()

    db = SessionLocal()
    try:
        # Cleanup any prior run of this test
        prior = db.query(SkillMarketplace).filter_by(
            name="__test_default_prompt__"
        ).first()
        if prior is not None:
            db.delete(prior)
            db.commit()

        # Insert with the type column OMITTED so MySQL applies the
        # column default (set by ensure_marketplace_type_column).
        # skill_marketplace has no tenant_id column on master; only
        # InstalledSkill does.
        db.execute(text(
            "INSERT INTO skill_marketplace (name, category, type_config) "
            "VALUES ('__test_default_prompt__', 'test', NULL)"
        ))
        db.commit()

        sample = db.query(SkillMarketplace).filter_by(
            name="__test_default_prompt__"
        ).first()
        assert sample is not None, (
            "INSERT succeeded but follow-up SELECT on the same session "
            "returned None — read-your-writes is broken. This is a "
            "regression in the test, not the migration."
        )
        assert sample.type == "prompt"
        assert sample.type_config is None

        # Cleanup so a re-run starts clean.
        db.delete(sample)
        db.commit()
    finally:
        db.close()
