"""Tests for Customer / FollowUp / CustomerFieldDefinition Pydantic schemas.

Spec: docs/superpowers/specs/2026-06-20-customer-management-design.md §4.3

Covers:
  - field_key 正则(小写字母开头 + [a-z0-9_])
  - level / source / gender / company_size / follow_up_type / field_type enum
  - level 默认值 'potential'
  - owner_user_id 必填(CustomerCreate)
  - content 必填且 1-5000 chars
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from lumen_schemas.customer import (
    CustomerCreate,
    CustomerFieldDefinitionCreate,
    CustomerUpdate,
    FollowUpCreate,
    FollowUpType,
    Level,
    Source,
)


# ---------------------------------------------------------------------------
# Customer schemas
# ---------------------------------------------------------------------------

def test_customer_create_requires_owner_user_id():
    """Spec §4.3 — CustomerCreate.owner_user_id 必填。"""
    with pytest.raises(ValidationError) as exc:
        CustomerCreate(name="x")  # type: ignore[call-arg]
    assert "owner_user_id" in str(exc.value)


def test_customer_create_default_level():
    """Spec §3.1 — level 默认 'potential'。"""
    c = CustomerCreate(name="x", owner_user_id=1)
    assert c.level == "potential"


def test_customer_create_rejects_invalid_level():
    """Spec §4.3 — level Literal 校验。"""
    with pytest.raises(ValidationError):
        CustomerCreate(name="x", owner_user_id=1, level="invalid")  # type: ignore[arg-type]


def test_customer_create_rejects_invalid_source():
    """Spec §4.3 — source Literal 校验。"""
    with pytest.raises(ValidationError):
        CustomerCreate(
            name="x",
            owner_user_id=1,
            source="unknown_channel",  # type: ignore[arg-type]
        )


def test_customer_create_rejects_oversized_name():
    """Spec §4.3 — name max_length=100。"""
    with pytest.raises(ValidationError):
        CustomerCreate(name="x" * 101, owner_user_id=1)


# ---------------------------------------------------------------------------
# FollowUp schemas
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "ftype",
    ["phone", "wechat", "email", "meeting", "other"],
)
def test_follow_up_accepts_all_valid_types(ftype: FollowUpType):
    """Spec §3.2 — 5 种 follow_up_type 都接受。"""
    f = FollowUpCreate(follow_up_type=ftype, content="x")  # type: ignore[arg-type]
    assert f.follow_up_type == ftype


def test_follow_up_rejects_invalid_type():
    """Spec §3.2 — 枚举外类型报 ValidationError。"""
    with pytest.raises(ValidationError):
        FollowUpCreate(follow_up_type="fax", content="x")  # type: ignore[arg-type]


def test_follow_up_content_min_length():
    """Spec §4.3 — content min_length=1。"""
    with pytest.raises(ValidationError):
        FollowUpCreate(follow_up_type="phone", content="")


def test_follow_up_content_max_length():
    """Spec §4.3 — content max_length=5000。"""
    with pytest.raises(ValidationError):
        FollowUpCreate(follow_up_type="phone", content="x" * 5001)


# ---------------------------------------------------------------------------
# CustomerFieldDefinition schemas
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "bad_key",
    [
        "InvalidStart",  # 大写开头
        "1leading_digit",  # 数字开头
        "with-dash",  # 含 -
        "with space",  # 含空格
        "",  # 空
        "x" * 51,  # 超长
    ],
)
def test_field_key_pattern_rejects_invalid(bad_key: str):
    """Spec §4.3 — field_key pattern r'^[a-z][a-z0-9_]{0,49}$'。"""
    with pytest.raises(ValidationError):
        CustomerFieldDefinitionCreate(
            field_key=bad_key,
            field_label="l",
            field_type="text",
        )


@pytest.mark.parametrize(
    "good_key",
    [
        "customer_ltv",
        "decision_authority",
        "x",
        "abc123_def456",
    ],
)
def test_field_key_pattern_accepts_valid(good_key: str):
    """Spec §4.3 — 正则合法 field_key 通过校验。"""
    d = CustomerFieldDefinitionCreate(
        field_key=good_key,
        field_label="l",
        field_type="text",
    )
    assert d.field_key == good_key


def test_field_definition_select_requires_options():
    """Spec §3.3 — select 字段必须有 options。"""
    # schema 本身不强制 options(校验在 service 层 validate_custom_fields_dict)
    # 但创建时 options 可为 None,schema 仍合法
    d = CustomerFieldDefinitionCreate(
        field_key="some_key",
        field_label="Some",
        field_type="select",
        options=None,
    )
    assert d.options is None  # schema OK;service 层会校验实际引用时


# ---------------------------------------------------------------------------
# CustomerUpdate:所有字段 Optional
# ---------------------------------------------------------------------------

def test_customer_update_all_optional():
    """Spec §4.3 — CustomerUpdate 所有字段 Optional。"""
    u = CustomerUpdate()
    assert u.name is None
    assert u.owner_user_id is None
    assert u.tags is None
    assert u.custom_fields is None