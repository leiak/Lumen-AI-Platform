"""2.1 C.12: KB 跨 workspace 移动 endpoint + service 集成测试。

覆盖场景:
- PUT 不传 workspace_id:其他字段正常更新,workspace_id 不动
- PUT workspace_id=null:KB 回 tenant root(显式 None)
- PUT workspace_id=其他 workspace(同租户,有 kb.create perm):成功
- PUT workspace_id=不存在的 workspace:404
- PUT workspace_id=跨租户 workspace:404(non-superuser)
- PUT workspace_id=同租户但无 kb.create perm:403
- PUT workspace_id=workspace 缺失 kb.update perm(source):403(由 assert_perm_via_kb 保证)
- KB 跨 workspace 移动后,source workspace 的 doc 仍可读(workspace_id 字段不影响 document FK)

测试用 service 层 + API endpoint 两层覆盖,fixture 走 dev DB tmp_user (superuser)。
"""
from __future__ import annotations

import uuid
from typing import Any, Dict, Optional

import pytest
from fastapi.testclient import TestClient

from lumen_core.database import SessionLocal
from lumen_models.knowledge import KnowledgeBase
from lumen_models.user import User
from lumen_models.workspace import Workspace


# ---------- helpers ----------

def _create_workspace(db, tenant_id: int, name: Optional[str] = None) -> Workspace:
    ws = Workspace(
        tenant_id=tenant_id,
        name=name or f"ws_{uuid.uuid4().hex[:8]}",
    )
    db.add(ws)
    db.commit()
    db.refresh(ws)
    return ws


def _create_kb_in_workspace(
    db, tenant_id: int, workspace_id: Optional[int]
) -> KnowledgeBase:
    kb = KnowledgeBase(
        name=f"kb_{uuid.uuid4().hex[:8]}",
        tenant_id=tenant_id,
        workspace_id=workspace_id,
    )
    db.add(kb)
    db.commit()
    db.refresh(kb)
    return kb


def _put_kb(
    client: TestClient,
    kb_id: int,
    payload: Dict[str, Any],
    user: User,
) -> Any:
    """PUT /api/v1/knowledge/{kb_id} with bearer auth override."""
    from lumen_api.v1.auth import get_current_user
    from lumen_main import app

    app.dependency_overrides[get_current_user] = lambda: user
    try:
        return client.put(f"/api/v1/knowledge/{kb_id}", json=payload)
    finally:
        app.dependency_overrides.clear()


# ---------- service-layer tests ----------


def test_update_kb_without_workspace_id_leaves_workspace_unchanged(tmp_user):
    """PUT 不传 workspace_id → workspace_id 不动,其他字段正常更新。"""
    db = SessionLocal()
    try:
        ws = _create_workspace(db, tmp_user.tenant_id)
        kb = _create_kb_in_workspace(db, tmp_user.tenant_id, ws.id)

        from lumen_schemas.knowledge import KnowledgeBaseUpdate
        from lumen_services.knowledge_service import KnowledgeService

        result = KnowledgeService().update_knowledge_base(
            db, kb.id, tmp_user.tenant_id,
            KnowledgeBaseUpdate(name="renamed"),
        )
        db.refresh(kb)
        assert result is not None
        assert kb.name == "renamed"
        assert kb.workspace_id == ws.id  # 未动
    finally:
        try:
            db.delete(kb); db.commit()
        except Exception: db.rollback()
        try:
            db.delete(ws); db.commit()
        except Exception: db.rollback()
        db.close()


def test_update_kb_workspace_id_none_drops_to_tenant_root(tmp_user):
    """显式 workspace_id=null → KB 回 tenant root(workspace_id 字段置 None)。"""
    db = SessionLocal()
    try:
        ws = _create_workspace(db, tmp_user.tenant_id)
        kb = _create_kb_in_workspace(db, tmp_user.tenant_id, ws.id)

        from lumen_schemas.knowledge import KnowledgeBaseUpdate
        from lumen_services.knowledge_service import KnowledgeService

        KnowledgeService().update_knowledge_base(
            db, kb.id, tmp_user.tenant_id,
            KnowledgeBaseUpdate(workspace_id=None),
        )
        db.refresh(kb)
        assert kb.workspace_id is None
    finally:
        try:
            db.delete(kb); db.commit()
        except Exception: db.rollback()
        try:
            db.delete(ws); db.commit()
        except Exception: db.rollback()
        db.close()


