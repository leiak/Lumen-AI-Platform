"""Tests for WxMaterialService business logic.

Spec: docs/superpowers/specs/2026-06-17-wx-publisher-design.md §3.5 / §4.2

3 tests:
- create_material 强制 source_type='manual'
- list_materials source_type 过滤正确
- aggregate_tags 返所有 tenant 内 distinct tag list
"""
from __future__ import annotations

import pytest

from lumen_schemas.wx_publisher import WxMaterialCreate
from lumen_services.wx_publisher.material_service import WxMaterialService

from _wx_publisher_helpers import (
    cleanup_tracked,
    fresh_session,
    make_material,
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
def track_material_ids():
    return []


@pytest.fixture
def cleanup_rows(track_user_ids, track_tenant_ids, track_material_ids):
    yield
    cleanup_tracked(
        user_ids=track_user_ids, tenant_ids=track_tenant_ids,
        material_ids=track_material_ids,
    )


# ---- tests ------------------------------------------------------------------

def test_create_material_source_type_manual(
    db_session, cleanup_rows, track_material_ids,
    track_user_ids, track_tenant_ids,
):
    """create_material 强制 source_type='manual'"""
    tenant = make_tenant(db_session)
    track_tenant_ids.append(tenant.id)
    user = make_user(db_session, tenant_id=tenant.id)
    track_user_ids.append(user.id)

    svc = WxMaterialService()
    # Caller can't sneak in source_type — it's hard-coded in service
    payload = WxMaterialCreate(
        title="note-1",
        content="some content body",
        tags=["research", "draft"],
    )
    row = svc.create_material(
        db_session, current_user=user, payload=payload,
    )
    track_material_ids.append(row.id)

    assert row.source_type == "manual"
    assert row.title == "note-1"
    assert row.kb_chunk_id is None
    assert row.is_used is False


def test_list_materials_filters_by_source_type(
    db_session, cleanup_rows, track_material_ids,
    track_user_ids, track_tenant_ids,
):
    """list_materials source_type 过滤正确"""
    tenant = make_tenant(db_session)
    track_tenant_ids.append(tenant.id)
    user = make_user(db_session, tenant_id=tenant.id)
    track_user_ids.append(user.id)

    # 2 manual + 1 kb
    m1 = make_material(
        db_session, tenant_id=tenant.id, user_id=user.id, source_type="manual",
    )
    m2 = make_material(
        db_session, tenant_id=tenant.id, user_id=user.id, source_type="manual",
    )
    m3 = make_material(
        db_session, tenant_id=tenant.id, user_id=user.id, source_type="kb",
    )
    track_material_ids.extend([m1.id, m2.id, m3.id])

    svc = WxMaterialService()
    all_rows, total_all = svc.list_materials(
        db_session, current_user=user, page=1, page_size=20,
    )
    assert total_all == 3

    manual_rows, manual_total = svc.list_materials(
        db_session, current_user=user, page=1, page_size=20,
        source_type="manual",
    )
    assert manual_total == 2
    assert all(r.source_type == "manual" for r in manual_rows)

    kb_rows, kb_total = svc.list_materials(
        db_session, current_user=user, page=1, page_size=20,
        source_type="kb",
    )
    assert kb_total == 1
    assert kb_rows[0].id == m3.id


def test_aggregate_tags_returns_distinct_list(
    db_session, cleanup_rows, track_material_ids,
    track_user_ids, track_tenant_ids,
):
    """aggregate_tags 返所有 tenant 内 distinct tag list"""
    tenant = make_tenant(db_session)
    track_tenant_ids.append(tenant.id)
    user = make_user(db_session, tenant_id=tenant.id)
    track_user_ids.append(user.id)

    m1 = make_material(
        db_session, tenant_id=tenant.id, user_id=user.id,
        tags=["research", "draft"],
    )
    m2 = make_material(
        db_session, tenant_id=tenant.id, user_id=user.id,
        tags=["research", "published"],
    )
    m3 = make_material(
        db_session, tenant_id=tenant.id, user_id=user.id,
        tags=["new"],
    )
    track_material_ids.extend([m1.id, m2.id, m3.id])

    svc = WxMaterialService()
    tags = svc.aggregate_tags(db_session, current_user=user)
    # Sorted, distinct — set = {draft, new, published, research}
    assert tags == ["draft", "new", "published", "research"]

    # Tenant isolation: another tenant sees no tags
    other_tenant = make_tenant(db_session, suffix="other")
    track_tenant_ids.append(other_tenant.id)
    other_user = make_user(db_session, tenant_id=other_tenant.id)
    track_user_ids.append(other_user.id)
    other_tags = svc.aggregate_tags(db_session, current_user=other_user)
    assert other_tags == []
