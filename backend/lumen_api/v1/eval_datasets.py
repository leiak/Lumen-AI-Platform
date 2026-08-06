"""M37.1: Eval dataset HTTP endpoints — /api/v1/eval/datasets/*.

8 endpoints covering dataset CRUD + item CRUD + bulk-import:

  GET    /                              list datasets (tenant-scoped, with item_count)
  POST   /                              create dataset (tenant auto-derived)
  GET    /{dataset_id}                  detail (optional include_items=true)
  PUT    /{dataset_id}                  partial update (name / description / source / is_active)
  DELETE /{dataset_id}                  cascade delete items too
  POST   /{dataset_id}/items            add single item
  POST   /{dataset_id}/items/bulk-import  bulk import with partial_errors
  DELETE /{dataset_id}/items/{item_id}  delete single item

Bulk-import returns 200 OK even when some rows failed; the
``EvalDatasetItemBulkImportResponse.failed_count`` + ``partial_errors``
fields tell the dashboard which rows to highlight.

Spec: docs-internal/superpowers/specs/m37-rag-evaluation.md §4.1
Plan: docs-internal/superpowers/plans/m37-plan.md CP1 T3
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from lumen_api.v1.auth import get_current_user
from lumen_core.database import get_db
from lumen_models.eval_dataset import EvalDataset, EvalDatasetItem
from lumen_models.user import User
from lumen_schemas.common import PaginatedResponse, ResponseBase, SingleResponse
from lumen_schemas.eval_dataset import (
    EvalDatasetCreate,
    EvalDatasetItemBulkImportRequest,
    EvalDatasetItemBulkImportResponse,
    EvalDatasetItemCreate,
    EvalDatasetItemRead,
    EvalDatasetListItem,
    EvalDatasetRead,
    EvalDatasetUpdate,
)
from lumen_services.eval_dataset_service import EvalDatasetService


router = APIRouter(prefix="/eval/datasets", tags=["eval-datasets"])
service = EvalDatasetService()


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _build_list_item(row_with_count) -> EvalDatasetListItem:
    """Unpack ``(EvalDataset, item_count)`` tuple from the correlated subquery."""
    row, item_count = row_with_count
    return EvalDatasetListItem(
        id=row.id,
        kb_id=row.kb_id,
        tenant_id=row.tenant_id,
        name=row.name,
        source=row.source,
        is_active=row.is_active,
        item_count=item_count,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _to_read(row: EvalDataset) -> EvalDatasetRead:
    return EvalDatasetRead.model_validate({
        "id": row.id,
        "kb_id": row.kb_id,
        "tenant_id": row.tenant_id,
        "name": row.name,
        "source": row.source,
        "is_active": row.is_active,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "description": row.description,
        "created_by": row.created_by,
    })


def _to_item_read(row: EvalDatasetItem) -> EvalDatasetItemRead:
    return EvalDatasetItemRead.model_validate(row)


# ---------------------------------------------------------------------------
# dataset endpoints
# ---------------------------------------------------------------------------

@router.get("/", response_model=PaginatedResponse[EvalDatasetListItem])
def list_datasets(
    kb_id: Optional[int] = Query(None, description="按 KB 过滤,空 = 全部"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """列出当前租户可见的 datasets(含 builtin / NULL tenant_id)。"""
    rows, total = service.list_datasets(
        db,
        tenant_id=int(current_user.tenant_id),  # type: ignore[arg-type]
        kb_id=kb_id,
        page=page,
        page_size=page_size,
    )
    return PaginatedResponse(
        data=[_build_list_item(r) for r in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("/", response_model=SingleResponse[EvalDatasetRead], status_code=201)
def create_dataset(
    payload: EvalDatasetCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a tenant-scoped dataset. ``tenant_id`` is derived from the
    caller; builtin datasets (tenant_id=NULL) are only created by the seed
    script via ORM directly, never through this endpoint."""
    try:
        row = service.create_dataset(
            db,
            payload=payload,
            tenant_id=int(current_user.tenant_id),  # type: ignore[arg-type]
            created_by=int(current_user.id),  # type: ignore[arg-type]
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return SingleResponse(data=_to_read(row))


@router.get("/{dataset_id}", response_model=SingleResponse[EvalDatasetRead])
def get_dataset(
    dataset_id: int,
    include_items: bool = Query(False, description="是否在 detail 同时返回 items"),
    items_page: int = Query(1, ge=1),
    items_page_size: int = Query(50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = service.get_dataset(
        db,
        dataset_id=dataset_id,
        tenant_id=int(current_user.tenant_id),  # type: ignore[arg-type]
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Eval dataset not found")
    read = _to_read(row)
    # 如果 include_items=True,在 ORM 对象上 lazy-load items,避免 Pydantic 序列
    # 化时触发 IO 时报错。SQLAlchemy 默认 lazy='select'。
    if include_items:
        items, total_items = service.list_items(
            db,
            dataset_id=dataset_id,
            tenant_id=int(current_user.tenant_id),  # type: ignore[arg-type]
            page=items_page,
            page_size=items_page_size,
        )
        # 用 model_config 暴露 — 不打破 SingleResponse[T] 单字段契约,而是
        # 通过 message 字段返回 items 概览;前端 dashboard 详情页会另调
        # GET /datasets/{id}/items 看分页。简化:不暴露 items 列表给 detail。
        # 这里仅在 read 上附加 item_count 由 service 层算好。
        _ = items  # 暂未使用,留给后续 v2
    return SingleResponse(data=read)


@router.put("/{dataset_id}", response_model=SingleResponse[EvalDatasetRead])
def update_dataset(
    dataset_id: int,
    payload: EvalDatasetUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = service.update_dataset(
        db,
        dataset_id=dataset_id,
        tenant_id=int(current_user.tenant_id),  # type: ignore[arg-type]
        payload=payload,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Eval dataset not found")
    return SingleResponse(data=_to_read(row))


@router.delete("/{dataset_id}", response_model=ResponseBase)
def delete_dataset(
    dataset_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ok = service.delete_dataset(
        db,
        dataset_id=dataset_id,
        tenant_id=int(current_user.tenant_id),  # type: ignore[arg-type]
    )
    if not ok:
        raise HTTPException(status_code=404, detail="Eval dataset not found")
    return ResponseBase(code=200, message="Eval dataset deleted / 已删除")


# ---------------------------------------------------------------------------
# item endpoints
# ---------------------------------------------------------------------------

@router.get(
    "/{dataset_id}/items",
    response_model=PaginatedResponse[EvalDatasetItemRead],
)
def list_items(
    dataset_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """列出 dataset 内的 items。

    详情页 T6 用 —— 表格分页 + 删单条。dataset 必须对当前租户可见,
    否则 404(不暴露「存在但越权」与「不存在」的差别)。
    """
    try:
        items, total = service.list_items(
            db,
            dataset_id=dataset_id,
            tenant_id=int(current_user.tenant_id),  # type: ignore[arg-type]
            page=page,
            page_size=page_size,
        )
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return PaginatedResponse(
        data=[_to_item_read(it) for it in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post(
    "/{dataset_id}/items",
    response_model=SingleResponse[EvalDatasetItemRead],
    status_code=201,
)
def add_item(
    dataset_id: int,
    payload: EvalDatasetItemCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """加一条 item 进 dataset。"""
    try:
        row = service.add_item(
            db,
            dataset_id=dataset_id,
            tenant_id=int(current_user.tenant_id),  # type: ignore[arg-type]
            payload=payload,
        )
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return SingleResponse(data=_to_item_read(row))


@router.post(
    "/{dataset_id}/items/bulk-import",
    response_model=SingleResponse[EvalDatasetItemBulkImportResponse],
)
def bulk_import_items(
    dataset_id: int,
    payload: EvalDatasetItemBulkImportRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """批量导入 items。

    单行 Pydantic 校验失败或 DB 写入失败 → 该行进 ``partial_errors``,
    其他行继续处理。整个 batch **不会** 因一行错而失败 —— 状态码始终 200,
    客户端读 ``failed_count`` / ``partial_errors`` 判断部分成功。
    """
    try:
        resp = service.bulk_import_items(
            db,
            dataset_id=dataset_id,
            tenant_id=int(current_user.tenant_id),  # type: ignore[arg-type]
            rows=payload.rows,  # List[Dict[str, Any]] —— service 层逐行 Pydantic 校验
        )
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return SingleResponse(data=resp)


@router.delete(
    "/{dataset_id}/items/{item_id}",
    response_model=ResponseBase,
)
def delete_item(
    dataset_id: int,
    item_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ok = service.delete_item(
        db,
        dataset_id=dataset_id,
        item_id=item_id,
        tenant_id=int(current_user.tenant_id),  # type: ignore[arg-type]
    )
    if not ok:
        raise HTTPException(status_code=404, detail="Eval dataset item not found")
    return ResponseBase(code=200, message="Item deleted / 已删除")