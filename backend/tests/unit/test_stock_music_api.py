"""Integration tests for /api/v1/stock-musics endpoints.

M36.2.2: 验证列表 / 详情 / 音频代理都遵循租户隔离 + Bearer 鉴权契约,
镜像 ``test_stock_asset_api``。
"""
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from lumen_core.config import settings
from lumen_core.database import SessionLocal, ensure_stock_musics_table
from lumen_core.security import get_password_hash
from lumen_models.stock_music import StockMusic
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
        t = Tenant(name=f"sm_api_t_{suffix}", code=f"sm_api_t_{suffix}")
        db.add(t); db.commit(); db.refresh(t)
        u = User(
            username=f"sm_api_u_{suffix}",
            email=f"sm_api_{suffix}@test.local",
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
    ensure_stock_musics_table()
    suffix = uuid.uuid4().hex[:8]
    tenant_id, user_id, username = _make_setup(suffix)
    yield {"tenant_id": tenant_id, "user_id": user_id, "username": username}
    db = SessionLocal()
    try:
        db.query(StockMusic).filter(StockMusic.tenant_id == tenant_id).delete(
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


def _make_music(db, *, name: str, category: str, tenant_id, rel_path: str) -> StockMusic:
    row = StockMusic(
        name=name, category=category, description="",
        file_path=rel_path, mime_type="audio/mpeg",
        file_size=235000, duration_seconds=30.0,
        source="builtin", tenant_id=tenant_id,
    )
    db.add(row); db.commit(); db.refresh(row)
    return row


def test_list_requires_auth(client):
    res = client.get("/api/v1/stock-musics/")
    assert res.status_code == 401


def test_list_returns_paginated_envelope(client, setup):
    headers = _make_auth_header(setup["user_id"], setup["username"])
    res = client.get("/api/v1/stock-musics/?page=1&page_size=24", headers=headers)
    assert res.status_code == 200
    body = res.json()
    assert body["code"] == 200
    assert isinstance(body["data"], list)
    assert "total" in body
    assert body["page"] == 1
    assert body["page_size"] == 24


def test_list_excludes_other_tenant_rows(client, setup):
    """A second tenant's BGM row must be invisible to the first tenant."""
    db = SessionLocal()
    suffix = uuid.uuid4().hex[:8]
    other_t = Tenant(name=f"sm_other_{suffix}", code=f"sm_other_{suffix}")
    db.add(other_t); db.commit(); db.refresh(other_t)
    other_row = _make_music(
        db, name=f"x_{suffix}", category="商务",
        tenant_id=other_t.id,
        rel_path=f"stock/music/{other_t.id}/x_{suffix}.mp3",
    )
    other_id = other_row.id
    db.close()
    headers = _make_auth_header(setup["user_id"], setup["username"])
    res = client.get(
        f"/api/v1/stock-musics/?search={suffix}", headers=headers,
    )
    assert res.status_code == 200
    ids = {row["id"] for row in res.json()["data"]}
    assert other_id not in ids


def test_get_detail_returns_envelope(client, setup):
    db = SessionLocal()
    suffix = uuid.uuid4().hex[:8]
    row = _make_music(
        db, name=f"d_{suffix}", category="舒缓",
        tenant_id=None, rel_path=f"stock/music/d_{suffix}.mp3",
    )
    row_id = row.id
    db.close()
    headers = _make_auth_header(setup["user_id"], setup["username"])
    res = client.get(f"/api/v1/stock-musics/{row_id}", headers=headers)
    assert res.status_code == 200
    body = res.json()
    assert body["code"] == 200
    assert body["data"]["id"] == row_id
    assert body["data"]["file_path"] == f"stock/music/d_{suffix}.mp3"


def test_get_file_streams_bytes(client, setup):
    """Audio proxy serves the on-disk bytes with the configured media type."""
    db = SessionLocal()
    suffix = uuid.uuid4().hex[:8]
    rel_path = f"stock/music/file_{suffix}.mp3"
    abs_path = settings.STORAGE_DIR / rel_path
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    abs_path.write_bytes(b"ID3\x03\x00\x00\x00\x00\x00\x00stub")
    row = StockMusic(
        name=f"f_{suffix}", category="氛围", description="",
        file_path=rel_path, mime_type="audio/mpeg",
        file_size=abs_path.stat().st_size, duration_seconds=0.1,
        source="builtin", tenant_id=None,
    )
    db.add(row); db.commit(); db.refresh(row)
    row_id = row.id
    db.close()
    headers = _make_auth_header(setup["user_id"], setup["username"])
    res = client.get(f"/api/v1/stock-musics/{row_id}/file", headers=headers)
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("audio/")
    assert res.content.startswith(b"ID3")
    abs_path.unlink(missing_ok=True)


def test_get_file_404_when_missing(client, setup):
    """Missing on-disk file → 404 (never leak row metadata)."""
    db = SessionLocal()
    suffix = uuid.uuid4().hex[:8]
    row = _make_music(
        db, name=f"miss_{suffix}", category="氛围",
        tenant_id=None, rel_path=f"stock/music/miss_{suffix}.mp3",
    )
    row_id = row.id
    db.close()
    headers = _make_auth_header(setup["user_id"], setup["username"])
    res = client.get(f"/api/v1/stock-musics/{row_id}/file", headers=headers)
    assert res.status_code == 404
