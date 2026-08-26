"""M38.2: Workspace service layer.

Encapsulates the SQL behind the workspace API endpoints. Tenant
isolation is enforced by every method that touches a row — admin
cross-tenant access is a deliberate decision left to the API
layer (which passes ``is_superuser`` through and skips the tenant
filter).

The service also owns the "tree" query that the sidebar needs in
one round-trip: ``get_workspace_tree`` pulls KBs + folders + doc
counts with three SQL statements (no recursion; the tree shape is
built in Python) — the spec §5.2 N+1 mitigation.

Spec: ``docs-internal/superpowers/specs/2026-08-26-kb-workspace-folder.md``
§ 5.1, § 5.2.
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from lumen_models.knowledge import Document, KnowledgeBase
from lumen_models.workspace import DocumentFolder, Workspace
from lumen_schemas.workspace import (
    FolderTreeNode,
    KnowledgeBaseTreeNode,
    WorkspaceCreate,
    WorkspaceRead,
    WorkspaceTreeResponse,
    WorkspaceUpdate,
)
from lumen_schemas.document_folder import DocumentFolderTreeNode

logger = logging.getLogger(__name__)


class WorkspaceService:
    """Stateless service — instantiate per-request or share via DI."""

    # --- list -----------------------------------------------------------

    def list_workspaces(
        self,
        db: Session,
        tenant_id: int,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[List[WorkspaceRead], int]:
        """Paginated list of workspaces in a tenant.

        Returns ``(items, total)`` so the API layer can wrap it in
        ``PaginatedResponse``. ``knowledge_base_count`` is filled
        in via a single GROUP BY — same N+1 avoidance as
        ``KnowledgeService.list_knowledge_bases``.
        """
        query = db.query(Workspace).filter(Workspace.tenant_id == tenant_id)
        total = query.count()
        rows = (
            query.order_by(Workspace.created_at.asc(), Workspace.id.asc())
            .offset(max(0, (page - 1) * page_size))
            .limit(page_size)
            .all()
        )
        if not rows:
            return [], total
        kb_counts = dict(
            db.query(KnowledgeBase.workspace_id, func.count(KnowledgeBase.id))
            .filter(KnowledgeBase.workspace_id.in_([w.id for w in rows]))
            .group_by(KnowledgeBase.workspace_id)
            .all()
        )
        out: List[WorkspaceRead] = []
        for ws in rows:
            ws.knowledge_base_count = kb_counts.get(ws.id, 0)
            out.append(WorkspaceRead.model_validate(ws))
        return out, total

    # --- create / read / update / delete --------------------------------

    def create_workspace(
        self,
        db: Session,
        tenant_id: int,
        data: WorkspaceCreate,
        owner_id: Optional[int] = None,
    ) -> WorkspaceRead:
        """Create a workspace.

        Raises ``409 Conflict`` when (tenant_id, name) collides
        with an existing row (the DB enforces the unique key; we
        translate the IntegrityError into a clean HTTP error so
        the frontend can show "该租户下已存在同名 workspace").
        """
        from sqlalchemy.exc import IntegrityError

        ws = Workspace(
            tenant_id=tenant_id,
            name=data.name,
            description=data.description,
            icon=data.icon,
            color=data.color,
            owner_id=owner_id,
        )
        db.add(ws)
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            raise HTTPException(
                status_code=409,
                detail=f"该租户下已存在同名 workspace: {data.name!r}",
            ) from exc
        db.refresh(ws)
        ws.knowledge_base_count = 0
        return WorkspaceRead.model_validate(ws)

    def get_workspace(
        self,
        db: Session,
        workspace_id: int,
        tenant_id: int,
        is_superuser: bool = False,
    ) -> Optional[WorkspaceRead]:
        """Single workspace; ``None`` when not found.

        Admins (``is_superuser=True``) skip the tenant filter; non-
        admins always get tenant-scoped results.
        """
        q = db.query(Workspace).filter(Workspace.id == workspace_id)
        if not is_superuser:
            q = q.filter(Workspace.tenant_id == tenant_id)
        ws = q.first()
        if ws is None:
            return None
        ws.knowledge_base_count = (
            db.query(func.count(KnowledgeBase.id))
            .filter(KnowledgeBase.workspace_id == ws.id)
            .scalar()
            or 0
        )
        return WorkspaceRead.model_validate(ws)

    def update_workspace(
        self,
        db: Session,
        workspace_id: int,
        tenant_id: int,
        data: WorkspaceUpdate,
        is_superuser: bool = False,
    ) -> Optional[WorkspaceRead]:
        """Patch a workspace. Owner-or-admin only is enforced at the API layer.

        Returns ``None`` when the row isn't visible to the caller.
        Name uniqueness still triggers 409 on conflict.
        """
        from sqlalchemy.exc import IntegrityError

        q = db.query(Workspace).filter(Workspace.id == workspace_id)
        if not is_superuser:
            q = q.filter(Workspace.tenant_id == tenant_id)
        ws = q.first()
        if ws is None:
            return None
        updates = data.model_dump(exclude_unset=True)
        for field, value in updates.items():
            setattr(ws, field, value)
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            raise HTTPException(
                status_code=409,
                detail=f"该租户下已存在同名 workspace: {data.name!r}",
            ) from exc
        db.refresh(ws)
        ws.knowledge_base_count = (
            db.query(func.count(KnowledgeBase.id))
            .filter(KnowledgeBase.workspace_id == ws.id)
            .scalar()
            or 0
        )
        return WorkspaceRead.model_validate(ws)

    def delete_workspace(
        self,
        db: Session,
        workspace_id: int,
        tenant_id: int,
        is_superuser: bool = False,
    ) -> bool:
        """Hard-delete a workspace.

        KBs hanging off it survive (``workspace_id`` is ON DELETE
        SET NULL on the FK). Returns ``True`` when a row was
        deleted, ``False`` when the workspace wasn't visible to
        the caller.
        """
        q = db.query(Workspace).filter(Workspace.id == workspace_id)
        if not is_superuser:
            q = q.filter(Workspace.tenant_id == tenant_id)
        ws = q.first()
        if ws is None:
            return False
        db.delete(ws)
        db.commit()
        return True

    # --- tree -----------------------------------------------------------

    def get_workspace_tree(
        self,
        db: Session,
        workspace_id: int,
        tenant_id: int,
        is_superuser: bool = False,
    ) -> Optional[WorkspaceTreeResponse]:
        """Single round-trip tree response for the sidebar.

        Three SQL statements total:
        1. KBs (filtered by ``workspace_id``)
        2. Folders under those KBs (``deleted_at IS NULL``)
        3. Document counts grouped by ``knowledge_base_id`` AND
           ``folder_id`` — assembled into KB-root and per-folder
           counts in Python.

        No recursion, no N+1. Tree shape built from a dict keyed by
        ``(kb_id, parent_id)``.
        """
        q = db.query(Workspace).filter(Workspace.id == workspace_id)
        if not is_superuser:
            q = q.filter(Workspace.tenant_id == tenant_id)
        ws = q.first()
        if ws is None:
            return None
        ws.knowledge_base_count = (
            db.query(func.count(KnowledgeBase.id))
            .filter(KnowledgeBase.workspace_id == ws.id)
            .scalar()
            or 0
        )

        kbs = (
            db.query(KnowledgeBase)
            .filter(KnowledgeBase.workspace_id == ws.id)
            .order_by(KnowledgeBase.created_at.asc(), KnowledgeBase.id.asc())
            .all()
        )
        if not kbs:
            return WorkspaceTreeResponse(
                workspace=WorkspaceRead.model_validate(ws),
                knowledge_bases=[],
            )

        kb_ids = [kb.id for kb in kbs]
        folders = (
            db.query(DocumentFolder)
            .filter(
                DocumentFolder.knowledge_base_id.in_(kb_ids),
                DocumentFolder.deleted_at.is_(None),
            )
            .order_by(
                DocumentFolder.knowledge_base_id.asc(),
                DocumentFolder.parent_id.asc().nulls_first(),
                DocumentFolder.order_index.asc(),
                DocumentFolder.id.asc(),
            )
            .all()
        )

        # Doc counts in one GROUP BY (kb_id, folder_id). folder_id
        # NULL = KB-root documents; non-NULL = inside that folder.
        doc_count_rows = (
            db.query(
                Document.knowledge_base_id,
                Document.folder_id,
                func.count(Document.id),
            )
            .filter(Document.knowledge_base_id.in_(kb_ids))
            .group_by(Document.knowledge_base_id, Document.folder_id)
            .all()
        )
        kb_root_counts: Dict[int, int] = {}
        folder_counts: Dict[int, int] = {}
        for kb_id, folder_id, cnt in doc_count_rows:
            if folder_id is None:
                kb_root_counts[kb_id] = cnt
            else:
                folder_counts[folder_id] = cnt

        # Build folder tree per KB. ``parent_id`` is None for top-
        # level rows; children attach under their parent_id.
        nodes: Dict[int, DocumentFolderTreeNode] = {}
        kb_top_level: Dict[int, List[DocumentFolderTreeNode]] = {kb.id: [] for kb in kbs}
        for f in folders:
            n = DocumentFolderTreeNode(
                id=f.id,
                name=f.name,
                description=f.description,
                order_index=f.order_index,
                parent_id=f.parent_id,
                children=[],
                document_count=folder_counts.get(f.id, 0),
            )
            nodes[f.id] = n
            if f.parent_id is None:
                kb_top_level[f.knowledge_base_id].append(n)
            else:
                parent = nodes.get(f.parent_id)
                if parent is not None:
                    parent.children.append(n)
                else:
                    # Orphan: parent is missing or already deleted.
                    # Fall back to KB root so the user still sees
                    # the folder — better than silently dropping it.
                    kb_top_level.setdefault(f.knowledge_base_id, []).append(n)

        kb_nodes: List[KnowledgeBaseTreeNode] = []
        for kb in kbs:
            kb_nodes.append(KnowledgeBaseTreeNode(
                id=kb.id,
                name=kb.name,
                description=kb.description,
                # ``KnowledgeBaseBase`` doesn't model icon/color —
                # those live on the workspace layer only.
                folders=[
                    FolderTreeNode(
                        id=n.id,
                        name=n.name,
                        description=n.description,
                        icon=None,
                        color=None,
                        children=[
                            FolderTreeNode(
                                id=c.id,
                                name=c.name,
                                description=c.description,
                                icon=None,
                                color=None,
                                children=[],  # depth = 2 for now;
                                              # recursive renderer
                                              # in the frontend
                                              # walks deeper if
                                              # needed.
                                document_count=c.document_count,
                            ) for c in n.children
                        ],
                        document_count=n.document_count,
                    ) for n in kb_top_level.get(kb.id, [])
                ],
                document_count=kb_root_counts.get(kb.id, 0),
            ))

        return WorkspaceTreeResponse(
            workspace=WorkspaceRead.model_validate(ws),
            knowledge_bases=kb_nodes,
        )


workspace_service = WorkspaceService()
