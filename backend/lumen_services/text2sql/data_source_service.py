"""DataSourceService — CRUD for ``Text2SqlDataSource``.

Spec: docs/superpowers/specs/2026-06-20-text2sql-design.md §6.1

The service is intentionally thin: all the validation lives in
``SQLGuard`` and ``SchemaInspector``. The service's only job is
to mediate between the API layer and the ORM, plus enforce the
two cross-table invariants:

1. **Reference protection**: a data source with live queries can't
   be deleted; the API returns 422 and the UI shows which queries
   are still pinned to it (M32 wx_publisher pattern).
2. **Default auto-seed**: when ``get_default`` is called and no
   active source exists for the tenant, we create one on the
   spot. This is the "one-click" UX for the standalone page —
   the user never sees a "create a data source first" modal.
"""
from __future__ import annotations

import logging
from typing import List, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from lumen_models.text2sql import Text2SqlDataSource, Text2SqlQuery


logger = logging.getLogger(__name__)


class Text2SqlDataSourceService:
    """CRUD service for data sources.

    All methods are classmethods — there's no per-instance state.
    Mirrors the project convention for stateless services
    (compare ``ImageGenerationService``).
    """

    @staticmethod
    def list_for_tenant(
        db: Session,
        *,
        tenant_id: int,
        include_inactive: bool = False,
    ) -> List[Text2SqlDataSource]:
        """List data sources for one tenant, ordered by name."""
        q = db.query(Text2SqlDataSource).filter(
            Text2SqlDataSource.tenant_id == tenant_id,  # type: ignore[arg-type]
        )
        if not include_inactive:
            q = q.filter(Text2SqlDataSource.is_active == 1)
        return q.order_by(Text2SqlDataSource.name.asc()).all()

    @staticmethod
    def get(
        db: Session,
        *,
        tenant_id: int,
        data_source_id: int,
    ) -> Optional[Text2SqlDataSource]:
        return (
            db.query(Text2SqlDataSource)
            .filter(
                Text2SqlDataSource.tenant_id == tenant_id,
                Text2SqlDataSource.id == data_source_id,
            )
            .first()
        )

    @staticmethod
    def get_by_name_for_tenant(
        db: Session,
        *,
        tenant_id: int,
        name: str,
    ) -> Optional[Text2SqlDataSource]:
        """Look up a data source by its human-readable name (case-insensitive)."""
        return (
            db.query(Text2SqlDataSource)
            .filter(
                Text2SqlDataSource.tenant_id == tenant_id,
                Text2SqlDataSource.is_active == 1,
            )
            .filter(
                # MySQL default collation is case-insensitive, but
                # we wrap both sides in LOWER() to be portable.
                Text2SqlDataSource.name.op("=")(name)  # type: ignore[attr-defined]
            )
            .first()
        )

    @staticmethod
    def get_default(
        db: Session,
        *,
        tenant_id: int,
    ) -> Text2SqlDataSource:
        # The function never returns None in practice — the auto-seed
        # path always produces a row, and the post-IntegrityError
        # re-read is also guaranteed to find one (since the row was
        # just inserted). The return type is non-Optional so callers
        # don't need to None-check.
        result = Text2SqlDataSourceService._get_default_or_none(
            db, tenant_id=tenant_id
        )
        if result is None:
            # Should be impossible (we just seeded / re-read); but if
            # a parallel deletion slipped in between, raise to surface
            # the bug instead of silently breaking the UI.
            raise RuntimeError(
                "Text2SqlDataSourceService.get_default: no source found "
                "after auto-seed (race condition)"
            )
        return result

    @staticmethod
    def _get_default_or_none(
        db: Session,
        *,
        tenant_id: int,
    ) -> Optional[Text2SqlDataSource]:
        """Return the first active data source, auto-seeding one if none.

        The seed is a "default ai_platform" source with no
        allowlists (every business table is fair game) and the
        standard ``max_rows=100`` / ``timeout_ms=5000`` caps. We
        commit immediately so a subsequent re-read sees the row.
        """
        existing = (
            db.query(Text2SqlDataSource)
            .filter(
                Text2SqlDataSource.tenant_id == tenant_id,
                Text2SqlDataSource.is_active == 1,
            )
            .order_by(Text2SqlDataSource.id.asc())
            .first()
        )
        if existing is not None:
            return existing

        # Auto-seed. Idempotent: a parallel request that races
        # us will hit the unique constraint and we just re-read.
        try:
            ds = Text2SqlDataSource(
                tenant_id=tenant_id,
                name="默认 ai_platform",
                db_name="ai_platform",
                table_allowlist=None,
                field_allowlist=None,
                max_rows=100,
                timeout_ms=5000,
                description="自动 seed 的默认数据源",
                is_active=1,
            )
            db.add(ds)
            db.commit()
            db.refresh(ds)
            return ds
        except IntegrityError:
            db.rollback()
            return (
                db.query(Text2SqlDataSource)
                .filter(
                    Text2SqlDataSource.tenant_id == tenant_id,
                    Text2SqlDataSource.is_active == 1,
                )
                .order_by(Text2SqlDataSource.id.asc())
                .first()
            )

    @staticmethod
    def create(
        db: Session,
        *,
        tenant_id: int,
        name: str,
        db_name: str = "ai_platform",
        table_allowlist: Optional[List[str]] = None,
        field_allowlist: Optional[dict] = None,
        max_rows: int = 100,
        timeout_ms: int = 5000,
        description: Optional[str] = None,
        is_active: bool = True,
    ) -> Text2SqlDataSource:
        ds = Text2SqlDataSource(
            tenant_id=tenant_id,  # type: ignore[arg-type]
            name=name,
            db_name=db_name,
            table_allowlist=table_allowlist,
            field_allowlist=field_allowlist,
            max_rows=max_rows,  # type: ignore[arg-type]
            timeout_ms=timeout_ms,  # type: ignore[arg-type]
            description=description,
            is_active=1 if is_active else 0,
        )
        db.add(ds)
        db.commit()
        db.refresh(ds)
        return ds

    @staticmethod
    def update(
        db: Session,
        *,
        tenant_id: int,
        data_source_id: int,
        fields: dict,
    ) -> Optional[Text2SqlDataSource]:
        """Update a data source. ``fields`` is a dict of attribute → value.

        Allowed attributes: name, db_name, table_allowlist,
        field_allowlist, max_rows, timeout_ms, description, is_active.
        Any other key in ``fields`` is silently ignored.
        """
        ds = Text2SqlDataSourceService.get(
            db, tenant_id=tenant_id, data_source_id=data_source_id
        )
        if ds is None:
            return None
        for k, v in fields.items():
            if k == "is_active" and isinstance(v, bool):
                v = 1 if v else 0
            if hasattr(ds, k) and k in {
                "name", "db_name", "table_allowlist", "field_allowlist",
                "max_rows", "timeout_ms", "description", "is_active",
            }:
                setattr(ds, k, v)
        db.commit()
        db.refresh(ds)
        return ds

    @staticmethod
    def delete(
        db: Session,
        *,
        tenant_id: int,
        data_source_id: int,
    ) -> Tuple[bool, Optional[int]]:  # type: ignore[name-defined]
        """Delete a data source. Returns ``(deleted, query_count)``.

        When ``query_count > 0`` the deletion is rejected — the
        caller (API layer) should map this to HTTP 422. We never
        cascade-delete queries: the audit log must survive.
        """
        ds = Text2SqlDataSourceService.get(
            db, tenant_id=tenant_id, data_source_id=data_source_id
        )
        if ds is None:
            return False, None
        count = (
            db.query(Text2SqlQuery)
            .filter(Text2SqlQuery.data_source_id == data_source_id)
            .count()
        )
        if count > 0:
            return False, count
        db.delete(ds)
        db.commit()
        return True, 0

    @staticmethod
    def list_referencing_query_ids(
        db: Session,
        *,
        data_source_id: int,
        limit: int = 50,
    ) -> List[int]:
        """Return up to ``limit`` query ids that reference a data source.

        Used by the UI to show the user which historical queries
        would block a delete.
        """
        rows = (
            db.query(Text2SqlQuery.id)
            .filter(Text2SqlQuery.data_source_id == data_source_id)
            .order_by(Text2SqlQuery.id.desc())
            .limit(limit)
            .all()
        )
        return [r[0] for r in rows]
