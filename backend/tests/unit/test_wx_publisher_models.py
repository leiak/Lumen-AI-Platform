"""Tests for wx_publisher 6 models + ensure_* migrations.

Spec: docs/superpowers/specs/2026-06-17-wx-publisher-design.md §3 / §8.1

6 tests, one per model — covers:
- Required fields + defaults
- Tenant FK
- JSON / LargeBinary / MEDIUMBLOB columns
- UNIQUE constraint on WxDraftSection
- SET NULL FK on WxMaterial.kb_chunk_id
- WxPublishRecord status flow
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from lumen_models.wx_publisher import (
    WxAccount,
    WxDraft,
    WxDraftSection,
    WxMaterial,
    WxPublishRecord,
    WxTemplate,
)

from _wx_publisher_helpers import (
    cleanup_tracked,
    fresh_session,
    make_account,
    make_draft,
    make_material,
    make_publish_record,
    make_section,
    make_template,
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
def track_account_ids():
    return []


@pytest.fixture
def track_template_ids():
    return []


@pytest.fixture
def track_draft_ids():
    return []


@pytest.fixture
def track_material_ids():
    return []


@pytest.fixture
def track_record_ids():
    return []


@pytest.fixture
def cleanup_wx_publisher_rows(
    track_user_ids, track_tenant_ids, track_account_ids,
    track_template_ids, track_draft_ids, track_material_ids, track_record_ids,
):
    yield
    cleanup_tracked(
        user_ids=track_user_ids, tenant_ids=track_tenant_ids,
        account_ids=track_account_ids, template_ids=track_template_ids,
        draft_ids=track_draft_ids, material_ids=track_material_ids,
        record_ids=track_record_ids,
    )


# ---- WxAccount --------------------------------------------------------------

def test_wx_account_create(
    db_session, cleanup_wx_publisher_rows, track_account_ids,
    track_user_ids, track_tenant_ids,
):
    """WxAccount: 必填字段 + 默认值 + tenant_id FK"""
    tenant = make_tenant(db_session)
    track_tenant_ids.append(tenant.id)
    user = make_user(db_session, tenant_id=tenant.id)
    track_user_ids.append(user.id)
    encrypted = b"x" * 64

    row = WxAccount(
        tenant_id=tenant.id,
        user_id=user.id,
        app_id="wx" + uuid.uuid4().hex[:16],
        app_secret_encrypted=encrypted,
        name="primary",
    )
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    track_account_ids.append(row.id)

    assert row.id is not None
    assert row.tenant_id == tenant.id
    # Spec §3.1 default values
    assert row.account_type == "subscription"
    assert row.is_mock is True
    assert row.is_active is True
    assert row.app_secret_encrypted == encrypted
    assert row.access_token is None
    assert row.access_token_expires_at is None
    assert row.ip_whitelist is None
    assert row.last_verified_at is None


# ---- WxTemplate -------------------------------------------------------------

def test_wx_template_create(
    db_session, cleanup_wx_publisher_rows, track_template_ids,
    track_user_ids, track_tenant_ids,
):
    """WxTemplate: html_body / category / css_variables JSON / thumbnail BLOB"""
    tenant = make_tenant(db_session)
    track_tenant_ids.append(tenant.id)
    user = make_user(db_session, tenant_id=tenant.id)
    track_user_ids.append(user.id)
    jpeg_bytes = b"\xff\xd8\xff\xe0" + b"\x00" * 100  # pretend JPEG

    row = WxTemplate(
        tenant_id=tenant.id,
        name="magazine-v1",
        category="magazine",
        description="Magazine layout",
        html_body="<html>hello</html>",
        css_variables={"primary": "#1a1a1a", "font": "serif"},
        preview_html="<p>preview</p>",
        thumbnail=jpeg_bytes,
        is_system=False,
        created_by=user.id,
    )
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    track_template_ids.append(row.id)

    assert row.id is not None
    assert row.category == "magazine"
    assert row.css_variables == {"primary": "#1a1a1a", "font": "serif"}
    assert row.thumbnail == jpeg_bytes
    assert row.usage_count == 0
    assert row.is_system is False
    assert row.created_by == user.id


# ---- WxDraft ---------------------------------------------------------------

def test_wx_draft_create(
    db_session, cleanup_wx_publisher_rows, track_draft_ids, track_account_ids,
    track_user_ids, track_tenant_ids,
):
    """WxDraft: account_id/template_id SET NULL FK + status default 'draft'"""
    tenant = make_tenant(db_session)
    track_tenant_ids.append(tenant.id)
    user = make_user(db_session, tenant_id=tenant.id)
    track_user_ids.append(user.id)
    account = make_account(db_session, tenant_id=tenant.id, user_id=user.id)
    track_account_ids.append(account.id)

    row = WxDraft(
        tenant_id=tenant.id,
        user_id=user.id,
        account_id=account.id,
        template_id=None,
        title="Hello",
        content_markdown="# Hello",
    )
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    track_draft_ids.append(row.id)

    # Spec §3.3 defaults
    assert row.status == "draft"
    assert row.tags is None
    assert row.account_id == account.id
    assert row.template_id is None
    assert row.scheduled_at is None
    assert row.published_at is None
    assert row.wechat_media_id is None
    assert row.error_message is None


# ---- WxDraftSection UNIQUE constraint --------------------------------------

def test_wx_draft_section_unique_order(
    db_session, cleanup_wx_publisher_rows, track_draft_ids,
    track_user_ids, track_tenant_ids,
):
    """WxDraftSection: UNIQUE(draft_id, order_index) 拒绝重复"""
    tenant = make_tenant(db_session)
    track_tenant_ids.append(tenant.id)
    user = make_user(db_session, tenant_id=tenant.id)
    track_user_ids.append(user.id)
    draft = make_draft(db_session, tenant_id=tenant.id, user_id=user.id)
    track_draft_ids.append(draft.id)

    s1 = make_section(db_session, tenant_id=tenant.id, draft_id=draft.id, order_index=0)
    assert s1.id is not None

    # Same (draft_id, order_index) → IntegrityError
    dup = WxDraftSection(
        tenant_id=tenant.id,
        draft_id=draft.id,
        order_index=0,
        content_markdown="duplicate",
    )
    db_session.add(dup)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()

    # Different order_index on same draft → ok
    s3 = make_section(db_session, tenant_id=tenant.id, draft_id=draft.id, order_index=1)
    assert s3.id is not None


# ---- WxMaterial with kb_chunk_id SET NULL ----------------------------------

def test_wx_material_with_kb_chunk_fk(
    db_session, cleanup_wx_publisher_rows, track_material_ids,
    track_user_ids, track_tenant_ids,
):
    """WxMaterial: kb_chunk_id SET NULL FK, 删 chunk 不级联 material"""
    tenant = make_tenant(db_session)
    track_tenant_ids.append(tenant.id)
    user = make_user(db_session, tenant_id=tenant.id)
    track_user_ids.append(user.id)

    row = make_material(
        db_session, tenant_id=tenant.id, user_id=user.id, source_type="manual",
    )
    track_material_ids.append(row.id)

    assert row.kb_chunk_id is None
    assert row.source_type == "manual"

    # Setting kb_chunk_id to a non-existent value should fail FK on commit
    row.kb_chunk_id = 999999999
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()

    # After rollback the in-memory value may have been reset; force
    # None and re-commit so cleanup can find the row.
    fresh = db_session.query(WxMaterial).filter(WxMaterial.id == row.id).first()
    fresh.kb_chunk_id = None
    db_session.commit()


# ---- WxPublishRecord status flow -------------------------------------------

def test_wx_publish_record_status_flow(
    db_session, cleanup_wx_publisher_rows, track_record_ids, track_draft_ids,
    track_account_ids, track_user_ids, track_tenant_ids,
):
    """WxPublishRecord: status 字段支持 queued→uploading→...→success/failed 流"""
    tenant = make_tenant(db_session)
    track_tenant_ids.append(tenant.id)
    user = make_user(db_session, tenant_id=tenant.id)
    track_user_ids.append(user.id)
    account = make_account(db_session, tenant_id=tenant.id, user_id=user.id)
    track_account_ids.append(account.id)
    draft = make_draft(
        db_session, tenant_id=tenant.id, user_id=user.id, account_id=account.id,
    )
    track_draft_ids.append(draft.id)

    # queued
    rec = make_publish_record(
        db_session, tenant_id=tenant.id, draft_id=draft.id,
        account_id=account.id, user_id=user.id, status="queued",
    )
    track_record_ids.append(rec.id)
    assert rec.status == "queued"

    # Simulate status progression: queued → uploading → ... → success
    for next_status in ("uploading", "uploading_draft", "publishing", "success"):
        rec.status = next_status
        db_session.commit()
        db_session.refresh(rec)
        assert rec.status == next_status

    # Failed path on a fresh record
    rec2 = make_publish_record(
        db_session, tenant_id=tenant.id, draft_id=draft.id,
        account_id=account.id, user_id=user.id, status="failed",
    )
    track_record_ids.append(rec2.id)
    rec2.error_code = "40001"
    rec2.error_message = "invalid credential"
    rec2.duration_ms = 1234
    db_session.commit()
    db_session.refresh(rec2)
    assert rec2.status == "failed"
    assert rec2.error_code == "40001"
    assert rec2.error_message == "invalid credential"
    assert rec2.duration_ms == 1234
