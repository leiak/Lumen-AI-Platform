"""M38.2: unit tests for ``FolderService``.

Mirrors the workspace-service test approach: a hand-rolled
``_FakeSession`` that records row mutations + a few ``aggregate_rows``
so the service-layer BFS / cascade paths can be exercised
without a real database.

Spec §7.1 — folder CRUD + soft delete + restore + document move.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import pytest
from sqlalchemy.sql import operators

from lumen_services.folder_service import FolderService


# ---- SQLAlchemy clause introspection ----------------------------------


def _class_name_of(model: Any) -> Optional[str]:
    """``DocumentFolder`` class or ``DocumentFolder.id`` column → class name.

    SQLAlchemy 单 column 查询 (``db.query(DocumentFolder.id)``) 传入
    的是 ``InstrumentedAttribute``,没有 ``__name__``,但有
    ``.class_`` 指向原 ORM 类。fake 的 ``__model__`` discriminator
    存的是类名字符串,这里统一转成 class name 再比对。
    """
    if isinstance(model, type):
        return model.__name__
    cls = getattr(model, "class_", None)
    if cls is not None:
        return cls.__name__
    return None


def _column_key(col: Any) -> Optional[str]:
    """``DocumentFolder.parent_id`` → ``"parent_id"`` (Python attribute name)."""
    return getattr(col, "key", None) or getattr(col, "name", None)


def _literal(v: Any) -> Any:
    """BindParameter / scalar / list → raw value.

    SQLAlchemy 把 ``42`` 包成 ``BindParameter``, ``.value`` 才是真值。
    """
    return getattr(v, "value", v)


# ---- Fake session + query ---------------------------------------------


class _FakeQuery:
    def __init__(self, rows: List[Any], scalar: int = 0):
        self._rows = list(rows)
        self._filters: List[Any] = []
        self._order = []
        self._offset = 0
        self._limit = None
        self._scalar = scalar

    def filter(self, *clauses):
        self._filters.extend(clauses)
        return self

    def count(self) -> int:
        return len([r for r in self._rows if self._row_matches(r)])

    def first(self):
        for r in self._rows:
            if self._row_matches(r):
                return r
        return None

    def order_by(self, *args):
        self._order.extend(args)
        return self

    def offset(self, n: int):
        self._offset = n
        return self

    def limit(self, n: int):
        self._limit = n
        return self

    def group_by(self, *args):
        # GROUP BY 已在 aggregate_rows 里折叠掉,这里是 no-op
        return self

    def all(self):
        matched = [r for r in self._rows if self._row_matches(r)]
        if self._offset:
            matched = matched[self._offset:]
        if self._limit is not None:
            matched = matched[: self._limit]
        return matched

    def scalar(self):
        return self._scalar

    # --- clause evaluation ---

    def _row_matches(self, row) -> bool:
        for clause in self._filters:
            if not self._match_clause(clause, row):
                return False
        return True

    def _match_clause(self, clause, row) -> bool:
        op = getattr(clause, "operator", None)
        if op is None:
            return True
        if op is operators.eq:
            return self._eval_eq(clause, row, want_none=False)
        if op is operators.is_:
            return self._eval_eq(clause, row, want_none=True)
        if op is operators.is_not:
            return self._eval_eq(clause, row, want_none=True, negate=True)
        if op is operators.in_op:
            attr = _column_key(getattr(clause, "left", None))
            if attr is None:
                return True
            actual = getattr(row, attr, None)
            right = getattr(clause, "right", None)
            elements = list(getattr(right, "elements", [right]))
            return actual in [_literal(e) for e in elements]
        # 不识别的 operator (ne / like / ...) 先放过,免得误伤
        return True

    def _eval_eq(self, clause, row, *, want_none: bool, negate: bool = False) -> bool:
        attr = _column_key(getattr(clause, "left", None))
        if attr is None:
            return True
        actual = getattr(row, attr, None)
        if want_none:
            expected = None
            result = actual is expected
        else:
            expected = _literal(getattr(clause, "right", None))
            result = actual == expected
        return (not result) if negate else result


class _FakeSession:
    def __init__(
        self,
        rows: Optional[List[Any]] = None,
        aggregate_rows: Optional[List[Any]] = None,
        aggregate_scalar: int = 0,
        execute_results: Optional[List[Dict[str, Any]]] = None,
    ):
        self.rows = list(rows or [])
        self.aggregate_rows = list(aggregate_rows or [])
        self.aggregate_scalar = aggregate_scalar
        # ``db.execute(update(...)).rowcount`` 是软删用的;这里预置每个
        # execute 调用的预期 rowcount。
        self.execute_results = list(execute_results or [])
        self.execute_calls = 0
        self.commits = 0
        self.deleted: List[Any] = []
        self.next_id = max((r.id for r in self.rows), default=0) + 1

    def query(self, *models):
        model = models[0]
        if len(models) > 1:
            # aggregate / group-by 查询走 aggregate_rows
            q = _FakeQuery(self.aggregate_rows, scalar=self.aggregate_scalar)
            return q
        target_name = _class_name_of(model)
        rows_for_model = [
            r for r in self.rows
            if target_name is not None and getattr(r, "__model__", None) == target_name
        ]
        q = _FakeQuery(rows_for_model, scalar=self.aggregate_scalar)
        return q

    def get(self, model, pk):
        target_name = _class_name_of(model)
        for r in self.rows:
            if (
                target_name is not None
                and getattr(r, "__model__", None) == target_name
                and getattr(r, "id", None) == pk
            ):
                return r
        return None

    def commit(self):
        self.commits += 1

    def refresh(self, obj):
        if getattr(obj, "created_at", None) is None:
            obj.created_at = datetime.now(timezone.utc)
        if getattr(obj, "updated_at", None) is None:
            obj.updated_at = obj.created_at

    def add(self, obj):
        if not hasattr(obj, "id") or obj.id is None:
            obj.id = self.next_id
            self.next_id += 1
        self.rows.append(obj)

    def delete(self, obj):
        if obj in self.rows:
            self.rows.remove(obj)
        self.deleted.append(obj)

    def rollback(self):
        pass

    def execute(self, stmt):
        # soft delete 用 ``DocumentFolder.__table__.update()``
        # 路径,直接走 ``rowcount`` —— 测试在 ``execute_results``
        # 里预置每条调用的预期值。
        class _Result:
            pass

        result = _Result()
        if self.execute_results:
            result.rowcount = self.execute_results[self.execute_calls].get("rowcount", 0)
        else:
            result.rowcount = 0
        self.execute_calls += 1
        return result


# ---- row factories ---------------------------------------------------


def _make_kb(*, id: int = 1, tenant_id: int = 1):
    k = type("K", (), {})()
    k.id = id
    k.tenant_id = tenant_id
    k.__model__ = "KnowledgeBase"
    return k


def _make_folder(
    *,
    id: int,
    knowledge_base_id: int,
    name: str,
    parent_id: Optional[int] = None,
    deleted_at: Optional[datetime] = None,
    order_index: int = 0,
):
    f = type("F", (), {})()
    f.id = id
    f.knowledge_base_id = knowledge_base_id
    f.parent_id = parent_id
    f.name = name
    f.description = None
    f.order_index = order_index
    f.created_by = None
    f.deleted_at = deleted_at
    f.created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    f.updated_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    f.document_count = 0
    f.path = None
    f.__model__ = "DocumentFolder"
    return f


def _make_doc(*, id: int, knowledge_base_id: int, folder_id: Optional[int] = None):
    d = type("D", (), {})()
    d.id = id
    d.knowledge_base_id = knowledge_base_id
    d.folder_id = folder_id
    d.__model__ = "Document"
    return d


# -- CRUD ---------------------------------------------------------------


def test_get_folder_returns_none_for_missing():
    db = _FakeSession([_make_kb()])
    service = FolderService()
    assert service.get_folder(db, folder_id=999, tenant_id=1) is None


def test_create_folder_with_null_parent():
    from lumen_schemas.document_folder import DocumentFolderCreate

    db = _FakeSession([_make_kb()])
    service = FolderService()
    folder = service.create_folder(
        db,
        kb_id=1,
        tenant_id=1,
        data=DocumentFolderCreate(name="研发"),
        created_by=7,
    )
    assert folder.name == "研发"
    assert folder.parent_id is None


def test_create_folder_with_bad_parent_raises_400():
    from fastapi import HTTPException
    from lumen_schemas.document_folder import DocumentFolderCreate

    db = _FakeSession([_make_kb()])  # 没有 parent folder
    service = FolderService()
    with pytest.raises(HTTPException) as exc:
        service.create_folder(
            db,
            kb_id=1,
            tenant_id=1,
            data=DocumentFolderCreate(name="x", parent_id=42),
        )
    assert exc.value.status_code == 400


def test_update_folder_rejects_cycle_into_descendant():
    from fastapi import HTTPException
    from lumen_schemas.document_folder import DocumentFolderUpdate

    a = _make_folder(id=1, knowledge_base_id=1, name="A")
    b = _make_folder(id=2, knowledge_base_id=1, name="B", parent_id=1)
    db = _FakeSession([_make_kb(), a, b])
    service = FolderService()
    # 把 A 移到 B 下 —— B 是 A 的后代,会形成环
    with pytest.raises(HTTPException) as exc:
        service.update_folder(
            db,
            folder_id=1,
            tenant_id=1,
            data=DocumentFolderUpdate(parent_id=2),
        )
    assert exc.value.status_code == 400


def test_soft_delete_folder_cascades_to_descendants():
    a = _make_folder(id=1, knowledge_base_id=1, name="A")
    b = _make_folder(id=2, knowledge_base_id=1, name="B", parent_id=1)
    c = _make_folder(id=3, knowledge_base_id=1, name="C", parent_id=2)
    db = _FakeSession(
        rows=[_make_kb(), a, b, c],
        # service 只 execute 一次 (DocumentFolder.__table__.update),
        # 3 个 folder 全部 deleted_at IS NULL → 全部翻 → rowcount=3
        execute_results=[{"rowcount": 3}],
    )
    service = FolderService()
    scanned, deleted = service.soft_delete_folder(
        db, folder_id=1, tenant_id=1
    )
    assert scanned == 3
    assert deleted == 3


def test_restore_folder_unmarks_deleted_at():
    a = _make_folder(
        id=1, knowledge_base_id=1, name="A",
        deleted_at=datetime.now(timezone.utc),
    )
    db = _FakeSession([_make_kb(), a])
    service = FolderService()
    folder = service.restore_folder(db, folder_id=1, tenant_id=1)
    assert folder is not None
    assert folder.deleted_at is None


# -- document move ------------------------------------------------------


def test_move_document_to_null_folder_means_root():
    doc = _make_doc(id=10, knowledge_base_id=1, folder_id=5)
    db = _FakeSession([_make_kb(), doc])
    service = FolderService()
    assert service.move_document(
        db, document_id=10, target_folder_id=None, tenant_id=1
    ) is True
    assert doc.folder_id is None


def test_move_document_rejects_cross_kb_folder():
    from fastapi import HTTPException

    doc = _make_doc(id=10, knowledge_base_id=1, folder_id=5)
    target = _make_folder(id=99, knowledge_base_id=2, name="Other")
    db = _FakeSession([_make_kb(), doc, target])
    service = FolderService()
    with pytest.raises(HTTPException) as exc:
        service.move_document(
            db, document_id=10, target_folder_id=99, tenant_id=1
        )
    assert exc.value.status_code == 400


def test_move_document_returns_false_for_unknown_doc():
    db = _FakeSession([_make_kb()])
    service = FolderService()
    assert service.move_document(
        db, document_id=999, target_folder_id=None, tenant_id=1
    ) is False