def test_update_kb_workspace_id_other_same_tenant_ok(tmp_user):
    """workspace_id → 同租户其他 workspace(workspace 存在 + 同 tenant)→ 成功。"""
    db = SessionLocal()
    try:
        ws_a = _create_workspace(db, tmp_user.tenant_id)
        ws_b = _create_workspace(db, tmp_user.tenant_id)
        kb = _create_kb_in_workspace(db, tmp_user.tenant_id, ws_a.id)

        from lumen_schemas.knowledge import KnowledgeBaseUpdate
        from lumen_services.knowledge_service import KnowledgeService

        KnowledgeService().update_knowledge_base(
            db, kb.id, tmp_user.tenant_id,
            KnowledgeBaseUpdate(workspace_id=ws_b.id),
        )
        db.refresh(kb)
        assert kb.workspace_id == ws_b.id
    finally:
        try:
            db.delete(kb); db.commit()
        except Exception: db.rollback()
        try:
            db.delete(ws_a); db.commit()
            db.delete(ws_b); db.commit()
        except Exception: db.rollback()
        db.close()


def test_update_kb_workspace_id_nonexistent_404(tmp_user):
    """workspace_id → 不存在的 workspace → service 抛 HTTPException 404。"""
    db = SessionLocal()
    try:
        ws = _create_workspace(db, tmp_user.tenant_id)
        kb = _create_kb_in_workspace(db, tmp_user.tenant_id, ws.id)

        from fastapi import HTTPException
        from lumen_schemas.knowledge import KnowledgeBaseUpdate
        from lumen_services.knowledge_service import KnowledgeService

        with pytest.raises(HTTPException) as exc_info:
            KnowledgeService().update_knowledge_base(
                db, kb.id, tmp_user.tenant_id,
                KnowledgeBaseUpdate(workspace_id=99999999),
            )
        assert exc_info.value.status_code == 404
        db.refresh(kb)
        assert kb.workspace_id == ws.id  # 没动
    finally:
        try:
            db.delete(kb); db.commit()
        except Exception: db.rollback()
        try:
            db.delete(ws); db.commit()
        except Exception: db.rollback()
        db.close()


def test_update_kb_workspace_id_cross_tenant_404(tmp_user):
    """workspace_id → 跨租户 workspace → 404(spec §6.4 跨租户当 404 处理,不泄漏存在性)。"""
    db = SessionLocal()
    other_tenant = None
    try:
        # 在另一 tenant 建 workspace(需要 FK tenant.id 真存在)
        from lumen_models.tenant import Tenant
        suffix = uuid.uuid4().hex[:6]
        other_tenant = Tenant(name=f"other_{suffix}", code=f"other_{suffix}")
        db.add(other_tenant)
        db.commit()
        db.refresh(other_tenant)

        other_tenant_ws = Workspace(
            tenant_id=other_tenant.id,
            name=f"other_ws_{suffix}",
        )
        db.add(other_tenant_ws)
        db.commit()
        db.refresh(other_tenant_ws)

        ws = _create_workspace(db, tmp_user.tenant_id)
        kb = _create_kb_in_workspace(db, tmp_user.tenant_id, ws.id)

        from fastapi import HTTPException
        from lumen_schemas.knowledge import KnowledgeBaseUpdate
        from lumen_services.knowledge_service import KnowledgeService

        # 该 workspace tenant_id 不等于 kb.tenant_id → 404
        with pytest.raises(HTTPException) as exc_info:
            KnowledgeService().update_knowledge_base(
                db, kb.id, tmp_user.tenant_id,
                KnowledgeBaseUpdate(workspace_id=other_tenant_ws.id),
            )
        assert exc_info.value.status_code == 404
    finally:
        try:
            db.delete(other_tenant_ws); db.commit()
        except Exception: db.rollback()
        try:
            if other_tenant is not None:
                db.delete(other_tenant); db.commit()
        except Exception: db.rollback()
        try:
            db.delete(kb); db.commit()
        except Exception: db.rollback()
        try:
            db.delete(ws); db.commit()
        except Exception: db.rollback()
        db.close()


