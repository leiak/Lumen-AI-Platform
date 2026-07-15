"""Tests for WxTemplateService business logic.

Spec: docs/superpowers/specs/2026-06-17-wx-publisher-design.md §3.2 / §4.2

3 tests:
- create_template: is_system=True 仅 superuser 能设,普通 user 静默降级 False
- update_template: 系统模板 update 返 403
- increment_usage_count: usage_count +1 正确写入
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from lumen_schemas.wx_publisher import WxTemplateCreate, WxTemplateUpdate
from lumen_services.wx_publisher.template_service import WxTemplateService

from _wx_publisher_helpers import (
    cleanup_tracked,
    fresh_session,
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
def track_template_ids():
    return []


@pytest.fixture
def cleanup_rows(track_user_ids, track_tenant_ids, track_template_ids):
    yield
    cleanup_tracked(
        user_ids=track_user_ids, tenant_ids=track_tenant_ids,
        template_ids=track_template_ids,
    )


# ---- tests ------------------------------------------------------------------

def test_create_template_is_system_superuser_only(
    db_session, cleanup_rows, track_template_ids,
    track_user_ids, track_tenant_ids,
):
    """is_system=True 仅 superuser 能设,普通 user 静默降级 False"""
    tenant = make_tenant(db_session)
    track_tenant_ids.append(tenant.id)
    plain_user = make_user(db_session, tenant_id=tenant.id, is_superuser=False)
    track_user_ids.append(plain_user.id)
    super_user = make_user(db_session, tenant_id=tenant.id, is_superuser=True)
    track_user_ids.append(super_user.id)

    svc = WxTemplateService()

    # Plain user asks for is_system=True → silently downgraded to False
    payload_user = WxTemplateCreate(
        name="user-says-system",
        category="minimal",
        html_body="<p>html</p>",
        css_variables={"primary": "#000"},
        is_system=True,
    )
    row_user = svc.create_template(
        db_session, current_user=plain_user, payload=payload_user,
    )
    track_template_ids.append(row_user.id)
    assert row_user.is_system is False

    # Superuser can set is_system=True
    payload_super = WxTemplateCreate(
        name="real-system",
        category="tech",
        html_body="<p>html</p>",
        css_variables={"primary": "#000"},
        is_system=True,
    )
    row_super = svc.create_template(
        db_session, current_user=super_user, payload=payload_super,
    )
    track_template_ids.append(row_super.id)
    assert row_super.is_system is True


def test_update_template_system_template_403(
    db_session, cleanup_rows, track_template_ids,
    track_user_ids, track_tenant_ids,
):
    """系统模板 update 返 403"""
    tenant = make_tenant(db_session)
    track_tenant_ids.append(tenant.id)
    super_user = make_user(db_session, tenant_id=tenant.id, is_superuser=True)
    track_user_ids.append(super_user.id)
    system_tpl = make_template(
        db_session, tenant_id=tenant.id, user_id=super_user.id, is_system=True,
    )
    track_template_ids.append(system_tpl.id)

    svc = WxTemplateService()
    payload = WxTemplateUpdate(name="attempt-rename")

    with pytest.raises(HTTPException) as exc_info:
        svc.update_template(
            db_session, current_user=super_user,
            template_id=system_tpl.id, payload=payload,
        )
    assert exc_info.value.status_code == 403


def test_increment_usage_count(
    db_session, cleanup_rows, track_template_ids,
    track_user_ids, track_tenant_ids,
):
    """usage_count +1 正确写入"""
    tenant = make_tenant(db_session)
    track_tenant_ids.append(tenant.id)
    user = make_user(db_session, tenant_id=tenant.id)
    track_user_ids.append(user.id)
    tpl = make_template(
        db_session, tenant_id=tenant.id, user_id=user.id, usage_count=5,
    )
    track_template_ids.append(tpl.id)

    svc = WxTemplateService()
    assert tpl.usage_count == 5

    svc.increment_usage_count(db_session, template_id=tpl.id)
    db_session.refresh(tpl)
    assert tpl.usage_count == 6

    svc.increment_usage_count(db_session, template_id=tpl.id)
    db_session.refresh(tpl)
    assert tpl.usage_count == 7
