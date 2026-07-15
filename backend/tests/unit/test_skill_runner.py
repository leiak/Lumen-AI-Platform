"""Unit tests for SkillRunner.get_active_skills.

Behavior contract under test (from the plan):
  1. None / empty input -> [].
  2. All valid ids -> one RenderedSkill per id, ordered by Skill.id ASC,
     with the correct marketplace name (regression for the Cartesian bug).
  3. Cross-tenant: skill installed by a different tenant -> [] + warning.
  4. Inactive skill: Skill.is_active=False -> [].
  5. Cap at 5: 7 valid ids -> 5 returned in Skill.id ASC order, the
     trailing 2 ids show up in the dropped set in the warning.

We use a real test session (SessionLocal) so the SQL is actually executed;
this is what would have caught the missing join in C1.
"""
import os
import re
import sys
import uuid

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))


def _warning_mentions_id(message: str, skill_id: int) -> bool:
    """Return True iff `skill_id` appears as a list element in `message`.

    The runner's warning format is `dropped ids [a, b, c] (tenant=...)`.
    A plain substring check would falsely match a digit inside a larger
    number (e.g. id 42 matches "10042"), so we look for the id bounded
    by list punctuation.
    """
    pattern = r'(?:\[|, )' + str(skill_id) + r'(?:, |\])'
    return re.search(pattern, message) is not None


@pytest.fixture
def skills_seed():
    """Seed tenant 1 with 2 active skills (and their marketplace/install rows).

    Yields a dict with the relevant ids. Cleans up in reverse-FK order on
    teardown so the shared dev DB stays tidy. Follows the pattern in
    tests/unit/test_mcp_local_server.py.
    """
    from lumen_core.database import SessionLocal
    from lumen_models.skill import Skill
    from lumen_models.skill_marketplace import InstalledSkill, SkillMarketplace
    from lumen_models.tenant import Tenant

    db = SessionLocal()
    created_marketplace_ids = []
    created_skill_ids = []
    created_installed_ids = []
    try:
        # Cleanup pre-existing 'del-in-use-*' / 'doubler-*' / 'list-prompt-*'
        # / 'test-prompt-*' / 'test-script-*' / 'test-http-*' rows from
        # other test runs (the dev DB is shared and accumulates
        # noise). If we don't, the cap-at-5 / inactive tests get
        # polluted with foreign skill rows whose contents we don't
        # know. We delete in reverse-FK order to avoid constraint
        # violations.
        _noisy_prefixes = (
            "del-in-use-", "doubler-", "list-prompt-",
            "test-prompt-", "test-script-", "test-http-",
            "e2e-doubler-",
        )
        noisy_marketplace = (
            db.query(SkillMarketplace)
            # tenant_id is a master Schema addition only on the
            # openclaw-integration branch (M23 PoC) — see ModelConfig
            # above. On master we identify by the noisy name prefix
            # alone.
            .all()
        )
        for m in noisy_marketplace:
            if any(m.name.startswith(p) for p in _noisy_prefixes):
                db.query(InstalledSkill).filter(
                    InstalledSkill.marketplace_skill_id == m.id
                ).delete(synchronize_session=False)
                db.query(Skill).filter(
                    Skill.name == m.name
                ).delete(synchronize_session=False)
                db.delete(m)
        db.commit()

        # Tenant 1 is the default; conftest's tmp_user ensures it exists,
        # but be defensive in case this fixture is used standalone.
        if not db.query(Tenant).filter(Tenant.id == 1).first():
            db.add(Tenant(id=1, name="Default Tenant", code="default"))
            db.commit()

        suffix = uuid.uuid4().hex[:8]
        seed = {"marketplace": [], "skills": [], "installed": []}
        for i in range(2):
            mp = SkillMarketplace(
                name=f"skmp-{suffix}-{i}",
                category="test",
                description=f"marketplace {i}",
                content=f"marketplace content {i}",
            )
            db.add(mp); db.commit(); db.refresh(mp)
            created_marketplace_ids.append(mp.id)
            seed["marketplace"].append({"id": mp.id, "name": mp.name, "content": mp.content})

            sk = Skill(
                name=f"sk-{suffix}-{i}",
                description=f"skill {i}",
                category="test",
                content=f"skill content {i}",
                is_builtin=False,
                is_active=True,
            )
            db.add(sk); db.commit(); db.refresh(sk)
            created_skill_ids.append(sk.id)
            seed["skills"].append({"id": sk.id, "name": sk.name, "content": sk.content})

            ins = InstalledSkill(
                tenant_id=1,
                marketplace_skill_id=mp.id,
                skill_id=sk.id,
                status="active",
            )
            db.add(ins); db.commit(); db.refresh(ins)
            created_installed_ids.append(ins.id)
            seed["installed"].append({"id": ins.id, "skill_id": sk.id, "marketplace_skill_id": mp.id})

        yield seed
    finally:
        # Reverse FK order: InstalledSkill -> Skill -> SkillMarketplace
        try:
            for iid in created_installed_ids:
                db.query(InstalledSkill).filter(InstalledSkill.id == iid).delete()
            for sid in created_skill_ids:
                db.query(Skill).filter(Skill.id == sid).delete()
            for mid in created_marketplace_ids:
                db.query(SkillMarketplace).filter(SkillMarketplace.id == mid).delete()
            db.commit()
        except Exception:
            db.rollback()
        finally:
            db.close()


