"""M38.2: Workspace + DocumentFolder ORM models.

Two lightweight navigation primitives layered on top of the
existing tenant → KB → Document hierarchy:

- ``Workspace`` groups KBs inside a tenant. NOT a permission boundary
  in this MVP — the spec explicitly defers RBAC to a later release.
  The intent is purely UX (sidebar tree, breadcrumb) and structural
  (so an enterprise tenant can carve its 30+ KBs into 研发/产品/HR
  groups without resorting to multiple sub-tenants).

- ``DocumentFolder`` is a tree inside a single KB. Strictly
  belongs to one KB (no cross-KB sharing in MVP). Soft-deleted via
  ``deleted_at`` so accidental deletes can be restored within a
  retention window.

Backward compat:
- ``KnowledgeBase.workspace_id`` is nullable; NULL = the KB hangs
  directly off the tenant (the pre-M38.2 world).
- ``Document.folder_id`` is nullable; NULL = the document sits at
  the KB root.

Spec: ``docs-internal/superpowers/specs/2026-08-26-kb-workspace-folder.md``
§ 3.
"""
from __future__ import annotations

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from lumen_models.base import BaseModel


class Workspace(BaseModel):
    """M38.2: navigation/aggregation root inside a tenant.

    Owns zero or more ``KnowledgeBase`` rows via the
    ``KnowledgeBase.workspace_id`` FK. Deleting a workspace leaves
    the KBs intact (ON DELETE SET NULL on the FK) — the workspace
    is purely structural.
    """

    __tablename__ = "workspaces"

    # Tenant ownership. Mirrors ``KnowledgeBase.tenant_id`` and the
    # project's "every navigable entity lives inside a tenant"
    # convention. ON DELETE CASCADE so deleting a tenant cleans
    # up its workspaces.
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    # Display name shown in the sidebar. Combined with tenant_id
    # in a unique constraint so two workspaces inside the same
    # tenant can't share a name (the spec §3.1 rule).
    name = Column(String(100), nullable=False)
    # Free-form description / purpose blurb. Helps the sidebar
    # hover tooltip say what a workspace is for.
    description = Column(Text, nullable=True)
    # Creator. Nullable + SET NULL so deleting a user doesn't
    # cascade-delete their workspaces — the tenant still owns
    # the rows.
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    # Free-form icon key (emoji or antd icon name) and color hex.
    # No validation on the front-end side; the UI picks a fallback
    # if the value doesn't parse.
    icon = Column(String(50), nullable=True)
    color = Column(String(20), nullable=True)

    # No SQL-level unique constraint here — the DB-side
    # ``uq_workspaces_tenant_name`` is created by
    # ``ensure_workspaces_table()`` (information_schema-gated
    # ALTER TABLE) and surfaces as a 409 on duplicate names.
    # Adding a ``UniqueConstraint`` here would force the ORM to
    # expect it to exist; keeping the column definition simple
    # matches the project's ensure_* pattern for everything else.


class DocumentFolder(BaseModel):
    """M38.2: tree node inside a single KB.

    Self-referential via ``parent_id``; NULL = KB root. Soft-deleted
    via ``deleted_at`` so restore is possible without resurrecting
    a hard delete. Children of a soft-deleted folder are
    soft-deleted too (BFS cascade, see ``folder_service``).
    """

    __tablename__ = "document_folders"

    # KB ownership. ON DELETE CASCADE — dropping a KB drops its
    # folder tree (and the FK ON DELETE SET NULL on
    # ``documents.folder_id`` cleans up the document rows).
    knowledge_base_id = Column(Integer, ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False)
    # Parent folder. Self-FK with ON DELETE CASCADE so removing
    # a parent recursively removes children (the SQL is the
    # safety net; the service-layer BFS does the soft delete
    # in a single UPDATE for visibility).
    parent_id = Column(Integer, ForeignKey("document_folders.id", ondelete="CASCADE"), nullable=True)
    # Display name. Forward slashes rejected at the API layer
    # (spec §9.2 — UX ambiguity with path parsing).
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    # Sibling ordering. Lower numbers first; equal numbers fall
    # back to id. ``order_index`` is independent of name so the
    # user can pin a hot folder to the top without renaming.
    order_index = Column(Integer, default=0, nullable=False)
    # Creator. Nullable + SET NULL for the same reason as
    # ``Workspace.owner_id``.
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    # Soft-delete tombstone. NULL = active; non-NULL = the
    # deletion timestamp. List endpoints filter
    # ``deleted_at IS NULL``.
    deleted_at = Column(DateTime, nullable=True)
