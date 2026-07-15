"""Shared factories for wx_publisher test files (M32 T14).

This module ships plain **factory functions** (no @pytest.fixture) so
each test file can build its own fixtures. Putting fixtures in a
``conftest.py`` is avoided on purpose: the project convention is
fixtures-local-to-test-file or in the top-level ``tests/conftest.py``;
this helper module is imported as needed by individual test files.

Pattern mirrors tests/unit/test_image_generation_model.py:
- ``db_session`` fixture in each test file yields a fresh SessionLocal
- Caller is responsible for cleaning up rows it inserts via the
  ``track_*`` fixture lists + a single ``cleanup_*`` fixture
"""
from __future__ import annotations

import json
import uuid

from lumen_core.database import SessionLocal
from lumen_core.security import get_password_hash
from lumen_models.tenant import Tenant
from lumen_models.user import User
# Importing all FK target models so the SQLAlchemy metadata is fully
# populated when wx_publisher tables reference them (wx_drafts → generated_images,
# wx_materials → document_chunks, wx_draft_sections → model_configs).
from lumen_models import (  # noqa: F401
    agent as _agent,
    image_generation as _image_generation,
    knowledge as _knowledge,
    model_config as _model_config,
    user as _user_model,
)
from lumen_models.wx_publisher import (
    WxAccount,
    WxDraft,
    WxDraftSection,
    WxMaterial,
    WxPublishRecord,
    WxTemplate,
)


# ---- Session / cleanup helpers ---------------------------------------------

def fresh_session():
    """Open a new SessionLocal. Caller is responsible for closing."""
    return SessionLocal()


def cleanup_tracked(
    *,
    user_ids: list[int] | None = None,
    tenant_ids: list[int] | None = None,
    account_ids: list[int] | None = None,
    template_ids: list[int] | None = None,
    draft_ids: list[int] | None = None,
    material_ids: list[int] | None = None,
    record_ids: list[int] | None = None,
) -> None:
    """Bulk-DELETE tracked rows in FK-respecting order.

    Used as the teardown body of a per-file ``cleanup_*`` fixture.
    Order: sections (before drafts so the explicit DELETE is
    independent of the ON DELETE CASCADE) → drafts → materials →
    records → templates → accounts → users → tenants.
    """
    db = SessionLocal()
    try:
        if draft_ids:
            db.query(WxDraftSection).filter(
                WxDraftSection.draft_id.in_(draft_ids)
            ).delete(synchronize_session=False)
            db.commit()
            db.query(WxDraft).filter(
                WxDraft.id.in_(draft_ids)
            ).delete(synchronize_session=False)
            db.commit()
        if material_ids:
            db.query(WxMaterial).filter(
                WxMaterial.id.in_(material_ids)
            ).delete(synchronize_session=False)
            db.commit()
        if record_ids:
            db.query(WxPublishRecord).filter(
                WxPublishRecord.id.in_(record_ids)
            ).delete(synchronize_session=False)
            db.commit()
        if template_ids:
            db.query(WxTemplate).filter(
                WxTemplate.id.in_(template_ids)
            ).delete(synchronize_session=False)
            db.commit()
        if account_ids:
            db.query(WxAccount).filter(
                WxAccount.id.in_(account_ids)
            ).delete(synchronize_session=False)
            db.commit()
        if user_ids:
            db.query(User).filter(
                User.id.in_(user_ids)
            ).delete(synchronize_session=False)
            db.commit()
        if tenant_ids:
            db.query(Tenant).filter(
                Tenant.id.in_(tenant_ids)
            ).delete(synchronize_session=False)
            db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()


# ---- Factories --------------------------------------------------------------

def make_tenant(db, *, suffix: str | None = None) -> Tenant:
    """Create + commit a fresh Tenant row."""
    suffix = suffix or uuid.uuid4().hex[:8]
    t = Tenant(name=f"wxp_t_{suffix}", code=f"wxp_{suffix}")
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


