"""M38.2: DocumentFolder service layer.

Folder CRUD + soft delete with cascading children + restore.
Tenant isolation is enforced via the parent KB's ``tenant_id``
(spec §1.3: ``KnowledgeBase.tenant_id`` remains the source of
truth for isolation even after workspace is introduced).

The BFS soft delete lives here rather than relying on the
``ON DELETE CASCADE`` self-FK because:

1. CASCADE is hard-delete; spec §4.2 mandates soft delete with a
   30-day restore window.
2. Surfacing the count of affected folders in the API response
   is much easier when the service does the work itself.

Spec: ``docs-internal/superpowers/specs/2026-08-26-kb-workspace-folder.md``
§ 4.2, § 5.2.
"""
from __future__ import annotations

import logging
from collections import deque
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from lumen_models.knowledge import Document, KnowledgeBase
from lumen_models.workspace import DocumentFolder
from lumen_schemas.document_folder import (
    DocumentFolderCreate,
    DocumentFolderRead,
    DocumentFolderTreeNode,
    DocumentFolderUpdate,
)

logger = logging.getLogger(__name__)


def _assert_kb_visible(kb: Optional[KnowledgeBase], tenant_id: int, is_superuser: bool) -> None:
    """Tenant-isolation helper — 404s when the KB isn't visible.

    Spec §1.3: workspaces are navigation only, ``KnowledgeBase.
    tenant_id`` stays the authority for isolation.
    """
    if kb is None:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    if not is_superuser and kb.tenant_id != tenant_id:
        # Treat cross-tenant access as 404 to avoid leaking the
        # existence of the row.
        raise HTTPException(status_code=404, detail="Knowledge base not found")