def test_empty_input_returns_empty_tuple():
    from lumen_core.database import SessionLocal
    from lumen_services.skill_runner import SkillRunner

    db = SessionLocal()
    try:
        # M16: returns (prompts, tools) tuple
        assert SkillRunner.get_active_skills(db, tenant_id=1, skill_ids=None) == ([], [])
        assert SkillRunner.get_active_skills(db, tenant_id=1, skill_ids=[]) == ([], [])
    finally:
        db.close()


def test_all_valid_returns_correct_marketplace_name(skills_seed):
    """Regression for C1: the missing SkillMarketplace join produced a
    Cartesian product, so .name was whatever marketplace row the DB
    happened to iterate. With the fix, each Skill is paired with the
    SkillMarketplace row it was installed from.
    """
    from lumen_core.database import SessionLocal
    from lumen_services.skill_runner import SkillRunner

    sk0 = skills_seed["skills"][0]
    sk1 = skills_seed["skills"][1]
    mp0 = skills_seed["marketplace"][0]
    mp1 = skills_seed["marketplace"][1]

    db = SessionLocal()
    try:
        # Provide in reverse-id order to also exercise the Skill.id ASC sort.
        prompts, tools = SkillRunner.get_active_skills(
            db, tenant_id=1, skill_ids=[sk1["id"], sk0["id"]]
        )
        # No tool executors are in the registry for these marketplace rows
        # (no type/type_config), so tools is always empty here.
        assert tools == []
        assert len(prompts) == 2

        # Ordered by Skill.id ASC
        assert prompts[0].name == mp0["name"]
        assert prompts[0].content == sk0["content"]
        assert prompts[1].name == mp1["name"]
        assert prompts[1].content == sk1["content"]
    finally:
        db.close()


def test_cross_tenant_returns_empty_and_warns(skills_seed, caplog):
    """A skill installed by a different tenant must not leak into tenant 1."""
    import logging
    from lumen_core.database import SessionLocal
    from lumen_models.skill import Skill
    from lumen_models.skill_marketplace import InstalledSkill, SkillMarketplace
    from lumen_models.tenant import Tenant
    from lumen_services.skill_runner import SkillRunner

    # Ensure tenant 2 exists.
    suffix = uuid.uuid4().hex[:8]
    new_skill_id = None
    new_marketplace_id = None
    new_installed_id = None
    db = SessionLocal()
    try:
        if not db.query(Tenant).filter(Tenant.id == 2).first():
            db.add(Tenant(id=2, name="Other Tenant", code="other"))
            db.commit()

        # Create a NEW skill + marketplace + install ONLY under tenant 2.
        # If we reused a fixture skill, it would also be installed for
        # tenant 1 (the InstalledSkill unique key is (tenant_id,
        # marketplace_skill_id), not (skill_id, tenant_id)).
        mp = SkillMarketplace(
            name=f"skmp-xt-{suffix}",
            category="test",
            description="cross-tenant marketplace",
            content="cross-tenant marketplace content",
        )
        db.add(mp); db.commit(); db.refresh(mp)
        new_marketplace_id = mp.id

        sk = Skill(
            name=f"sk-xt-{suffix}",
            description="cross-tenant skill",
            category="test",
            content="cross-tenant skill content",
            is_builtin=False,
            is_active=True,
        )
        db.add(sk); db.commit(); db.refresh(sk)
        new_skill_id = sk.id

        ins = InstalledSkill(
            tenant_id=2, marketplace_skill_id=mp.id, skill_id=sk.id,
            status="active",
        )
        db.add(ins); db.commit(); db.refresh(ins)
        new_installed_id = ins.id
    finally:
        db.close()

    db = SessionLocal()
    try:
        with caplog.at_level(logging.WARNING, logger="lumen_services.skill_runner"):
            prompts, tools = SkillRunner.get_active_skills(
                db, tenant_id=1, skill_ids=[new_skill_id]
            )
        assert prompts == []
        assert tools == []
        # The id was dropped because it's only installed under tenant 2.
        assert any(
            _warning_mentions_id(rec.message, new_skill_id)
            for rec in caplog.records
        )
    finally:
        db.close()
        # Cleanup: reverse FK order.
        try:
            db2 = SessionLocal()
            try:
                if new_installed_id is not None:
                    db2.query(InstalledSkill).filter(InstalledSkill.id == new_installed_id).delete()
                if new_skill_id is not None:
                    db2.query(Skill).filter(Skill.id == new_skill_id).delete()
                if new_marketplace_id is not None:
                    db2.query(SkillMarketplace).filter(SkillMarketplace.id == new_marketplace_id).delete()
                db2.commit()
            finally:
                db2.close()
        except Exception:
            pass


