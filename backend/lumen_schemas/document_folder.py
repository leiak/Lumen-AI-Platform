"""M38.2: DocumentFolder Pydantic schemas.

CRUD pairs (Create / Update / Read) plus a tree-shape
``FolderTreeNode`` for the ``?tree=true`` list response. The
``FolderRead`` carries the ``path`` field (computed ancestor chain)
so the breadcrumb can render without an extra round-trip.

Spec: ``docs-internal/superpowers/specs/2026-08-26-kb-workspace-folder.md``
§ 4.2.
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class DocumentFolderCreate(BaseModel):
    """Body for ``POST /api/v1/knowledge/{kb_id}/folders``."""

    name: str = Field(..., min_length=1, max_length=100, description="Folder display name.")
    parent_id: Optional[int] = Field(None, description="Parent folder id; NULL = KB root.")
    description: Optional[str] = None
    order_index: Optional[int] = Field(0, description="Sibling ordering; lower numbers first.")


class DocumentFolderUpdate(BaseModel):
    """Body for ``PUT /api/v1/folders/{id}``.

    Move (change ``parent_id``) is allowed; the service layer
    rejects moves that would create a cycle (a folder cannot be a
    descendant of itself).
    """

    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = None
    parent_id: Optional[int] = Field(None, description="New parent; NULL = move to KB root.")
    order_index: Optional[int] = None


class DocumentFolderRead(BaseModel):
    """Single folder — returned by GET single + list endpoints."""

    id: int
    knowledge_base_id: int
    parent_id: Optional[int] = None
    name: str
    description: Optional[str] = None
    order_index: int = 0
    created_by: Optional[int] = None
    # NULL = active row; non-NULL = soft-delete tombstone. List
    # endpoints filter this out; the read endpoint surfaces it so
    # the "Recently Deleted" UI can decide whether to offer a
    # restore button.
    deleted_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    # Ancestor chain rendered as "研发 / 后端 / API 规范". Computed
    # by the service layer via a single BFS up the tree.
    path: Optional[str] = None
    # Document count inside this folder. Populated by the service
    # layer; used by the sidebar badge.
    document_count: int = 0

    class Config:
        from_attributes = True


class DocumentFolderTreeNode(BaseModel):
    """Recursive node for ``GET /knowledge/{kb_id}/folders?tree=true``."""

    id: int
    name: str
    description: Optional[str] = None
    order_index: int = 0
    parent_id: Optional[int] = None
    children: List["DocumentFolderTreeNode"] = Field(default_factory=list)
    document_count: int = 0


# Forward-reference rebuild (Pydantic v2 needs the post-hoc
# resolution for recursive annotations).
DocumentFolderTreeNode.model_rebuild()
