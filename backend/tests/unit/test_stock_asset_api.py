"""Integration tests for /api/v1/stock-assets endpoints.

M36.2.1: 验证列表/详情/图片代理都遵循租户隔离 + Bearer 鉴权契约。
"""
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from lumen_core.config import settings
from lumen_core.database import SessionLocal, ensure_stock_assets_table
from lumen_core.security import get_password_hash
from lumen_models.stock_asset import StockAsset
from lumen_models.tenant import Tenant
from lumen_models.user import User


def _make_client():
    from lumen_main import app
    return TestClient(app)


def _make_auth_header(user_id: int, username: str):
    from lumen_services.auth_service import create_access_token
    token = create_access_token(data={"sub": username, "user_id": user_id})
    return {"Authorization": f"Bearer {token}"}


def _make_setup(suffix: str):
    db = SessionLocal()
    try:
        t = Tenant(name=f"stock_api_t_{suffix}", code=f"stock_api_t_{suffix}")
        db.add(t); db.commit(); db.refresh(t)
        u = User(
            username=f"stock_api_u_{suffix}",
            email=f"stock_api_{suffix}@test.local",
            hashed_password=get_password_hash("x"),
            tenant_id=t.id, is_active=True,
        )
        db.add(u); db.commit(); db.refresh(u)
        return t.id, u.id, u.username
    finally:
        db.close()


@pytest.fixture
def client():
    return _make_client()


@pytest.fixture
def setup():
    ensure_stock_assets_table()
    suffix = uuid.uuid4().hex[:8]
    tenant_id, user_id, username = _make_setup(suffix)
    yield {"tenant_id": tenant_id, "user_id": user_id, "username": username}
    # Cleanup
    db = SessionLocal()
    try:
        db.query(StockAsset).filter(StockAsset.tenant_id == tenant_id).delete(
            synchronize_session=False,
        )
        db.commit()
        db.query(User).filter(User.id == user_id).delete(synchronize_session=False)
        db.commit()
        db.query(Tenant).filter(Tenant.id == tenant_id).delete(synchronize_session=False)
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()


def _make_stock(db, *, name: str, category: str, tenant_id, rel_path: str) -> StockAsset:
    row = StockAsset(
        name=name, category=category, tags=[category],
        file_path=rel_path, mime_type="image/png", file_size=128,
        source="builtin", tenant_id=tenant_id,
    )
    db.add(row); db.commit(); db.refresh(row)
    return row


def test_list_requires_auth(client):
    res = client.get("/api/v1/stock-assets/")
    assert res.status_code == 401


def test_list_returns_paginated_envelope(client, setup):
    headers = _make_auth_header(setup["user_id"], setup["username"])
    res = client.get("/api/v1/stock-assets/?page=1&page_size=24", headers=headers)
    assert res.status_code == 200
    body = res.json()
    assert body["code"] == 200
    assert isinstance(body["data"], list)
    assert "total" in body
    assert body["page"] == 1
    assert body["page_size"] == 24


def test_list_includes_global_and_own_tenant(client, setup):
    db = SessionLocal()
    suffix = uuid.uuid4().hex[:8]
    g = _make_stock(
        db, name=f"g_{suffix}", category="风景",
        tenant_id=None, rel_path=f"stock/g_{suffix}.png",
    )
    own = _make_stock(
        db, name=f"o_{suffix}", category="产品",
        tenant_id=setup["tenant_id"],
        rel_path=f"stock/{setup['tenant_id']}/o_{suffix}.png",
    )
    g_id, own_id = g.id, own.id
    db.close()
    headers = _make_auth_header(setup["user_id"], setup["username"])
    res = client.get(
        f"/api/v1/stock-assets/?search={suffix}", headers=headers,
    )
    assert res.status_code == 200
    ids = {row["id"] for row in res.json()["data"]}
    assert g_id in ids
    assert own_id in ids


def test_list_excludes_other_tenant_rows(client, setup):
    """A second tenant's row must be invisible to the first tenant."""
    db = SessionLocal()
    suffix = uuid.uuid4().hex[:8]
    other_t = Tenant(
        name=f"other_{suffix}", code=f"other_{suffix}",
    )
    db.add(other_t); db.commit(); db.refresh(other_t)
    other_row = _make_stock(
        db, name=f"x_{suffix}", category="商务",
        tenant_id=other_t.id,
        rel_path=f"stock/{other_t.id}/x_{suffix}.png",
    )
    other_id = other_row.id
    db.close()
    headers = _make_auth_header(setup["user_id"], setup["username"])
    res = client.get(
        f"/api/v1/stock-assets/?search={suffix}", headers=headers,
    )
    assert res.status_code == 200
    ids = {row["id"] for row in res.json()["data"]}
    assert other_id not in ids


def test_get_detail_404_for_missing(client, setup):
    headers = _make_auth_header(setup["user_id"], setup["username"])
    res = client.get("/api/v1/stock-assets/9999999", headers=headers)
    assert res.status_code == 404


def test_get_detail_returns_envelope(client, setup):
    db = SessionLocal()
    suffix = uuid.uuid4().hex[:8]
    row = _make_stock(
        db, name=f"d_{suffix}", category="风景",
        tenant_id=None, rel_path=f"stock/d_{suffix}.png",
    )
    row_id = row.id
    db.close()
    headers = _make_auth_header(setup["user_id"], setup["username"])
    res = client.get(f"/api/v1/stock-assets/{row_id}", headers=headers)
    assert res.status_code == 200
    body = res.json()
    assert body["code"] == 200
    assert body["data"]["id"] == row_id
    assert body["data"]["name"] == f"d_{suffix}"
    assert body["data"]["file_path"] == f"stock/d_{suffix}.png"


def test_get_image_streams_bytes(client, setup):
    """Image proxy serves the on-disk bytes with the configured media type."""
    db = SessionLocal()
    suffix = uuid.uuid4().hex[:8]
    rel_path = f"stock/img_{suffix}.png"
    abs_path = settings.STORAGE_DIR / rel_path
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    abs_path.write_bytes(b"\x89PNG\r\n\x1a\nstub")
    row = StockAsset(
        name=f"img_{suffix}", category="风景", tags=[],
        file_path=rel_path, mime_type="image/png", file_size=abs_path.stat().st_size,
        source="builtin", tenant_id=None,
    )
    db.add(row); db.commit(); db.refresh(row)
    row_id = row.id
    db.close()
    headers = _make_auth_header(setup["user_id"], setup["username"])
    res = client.get(f"/api/v1/stock-assets/{row_id}/image", headers=headers)
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("image/")
    assert res.content.startswith(b"\x89PNG")
    abs_path.unlink(missing_ok=True)


def test_get_image_404_when_file_missing(client, setup):
    """file_path on disk absent → 404, never leak the row metadata."""
    db = SessionLocal()
    suffix = uuid.uuid4().hex[:8]
    row = _make_stock(
        db, name=f"miss_{suffix}", category="风景",
        tenant_id=None, rel_path=f"stock/miss_{suffix}.png",
    )
    row_id = row.id
    db.close()
    headers = _make_auth_header(setup["user_id"], setup["username"])
    res = client.get(f"/api/v1/stock-assets/{row_id}/image", headers=headers)
    assert res.status_code == 404