def make_user(
    db, *, tenant_id: int, suffix: str | None = None,
    is_superuser: bool = False,
) -> User:
    """Create + commit a fresh User under the given tenant."""
    suffix = suffix or uuid.uuid4().hex[:8]
    u = User(
        username=f"wxp_u_{suffix}",
        email=f"wxp_{suffix}@test.local",
        hashed_password=get_password_hash("x"),
        tenant_id=tenant_id,
        is_active=True,
        is_superuser=is_superuser,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def make_account(
    db, *, tenant_id: int, user_id: int, suffix: str | None = None,
    app_id: str | None = None,
    is_mock: bool = True,
    app_secret_encrypted: bytes = b"encrypted-secret-bytes",
) -> WxAccount:
    """Create + commit a WxAccount row. AppSecret is supplied as bytes
    (caller can use WxAccountService.encrypt_app_secret() for real enc)."""
    suffix = suffix or uuid.uuid4().hex[:8]
    # 18-32 char app_id matching schema pattern: ``wx`` + 16 chars = 18
    if app_id is None:
        # Use deterministic suffix padded to 16 chars after the ``wx`` prefix
        suffix_padded = suffix.ljust(16, "0")[:16]
        app_id = f"wx{suffix_padded}"
    row = WxAccount(
        tenant_id=tenant_id,
        user_id=user_id,
        app_id=app_id,
        app_secret_encrypted=app_secret_encrypted,
        name=f"wxp_acc_{suffix}",
        account_type="subscription",
        is_mock=is_mock,
        is_active=True,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def make_template(
    db, *, tenant_id: int, user_id: int, suffix: str | None = None,
    is_system: bool = False,
    usage_count: int = 0,
) -> WxTemplate:
    """Create + commit a minimal WxTemplate row."""
    suffix = suffix or uuid.uuid4().hex[:8]
    row = WxTemplate(
        tenant_id=tenant_id,
        name=f"wxp_tpl_{suffix}",
        category="minimal",
        description=None,
        html_body="<p>test template body " + suffix + "</p>",
        css_variables={"primary": "#000"},
        preview_html=None,
        thumbnail=None,
        is_system=is_system,
        created_by=user_id,
        usage_count=usage_count,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def make_draft(
    db, *, tenant_id: int, user_id: int, suffix: str | None = None,
    status: str = "draft",
    account_id: int | None = None,
    template_id: int | None = None,
    content_markdown: str = "hello",
) -> WxDraft:
    """Create + commit a minimal WxDraft row."""
    suffix = suffix or uuid.uuid4().hex[:8]
    row = WxDraft(
        tenant_id=tenant_id,
        user_id=user_id,
        account_id=account_id,
        template_id=template_id,
        title=f"wxp_drft_{suffix}",
        summary=None,
        author=None,
        content_markdown=content_markdown,
        content_html=None,
        status=status,
        tags=None,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def make_section(
    db, *, tenant_id: int, draft_id: int, order_index: int = 0,
    heading: str | None = None,
    content_markdown: str = "section body",
) -> WxDraftSection:
    """Create + commit a WxDraftSection row."""
    row = WxDraftSection(
        tenant_id=tenant_id,
        draft_id=draft_id,
        order_index=order_index,
        heading=heading,
        content_markdown=content_markdown,
        content_html=None,
        ai_prompt=None,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def make_material(
    db, *, tenant_id: int, user_id: int, suffix: str | None = None,
    source_type: str = "manual",
    tags: list[str] | None = None,
) -> WxMaterial:
    """Create + commit a WxMaterial row."""
    suffix = suffix or uuid.uuid4().hex[:8]
    row = WxMaterial(
        tenant_id=tenant_id,
        user_id=user_id,
        title=f"wxp_mat_{suffix}",
        content="material content for " + suffix,
        source_type=source_type,
        kb_chunk_id=None,
        tags=json.dumps(tags) if tags else None,
        is_used=False,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def make_publish_record(
    db, *, tenant_id: int, draft_id: int, account_id: int, user_id: int,
    status: str = "queued", suffix: str | None = None,
) -> WxPublishRecord:
    """Create + commit a WxPublishRecord row."""
    suffix = suffix or uuid.uuid4().hex[:8]
    row = WxPublishRecord(
        tenant_id=tenant_id,
        draft_id=draft_id,
        account_id=account_id,
        user_id=user_id,
        wechat_media_id=None,
        wechat_msg_id=None,
        status=status,
        error_code=None,
        error_message=None,
        duration_ms=None,
        started_at=None,
        completed_at=None,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row
