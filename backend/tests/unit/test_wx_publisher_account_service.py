"""Tests for WxAccountService business logic.

Spec: docs/superpowers/specs/2026-06-17-wx-publisher-design.md §3.1 / §4.2

5 tests:
- Fernet encrypt/decrypt roundtrip
- mask_app_secret format
- create_account stores encrypted (not plaintext) AppSecret
- Cross-tenant get_account → 404
- is_mock short-circuit on get_access_token
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from lumen_core.config import settings
from lumen_schemas.wx_publisher import WxAccountCreate
from lumen_services.wx_publisher.account_service import (
    WxAccountService,
    mask_app_secret,
)

from _wx_publisher_helpers import (
    cleanup_tracked,
    fresh_session,
    make_account,
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
def cleanup_rows(track_user_ids, track_tenant_ids, track_account_ids):
    yield
    cleanup_tracked(
        user_ids=track_user_ids, tenant_ids=track_tenant_ids,
        account_ids=track_account_ids,
    )


# ---- tests ------------------------------------------------------------------

def test_encrypt_decrypt_roundtrip():
    """Fernet encrypt/decrypt roundtrip(用 dev sentinel 派生 key)"""
    svc = WxAccountService()
    plain = "this_is_a_32_char_app_secret_xx"
    encrypted = svc.encrypt_app_secret(plain)
    # Fernet ciphertext is bytes, never equal to plaintext
    assert isinstance(encrypted, bytes)
    assert plain.encode() not in encrypted
    # Decrypt recovers the original
    decrypted = svc.decrypt_app_secret(encrypted)
    assert decrypted == plain


def test_mask_app_secret_format():
    """mask 格式 'ab****cd' (首尾 2 位)"""
    masked = mask_app_secret("abcdefghijklmnop")
    assert masked == "ab****op"

    # Short-string degenerate case
    masked_short = mask_app_secret("abcd")
    assert masked_short == "ab****cd"

    # Boundary: 5 chars
    masked_5 = mask_app_secret("abcde")
    assert masked_5 == "ab****de"


def test_create_account_stores_encrypted_not_plain(
    db_session, cleanup_rows, track_account_ids,
    track_user_ids, track_tenant_ids,
):
    """create_account 写库的是 encrypted bytes, 不是明文"""
    tenant = make_tenant(db_session)
    track_tenant_ids.append(tenant.id)
    user = make_user(db_session, tenant_id=tenant.id)
    track_user_ids.append(user.id)

    svc = WxAccountService()
    plain_secret = "a" * 32  # 32-char secret
    payload = WxAccountCreate(
        name="primary",
        app_id="wx" + ("1" * 16),  # wx + 16 digits = 18 chars
        app_secret=plain_secret,
    )
    row = svc.create_account(
        db_session, current_user=user, payload=payload,
    )
    track_account_ids.append(row.id)

    # The row was persisted
    assert row.id is not None
    # The stored bytes are NOT the plaintext
    assert plain_secret.encode("utf-8") != row.app_secret_encrypted
    assert row.app_secret_encrypted != plain_secret
    # Decrypting recovers the original
    decrypted = svc.decrypt_app_secret(row.app_secret_encrypted)
    assert decrypted == plain_secret


def test_get_account_404_on_cross_tenant(
    db_session, cleanup_rows, track_account_ids,
    track_user_ids, track_tenant_ids,
):
    """跨租户 get_account 返 404, 不泄露存在性"""
    # Two tenants, two users
    t1 = make_tenant(db_session, suffix="t1")
    t2 = make_tenant(db_session, suffix="t2")
    track_tenant_ids.extend([t1.id, t2.id])
    u1 = make_user(db_session, tenant_id=t1.id)
    u2 = make_user(db_session, tenant_id=t2.id)
    track_user_ids.extend([u1.id, u2.id])

    # Account belongs to tenant 1
    acc = make_account(db_session, tenant_id=t1.id, user_id=u1.id)
    track_account_ids.append(acc.id)

    svc = WxAccountService()

    # Tenant 1 sees its own account
    row = svc.get_account(db_session, current_user=u1, account_id=acc.id)
    assert row.id == acc.id

    # Tenant 2 gets 404, not 403 (防 IDOR 信息泄露)
    with pytest.raises(HTTPException) as exc_info:
        svc.get_account(db_session, current_user=u2, account_id=acc.id)
    assert exc_info.value.status_code == 404


def test_get_access_token_mock_short_circuit(
    db_session, cleanup_rows, track_account_ids,
    track_user_ids, track_tenant_ids,
):
    """is_mock=True 返 'mock_access_token_xxx', 不调 real API"""
    tenant = make_tenant(db_session)
    track_tenant_ids.append(tenant.id)
    user = make_user(db_session, tenant_id=tenant.id)
    track_user_ids.append(user.id)
    # is_mock=True by default
    acc = make_account(db_session, tenant_id=tenant.id, user_id=user.id, is_mock=True)
    track_account_ids.append(acc.id)

    svc = WxAccountService()
    token = svc.get_access_token(
        db_session, current_user=user, account_id=acc.id,
    )
    # Stable per-account mock token — must NOT call Wechat API
    assert token == f"mock_access_token_{acc.id}"
    # Stable across calls
    token2 = svc.get_access_token(
        db_session, current_user=user, account_id=acc.id,
    )
    assert token2 == token
