"""M38.2: document folder endpoints.

Mounted under ``/api/v1/knowledge/{kb_id}/folders`` (per-KB list +
create) and ``/api/v1/folders/{id}`` (single get / patch / soft
delete / restore). The document-move endpoint lives in
``knowledge.py`` alongside the rest of the document CRUD.

Tenant isolation is enforced by the service layer; the API just
forwards the caller's tenant_id + admin flag.

Spec: ``docs-internal/superpowers/specs/2026-08-26-kb-workspace-folder.md``
§ 4.2.
"""
from __future__ import annotations

from typing import List, Optional, Union

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from lumen_api.v1.auth import get_current_user
from lumen_core.database import get_db
from lumen_models.user import User
from lumen_schemas.common import SingleResponse
from lumen_schemas.document_folder import (
    DocumentFolderCreate,
    DocumentFolderRead,
    DocumentFolderTreeNode,
    DocumentFolderUpdate,
)
from lumen_services.folder_service import folder_service
from lumen_services.permission_service import (
    assert_perm_via_folder,
    assert_perm_via_kb,
)

router = APIRouter(tags=["folders"])


def _is_admin(user: User) -> bool:
    """Mirror the workspace.py helper — used for cross-tenant access."""
    return bool(getattr(user, "is_superuser", False))


# -- per-KB list + create -----------------------------------------------


