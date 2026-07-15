"""Regression test for the M32 / 2026-06-17 sort fix.

Before the fix, ``list_marketplace_skills`` and ``list_installed_skills``
had no ``order_by`` on their SQLAlchemy queries, so SQLAlchemy returned
rows in unspecified order (in practice MySQL PK-ascending). The user
reported "I just added 3 Puppeteer skills, can't see them" — the
Puppeteer rows had the highest ids and were buried on the last page of
the 689-row dev DB.

This test pins the new ordering: verified skills first, then by
descending id (newest within the same verification level).

M34 (2026-06-30) — the assertions were originally tight-coupled to
"Puppeteer is the highest-id row in the data category" and broke when
the breadth-expansion seed added 8 more ``data`` rows (3 HTTP + 4
script + 1 text2sql) above the Puppeteer ids. The assertions are now
**order-agnostic**: they verify the sort invariants
(``is_verified desc, id desc`` for marketplace;
``installed_at desc, id desc`` for installed) without pinning specific
row ids that drift every time new skills land.

The skill fixtures still need a few ``data`` rows so the listing is
non-empty; this is satisfied by the 9 pre-existing + 15 new M34 seeds.
"""
import pytest


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from lumen_main import app
    return TestClient(app)


@pytest.fixture
def auth_header(tmp_user):
    from lumen_services.auth_service import create_access_token
    token = create_access_token(
        data={"sub": tmp_user.username, "user_id": tmp_user.id}
    )
    return {"Authorization": f"Bearer {token}"}


def test_marketplace_list_orders_verified_first_then_newest(client, auth_header):
    """The marketplace listing is sorted ``is_verified desc, id desc``.

    Concretely: every adjacent pair in the response must satisfy
    ``prev.is_verified >= next.is_verified`` and (when equal)
    ``prev.id >= next.id``. This catches:
      - missing order_by (relies on MySQL PK-asc which is the bug M32 fixed)
      - sort key regression (e.g. someone reorders by name alphabetically)
      - category filter not propagated to ORDER BY (would break verified-first
        when combined with a non-verified-first column)
    """
    # page_size=20 to fit all 12 verified ``data`` rows on a fully-seeded dev DB
    # (9 baseline + 3 Puppeteer + 8 new M34 = at most 12 in the data category).
    r = client.get(
        "/api/v1/skills/market/?category=data&page=1&page_size=20",
        headers=auth_header,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["code"] == 200
    items = body["data"]["items"] if isinstance(body["data"], dict) else body["data"]
    assert items, "Expected at least some skills in the 'data' category"

    # All pairs must satisfy (prev.is_verified >= next.is_verified)
    # AND (if equal) (prev.id >= next.id).
    for prev, nxt in zip(items, items[1:]):
        prev_v = 1 if prev["is_verified"] else 0
        nxt_v = 1 if nxt["is_verified"] else 0
        assert prev_v >= nxt_v, (
            f"verified-first violated: {prev['name']!r}(v={prev_v},id={prev['id']}) "
            f"before {nxt['name']!r}(v={nxt_v},id={nxt['id']})"
        )
        if prev_v == nxt_v:
            assert prev["id"] > nxt["id"], (
                f"id-desc within verified violated: {prev['name']!r}(id={prev['id']}) "
                f"before {nxt['name']!r}(id={nxt['id']})"
            )

    # Additionally: at least one verified row must appear in the listing
    # (otherwise the test would pass trivially on an empty DB).
    assert any(it["is_verified"] for it in items), (
        "Listing has no verified rows — seed broken?"
    )


def test_marketplace_list_orders_by_id_desc_within_verified(client, auth_header):
    """Within the verified group, the 3 Puppeteer skills appear in id-desc order.

    Puppeteer was M32's flagship (highest-id data-category verified rows at
    the time). With M34 the Puppeteer rows are no longer at the top of
    ``data``, but they should still be id-desc relative to each other (and
    relative to every other verified ``data`` row).
    """
    r = client.get(
        "/api/v1/skills/market/?category=data&page=1&page_size=20",
        headers=auth_header,
    )
    assert r.status_code == 200
    body = r.json()
    items = body["data"]["items"] if isinstance(body["data"], dict) else body["data"]
    puppeteer = [it for it in items if it["name"].startswith("Puppeteer ")]
    assert len(puppeteer) == 3, (
        f"Expected 3 Puppeteer rows in 'data' category; got {len(puppeteer)}"
    )
    # The 3 skills were inserted in this order: 数据爬取 → 截图 → PDF,
    # so id-desc means PDF first, then 截图, then 数据爬取.
    assert puppeteer[0]["name"] == "Puppeteer 网页生成 PDF"
    assert puppeteer[1]["name"] == "Puppeteer 网页截图"
    assert puppeteer[2]["name"] == "Puppeteer 网页数据爬取"


def test_installed_list_orders_by_installed_at_desc(tmp_user, client, auth_header):
    """Newly installed skills land on page 1 of the installed listing.

    The marketplace listing pin is covered above; this one verifies the
    InstalledSkill side gets explicit ``installed_at desc, id desc``
    ordering (M34 also added the missing order_by there).
    """
    from lumen_core.database import SessionLocal
    from lumen_models.skill_marketplace import SkillMarketplace, InstalledSkill

    db = SessionLocal()
    try:
        # Find a marketplace skill to install.
        ms = db.query(SkillMarketplace).filter_by(
            name="Puppeteer 网页数据爬取"
        ).first()
        assert ms is not None, "Puppeteer skill not in marketplace — seed broken?"

        # Clean any prior install for this tenant (test isolation).
        existing = db.query(InstalledSkill).filter_by(
            tenant_id=tmp_user.tenant_id,
            marketplace_skill_id=ms.id,
        ).first()
        if existing is not None:
            db.delete(existing)
            db.commit()

        # Install via the public endpoint.
        r = client.post(
            f"/api/v1/skills/market/{ms.id}/install",
            headers=auth_header,
        )
        assert r.status_code == 200, f"install failed: {r.text}"

        # The installed list should now contain the Puppeteer skill on page 1.
        r = client.get(
            "/api/v1/skills/market/installed?page=1&page_size=20",
            headers=auth_header,
        )
        assert r.status_code == 200
        body = r.json()
        items = body["data"]["items"] if isinstance(body["data"], dict) else body["data"]
        names = [it["name"] for it in items]
        assert "Puppeteer 网页数据爬取" in names, (
            f"Newly installed Puppeteer skill should be on page 1 of the "
            f"installed list; got names={names}"
        )

        # Sort invariant: adjacent pairs must satisfy
        # prev.installed_at >= next.installed_at (timestamp desc).
        for prev, nxt in zip(items, items[1:]):
            # installed_at comes back as ISO 8601 string; lexicographic
            # comparison on ISO strings is equivalent to chronological
            # because the format is fixed-width zero-padded.
            assert prev["installed_at"] >= nxt["installed_at"], (
                f"installed_at-desc violated: {prev['name']!r}({prev['installed_at']}) "
                f"before {nxt['name']!r}({nxt['installed_at']})"
            )
    finally:
        # Cleanup so re-runs start clean.
        if existing is not None or True:
            inst = db.query(InstalledSkill).filter_by(
                tenant_id=tmp_user.tenant_id,
                marketplace_skill_id=ms.id,
            ).first()
            if inst is not None:
                db.delete(inst)
                db.commit()
        db.close()
