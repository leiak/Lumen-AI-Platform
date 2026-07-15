"""Pydantic schema validation tests for wx_publisher.

Spec: docs/superpowers/specs/2026-06-17-wx-publisher-design.md §4.3

6 tests, all pure-Pydantic (no DB) — covers:
- 18-char AppID accepted
- Short AppID rejected
- Non-``wx`` prefix rejected
- Short AppSecret rejected
- category Literal validation
- model_config.from_attributes=True on response schemas (regression for
  2026-06-29 publish 500 — Pydantic v2 默认 from_attributes=False,传 ORM
  对象 raise ValidationError)
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from lumen_schemas.wx_publisher import (
    WxAccountCreate,
    WxAccountResponse,
    WxDraftListItem,
    WxMaterialListItem,
    WxTemplateCreate,
    WxTemplateListItem,
    WxPublishRecordListItem,
    WxPublishRecordResponse,
)


def _valid_app_id_18() -> str:
    """18 chars: ``wx`` + 16 lowercase alphanumerics."""
    return "wx" + "a1b2c3d4e5f6g7h8"


def test_wx_account_create_valid_18char_app_id():
    """18 字符 AppID 通过"""
    s = WxAccountCreate(
        name="primary",
        app_id=_valid_app_id_18(),
        app_secret="a" * 32,  # 32 chars — well above 20 floor
    )
    assert s.app_id == "wx" + "a1b2c3d4e5f6g7h8"
    assert s.account_type == "subscription"  # default
    assert s.is_mock is True  # default


def test_wx_account_create_rejects_short_app_id():
    """<18 字符 AppID 拒绝(模式要求 wx + 16-32 字符)"""
    # 17 chars total: wx + 15
    short_app_id = "wx" + "a" * 15
    assert len(short_app_id) == 17
    with pytest.raises(ValidationError) as exc_info:
        WxAccountCreate(
            name="x",
            app_id=short_app_id,
            app_secret="a" * 32,
        )
    # The error is on the ``app_id`` field
    assert "app_id" in str(exc_info.value)


def test_wx_account_create_rejects_non_wx_prefix():
    """不以 wx 开头拒绝"""
    # 18 chars, but doesn't start with ``wx``
    bad_app_id = "ab" + "c" * 16
    with pytest.raises(ValidationError) as exc_info:
        WxAccountCreate(
            name="x",
            app_id=bad_app_id,
            app_secret="a" * 32,
        )
    assert "app_id" in str(exc_info.value)


def test_wx_account_create_rejects_short_app_secret():
    """AppSecret <20 字符拒绝"""
    with pytest.raises(ValidationError) as exc_info:
        WxAccountCreate(
            name="x",
            app_id=_valid_app_id_18(),
            app_secret="short",  # 5 chars, well below 20
        )
    assert "app_secret" in str(exc_info.value)


def test_wx_template_create_literal_category():
    """category 必须是 Literal 5 个之一,其他拒绝"""
    # Happy path: one of the 5 valid categories
    for valid in ("minimal", "tech", "magazine", "literary", "business"):
        s = WxTemplateCreate(
            name=f"tpl_{valid}",
            category=valid,
            html_body="<p>test</p>",
            css_variables={"primary": "#000"},
        )
        assert s.category == valid

    # Sad path: an invalid category value
    with pytest.raises(ValidationError) as exc_info:
        WxTemplateCreate(
            name="tpl_bad",
            category="not-a-valid-category",
            html_body="<p>test</p>",
            css_variables={},
        )
    assert "category" in str(exc_info.value)


# ====== 2026-06-29 publish 500 regression ======
# Bug: wx_publisher 全部 4 个响应 schema(WxAccountResponse / WxDraftListItem /
# WxTemplateListItem / WxPublishRecordListItem) model_config 缺 from_attributes,
# 导致 publish endpoint model_validate(record) raise ValidationError → 500。
# 修法:给响应基类 model_config = ConfigDict(from_attributes=True)。
# 测试:断言 model_config.from_attributes=True,且用 SimpleNamespace 模拟 ORM
# 对象能成功 model_validate。

class _OrmLike:
    """鸭子类型模拟 SQLAlchemy ORM 对象 — 给 model_validate 用,无 DB 依赖。"""

    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


@pytest.mark.parametrize(
    "schema_cls,sample",
    [
        # WxAccountResponse 全部字段都填上
        (
            WxAccountResponse,
            dict(
                id=1,
                name="primary",
                app_id="wx" + "a" * 16,
                app_secret_masked="ab****90",
                account_type="subscription",
                is_mock=True,
                is_active=True,
                last_verified_at=None,
                created_at="2026-06-29T00:00:00Z",
            ),
        ),
        # WxDraftListItem — 列表基类,WxDraftResponse/WxDraftDetail 都继承
        (
            WxDraftListItem,
            dict(
                id=1,
                title="draft",
                account_id=None,
                template_id=None,
                status="draft",
                scheduled_at=None,
                updated_at="2026-06-29T00:00:00Z",
            ),
        ),
        # WxTemplateListItem — WxTemplateDetail 继承
        (
            WxTemplateListItem,
            dict(
                id=1,
                name="tpl",
                category="minimal",
                description=None,
                is_system=False,
                usage_count=0,
                has_thumbnail=False,
                created_at="2026-06-29T00:00:00Z",
            ),
        ),
        # WxPublishRecordListItem — 直接 publish endpoint 用的基类
        (
            WxPublishRecordListItem,
            dict(
                id=1,
                draft_id=85,
                account_id=70,
                user_id=1,
                status="queued",
                wechat_media_id=None,
                wechat_msg_id=None,
                scheduled_at=None,
                started_at=None,
                completed_at=None,
                duration_ms=None,
            ),
        ),
        # WxMaterialListItem
        (
            WxMaterialListItem,
            dict(
                id=1,
                title="mat",
                content_preview="…",
                source_type="kb",
                kb_chunk_id=None,
                tags=None,
                is_used=False,
                created_at="2026-06-29T00:00:00Z",
            ),
        ),
    ],
)
def test_response_schema_accepts_orm_like_object(schema_cls, sample):
    """Regression: response schemas 必须能 model_validate(orm) (from_attributes=True)。"""
    assert schema_cls.model_config.get("from_attributes") is True
    validated = schema_cls.model_validate(_OrmLike(**sample))
    assert validated.id == sample["id"]


def test_publish_record_response_accepts_orm_record():
    """直接覆盖 publish endpoint 的实际 schema 路径(95 行也用同 schema)。

    真实事故链:`POST /wx-publisher/publish/` → service.create_publish_record
    → commit + refresh → endpoint 调 `WxPublishRecordResponse.model_validate(record)`
    → record 是 SQLAlchemy ORM 对象 → 没 from_attributes → ValidationError →
    FastAPI 默认 exception handler 兜底成 500 Internal Server Error。
    """
    assert WxPublishRecordResponse.model_config.get("from_attributes") is True
    # 模拟 ORM 行 — 只填 create_publish_record 返回 record 的必需字段
    orm_like = _OrmLike(
        id=33,
        draft_id=85,
        account_id=70,
        user_id=1,
        status="queued",
        wechat_media_id=None,
        wechat_msg_id=None,
        scheduled_at=None,
        started_at=None,
        completed_at=None,
        duration_ms=None,
        error_code=None,
        error_message=None,
        created_at="2026-06-29T03:49:32",
    )
    resp = WxPublishRecordResponse.model_validate(orm_like)
    assert resp.id == 33
    assert resp.draft_id == 85
    assert resp.account_id == 70
    assert resp.status == "queued"
