# Lumen AI Platform Test Suite
"""Shared pytest fixtures."""
import pytest
import uuid
from lumen_core.database import SessionLocal
from lumen_core.security import get_password_hash
from lumen_models.user import User
from lumen_models.tenant import Tenant
from lumen_models.knowledge import KnowledgeBase
# M38.2 ship 漏项补注册 + 全量 ensure_*:tests 走 conftest.py 而不 import lumen_main,
# 但 Base.metadata 需要所有 model 类注册才能解析 FK,MySQL schema 也需要 lumen_main
# 的 lifespan startup 跑过 ensure_* 才完整(workspace_id / folder_id / asset_storage_key 等
# 后加列不会出现在 schema.sql 里)。直调 lumen_main._lifespan 一次性全跑,
# 后续 lumen_main 加新 model / 新 ensure_* 时 conftest 不需要改。
#
# Phase 1 Group A 1.1 (2026-09-03):lifespan 是 async context manager,
# 进入时跑 startup 逻辑(yield 前),退出时跑 shutdown(yield 后)。
# 我们只想跑 startup 拿到 ensure_* 副作用,所以 `async with` 进入后立刻退出。
import asyncio
from lumen_main import _lifespan, app as _lumen_app

async def _drive_lifespan_startup_once():
    async with _lifespan(_lumen_app):
        pass

try:
    asyncio.run(_drive_lifespan_startup_once())
except Exception as e:
    # lifespan 在已有 dev DB 状态上对幂等 ALTER 会偶发重复键警告等,
    # schema 已就位时 ensure_* 应 no-op,任何异常继续往下(让个别 test 自己报清晰的错)。
    print(f"WARNING: lumen_main._lifespan startup failed: {e}")


@pytest.fixture
def tmp_user():
    """Create a throwaway user, yield it, then delete.

    Ensures a tenant with id=1 exists (creates 'default' if missing).
    Username and email are randomized per test to avoid unique-constraint
    collisions when tests run in the same DB session.
    """
    db = SessionLocal()
    u = None
    try:
        tenant = db.query(Tenant).filter(Tenant.id == 1).first()
        if not tenant:
            tenant = Tenant(id=1, name="Default Tenant", code="default")
            db.add(tenant)
            db.commit()
            db.refresh(tenant)

        suffix = uuid.uuid4().hex[:8]
        u = User(
            username=f"notif_test_user_{suffix}",
            email=f"notif_{suffix}@test.local",
            hashed_password=get_password_hash("x"),
            tenant_id=1,
            is_active=True,
            is_superuser=True,  # M38.2.x v2: 旧 fixture 的 tmp_kb 默认 workspace_id=None,写操作(document.create 等)按 spec §6.4 要 superuser
        )
        db.add(u)
        db.commit()
        db.refresh(u)
        yield u
    finally:
        try:
            if u is not None:
                db.delete(u)
                db.commit()
        except Exception:
            db.rollback()
        finally:
            db.close()


@pytest.fixture
def tmp_kb(tmp_user):
    from lumen_models.knowledge import KnowledgeBase
    from lumen_core.database import SessionLocal
    db = SessionLocal()
    try:
        kb = KnowledgeBase(
            name="notif_test_kb",
            tenant_id=tmp_user.tenant_id,
        )
        db.add(kb); db.commit(); db.refresh(kb)
        yield kb
    finally:
        try:
            db.delete(kb); db.commit()
        except Exception:
            db.rollback()
        finally:
            db.close()


# —— Plain helpers (not fixtures) ——
# These are module-level functions (not @pytest.fixture) so tests can
# call them with arbitrary kwargs. They are NOT auto-cleaned up —
# callers are responsible for opening a Session, inserting, and closing
# the session. Used by the chat API test suites.

def make_conv(db, *, user_id: int, tenant_id: int, agent_id=None, title="t"):
    """Create + commit + refresh a Conversation row.

    Returns the ORM instance. Caller owns the session lifecycle.
    Shared by ``tests/unit/test_chat_api_delete.py`` and
    ``tests/unit/test_chat_conversation_agent.py``.
    """
    from lumen_models.chat import Conversation
    conv = Conversation(
        title=title,
        user_id=user_id,
        tenant_id=tenant_id,
        agent_id=agent_id,
    )
    db.add(conv)
    db.commit()
    db.refresh(conv)
    return conv


