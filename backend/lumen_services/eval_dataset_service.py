"""M37.1: Eval dataset service layer.

CRUD for ``EvalDataset`` + ``EvalDatasetItem`` with tenant isolation
matching the ``StockService`` pattern: NULL ``tenant_id`` (builtin /
global) is visible to every tenant; non-NULL values scope the row to
one tenant. The service is the single source of truth for what gets
returned — the API layer is a thin router.

Bulk-import design (see ``m37-plan.md`` Risks §"bulk import 错误
fail-all"): one bad row in a batch does not fail the whole batch;
failed rows are returned in ``partial_errors`` (with their 0-based
``row_index`` from the original request) and the caller surfaces them
in the dashboard UI.

Spec: docs-internal/superpowers/specs/m37-rag-evaluation.md §4.1
"""
from typing import Any, Dict, List, Optional, Tuple

from pydantic import ValidationError
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from lumen_models.eval_dataset import EvalDataset, EvalDatasetItem
from lumen_models.knowledge import KnowledgeBase
from lumen_schemas.eval_dataset import (
    EvalDatasetCreate,
    EvalDatasetItemBulkImportError,
    EvalDatasetItemBulkImportResponse,
    EvalDatasetItemBulkImportRow,
    EvalDatasetItemCreate,
    EvalDatasetUpdate,
)