def test_inactive_skill_returns_empty(skills_seed, caplog):
    """A Skill with is_active=False must be filtered out."""
    import logging
    from lumen_core.database import SessionLocal
    from lumen_models.skill import Skill
    from lumen_services.skill_runner import SkillRunner

    target = skills_seed["skills"][0]
    target_id = target["id"]

    db = SessionLocal()
    try:
        db.query(Skill).filter(Skill.id == target_id).update(
            {Skill.is_active: False}
        )
        db.commit()
    finally:
        db.close()

    db = SessionLocal()
    try:
        with caplog.at_level(logging.WARNING, logger="lumen_services.skill_runner"):
            prompts, tools = SkillRunner.get_active_skills(
                db, tenant_id=1,
                skill_ids=[target_id, skills_seed["skills"][1]["id"]],
            )
        # Only the still-active one comes back; the inactive id is dropped.
        assert tools == []
        assert len(prompts) == 1
        assert prompts[0].content == skills_seed["skills"][1]["content"]
        assert any(
            _warning_mentions_id(rec.message, target_id)
            for rec in caplog.records
        )
    finally:
        db.close()
        # Restore active so the fixture's teardown doesn't surprise anything.
        try:
            db2 = SessionLocal()
            try:
                db2.query(Skill).filter(Skill.id == target_id).update(
                    {Skill.is_active: True}
                )
                db2.commit()
            finally:
                db2.close()
        except Exception:
            pass


