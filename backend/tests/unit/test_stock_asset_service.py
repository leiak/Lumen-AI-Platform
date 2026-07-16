"""Tests for StockService query layer.

Covers tenant-scoped list/get and the safe file-path resolver
(``get_file_abs_path``) that protects against ``..`` escapes.
"""
import uuid
from pathlib import Path

import pytest

from lumen_core.config import settings
from lumen_core.database import SessionLocal, ensure_stock_assets_table
from lumen_core.security import get_password_hash
from lumen_models.stock_asset import StockAsset
from lumen_models.tenant import Tenant
from lumen_models.user import User
from lumen_services.stock_service import StockService


@pytest.fixture
def db_session():
    ensure_stock_assets_table()
    db = SessionLocal()
    try:
        tenant = db.query(Tenant).filter(Tenant.id == 1).first()
        if not tenant:
            tenant = Tenant(id=1, name="Default Tenant", code="default")
            db.add(tenant)
            db.commit()
            db.refresh(tenant)
        yield db
    finally:
        db.close()


def _make_tenant(db, suffix: str) -> Tenant:
    t = Tenant(name=f"stock_svc_t_{suffix}", code=f"stock_svc_t_{suffix}")
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


def _make_user(db, *, tenant_id: int, suffix: str) -> User:
    u = User(
        username=f"stock_svc_u_{suffix}",
        email=f"stock_svc_{suffix}@test.local",
        hashed_password=get_password_hash("x"),
        tenant_id=tenant_id,
        is_active=True,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _make_stock(db, *, name: str, category: str, tenant_id, rel_path: str) -> StockAsset:
    row = StockAsset(
        name=name, category=category, tags=[category],
        file_path=rel_path, mime_type="image/png", file_size=128,
        source="builtin", tenant_id=tenant_id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def test_list_returns_global_and_own_tenant_only(db_session):
    """Service list exposes global rows + current tenant rows, never other tenants."""
    svc = StockService()
    suffix = uuid.uuid4().hex[:8]
    t1 = _make_tenant(db_session, f"t1_{suffix}")
    t2 = _make_tenant(db_session, f"t2_{suffix}")
    user1 = _make_user(db_session, tenant_id=t1.id, suffix=f"t1_{suffix}")

    global_row = _make_stock(
        db_session, name=f"g_{suffix}", category="风景",
        tenant_id=None, rel_path=f"stock/g_{suffix}.png",
    )
    own_row = _make_stock(
        db_session, name=f"o_{suffix}", category="产品",
        tenant_id=t1.id, rel_path=f"stock/{t1.id}/o_{suffix}.png",
    )
    other_row = _make_stock(
        db_session, name=f"x_{suffix}", category="商务",
        tenant_id=t2.id, rel_path=f"stock/{t2.id}/x_{suffix}.png",
    )
    g_id, o_id, x_id = global_row.id, own_row.id, other_row.id

    try:
        # search by suffix filters down to the three rows we just made.
        rows, total = svc.list_assets(
            db_session, tenant_id=t1.id, search=suffix,
            page=1, page_size=50,
        )
        ids = {r.id for r in rows}
        assert g_id in ids
        assert o_id in ids
        assert x_id not in ids
        assert total == 2
    finally:
        for row_id in (g_id, o_id, x_id):
            db_session.query(StockAsset).filter(StockAsset.id == row_id).delete(
                synchronize_session=False,
            )
        db_session.query(User).filter(User.id == user1.id).delete(
            synchronize_session=False,
        )
        for tid in (t1.id, t2.id):
            db_session.query(Tenant).filter(Tenant.id == tid).delete(
                synchronize_session=False,
            )
        db_session.commit()


def test_list_filters_by_category_and_search(db_session):
    svc = StockService()
    suffix = uuid.uuid4().hex[:8]
    keep = _make_stock(
        db_session, name=f"日照金山_{suffix}", category="风景",
        tenant_id=None, rel_path=f"stock/a_{suffix}.png",
    )
    drop = _make_stock(
        db_session, name=f"音箱_{suffix}", category="产品",
        tenant_id=None, rel_path=f"stock/b_{suffix}.png",
    )

    try:
        rows, total = svc.list_assets(
            db_session, tenant_id=None, category="风景", page=1, page_size=50,
        )
        assert all(r.category == "风景" for r in rows)
        assert keep.id in {r.id for r in rows}
        assert drop.id not in {r.id for r in rows}

        rows, total = svc.list_assets(
            db_session, tenant_id=None, search=suffix, page=1, page_size=50,
        )
        # search matches substring of `name` (we set name to include suffix)
        assert total == 2
    finally:
        for row_id in (keep.id, drop.id):
            db_session.query(StockAsset).filter(StockAsset.id == row_id).delete(
                synchronize_session=False,
            )
        db_session.commit()


def test_get_returns_global_or_own_tenant_row(db_session):
    svc = StockService()
    suffix = uuid.uuid4().hex[:8]
    t1 = _make_tenant(db_session, f"t1_{suffix}")
    t2 = _make_tenant(db_session, f"t2_{suffix}")
    g = _make_stock(
        db_session, name=f"g_{suffix}", category="风景",
        tenant_id=None, rel_path=f"stock/g_{suffix}.png",
    )
    o = _make_stock(
        db_session, name=f"o_{suffix}", category="风景",
        tenant_id=t1.id, rel_path=f"stock/{t1.id}/o_{suffix}.png",
    )
    other = _make_stock(
        db_session, name=f"x_{suffix}", category="风景",
        tenant_id=t2.id, rel_path=f"stock/{t2.id}/x_{suffix}.png",
    )

    try:
        # Global row visible to any tenant
        assert svc.get(db_session, asset_id=g.id, tenant_id=t1.id) is not None
        # Own tenant row visible
        assert svc.get(db_session, asset_id=o.id, tenant_id=t1.id) is not None
        # Other tenant's row hidden
        assert svc.get(db_session, asset_id=other.id, tenant_id=t1.id) is None
    finally:
        for row_id in (g.id, o.id, other.id):
            db_session.query(StockAsset).filter(StockAsset.id == row_id).delete(
                synchronize_session=False,
            )
        for tid in (t1.id, t2.id):
            db_session.query(Tenant).filter(Tenant.id == tid).delete(
                synchronize_session=False,
            )
        db_session.commit()


def test_get_file_abs_path_returns_existing_file(db_session):
    svc = StockService()
    suffix = uuid.uuid4().hex[:8]
    rel_path = f"stock/abs_{suffix}.png"
    abs_path = settings.STORAGE_DIR / rel_path
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    abs_path.write_bytes(b"\x89PNG\r\n\x1a\nstub")
    row = StockAsset(
        name=f"abs_{suffix}", category="风景", tags=[],
        file_path=rel_path, mime_type="image/png", file_size=10,
        source="builtin", tenant_id=None,
    )
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)

    try:
        resolved = svc.get_file_abs_path(row)
        assert resolved is not None
        assert Path(resolved).is_file()
    finally:
        db_session.query(StockAsset).filter(StockAsset.id == row.id).delete(
            synchronize_session=False,
        )
        db_session.commit()
        abs_path.unlink(missing_ok=True)


def test_get_file_abs_path_rejects_path_escape(db_session):
    """file_path = '../evil.png' must not be resolved outside STORAGE_DIR."""
    svc = StockService()
    suffix = uuid.uuid4().hex[:8]
    row = StockAsset(
        name=f"evil_{suffix}", category="风景", tags=[],
        file_path=f"../evil_{suffix}.png", mime_type="image/png", file_size=0,
        source="builtin", tenant_id=None,
    )
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    try:
        assert svc.get_file_abs_path(row) is None
    finally:
        db_session.query(StockAsset).filter(StockAsset.id == row.id).delete(
            synchronize_session=False,
        )
        db_session.commit()


def test_get_file_abs_path_rejects_absolute_path(db_session):
    """An absolute file_path must be rejected (only relative paths allowed)."""
    svc = StockService()
    suffix = uuid.uuid4().hex[:8]
    row = StockAsset(
        name=f"abs2_{suffix}", category="风景", tags=[],
        file_path=f"/etc/passwd_{suffix}", mime_type="image/png", file_size=0,
        source="builtin", tenant_id=None,
    )
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    try:
        assert svc.get_file_abs_path(row) is None
    finally:
        db_session.query(StockAsset).filter(StockAsset.id == row.id).delete(
            synchronize_session=False,
        )
        db_session.commit()