class FolderService:
    """Stateless service for folder CRUD + soft-delete + restore."""

    # --- list / tree ----------------------------------------------------

    def list_folders(
        self,
        db: Session,
        kb_id: int,
        tenant_id: int,
        is_superuser: bool = False,
        tree: bool = False,
    ) -> List:
        """List folders under a KB.

        ``tree=True`` returns the nested ``DocumentFolderTreeNode``
        shape; default is the flat list (one row per folder).
        Filters out soft-deleted rows.
        """
        kb = db.get(KnowledgeBase, kb_id)
        _assert_kb_visible(kb, tenant_id, is_superuser)

        rows = (
            db.query(DocumentFolder)
            .filter(
                DocumentFolder.knowledge_base_id == kb_id,
                DocumentFolder.deleted_at.is_(None),
            )
            .order_by(
                DocumentFolder.parent_id.asc().nulls_first(),
                DocumentFolder.order_index.asc(),
                DocumentFolder.id.asc(),
            )
            .all()
        )
        if not tree:
            return [
                DocumentFolderRead.model_validate(_with_doc_count(db, f))
                for f in rows
            ]

        # Document counts in one GROUP BY (folder_id). folder_id
        # NULL rows are ignored — the list endpoint surfaces
        # KB-root counts separately if needed.
        folder_ids = [f.id for f in rows]
        folder_counts: Dict[int, int] = {}
        if folder_ids:
            for fid, cnt in (
                db.query(Document.folder_id, func.count(Document.id))
                .filter(Document.folder_id.in_(folder_ids))
                .group_by(Document.folder_id)
                .all()
            ):
                folder_counts[fid] = cnt

        nodes: Dict[int, DocumentFolderTreeNode] = {}
        for f in rows:
            nodes[f.id] = DocumentFolderTreeNode(
                id=f.id,
                name=f.name,
                description=f.description,
                order_index=f.order_index,
                parent_id=f.parent_id,
                children=[],
                document_count=folder_counts.get(f.id, 0),
            )
        roots: List[DocumentFolderTreeNode] = []
        for f in rows:
            n = nodes[f.id]
            if f.parent_id is None:
                roots.append(n)
            else:
                parent = nodes.get(f.parent_id)
                if parent is not None:
                    parent.children.append(n)
                else:
                    # Orphan: parent missing or already deleted.
                    # Promote to root rather than dropping.
                    roots.append(n)
        return roots

    # --- single get ----------------------------------------------------

    def get_folder(
        self,
        db: Session,
        folder_id: int,
        tenant_id: int,
        is_superuser: bool = False,
    ) -> Optional[DocumentFolderRead]:
        """Single folder including the ancestor path string.

        ``path`` is computed via a single BFS up the tree; soft-
        deleted folders are still readable so the "Recently
        Deleted" UI can show them.
        """
        folder = db.get(DocumentFolder, folder_id)
        if folder is None:
            return None
        kb = db.get(KnowledgeBase, folder.knowledge_base_id)
        _assert_kb_visible(kb, tenant_id, is_superuser)
        folder.document_count = (
            db.query(func.count(Document.id))
            .filter(Document.folder_id == folder_id)
            .scalar()
            or 0
        )
        folder.path = _compute_path(db, folder)
        return DocumentFolderRead.model_validate(folder)

    # --- create --------------------------------------------------------

    def create_folder(
        self,
        db: Session,
        kb_id: int,
        tenant_id: int,
        data: DocumentFolderCreate,
        created_by: Optional[int] = None,
        is_superuser: bool = False,
    ) -> DocumentFolderRead:
        """Create a folder under a KB.

        Parent (if any) must belong to the same KB and not be
        soft-deleted. Cycle protection doesn't apply at create
        time (a folder has no descendants yet).
        """
        kb = db.get(KnowledgeBase, kb_id)
        _assert_kb_visible(kb, tenant_id, is_superuser)

        if data.parent_id is not None:
            parent = db.get(DocumentFolder, data.parent_id)
            if parent is None:
                raise HTTPException(status_code=400, detail="parent_id folder 不存在")
            if parent.knowledge_base_id != kb_id:
                raise HTTPException(
                    status_code=400,
                    detail="parent_id 与目标 KB 不一致",
                )
            if parent.deleted_at is not None:
                raise HTTPException(status_code=400, detail="parent_id 已被软删")

        folder = DocumentFolder(
            knowledge_base_id=kb_id,
            parent_id=data.parent_id,
            name=data.name,
            description=data.description,
            order_index=data.order_index or 0,
            created_by=created_by,
        )
        db.add(folder)
        db.commit()
        db.refresh(folder)
        folder.document_count = 0
        folder.path = _compute_path(db, folder)
        return DocumentFolderRead.model_validate(folder)

    # --- update --------------------------------------------------------

    def update_folder(
        self,
        db: Session,
        folder_id: int,
        tenant_id: int,
        data: DocumentFolderUpdate,
        is_superuser: bool = False,
    ) -> Optional[DocumentFolderRead]:
        """Patch a folder.

        Re-parenting (changing ``parent_id``) rejects cycles: a
        folder cannot be moved under one of its own descendants.
        """
        folder = db.get(DocumentFolder, folder_id)
        if folder is None:
            return None
        kb = db.get(KnowledgeBase, folder.knowledge_base_id)
        _assert_kb_visible(kb, tenant_id, is_superuser)

        updates = data.model_dump(exclude_unset=True)

        if "parent_id" in updates:
            new_parent_id = updates["parent_id"]
            if new_parent_id is not None:
                parent = db.get(DocumentFolder, new_parent_id)
                if parent is None:
                    raise HTTPException(status_code=400, detail="parent_id folder 不存在")
                if parent.knowledge_base_id != folder.knowledge_base_id:
                    raise HTTPException(
                        status_code=400,
                        detail="parent_id 与目标 KB 不一致",
                    )
                if parent.deleted_at is not None:
                    raise HTTPException(status_code=400, detail="parent_id 已被软删")
                # Cycle check — is the new parent somewhere inside
                # the subtree rooted at ``folder_id``? If yes, the
                # move would create a cycle (folder → descendant →
                # ... → new_parent → folder).
                if _is_descendant(db, ancestor=folder_id, target=new_parent_id):
                    raise HTTPException(
                        status_code=400,
                        detail="不能将 folder 移动到自己的子目录下",
                    )
            folder.parent_id = new_parent_id

        for field in ("name", "description", "order_index"):
            if field in updates and updates[field] is not None:
                setattr(folder, field, updates[field])

        db.commit()
        db.refresh(folder)
        folder.document_count = (
            db.query(func.count(Document.id))
            .filter(Document.folder_id == folder_id)
            .scalar()
            or 0
        )
        folder.path = _compute_path(db, folder)
        return DocumentFolderRead.model_validate(folder)

    # --- soft delete ---------------------------------------------------

    def soft_delete_folder(
        self,
        db: Session,
        folder_id: int,
        tenant_id: int,
        is_superuser: bool = False,
    ) -> Tuple[int, int]:
        """Soft-delete a folder + all its descendants.

        Returns ``(scanned_folder_count, deleted_count)``:
        - ``scanned_folder_count`` is the size of the BFS
          subtree, regardless of how many were already
          soft-deleted;
        - ``deleted_count`` is how many rows the UPDATE flipped
          from active to deleted.

        ``documents.folder_id`` is set to NULL by the FK ON
        DELETE SET NULL — but that's a hard delete trigger,
        which we don't fire here. The migration script
        (``scripts/hard_delete_old_soft_folders.py``) handles
        the eventual hard delete after the retention window;
        that hook is out of scope for the M38.2 MVP.
        """
        folder = db.get(DocumentFolder, folder_id)
        if folder is None:
            raise HTTPException(status_code=404, detail="Folder not found")
        kb = db.get(KnowledgeBase, folder.knowledge_base_id)
        _assert_kb_visible(kb, tenant_id, is_superuser)

        all_ids = _bfs_descendants(db, folder_id)
        if not all_ids:
            return 0, 0
        now = datetime.now(timezone.utc)
        # Direct UPDATE — bypasses ORM session per-row write.
        # ``deleted_at IS NULL`` guard means re-deleting an
        # already-deleted folder is a no-op.
        result = db.execute(
            DocumentFolder.__table__.update()
            .where(
                DocumentFolder.id.in_(all_ids),
                DocumentFolder.deleted_at.is_(None),
            )
            .values(deleted_at=now)
        )
        db.commit()
        return len(all_ids), result.rowcount or 0

    # --- restore -------------------------------------------------------

    def restore_folder(
        self,
        db: Session,
        folder_id: int,
        tenant_id: int,
        is_superuser: bool = False,
    ) -> Optional[DocumentFolderRead]:
        """Restore a soft-deleted folder (within the 30-day window).

        Spec §8 risk: the 30-day window is not enforced by the
        service yet — that's a follow-up Celery beat job. We
        surface the ``deleted_at`` field on the read response so
        the frontend can grey out restores older than the window.
        """
        folder = db.get(DocumentFolder, folder_id)
        if folder is None:
            return None
        kb = db.get(KnowledgeBase, folder.knowledge_base_id)
        _assert_kb_visible(kb, tenant_id, is_superuser)
        if folder.deleted_at is None:
            # Already active — return as-is, no error.
            folder.document_count = (
                db.query(func.count(Document.id))
                .filter(Document.folder_id == folder_id)
                .scalar()
                or 0
            )
            folder.path = _compute_path(db, folder)
            return DocumentFolderRead.model_validate(folder)
        folder.deleted_at = None
        db.commit()
        db.refresh(folder)
        folder.document_count = (
            db.query(func.count(Document.id))
            .filter(Document.folder_id == folder_id)
            .scalar()
            or 0
        )
        folder.path = _compute_path(db, folder)
        return DocumentFolderRead.model_validate(folder)

    # --- document move -------------------------------------------------

    def move_document(
        self,
        db: Session,
        document_id: int,
        target_folder_id: Optional[int],
        tenant_id: int,
        is_superuser: bool = False,
    ) -> bool:
        """Move a document into a folder (or KB root when ``target_folder_id`` is None).

        Returns ``True`` when the row was updated. ``False`` when
        the document isn't visible to the caller (treated as
        404 upstream — never leak cross-tenant existence).
        """
        doc = db.get(Document, document_id)
        if doc is None:
            return False
        kb = db.get(KnowledgeBase, doc.knowledge_base_id)
        _assert_kb_visible(kb, tenant_id, is_superuser)

        if target_folder_id is not None:
            target = db.get(DocumentFolder, target_folder_id)
            if target is None:
                raise HTTPException(status_code=400, detail="目标 folder 不存在")
            if target.knowledge_base_id != doc.knowledge_base_id:
                raise HTTPException(
                    status_code=400,
                    detail="目标 folder 不属于同一 KB",
                )
            if target.deleted_at is not None:
                raise HTTPException(status_code=400, detail="目标 folder 已软删")
        doc.folder_id = target_folder_id
        db.commit()
        return True


