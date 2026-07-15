"""M32 公众号助手 - 6 张表 model(账号/模板/草稿/章节/素材/发布记录)

Spec: docs/superpowers/specs/2026-06-17-wx-publisher-design.md §3
"""
from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    JSON,
    LargeBinary,
    ForeignKey,
    Boolean,
    DateTime,
    Index,
    UniqueConstraint,
)
from sqlalchemy.dialects.mysql import LONGTEXT, MEDIUMBLOB
from lumen_models.base import BaseModel


class WxAccount(BaseModel):
    __tablename__ = "wx_accounts"

    # tenant_id / id / created_at / updated_at are explicit per-table
    # (BaseModel only provides id + timestamps; tenant_id is a
    # project-wide convention, see models/image_generation.py /
    # models/knowledge.py).
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    app_id = Column(String(50), nullable=False)
    # Spec §3.1: VARBINARY(512) — AppSecret is encrypted with
    # cryptography.fernet before being persisted. SQLAlchemy's
    # ``LargeBinary(length=512)`` maps to VARBINARY(512) in MySQL
    # (same pattern as image_generation.py:34's MEDIUMBLOB thumbnail).
    app_secret_encrypted = Column(
        LargeBinary(length=512),  # type: ignore[arg-type]
        nullable=False,
    )
    name = Column(String(100), nullable=False)
    account_type = Column(String(20), nullable=False, default="subscription")
    is_mock = Column(Boolean, nullable=False, default=True)
    access_token = Column(String(512), nullable=True)
    access_token_expires_at = Column(DateTime, nullable=True)
    ip_whitelist = Column(Text, nullable=True)
    last_verified_at = Column(DateTime, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)

    __table_args__ = (
        # Spec §3.1: UNIQUE(tenant_id, app_id) — same app_id may exist
        # for different tenants but not twice within one tenant.
        UniqueConstraint("tenant_id", "app_id", name="uk_wx_accounts_tenant_appid"),
        Index("idx_wx_accounts_tenant_active", "tenant_id", "is_active"),
    )


class WxTemplate(BaseModel):
    __tablename__ = "wx_templates"

    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    category = Column(String(50), nullable=False, index=True)
    description = Column(String(500), nullable=True)
    # Spec §3.2: LONGTEXT for HTML body (multi-MB templates expected
    # for magazine-style designs). Use MySQL-specific LONGTEXT type so
    # ``Base.metadata.create_all`` produces the right column type on
    # our MySQL deployment.
    html_body = Column(LONGTEXT, nullable=False)
    css_variables = Column(JSON, nullable=False)
    preview_html = Column(LONGTEXT, nullable=True)
    # Spec §3.2: MEDIUMBLOB (16MB cap). 256x256 JPEG ~10-30KB, well under.
    thumbnail = Column(MEDIUMBLOB, nullable=True)
    is_system = Column(Boolean, nullable=False, default=False)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    usage_count = Column(Integer, nullable=False, default=0)

    __table_args__ = (
        Index("idx_wx_templates_tenant_category", "tenant_id", "category"),
    )


class WxDraft(BaseModel):
    __tablename__ = "wx_drafts"

    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    # Spec §3.3: account_id ON DELETE SET NULL — removing the bound
    # account should not cascade-delete the draft (we keep the draft
    # and let the user re-bind a different account).
    account_id = Column(
        Integer,
        ForeignKey("wx_accounts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    template_id = Column(
        Integer,
        ForeignKey("wx_templates.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    title = Column(String(200), nullable=False)
    summary = Column(String(500), nullable=True)
    author = Column(String(50), nullable=True)
    content_markdown = Column(LONGTEXT, nullable=False)
    content_html = Column(LONGTEXT, nullable=True)
    # Spec §3.3: cover_image_id FK to generated_images, SET NULL on delete.
    cover_image_id = Column(
        Integer,
        ForeignKey("generated_images.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    cover_url = Column(String(500), nullable=True)
    status = Column(String(20), nullable=False, default="draft", index=True)
    # Spec §3.3: kb_id FK to knowledge_bases, SET NULL on delete.
    kb_id = Column(
        Integer,
        ForeignKey("knowledge_bases.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    tags = Column(JSON, nullable=True)
    scheduled_at = Column(DateTime, nullable=True, index=True)
    published_at = Column(DateTime, nullable=True)
    wechat_media_id = Column(String(100), nullable=True)
    error_message = Column(Text, nullable=True)

    __table_args__ = (
        Index("idx_wx_drafts_tenant_status", "tenant_id", "status"),
        Index("idx_wx_drafts_tenant_updated", "tenant_id", "updated_at"),
    )


class WxDraftSection(BaseModel):
    __tablename__ = "wx_draft_sections"

    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    # Spec §3.4: draft_id ON DELETE CASCADE — sections are owned by their
    # draft; deleting a draft sweeps its sections atomically.
    draft_id = Column(
        Integer,
        ForeignKey("wx_drafts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    order_index = Column(Integer, nullable=False)
    heading = Column(String(200), nullable=True)
    content_markdown = Column(LONGTEXT, nullable=False)
    content_html = Column(LONGTEXT, nullable=True)
    ai_prompt = Column(Text, nullable=True)
    # Spec §3.4: ai_model_config_id FK to model_configs, SET NULL on delete
    # (deleting an old model shouldn't nuke section history).
    ai_model_config_id = Column(
        Integer,
        ForeignKey("model_configs.id", ondelete="SET NULL"),
        nullable=True,
    )

    __table_args__ = (
        # Spec §3.4: UNIQUE(draft_id, order_index) — each section slot
        # is unique within a draft so we can address sections by
        # (draft_id, order_index) without ambiguity.
        UniqueConstraint(
            "draft_id", "order_index", name="uk_wx_draft_sections_draft_order"
        ),
    )


class WxMaterial(BaseModel):
    __tablename__ = "wx_materials"

    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    title = Column(String(200), nullable=False)
    content = Column(LONGTEXT, nullable=False)
    source_type = Column(String(20), nullable=False, index=True)
    # Spec §3.5: kb_chunk_id FK to document_chunks, SET NULL on delete
    # (deleting a KB chunk shouldn't cascade-delete the material —
    # the material still has its own copy of the content).
    kb_chunk_id = Column(
        Integer,
        ForeignKey("document_chunks.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    tags = Column(JSON, nullable=True)
    is_used = Column(Boolean, nullable=False, default=False)

    __table_args__ = (
        Index("idx_wx_materials_tenant_source", "tenant_id", "source_type"),
    )


class WxPublishRecord(BaseModel):
    __tablename__ = "wx_publish_records"

    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    # Spec §3.6: draft_id ON DELETE CASCADE — the publish record is
    # useless without its source draft, and "soft-deleted" drafts are
    # handled via wx_drafts.status, not row deletion.
    draft_id = Column(
        Integer,
        ForeignKey("wx_drafts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Spec §3.6: account_id ON DELETE RESTRICT — never allow an account
    # to be hard-deleted while publish history still references it
    # (audit trail integrity).
    account_id = Column(
        Integer,
        ForeignKey("wx_accounts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    wechat_media_id = Column(String(100), nullable=True)
    wechat_msg_id = Column(String(100), nullable=True)
    status = Column(String(20), nullable=False, index=True)
    error_code = Column(String(50), nullable=True)
    error_message = Column(Text, nullable=True)
    duration_ms = Column(Integer, nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