@router.get(
    "/knowledge/{kb_id}/folders",
    response_model=SingleResponse[
        Union[List[DocumentFolderRead], List[DocumentFolderTreeNode]]
    ],
)
def list_folders(
    kb_id: int,
    tree: bool = Query(False, description="true = 嵌套树形;默认平铺列表"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List folders under a KB.

    M38.2.x v2: ``folder.read`` permission is required via KB.
    Soft-deleted folders are filtered out; restore endpoints
    surface them separately so a "Recently Deleted" UI can fetch
    them out-of-band.
    """
    assert_perm_via_kb(db, current_user, "folder.read", kb_id)
    items = folder_service.list_folders(
        db,
        kb_id=kb_id,
        tenant_id=current_user.tenant_id,
        is_superuser=_is_admin(current_user),
        tree=tree,
    )
    return SingleResponse(data=items)


@router.post(
    "/knowledge/{kb_id}/folders",
    response_model=SingleResponse[DocumentFolderRead],
)
def create_folder(
    kb_id: int,
    payload: DocumentFolderCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a folder under a KB.

    M38.2.x v2: ``folder.create`` permission is required via KB.
    Cross-KB parents are rejected at the service layer; this
    endpoint forwards the caller as the ``created_by`` owner.
    """
    assert_perm_via_kb(db, current_user, "folder.create", kb_id)
    folder = folder_service.create_folder(
        db,
        kb_id=kb_id,
        tenant_id=current_user.tenant_id,
        data=payload,
        created_by=current_user.id,
        is_superuser=_is_admin(current_user),
    )
    return SingleResponse(data=folder)


# -- single folder ------------------------------------------------------


@router.get(
    "/folders/{folder_id}",
    response_model=SingleResponse[DocumentFolderRead],
)
def get_folder(
    folder_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Single folder including the ancestor ``path`` string.

    M38.2.x v2: ``folder.read`` permission is required via folder → KB.
    """
    assert_perm_via_folder(db, current_user, "folder.read", folder_id)
    folder = folder_service.get_folder(
        db,
        folder_id=folder_id,
        tenant_id=current_user.tenant_id,
        is_superuser=_is_admin(current_user),
    )
    if folder is None:
        raise HTTPException(status_code=404, detail="Folder not found")
    return SingleResponse(data=folder)


@router.put(
    "/folders/{folder_id}",
    response_model=SingleResponse[DocumentFolderRead],
)
def update_folder(
    folder_id: int,
    payload: DocumentFolderUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Patch a folder.

    M38.2.x v2: ``folder.update`` permission is required via folder → KB.
    Re-parenting is allowed; the service rejects cycles
    (a folder cannot be moved into its own subtree).
    """
    assert_perm_via_folder(db, current_user, "folder.update", folder_id)
    folder = folder_service.update_folder(
        db,
        folder_id=folder_id,
        tenant_id=current_user.tenant_id,
        data=payload,
        is_superuser=_is_admin(current_user),
    )
    if folder is None:
        raise HTTPException(status_code=404, detail="Folder not found")
    return SingleResponse(data=folder)


@router.delete("/folders/{folder_id}")
def delete_folder(
    folder_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Soft-delete a folder + all descendants.

    M38.2.x v2: ``folder.delete`` permission is required via folder → KB.

    Returns the BFS subtree size + the number of rows the
    UPDATE flipped, so the frontend can render a "Moved N
    descendants to trash" toast without a second round-trip.
    Documents inside the deleted folder are detached
    (``folder_id`` becomes NULL via the FK ON DELETE SET NULL
    on hard delete; here we just null them explicitly via
    ``folder_id = NULL`` in the same soft-delete path so the
    user-visible behaviour matches the spec §8 "folder 下 N 篇
    文档将移动到 KB 根目录").
    """
    from datetime import datetime, timezone
    from sqlalchemy import update as sa_update
    from lumen_models.knowledge import Document
    from lumen_models.workspace import DocumentFolder

    folder = folder_service.get_folder(
        db,
        folder_id=folder_id,
        tenant_id=current_user.tenant_id,
        is_superuser=_is_admin(current_user),
    )
    if folder is None:
        raise HTTPException(status_code=404, detail="Folder not found")

    assert_perm_via_folder(db, current_user, "folder.delete", folder_id)

    # BFS descendants (module-level helper in folder_service).
    from lumen_services.folder_service import _bfs_descendants
    all_ids = _bfs_descendants(db, folder_id)
    if not all_ids:
        return {"scanned": 0, "deleted": 0}

    now = datetime.now(timezone.utc)
    # Detach documents in the deleted subtree so they fall back
    # to the KB root — spec §8 expectation "folder 下 N 篇文档
    # 将移动到 KB 根目录,不会删除". This is a one-shot UPDATE
    # that touches every doc whose folder_id lands in the BFS
    # set; ``folder_id IS NULL`` guard means re-deleting is a
    # no-op.
    doc_result = db.execute(
        sa_update(Document)
        .where(
            Document.folder_id.in_(all_ids),
            Document.folder_id.is_not(None),
        )
        .values(folder_id=None)
    )
    # Mark folder rows soft-deleted.
    folder_result = db.execute(
        sa_update(DocumentFolder)
        .where(
            DocumentFolder.id.in_(all_ids),
            DocumentFolder.deleted_at.is_(None),
        )
        .values(deleted_at=now)
    )
    db.commit()
    return {
        "scanned": len(all_ids),
        "deleted_folders": folder_result.rowcount or 0,
        "detached_documents": doc_result.rowcount or 0,
    }


@router.post(
    "/folders/{folder_id}/restore",
    response_model=SingleResponse[DocumentFolderRead],
)
def restore_folder(
    folder_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Restore a soft-deleted folder.

    M38.2.x v2: ``folder.restore`` permission is required via folder → KB.
    30-day window enforcement is a follow-up Celery task (spec
    §8 risk). The endpoint surfaces ``deleted_at`` on the
    response so the frontend can grey out rows older than the
    window without needing a separate fetch.
    """
    assert_perm_via_folder(db, current_user, "folder.restore", folder_id)
    folder = folder_service.restore_folder(
        db,
        folder_id=folder_id,
        tenant_id=current_user.tenant_id,
        is_superuser=_is_admin(current_user),
    )
    if folder is None:
        raise HTTPException(status_code=404, detail="Folder not found")
    return SingleResponse(data=folder)