# --- module-level helpers -----------------------------------------------


def _with_doc_count(db: Session, f: DocumentFolder) -> DocumentFolder:
    """Attach ``document_count`` + ``path`` transient attrs for Pydantic."""
    f.document_count = (
        db.query(func.count(Document.id))
        .filter(Document.folder_id == f.id)
        .scalar()
        or 0
    )
    f.path = _compute_path(db, f)
    return f


def _compute_path(db: Session, folder: DocumentFolder) -> str:
    """Build the ancestor chain string, e.g. ``"研发 / 后端 / API 规范"``.

    Iterative walk up the tree so we don't blow the recursion
    stack on deep folders. Cap at depth 10 to match the spec
    §8 "max depth" rule.
    """
    names: List[str] = []
    current: Optional[DocumentFolder] = folder
    seen: set[int] = set()
    depth = 0
    while current is not None and current.id not in seen and depth < 10:
        seen.add(current.id)
        names.append(current.name)
        depth += 1
        if current.parent_id is None:
            break
        current = db.get(DocumentFolder, current.parent_id)
    names.reverse()
    return " / ".join(names)


def _bfs_descendants(db: Session, root_id: int) -> List[int]:
    """Return ``[root_id, child, grandchild, ...]`` for soft-delete cascade."""
    queue: deque[int] = deque([root_id])
    out: List[int] = [root_id]
    while queue:
        parent = queue.popleft()
        for row in (
            db.query(DocumentFolder.id)
            .filter(DocumentFolder.parent_id == parent)
            .all()
        ):
            child = row.id
            if child not in out:
                out.append(child)
                queue.append(child)
    return out


def _is_descendant(db: Session, ancestor: int, target: int) -> bool:
    """True if ``target`` is somewhere under ``ancestor``.

    Used for the "don't move a folder into its own subtree" guard.
    """
    queue: deque[int] = deque([ancestor])
    seen: set[int] = set()
    while queue:
        node = queue.popleft()
        if node == target:
            return True
        if node in seen:
            continue
        seen.add(node)
        for row in (
            db.query(DocumentFolder.id)
            .filter(DocumentFolder.parent_id == node)
            .all()
        ):
            queue.append(row.id)
    return False


folder_service = FolderService()
