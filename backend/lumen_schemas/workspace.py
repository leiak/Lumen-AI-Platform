"""M38.2: Workspace Pydantic schemas.

Two CRUD pairs (Create + Read + Update) plus a tree-shape
``WorkspaceTreeResponse`` for the ``/tree`` endpoint that the
sidebar consumes as a single round-trip.

The schemas are intentionally thin — all tenant-isolation checks
happen in the service layer (mirrors the project's "tenant_id
is the only authoritative isolation boundary" rule).

Spec: ``docs-internal/superpowers/specs/2026-08-26-kb-workspace-folder.md``
§ 4.1.
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class WorkspaceCreate(BaseModel):
    """Body for ``POST /api/v1/workspaces``."""

    name: str = Field(..., min_length=1, max_length=100, description="Workspace display name; unique per tenant.")
    description: Optional[str] = Field(None, description="Free-form blurb shown in the sidebar hover tooltip.")
    icon: Optional[str] = Field(None, max_length=50, description="Emoji or antd icon key.")
    color: Optional[str] = Field(None, max_length=20, description="Hex colour for the sidebar badge.")


class WorkspaceUpdate(BaseModel):
    """Body for ``PUT /api/v1/workspaces/{id}``.

    All fields optional — unset fields are left untouched, matching
    the existing ``KnowledgeBaseUpdate`` pattern.
    """

    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = None
    icon: Optional[str] = Field(None, max_length=50)
    color: Optional[str] = Field(None, max_length=20)


class WorkspaceRead(BaseModel):
    """Single workspace — returned by GET single + list endpoints."""

    id: int
    tenant_id: int
    name: str
    description: Optional[str] = None
    owner_id: Optional[int] = None
    icon: Optional[str] = None
    color: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    # Number of KBs hanging off this workspace. Populated by the
    # service layer via a single GROUP BY query; surfaced so the
    # sidebar can show "研发组 (12 KBs)" without a second fetch.
    knowledge_base_count: int = 0

    class Config:
        from_attributes = True


class FolderTreeNode(BaseModel):
    """One node in the workspace tree.

    Holds KB metadata + the top-level folder list (children are
    nested under each folder entry). The frontend ``WorkspaceTree``
    component renders this directly — no client-side reshaping.
    """

    id: int
    name: str
    description: Optional[str] = None
    icon: Optional[str] = None
    color: Optional[str] = None
    # Top-level folders inside this KB (parent_id IS NULL). Nested
    # children are walked recursively by the service layer.
    folders: List["FolderTreeNode"] = Field(default_factory=list)
    # Flat list of documents at the KB root (folder_id IS NULL).
    # The sidebar uses this for the badge count; the right-pane
    # doc table re-fetches with a folder_id filter when the user
    # drills in.
    document_count: int = 0


class KnowledgeBaseTreeNode(BaseModel):
    """One KB node inside ``WorkspaceTree.kbs``."""

    id: int
    name: str
    description: Optional[str] = None
    # Top-level folders inside this KB. The tree shape matches
    # ``FolderTreeNode`` so the sidebar component only needs one
    # recursive renderer.
    folders: List[FolderTreeNode] = Field(default_factory=list)
    # Documents at the KB root (folder_id IS NULL).
    document_count: int = 0


class WorkspaceTreeResponse(BaseModel):
    """Response for ``GET /api/v1/workspaces/{id}/tree``.

    Single round-trip payload the sidebar renders without further
    fetches. Avoids the N+1 trap of "list KBs → list folders per KB
    → list docs per folder".
    """

    workspace: WorkspaceRead
    knowledge_bases: List[KnowledgeBaseTreeNode] = Field(default_factory=list)


# Resolve the forward reference ``FolderTreeNode`` makes inside its
# own definition. Pydantic v2 needs the post-hoc rebuild because
# the recursive annotation is only resolvable once both types exist.
FolderTreeNode.model_rebuild()
