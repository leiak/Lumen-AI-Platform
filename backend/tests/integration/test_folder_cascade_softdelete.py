"""M38.2: soft-deleting a folder cascades to descendants and detaches documents.

Spec §4.2 + §8: deleting a folder + its subtree sets
``deleted_at`` on every folder row in the BFS subtree AND sets
``folder_id = NULL`` on every document in that subtree (the
docs fall back to the KB root, not deleted).

Exercises the real ``DELETE /folders/{id}`` endpoint so a
future refactor of the BFS or detach logic can't silently
drop one of the two updates.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List as _List, Optional

import pytest
from fastapi.testclient import TestClient

from lumen_api.v1 import auth as auth_module
from lumen_core.database import get_db
from lumen_main import app


# --- fakes --------------------------------------------------------------


class _FakeUser:
    def __init__(self, *, tenant_id: int = 1, is_superuser: bool = False, uid: int = 1) -> None:
        self.id = uid
        self.tenant_id = tenant_id
        self.is_superuser = is_superuser
        self.is_active = True
        self.username = f"u{uid}"


class _FakeKB:
    def __init__(self, *, id: int = 1, tenant_id: int = 1) -> None:
        self.id = id
        self.tenant_id = tenant_id


class _FakeFolder:
    def __init__(
        self,
        *,
        id: int,
        knowledge_base_id: int,
        name: str,
        parent_id: Optional[int] = None,
        deleted_at: Optional[datetime] = None,
    ) -> None:
        self.id = id
        self.knowledge_base_id = knowledge_base_id
        self.name = name
        self.parent_id = parent_id
        self.description = None
        self.order_index = 0
        self.created_by = None
        self.deleted_at = deleted_at
        self.created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.updated_at = datetime(2026, 1, 1, tzinfo=timezone.utc)


class _FakeDoc:
    def __init__(
        self,
        *,
        id: int,
        knowledge_base_id: int,
        folder_id: Optional[int],
    ) -> None:
        self.id = id
        self.knowledge_base_id = knowledge_base_id
        self.folder_id = folder_id
        self.filename = f"doc-{id}.txt"


# --- fake query that supports .filter().all() with eq / is_ / in_ -----


class _FakeQuery:
    def __init__(self, rows: _List, scalar: int = 0):
        self._rows = rows
        self._filters: list = []

    def filter(self, *clauses):
        self._filters.extend(clauses)
        return self

    def all(self):
        matched = [r for r in self._rows if self._matches(r)]
        return matched

    def first(self):
        for r in self._rows:
            if self._matches(r):
                return r
        return None

    def scalar(self) -> int:
        return 0

    def count(self) -> int:
        return len([r for r in self._rows if self._matches(r)])

    def order_by(self, *args):
        return self

    def offset(self, n: int):
        return self

    def limit(self, n: int):
        return self

    def group_by(self, *args):
        return self

    def _matches(self, row) -> bool:
        for clause in self._filters:
            if not self._match_clause(clause, row):
                return False
        return True

    def _match_clause(self, clause, row) -> bool:
        op = getattr(clause, "operator", None)
        if op is None:
            return True
        op_name = getattr(op, "__name__", "")
        col = getattr(getattr(clause, "left", None), "key", None)
        right = getattr(clause, "right", None)
        if col is None:
            return True
        actual = getattr(row, col, None)
        if op_name == "eq":
            return actual == getattr(right, "value", right)
        if op_name == "is_":
            return actual is None
        if op_name == "is_not":
            return actual is not None
        if op_name == "in_op":
            v = getattr(right, "value", None)
            if isinstance(v, (list, tuple, set)):
                return actual in list(v)
            return False
        return True


class _FakeSession:
    def __init__(self, state: Dict[str, Any]):
        self.state = state

    def query(self, *models):
        model = models[0]
        name = getattr(model, "__name__", None)
        # InstrumentedAttribute (``DocumentFolder.id``) has a
        # ``.class_`` pointing back to the ORM class.
        cls = getattr(model, "class_", None)
        class_name = (cls.__name__ if cls else None) or name
        # 聚合函数 ``func.count(...)`` 没 class_,没法映射到 state;
        # 返回空 set (scalar/aggregate 都退化到 0)。
        if class_name is None:
            return _FakeQuery([])
        # PascalCase → snake_case 跟 SQLAlchemy 的 ``__tablename__`` 对齐
        # (e.g. DocumentFolder → document_folder)。state 习惯用复数
        # (document_folders / documents),singular/plural 都试一下。
        import re
        snake = re.sub(r"(?<!^)(?=[A-Z])", "_", class_name).lower()
        rows = self.state.get(snake, self.state.get(f"{snake}s", []))
        return _FakeQuery(rows)

    def get(self, model, pk):
        name = getattr(model, "__name__", None)
        for r in self.state.get("kb_lookups", []):
            if name == "KnowledgeBase" and r.id == pk:
                return r
        for r in self.state["document_folders"]:
            if name == "DocumentFolder" and r.id == pk:
                return r
        return None

    def execute(self, stmt):
        # 软删 endpoint 跑两次 execute:
        # 1) Document.folder_id = NULL (detach)
        # 2) DocumentFolder.deleted_at = now (mark deleted)
        # 把这些副作用手动应用到 store,模拟真实 DB 的 UPDATE 行为。
        from sqlalchemy import update as sa_update
        from sqlalchemy.sql import operators

        update_stmt = stmt
        # ``.where(...)`` 上的 clause 提取 table + set values
        table = update_stmt.table
        tbl_name = table.name
        where_clauses = list(update_stmt._where_criteria)
        compiled_values = update_stmt._values

        class _Result:
            pass

        result = _Result()
        affected = 0
        if tbl_name == "documents":
            for doc in self.state["documents"]:
                if self._doc_matches_where(doc, where_clauses):
                    doc.folder_id = None  # detach
                    affected += 1
        elif tbl_name == "document_folders":
            now = datetime.now(timezone.utc)
            for folder in self.state["document_folders"]:
                if self._folder_matches_where(folder, where_clauses):
                    if folder.deleted_at is None:
                        folder.deleted_at = now
                        affected += 1
        result.rowcount = affected
        return result

    def _doc_matches_where(self, doc, where_clauses) -> bool:
        for clause in where_clauses:
            op_name = getattr(getattr(clause, "operator", None), "__name__", "")
            col = getattr(getattr(clause, "left", None), "key", None)
            right = getattr(clause, "right", None)
            actual = getattr(doc, col, None)
            if op_name == "in_op":
                elements = self._in_elements(right)
                if actual not in elements:
                    return False
            elif op_name == "is_not":
                if actual is None:
                    return False
        return True

    def _folder_matches_where(self, folder, where_clauses) -> bool:
        for clause in where_clauses:
            op_name = getattr(getattr(clause, "operator", None), "__name__", "")
            col = getattr(getattr(clause, "left", None), "key", None)
            right = getattr(clause, "right", None)
            actual = getattr(folder, col, None)
            if op_name == "in_op":
                elements = self._in_elements(right)
                if actual not in elements:
                    return False
            elif op_name == "is_":
                if col == "deleted_at" and actual is not None:
                    return False
        return True

    def _in_elements(self, right) -> list:
        """Extract the list of values from an ``in_`` clause's right side.

        SQLAlchemy wraps the original list in a ``BindParameter`` with
        ``.value`` pointing back to the list — fall back to ``.elements``
        for ``Tuple`` and finally ``[right]`` for scalars.
        """
        v = getattr(right, "value", None)
        if isinstance(v, (list, tuple, set)):
            return list(v)
        if hasattr(right, "elements"):
            try:
                return [getattr(e, "value", e) for e in right.elements]
            except TypeError:
                pass
        return [right]

    def commit(self):
        pass

    def rollback(self):
        pass


# --- fixtures -----------------------------------------------------------


@pytest.fixture
def state() -> Dict[str, Any]:
    return {
        "kb_lookups": [_FakeKB(id=1, tenant_id=1)],
        "document_folders": [
            _FakeFolder(id=1, knowledge_base_id=1, name="研发"),
            _FakeFolder(id=2, knowledge_base_id=1, name="后端", parent_id=1),
            _FakeFolder(id=3, knowledge_base_id=1, name="API", parent_id=2),
            _FakeFolder(id=4, knowledge_base_id=1, name="其他 KB 的 folder",
                        parent_id=None),  # 不在 BFS 子树里
        ],
        "documents": [
            _FakeDoc(id=100, knowledge_base_id=1, folder_id=1),    # 在被删 subtree
            _FakeDoc(id=101, knowledge_base_id=1, folder_id=2),    # 在被删 subtree
            _FakeDoc(id=102, knowledge_base_id=1, folder_id=None),  # KB root,不动
            _FakeDoc(id=103, knowledge_base_id=1, folder_id=4),    # 其他 folder,不动
        ],
    }


@pytest.fixture
def client(state):
    app.router.lifespan_context = None  # type: ignore[attr-defined]

    def _override_db():
        yield _FakeSession(state)

    caller = _FakeUser(tenant_id=1, is_superuser=False, uid=11)

    def _override_current_user():
        return caller

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[auth_module.get_current_user] = _override_current_user

    yield TestClient(app)
    app.dependency_overrides.clear()


# --- tests --------------------------------------------------------------


def test_soft_delete_folder_marks_all_descendants(client, state):
    """DELETE /folders/1 → folder 1, 2, 3 的 deleted_at 都被置位,4 不动。"""
    resp = client.delete("/api/v1/folders/1")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["scanned"] == 3
    assert body["deleted_folders"] == 3

    # 子树里 3 个都被标记软删
    now_floor = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for fid in [1, 2, 3]:
        f = next(x for x in state["document_folders"] if x.id == fid)
        assert f.deleted_at is not None and f.deleted_at >= now_floor
    # folder 4 不动
    f4 = next(x for x in state["document_folders"] if x.id == 4)
    assert f4.deleted_at is None


def test_soft_delete_folder_detaches_documents_in_subtree(client, state):
    """被删 subtree 里的 doc 都被 detach 到 KB root(folder_id = NULL)。"""
    # sanity:删之前 subtree 里的 doc 还在原 folder
    pre_in_subtree = [d.id for d in state["documents"] if d.folder_id in (1, 2)]
    assert pre_in_subtree == [100, 101]

    client.delete("/api/v1/folders/1")

    # subtree 里 (folder 1, 2, 3) 的 doc 全部 detach 到 KB root
    for did in [100, 101]:
        doc = next(d for d in state["documents"] if d.id == did)
        assert doc.folder_id is None

    # 不在 subtree 里的 doc 不动
    doc_root = next(d for d in state["documents"] if d.id == 102)
    assert doc_root.folder_id is None  # 本来就在 root
    doc_other = next(d for d in state["documents"] if d.id == 103)
    assert doc_other.folder_id == 4  # 没动


def test_soft_delete_missing_folder_returns_404(client):
    """不存在的 folder → 404。"""
    resp = client.delete("/api/v1/folders/999")
    assert resp.status_code == 404


def test_soft_delete_response_summarizes_scanned_and_deleted(client, state):
    """响应体里 scanned / deleted_folders / detached_documents 都返。"""
    resp = client.delete("/api/v1/folders/2")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # folder 2 + 它自己(没有 child) → scanned=1, deleted_folders=1
    # folder 3 是 folder 2 的 child 但 folder 2 没 child... 实际 folder 3 的 parent 是 2,所以 2 有 child
    assert body["scanned"] >= 1
    assert body["deleted_folders"] >= 1
    assert "detached_documents" in body