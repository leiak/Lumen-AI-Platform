"""Tests for the Puppeteer skill seed (M32 / 2026-06-17).

Covers:
  - All 6 baseline prompt skills + 3 new Puppeteer prompt skills are
    present after a single call to ``seed_marketplace_data``.
  - The seed is idempotent per-name — running it again adds no rows.
  - The 3 Puppeteer skills have the right metadata (category, type,
    content references the Puppeteer GitHub repo + npm install).
  - The 3 Puppeteer skills have distinct content (not copy-paste).

The test file uses ``SessionLocal`` directly to avoid spinning up the
HTTP layer — ``seed_marketplace_data`` is a pure DB function with no
FastAPI dependencies. The first test snapshots the names present
before seeding and deletes only the rows it added, so it is safe to
re-run on a dev DB that already has the 6 baseline skills.

**M30 cleanup (2026-06-17):** The 5 tests in this file used to
each call ``seed_marketplace_data`` and then delete the rows they
added. Under parallel pytest execution the within-file races
(Test A's delete could fire while Test B was still asserting) caused
5 fails in the full suite. Switched to a **module-scoped fixture**
that seeds once before any test in this file and deletes once after
all tests — the 5 tests now run their assertions against a stable
snapshot, with no inter-test writes to clean up.
"""
import pytest


_PUPPETEER_NAMES = {
    "Puppeteer 网页数据爬取",
    "Puppeteer 网页截图",
    "Puppeteer 网页生成 PDF",
}
_BASELINE_NAMES = {
    "代码优化专家",
    "文档写作助手",
    "数据分析专家",
    "测试工程师",
    "API设计助手",
    "代码审查员",
}
_ALL_EXPECTED = _BASELINE_NAMES | _PUPPETEER_NAMES


def _snapshot_names(db) -> set[str]:
    from lumen_models.skill_marketplace import SkillMarketplace
    return {s.name for s in db.query(SkillMarketplace.name).all()}


def _delete_added_rows(db, before_names: set[str]) -> None:
    """Delete the SkillMarketplace rows whose names are NOT in ``before_names``."""
    from lumen_models.skill_marketplace import SkillMarketplace
    after_names = _snapshot_names(db)
    new_names = after_names - before_names
    if not new_names:
        return
    db.query(SkillMarketplace).filter(
        SkillMarketplace.name.in_(new_names)
    ).delete(synchronize_session=False)
    db.commit()


# M30 cleanup (2026-06-17): module-scoped seed — the 5 tests in
# this file share the same seed+cleanup cycle. Without this, each
# test's `_delete_added_rows` finally-clause could fire while
# another test in the file was still asserting, causing
# full-suite fails that pass in isolation.
@pytest.fixture(scope="module")
def puppeteer_seed():
    from lumen_core.database import SessionLocal
    from lumen_api.v1.skill_market import seed_marketplace_data

    db = SessionLocal()
    try:
        before = _snapshot_names(db)
        seed_marketplace_data(db)
        yield
    finally:
        _delete_added_rows(db, before)
        db.close()


def test_seed_marketplace_data_seeds_nine_skills(puppeteer_seed):
    """After a single seed call, all 6 baseline + 3 Puppeteer are present."""
    from lumen_core.database import SessionLocal
    db = SessionLocal()
    try:
        after = _snapshot_names(db)
        missing = _ALL_EXPECTED - after
        assert not missing, (
            f"After seed, expected all 9 baseline+Puppeteer skills. "
            f"Missing: {sorted(missing)}"
        )
    finally:
        db.close()


def test_seed_marketplace_data_is_idempotent(puppeteer_seed):
    """Calling seed 3 times adds no rows after the first call."""
    from lumen_core.database import SessionLocal
    from lumen_api.v1.skill_market import seed_marketplace_data

    db = SessionLocal()
    try:
        after_first = _snapshot_names(db)
        seed_marketplace_data(db)
        seed_marketplace_data(db)
        after_third = _snapshot_names(db)
        assert after_third == after_first, (
            f"Re-seeding added rows: {sorted(after_third - after_first)}"
        )
        assert len(after_third) == len(after_first), (
            f"Row count drifted: {len(after_first)} -> {len(after_third)}"
        )
    finally:
        db.close()