def test_cap_at_five(skills_seed, caplog):
    """7 valid ids requested -> 5 returned in Skill.id ASC order; the
    contract says the cap is applied BEFORE the DB query, so ids that
    didn't make the budget are NOT in the warning (the warning only
    captures ids the DB filter rejected as unknown/inactive/unauthorized).

    We also test the warning's interaction with the cap by passing 6
    valid + 1 invalid id: cap keeps the first 5 (or 6?) — actually cap
    keeps the first 5 in first-seen order; the 6th valid and the 1 invalid
    are over budget. So the warning should mention ONLY the invalid id
    that was sent to the DB (if any was). With 6 valid + 1 invalid
    passed in order [v1, v2, v3, v4, v5, v6, invalid], cap keeps
    [v1..v5], so invalid is over budget and NOT logged; with order
    [invalid, v1..v6], cap keeps [invalid, v1..v4], so v5, v6 are over
    budget and not logged, and invalid IS in the query -> warning.
    """
    import logging
    from lumen_core.database import SessionLocal
    from lumen_models.skill import Skill
    from lumen_models.skill_marketplace import InstalledSkill, SkillMarketplace
    from lumen_services.skill_runner import SkillRunner

    # Top up to 7 valid skills (fixture already created 2). We add 5 more,
    # each with its own marketplace row and an install under tenant 1.
    suffix = uuid.uuid4().hex[:8]
    new_skill_ids = []
    new_marketplace_ids = []
    new_installed_ids = []
    db = SessionLocal()
    try:
        for i in range(5):
            mp = SkillMarketplace(
                name=f"skmp-extra-{suffix}-{i}",
                category="test",
                description=f"extra marketplace {i}",
                content=f"extra marketplace content {i}",
            )
            db.add(mp); db.commit(); db.refresh(mp)
            new_marketplace_ids.append(mp.id)

            sk = Skill(
                name=f"sk-extra-{suffix}-{i}",
                description=f"extra skill {i}",
                category="test",
                content=f"extra skill content {i}",
                is_builtin=False,
                is_active=True,
            )
            db.add(sk); db.commit(); db.refresh(sk)
            new_skill_ids.append(sk.id)

            ins = InstalledSkill(
                tenant_id=1, marketplace_skill_id=mp.id, skill_id=sk.id,
                status="active",
            )
            db.add(ins); db.commit(); db.refresh(ins)
            new_installed_ids.append(ins.id)
    finally:
        db.close()

    all_skill_ids = [s["id"] for s in skills_seed["skills"]] + new_skill_ids
    # Add one id that does NOT exist in the DB; the cap will keep the
    # first 5 ids in first-seen order, and the unknown id is included
    # only if it lands in the first 5 positions.
    unknown_id = max(all_skill_ids) + 9999

    # Scenario A: 7 valid ids, all installed for tenant 1. Cap keeps
    # the first 5 in first-seen order; all 5 are found, so no warning
    # is emitted. The 2 trailing valid ids are not in any warning
    # because they were excluded by the cap, not by the DB filter.
    valid_only = list(reversed(all_skill_ids))  # not in ASC order
    db = SessionLocal()
    try:
        with caplog.at_level(logging.WARNING, logger="lumen_services.skill_runner"):
            prompts, tools = SkillRunner.get_active_skills(
                db, tenant_id=1, skill_ids=valid_only
            )
        assert tools == []
        assert len(prompts) == 5
        # No warning is emitted because all 5 queried ids were found.
        warning_records = [
            r for r in caplog.records
            if r.name == "lumen_services.skill_runner"
        ]
        assert warning_records == [], (
            f"no warning expected for 7 valid ids; got {warning_records}"
        )
        # The cap took the first 5 in first-seen order (which is
        # reversed), and the SQL ORDER BY Skill.id ASC sorts them.
        expected_ids = sorted(valid_only[:5])
        # Verify by content uniqueness and that the result has 5 entries.
        assert len({(r.name, r.content) for r in prompts}) == 5
        # The 2 over-budget ids are the 2 smallest (reversed list's
        # tail) — they never reach the DB or the warning.
        over_budget_ids = sorted(valid_only)[:2]
        for did in over_budget_ids:
            assert not any(
                _warning_mentions_id(rec.message, did)
                for rec in caplog.records
            ), (
                f"id {did} was over budget and must not appear in any warning"
            )
    finally:
        db.close()

    # Scenario B: 1 unknown + 6 valid ids. With 7 inputs, cap keeps the
    # first 5. If the unknown id is in the first 5 positions, it IS sent
    # to the DB and IS in the warning. We test the case where unknown is
    # first to exercise the cap+warning interaction explicitly.
    caplog.clear()
    db = SessionLocal()
    try:
        with caplog.at_level(logging.WARNING, logger="lumen_services.skill_runner"):
            prompts, tools = SkillRunner.get_active_skills(
                db, tenant_id=1,
                skill_ids=[unknown_id] + all_skill_ids[:6],
            )
        # Cap kept the first 5: [unknown, v1, v2, v3, v4]. The unknown
        # id is filtered out by the DB query, so 4 valid skills are
        # returned. This proves the cap and the warning work together.
        assert tools == []
        assert len(prompts) == 4
        # The unknown id was sent to the DB and is in the dropped set.
        unknown_records = [
            r for r in caplog.records
            if r.name == "lumen_services.skill_runner"
            and _warning_mentions_id(r.message, unknown_id)
        ]
        assert len(unknown_records) == 1, (
            f"unknown id should appear in exactly one warning; got {unknown_records}"
        )
        # Both over-budget valid ids (positions 4 and 5 of all_skill_ids)
        # are NOT in any warning — they were excluded by the cap before
        # the DB query.
        for over_budget_id in (all_skill_ids[4], all_skill_ids[5]):
            assert not any(
                _warning_mentions_id(rec.message, over_budget_id)
                for rec in caplog.records
            ), (
                f"over-budget valid id {over_budget_id} must not appear in any warning"
            )
    finally:
        db.close()
        # Cleanup the extras (reverse FK order).
        try:
            db2 = SessionLocal()
            try:
                for iid in new_installed_ids:
                    db2.query(InstalledSkill).filter(InstalledSkill.id == iid).delete()
                for sid in new_skill_ids:
                    db2.query(Skill).filter(Skill.id == sid).delete()
                for mid in new_marketplace_ids:
                    db2.query(SkillMarketplace).filter(SkillMarketplace.id == mid).delete()
                db2.commit()
            finally:
                db2.close()
        except Exception:
            pass
