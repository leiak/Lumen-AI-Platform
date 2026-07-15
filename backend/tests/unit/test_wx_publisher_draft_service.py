"""Tests for WxDraftService business logic.

Spec: docs/superpowers/specs/2026-06-17-wx-publisher-design.md §3.3 / §3.4 / §7.2

6 tests:
- create_draft default status = 'draft'
- update_draft locked when status=publishing → 409
- add_section appends to end (no conflict on unique order_index)
- reorder_sections 409 on duplicate order_index
- get_full_markdown merges sections into '## heading\\n\\ncontent' format
- delete_draft cascades sections (ON DELETE CASCADE)
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from lumen_schemas.wx_publisher import (
    WxDraftCreate,
    WxDraftSectionCreate,
    WxDraftUpdate,
)
from lumen_services.wx_publisher.draft_service import WxDraftService

from _wx_publisher_helpers import (
    cleanup_tracked,
    fresh_session,
    make_draft,
    make_section,
    make_tenant,
    make_user,
)


# ---- Per-file fixtures ------------------------------------------------------

@pytest.fixture
def db_session():
    db = fresh_session()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def track_user_ids():
    return []


@pytest.fixture
def track_tenant_ids():
    return []


@pytest.fixture
def track_draft_ids():
    return []


@pytest.fixture
def cleanup_rows(track_user_ids, track_tenant_ids, track_draft_ids):
    yield
    cleanup_tracked(
        user_ids=track_user_ids, tenant_ids=track_tenant_ids,
        draft_ids=track_draft_ids,
    )


# ---- tests ------------------------------------------------------------------

def test_create_draft_default_status(
    db_session, cleanup_rows, track_draft_ids,
    track_user_ids, track_tenant_ids,
):
    """create_draft status 默认 'draft'"""
    tenant = make_tenant(db_session)
    track_tenant_ids.append(tenant.id)
    user = make_user(db_session, tenant_id=tenant.id)
    track_user_ids.append(user.id)

    svc = WxDraftService()
    payload = WxDraftCreate(title="hello", content_markdown="# hi")
    row = svc.create_draft(db_session, current_user=user, payload=payload)
    track_draft_ids.append(row.id)

    assert row.status == "draft"
    assert row.title == "hello"
    assert row.content_markdown == "# hi"


def test_update_draft_locked_when_publishing(
    db_session, cleanup_rows, track_draft_ids,
    track_user_ids, track_tenant_ids,
):
    """status=publishing 时 update 返 409"""
    tenant = make_tenant(db_session)
    track_tenant_ids.append(tenant.id)
    user = make_user(db_session, tenant_id=tenant.id)
    track_user_ids.append(user.id)
    draft = make_draft(
        db_session, tenant_id=tenant.id, user_id=user.id, status="publishing",
    )
    track_draft_ids.append(draft.id)

    svc = WxDraftService()
    payload = WxDraftUpdate(title="new title", content_markdown="new body")

    with pytest.raises(HTTPException) as exc_info:
        svc.update_draft(
            db_session, current_user=user,
            draft_id=draft.id, payload=payload,
        )
    assert exc_info.value.status_code == 409


def test_add_section_appends_to_end(
    db_session, cleanup_rows, track_draft_ids,
    track_user_ids, track_tenant_ids,
):
    """add_section 追加到 order_index 末尾(无冲突)"""
    tenant = make_tenant(db_session)
    track_tenant_ids.append(tenant.id)
    user = make_user(db_session, tenant_id=tenant.id)
    track_user_ids.append(user.id)
    draft = make_draft(db_session, tenant_id=tenant.id, user_id=user.id)
    track_draft_ids.append(draft.id)

    # Existing section at order_index=0
    s0 = make_section(
        db_session, tenant_id=tenant.id, draft_id=draft.id, order_index=0,
    )
    assert s0.id is not None

    svc = WxDraftService()
    # Append at order_index=1 → no conflict
    payload = WxDraftSectionCreate(
        order_index=1, heading="h1", content_markdown="body 1",
    )
    s1 = svc.add_section(
        db_session, current_user=user, draft_id=draft.id, payload=payload,
    )
    assert s1.id is not None
    assert s1.order_index == 1

    # Try the same order_index=0 → should 409
    payload_dup = WxDraftSectionCreate(order_index=0, content_markdown="dup")
    with pytest.raises(HTTPException) as exc_info:
        svc.add_section(
            db_session, current_user=user, draft_id=draft.id, payload=payload_dup,
        )
    assert exc_info.value.status_code == 409


def test_reorder_sections_409_on_duplicate_order(
    db_session, cleanup_rows, track_draft_ids,
    track_user_ids, track_tenant_ids,
):
    """reorder 重复 order_index 返 409"""
    tenant = make_tenant(db_session)
    track_tenant_ids.append(tenant.id)
    user = make_user(db_session, tenant_id=tenant.id)
    track_user_ids.append(user.id)
    draft = make_draft(db_session, tenant_id=tenant.id, user_id=user.id)
    track_draft_ids.append(draft.id)

    s0 = make_section(
        db_session, tenant_id=tenant.id, draft_id=draft.id, order_index=0,
    )
    s1 = make_section(
        db_session, tenant_id=tenant.id, draft_id=draft.id, order_index=1,
    )
    s2 = make_section(
        db_session, tenant_id=tenant.id, draft_id=draft.id, order_index=2,
    )

    svc = WxDraftService()
    # All three new orders are the same → 409
    with pytest.raises(HTTPException) as exc_info:
        svc.reorder_sections(
            db_session, current_user=user, draft_id=draft.id,
            section_orders=[(s0.id, 5), (s1.id, 5), (s2.id, 5)],
        )
    assert exc_info.value.status_code == 409
    assert "Duplicate" in str(exc_info.value.detail) or "order_index" in str(exc_info.value.detail)


def test_get_full_markdown_merges_sections(
    db_session, cleanup_rows, track_draft_ids,
    track_user_ids, track_tenant_ids,
):
    """get_full_markdown 把 sections 拼成 '## heading\\n\\ncontent' 格式"""
    tenant = make_tenant(db_session)
    track_tenant_ids.append(tenant.id)
    user = make_user(db_session, tenant_id=tenant.id)
    track_user_ids.append(user.id)
    draft = make_draft(
        db_session, tenant_id=tenant.id, user_id=user.id,
        content_markdown="ignored because sections take precedence",
    )
    track_draft_ids.append(draft.id)

    s0 = make_section(
        db_session, tenant_id=tenant.id, draft_id=draft.id,
        order_index=0, heading="intro", content_markdown="hello world",
    )
    s1 = make_section(
        db_session, tenant_id=tenant.id, draft_id=draft.id,
        order_index=1, heading="body", content_markdown="more content",
    )

    svc = WxDraftService()
    full = svc.get_full_markdown(
        db_session, current_user=user, draft_id=draft.id,
    )
    # Section format: ``## heading\n\ncontent`` joined with ``\n\n``
    assert full == "## intro\n\nhello world\n\n## body\n\nmore content"


def test_delete_draft_cascades_sections(
    db_session, cleanup_rows, track_draft_ids,
    track_user_ids, track_tenant_ids,
):
    """delete_draft 级联删 sections(ON DELETE CASCADE)"""
    from lumen_models.wx_publisher import WxDraftSection
    tenant = make_tenant(db_session)
    track_tenant_ids.append(tenant.id)
    user = make_user(db_session, tenant_id=tenant.id)
    track_user_ids.append(user.id)
    draft = make_draft(db_session, tenant_id=tenant.id, user_id=user.id)
    track_draft_ids.append(draft.id)
    s0 = make_section(
        db_session, tenant_id=tenant.id, draft_id=draft.id, order_index=0,
    )
    s1 = make_section(
        db_session, tenant_id=tenant.id, draft_id=draft.id, order_index=1,
    )
    section_ids = [s0.id, s1.id]

    # Pre-check: 2 sections exist
    pre = db_session.query(WxDraftSection).filter(
        WxDraftSection.draft_id == draft.id
    ).count()
    assert pre == 2

    svc = WxDraftService()
    svc.delete_draft(db_session, current_user=user, draft_id=draft.id)

    # Post: 0 sections (ON DELETE CASCADE)
    post = db_session.query(WxDraftSection).filter(
        WxDraftSection.draft_id == draft.id
    ).count()
    assert post == 0

    # Track draft already removed by the service; remove from cleanup
    # list so teardown doesn't try to re-delete a non-existent row.
    track_draft_ids.remove(draft.id)