class EvalDatasetService:
    """CRUD for eval datasets + items. Stateless; one instance shared."""

    # ----- visibility helper ------------------------------------------------

    @staticmethod
    def _visibility_filter(tenant_id: Optional[int]):
        """NULL tenant_id (builtin) is visible to every tenant."""
        return or_(
            EvalDataset.tenant_id.is_(None),
            EvalDataset.tenant_id == tenant_id,
        )

    # ----- dataset CRUD -----------------------------------------------------

    def list_datasets(
        self,
        db: Session,
        *,
        tenant_id: Optional[int],
        kb_id: Optional[int] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Tuple[List[EvalDataset], int]:
        """List datasets visible to the given tenant. Optional kb filter.

        ``item_count`` is a correlated subquery to avoid an N+1 when the
        dashboard renders ``item_count`` per row. ``EvalDatasetItem`` rows
        cascade-delete with the dataset, so the count is always consistent.
        """
        item_count_sq = (
            db.query(func.count(EvalDatasetItem.id))
            .filter(EvalDatasetItem.dataset_id == EvalDataset.id)
            .correlate(EvalDataset)
            .scalar_subquery()
        )
        query = db.query(EvalDataset, item_count_sq.label("item_count")).filter(
            self._visibility_filter(tenant_id)
        )
        if kb_id is not None:
            query = query.filter(EvalDataset.kb_id == kb_id)
        total = query.with_entities(func.count(EvalDataset.id)).scalar() or 0
        rows = (
            query.order_by(EvalDataset.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        # rows are tuples (EvalDataset, item_count) — service callers
        # handle the unpacking in the API layer's _build_list_item.
        return rows, total

    def get_dataset(
        self,
        db: Session,
        *,
        dataset_id: int,
        tenant_id: Optional[int],
    ) -> Optional[EvalDataset]:
        return (
            db.query(EvalDataset)
            .filter(EvalDataset.id == dataset_id, self._visibility_filter(tenant_id))
            .first()
        )

    def create_dataset(
        self,
        db: Session,
        *,
        payload: EvalDatasetCreate,
        tenant_id: Optional[int],
        created_by: Optional[int],
    ) -> EvalDataset:
        """Create a tenant-scoped dataset. KB must be visible to the caller."""
        kb = (
            db.query(KnowledgeBase)
            .filter(
                KnowledgeBase.id == payload.kb_id,
                # KB visibility mirrors the dataset visibility rule.
                or_(
                    KnowledgeBase.tenant_id.is_(None),
                    KnowledgeBase.tenant_id == tenant_id,
                ),
            )
            .first()
        )
        if kb is None:
            raise ValueError(f"KB {payload.kb_id} not found or not visible to tenant {tenant_id}")
        row = EvalDataset(
            kb_id=payload.kb_id,
            tenant_id=tenant_id,
            name=payload.name,
            description=payload.description,
            source=payload.source,
            is_active=1,
            created_by=created_by,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row

    def update_dataset(
        self,
        db: Session,
        *,
        dataset_id: int,
        tenant_id: Optional[int],
        payload: EvalDatasetUpdate,
    ) -> Optional[EvalDataset]:
        row = self.get_dataset(db, dataset_id=dataset_id, tenant_id=tenant_id)
        if row is None:
            return None
        # 只更新非 None 字段 —— Pydantic 已把 None 当 "不传"
        for field in ("name", "description", "source", "is_active"):
            value = getattr(payload, field)
            if value is not None:
                setattr(row, field, value)
        db.commit()
        db.refresh(row)
        return row

    def delete_dataset(
        self,
        db: Session,
        *,
        dataset_id: int,
        tenant_id: Optional[int],
    ) -> bool:
        row = self.get_dataset(db, dataset_id=dataset_id, tenant_id=tenant_id)
        if row is None:
            return False
        db.delete(row)  # items CASCADE
        db.commit()
        return True

    # ----- item CRUD --------------------------------------------------------

    def list_items(
        self,
        db: Session,
        *,
        dataset_id: int,
        tenant_id: Optional[int],
        page: int = 1,
        page_size: int = 50,
    ) -> Tuple[List[EvalDatasetItem], int]:
        """List items in a dataset the caller can see. 403-shaped error
        surfaced by raising LookupError if the dataset is invisible."""
        if self.get_dataset(db, dataset_id=dataset_id, tenant_id=tenant_id) is None:
            raise LookupError(f"Dataset {dataset_id} not visible")
        query = db.query(EvalDatasetItem).filter(EvalDatasetItem.dataset_id == dataset_id)
        total = query.count()
        rows = (
            query.order_by(EvalDatasetItem.id.asc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        return rows, total

    def add_item(
        self,
        db: Session,
        *,
        dataset_id: int,
        tenant_id: Optional[int],
        payload: EvalDatasetItemCreate,
    ) -> EvalDatasetItem:
        if self.get_dataset(db, dataset_id=dataset_id, tenant_id=tenant_id) is None:
            raise LookupError(f"Dataset {dataset_id} not visible")
        row = EvalDatasetItem(
            dataset_id=dataset_id,
            query=payload.query,
            expected_doc_ids=payload.expected_doc_ids,
            expected_answer=payload.expected_answer,
            answer_keywords=payload.answer_keywords,
            category=payload.category,
            difficulty=payload.difficulty,
            notes=payload.notes,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row

    def bulk_import_items(
        self,
        db: Session,
        *,
        dataset_id: int,
        tenant_id: Optional[int],
        rows: List[Dict[str, Any]],
    ) -> EvalDatasetItemBulkImportResponse:
        """Per-row try/except — bad row goes to ``partial_errors`` instead of
        failing the batch. This matches the M37 plan Risks §"bulk import 错误
        fail-all" mitigation and mirrors the JSON-import behavior on the
        ``faq_entries`` endpoint.
        """
        if self.get_dataset(db, dataset_id=dataset_id, tenant_id=tenant_id) is None:
            raise LookupError(f"Dataset {dataset_id} not visible")

        imported_count = 0
        partial_errors: List[EvalDatasetItemBulkImportError] = []

        for idx, raw in enumerate(rows):
            try:
                # Pydantic Literal validation: invalid category/difficulty
                # raises ValidationError before we touch the DB.
                parsed = EvalDatasetItemBulkImportRow.model_validate(raw)
            except ValidationError as e:
                partial_errors.append(
                    EvalDatasetItemBulkImportError(
                        row_index=idx,
                        error=_format_validation_error(e),
                    )
                )
                continue
            try:
                db.add(EvalDatasetItem(
                    dataset_id=dataset_id,
                    query=parsed.query,
                    expected_doc_ids=parsed.expected_doc_ids,
                    expected_answer=parsed.expected_answer,
                    answer_keywords=parsed.answer_keywords,
                    category=parsed.category,
                    difficulty=parsed.difficulty,
                    notes=parsed.notes,
                ))
                db.flush()
                imported_count += 1
            except Exception as e:  # DB-level failure (FK / JSON encode / etc.)
                db.rollback()
                partial_errors.append(
                    EvalDatasetItemBulkImportError(
                        row_index=idx,
                        error=f"db error: {e}",
                    )
                )

        db.commit()
        return EvalDatasetItemBulkImportResponse(
            imported_count=imported_count,
            failed_count=len(partial_errors),
            partial_errors=partial_errors,
        )

    def delete_item(
        self,
        db: Session,
        *,
        dataset_id: int,
        item_id: int,
        tenant_id: Optional[int],
    ) -> bool:
        if self.get_dataset(db, dataset_id=dataset_id, tenant_id=tenant_id) is None:
            return False
        row = (
            db.query(EvalDatasetItem)
            .filter(
                EvalDatasetItem.id == item_id,
                EvalDatasetItem.dataset_id == dataset_id,
            )
            .first()
        )
        if row is None:
            return False
        db.delete(row)
        db.commit()
        return True


def _format_validation_error(e: ValidationError) -> str:
    """Render a Pydantic ValidationError as a one-line human message.

    First error wins — the dashboard surfaces the row's primary issue in a
    tooltip; the full traceback stays in the service log.
    """
    errs = e.errors()
    if not errs:
        return "validation error"
    first = errs[0]
    loc = ".".join(str(x) for x in first.get("loc", ())) or "row"
    msg = first.get("msg", "invalid")
    return f"{loc}: {msg}"