def make_agent(db, *, tenant_id: int, name="a", is_active=True,
               model_name="qwen2.5:7b"):
    """Create + commit + refresh an Agent row.

    Returns the ORM instance. Caller owns the session lifecycle.
    Shared by ``tests/unit/test_chat_conversation_agent.py``.
    """
    from lumen_models.agent import Agent
    a = Agent(
        name=name,
        prompt_template="p",
        model_name=model_name,
        temperature=0,
        tenant_id=tenant_id,
        is_active=is_active,
    )
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


def make_team(db, *, tenant_id: int, name="t", manager_agent_id=None,
              is_active=True):
    """Create + commit + refresh an AgentTeam row.

    Returns the ORM instance. Caller owns the session lifecycle.
    Used by ``test_chat_conversation_agent.py`` for the M30 P1-5
    "team-bound conv rejects agent_id" regression.
    """
    from lumen_models.agent_team import AgentTeam
    if manager_agent_id is None:
        # A team needs a manager FK; create a minimal agent.
        manager_agent_id = make_agent(
            db, tenant_id=tenant_id, name=f"{name}-manager",
        ).id
    t = AgentTeam(
        name=name,
        manager_agent_id=manager_agent_id,
        tenant_id=tenant_id,
        is_active=is_active,
        route_policy="manager_decides",
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


# —— M38.2.x v2: Workspace RBAC fixture helpers ——
#
# `_grant_default_workspace_admin(user_id, ws_id=None)` 把指定 user 在
# 指定 workspace 上「全 perm」都开出来。spec §6.4 老数据 (``workspace_id
# IS NULL`` 的 KB) 默认 read-class 对全员 in-tenant 开放,所以既有 1537 测试
# (用的都是 ``workspace_id=None`` KB) 不破 —— 读操作天然通过,写操作本来
# 就需要 superuser,那些 test 本身就走 superuser 路径。
#
# 新加的 workspace-scoped RBAC 测试 (``test_workspace_rbac_api`` 等) 走
# workspace fixture 路径,调用本 helper 后 user 就有 owner-bypass 之外的
# 全 perm 可测。

def _grant_default_workspace_admin(db, user_id: int, workspace_id: int) -> None:
    """给指定 user 在指定 workspace 上 grant ALL 19 个 perm。

    用 ``db.flush()`` 让 caller 在同一 session 里看到 grant 行;不在这里
    commit —— 由 caller 决定事务边界(便于多 fixture 共享一个 transaction)。
    """
    from lumen_models.workspace_member_permission import WorkspaceMemberPermission
    from lumen_services.permission_service import _ALL_PERMS
    for perm in _ALL_PERMS:
        db.add(WorkspaceMemberPermission(
            workspace_id=workspace_id,
            user_id=user_id,
            permission=perm,
            granted_by=user_id,  # 测试 helper 自授权,生产路径走真正的 actor
        ))
    db.flush()


@pytest.fixture
def tmp_workspace(tmp_user):
    """Create a workspace owned by ``tmp_user`` (so owner auto-bypass 触发),
    yield it, then cleanup (delete member rows first, then workspace).

    ``tmp_user`` 自动成为 owner → ``_is_owner`` check 在 workspace-scoped
    endpoint 一律 pass,无须手动 grant。RBAC 否定用例自己调
    ``_grant_default_workspace_admin(db, tmp_user.id, ws.id)`` 正面 grant,
    然后再 DELETE 来测拒绝。
    """
    from lumen_models.workspace import Workspace
    db = SessionLocal()
    ws = None
    try:
        ws = Workspace(
            tenant_id=tmp_user.tenant_id,
            owner_id=tmp_user.id,
            name=f"notif_test_ws_{uuid.uuid4().hex[:6]}",
            description="M38.2.x v2 fixture workspace",
        )
        db.add(ws)
        db.commit()
        db.refresh(ws)
        yield ws
    finally:
        try:
            if ws is not None:
                from lumen_models.workspace_member_permission import (
                    WorkspaceMemberPermission,
                )
                db.query(WorkspaceMemberPermission).filter(
                    WorkspaceMemberPermission.workspace_id == ws.id
                ).delete()
                db.delete(ws)
                db.commit()
        except Exception:
            db.rollback()
        finally:
            db.close()
