"""ExternalApp + ExternalVisitor models for the embeddable chat widget.

Field-level documentation lives in
``docs/superpowers/specs/2026-06-08-external-chat-widget-design.md`` § 4.
"""
from sqlalchemy import (
    Column, String, Text, Integer, ForeignKey, DateTime, Boolean, JSON,
    UniqueConstraint, Index,
)
from sqlalchemy.orm import relationship
from datetime import datetime
from lumen_models.base import BaseModel


class ExternalApp(BaseModel):
    """One row = one third-party consumer of the embeddable chat widget.

    The ``app_key`` is the public identifier embedded in the page (safe to
    expose); the ``app_secret_hash`` is bcrypt, never returned to the
    browser. The plain-text secret is returned ONCE at creation time
    (see ``POST /api/v1/external-apps``).
    """
    __tablename__ = "external_apps"

    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    app_key = Column(String(64), nullable=False, unique=True)
    app_secret_hash = Column(String(255), nullable=False)
    allowed_origins = Column(JSON, nullable=False)  # list[str] — exact or "https://*.example.com"
    allowed_agent_ids = Column(JSON, nullable=False, default=list)  # list[int]
    allowed_team_ids = Column(JSON, nullable=False, default=list)  # list[int]
    scopes = Column(
        String(255), nullable=False, default="chat:stream,chat:upload,conv:read"
    )
    rate_limit_per_min = Column(Integer, nullable=False, default=60)
    is_active = Column(Boolean, nullable=False, default=True)
    description = Column(Text, nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    last_used_at = Column(DateTime, nullable=True)

    visitors = relationship(
        "ExternalVisitor", back_populates="app", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_external_apps_tenant_active", "tenant_id", "is_active"),
        Index("ix_external_apps_tenant_created", "tenant_id", "created_at"),
    )


class ExternalVisitor(BaseModel):
    """One row = one client-side visitor UUID seen by a given app.

    The ``visitor_id`` is supplied by the widget (client-trusted but
    persistent — it's stored in localStorage on the visitor's browser).
    Uniqueness is scoped per-app so the same UUID can be reused across
    different widgets on different sites.
    """
    __tablename__ = "external_visitors"

    app_id = Column(Integer, ForeignKey("external_apps.id"), nullable=False, index=True)
    visitor_id = Column(String(64), nullable=False)
    display_name = Column(String(100), nullable=True)
    visitor_metadata = Column("visitor_metadata", JSON, nullable=True)  # renamed in DB to avoid SQLAlchemy reserved `metadata`
    first_seen_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_seen_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    app = relationship("ExternalApp", back_populates="visitors")

    __table_args__ = (
        UniqueConstraint("app_id", "visitor_id", name="uq_external_visitors_app_visitor"),
        Index("ix_external_visitors_app_lastseen", "app_id", "last_seen_at"),
    )