def test_puppeteer_skill_metadata_is_correct(puppeteer_seed):
    """Each Puppeteer skill: category=data, type=prompt, content has the right shape."""
    from lumen_core.database import SessionLocal
    from lumen_models.skill_marketplace import SkillMarketplace

    db = SessionLocal()
    try:
        rows = {
            s.name: s for s in db.query(SkillMarketplace).filter(
                SkillMarketplace.name.in_(_PUPPETEER_NAMES)
            ).all()
        }
        assert set(rows.keys()) == _PUPPETEER_NAMES, (
            f"Expected 3 Puppeteer rows; got {sorted(rows.keys())}"
        )
        for name, s in rows.items():
            assert s.category == "data", (
                f"{name}: expected category='data', got {s.category!r}"
            )
            assert s.type == "prompt", (
                f"{name}: expected type='prompt', got {s.type!r}"
            )
            assert s.is_verified == 1, (
                f"{name}: expected is_verified=1, got {s.is_verified!r}"
            )
            assert s.version == "1.0.0", (
                f"{name}: expected version='1.0.0', got {s.version!r}"
            )
            assert s.content is not None and len(s.content) > 200, (
                f"{name}: content too short ({len(s.content or '')} chars)"
            )
            assert "github.com/puppeteer/puppeteer" in s.content, (
                f"{name}: content must link to the Puppeteer GitHub repo"
            )
            assert "npm install puppeteer" in s.content, (
                f"{name}: content must mention the `npm install puppeteer` "
                f"prerequisite"
            )
    finally:
        db.close()


def test_puppeteer_skills_have_distinct_content(puppeteer_seed):
    """The 3 Puppeteer skills' content strings are pairwise different."""
    from lumen_core.database import SessionLocal
    from lumen_models.skill_marketplace import SkillMarketplace

    db = SessionLocal()
    try:
        rows = db.query(SkillMarketplace).filter(
            SkillMarketplace.name.in_(_PUPPETEER_NAMES)
        ).all()
        contents = [s.content for s in rows]
        assert len(contents) == 3
        # Pairwise distinct — guards against accidental copy-paste between
        # the scrape / screenshot / PDF content constants.
        assert len(set(contents)) == 3, (
            "Puppeteer skills have duplicate content — likely copy-paste "
            "between the 3 _PUPPETEER_* content constants."
        )
    finally:
        db.close()


def test_puppeteer_content_references_key_api_surfaces(puppeteer_seed):
    """The 3 Puppeteer skills' content covers the right API surface each."""
    from lumen_core.database import SessionLocal
    from lumen_models.skill_marketplace import SkillMarketplace

    db = SessionLocal()
    try:
        by_name = {
            s.name: s.content for s in db.query(SkillMarketplace).filter(
                SkillMarketplace.name.in_(_PUPPETEER_NAMES)
            ).all()
        }
        # Scrape skill covers the data-extraction API.
        scrape = by_name["Puppeteer 网页数据爬取"]
        for needle in ("page.evaluate", "page.$$eval", "page.goto"):
            assert needle in scrape, (
                f"Scrape skill content missing API surface {needle!r}"
            )

        # Screenshot skill covers page.screenshot + element.screenshot.
        screenshot = by_name["Puppeteer 网页截图"]
        for needle in ("page.screenshot", "element.screenshot", "fullPage"):
            assert needle in screenshot, (
                f"Screenshot skill content missing API surface {needle!r}"
            )

        # PDF skill covers page.pdf + key options.
        pdf = by_name["Puppeteer 网页生成 PDF"]
        for needle in ("page.pdf", "format", "margin", "printBackground"):
            assert needle in pdf, (
                f"PDF skill content missing API surface {needle!r}"
            )
    finally:
        db.close()
