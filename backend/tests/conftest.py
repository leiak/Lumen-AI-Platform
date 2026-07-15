# Lumen AI Platform Test Suite
"""Shared pytest fixtures."""
import pytest
import uuid
from lumen_core.database import SessionLocal
from lumen_core.security import get_password_hash
from lumen_models.user import User
from lumen_models.tenant import Tenant
from lumen_models.knowledge import KnowledgeBase


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