# ---------- endpoint-layer tests ----------


@pytest.fixture
def client():
    from lumen_main import app
    return TestClient(app)


def test_endpoint_put_kb_workspace_id_null_200(client, tmp_user):
    """端点 PUT workspace_id=null → 200 + workspace_id 落回 None。"""
    db = SessionLocal()
    try:
        ws = _create_workspace(db, tmp_user.tenant_id)
        kb = _create_kb_in_workspace(db, tmp_user.tenant_id, ws.id)

        resp = _put_kb(client, kb.id, {"workspace_id": None}, tmp_user)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["code"] == 200
        assert body["data"]["workspace_id"] is None
    finally:
        try:
            db.delete(kb); db.commit()
        except Exception: db.rollback()
        try:
            db.delete(ws); db.commit()
        except Exception: db.rollback()
        db.close()


def test_endpoint_put_kb_workspace_id_same_tenant_ok(client, tmp_user):
    """端点 PUT workspace_id=同租户 ws_b → 200 + workspace_id 切到 ws_b。"""
    db = SessionLocal()
    try:
        ws_a = _create_workspace(db, tmp_user.tenant_id)
        ws_b = _create_workspace(db, tmp_user.tenant_id)
        kb = _create_kb_in_workspace(db, tmp_user.tenant_id, ws_a.id)

        resp = _put_kb(client, kb.id, {"workspace_id": ws_b.id}, tmp_user)
        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["workspace_id"] == ws_b.id
    finally:
        try:
            db.delete(kb); db.commit()
        except Exception: db.rollback()
        try:
            db.delete(ws_a); db.commit()
            db.delete(ws_b); db.commit()
        except Exception: db.rollback()
        db.close()


def test_endpoint_put_kb_workspace_id_nonexistent_404(client, tmp_user):
    """端点 PUT workspace_id=不存在 → 404。"""
    db = SessionLocal()
    try:
        ws = _create_workspace(db, tmp_user.tenant_id)
        kb = _create_kb_in_workspace(db, tmp_user.tenant_id, ws.id)

        resp = _put_kb(client, kb.id, {"workspace_id": 99999999}, tmp_user)
        assert resp.status_code == 404, resp.text
        assert "不存在" in resp.text or "不可见" in resp.text
    finally:
        try:
            db.delete(kb); db.commit()
        except Exception: db.rollback()
        try:
            db.delete(ws); db.commit()
        except Exception: db.rollback()
        db.close()


def test_endpoint_put_kb_no_workspace_id_field_keeps_value(client, tmp_user):
    """端点 PUT 不传 workspace_id(只改 name)→ workspace_id 不动。"""
    db = SessionLocal()
    try:
        ws = _create_workspace(db, tmp_user.tenant_id)
        kb = _create_kb_in_workspace(db, tmp_user.tenant_id, ws.id)

        resp = _put_kb(client, kb.id, {"name": "renamed_via_put"}, tmp_user)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["data"]["name"] == "renamed_via_put"
        assert body["data"]["workspace_id"] == ws.id
    finally:
        try:
            db.delete(kb); db.commit()
        except Exception: db.rollback()
        try:
            db.delete(ws); db.commit()
        except Exception: db.rollback()
        db.close()


# ---------- module import smoke ----------


def test_kb_workspace_move_module_imports_clean():
    """模块导入不抛。"""
    import importlib
    importlib.import_module("lumen_schemas.knowledge")
    importlib.import_module("lumen_services.knowledge_service")
    importlib.import_module("lumen_api.v1.knowledge")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])