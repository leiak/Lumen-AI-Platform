"""Admin CRUD for /api/v1/external-apps — full lifecycle management
of external widget credentials.

Distinct from /external/* (the public, bearer-token routes). All
endpoints here require a logged-in user with appropriate RBAC
permission (default: admin role = is_superuser), and are tenant-scoped:
a user in tenant A cannot see / mutate apps in tenant B (404, not 403,
to avoid id enumeration).
"""
import secrets
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from lumen_api.v1.auth import get_current_user
from lumen_core.database import get_db
from lumen_core.dynamic_cors import get_cors_cache
from lumen_core.security import get_password_hash
from lumen_models.agent import Agent
from lumen_models.agent_team import AgentTeam
from lumen_models.chat import Conversation
from lumen_models.external_app import ExternalApp, ExternalVisitor
from lumen_models.user import User
from lumen_schemas.common import PaginatedResponse, SingleResponse
from lumen_schemas.external_apps import (
    ExternalAppCreate, ExternalAppUpdate,
    ExternalAppResponse, ExternalAppCreated, ExternalAppUsage,
)

router = APIRouter(prefix="/external-apps", tags=["external-apps"])


def _require_admin(u: User) -> None:
    """Admin gate for /external-apps/* endpoints.

    MVP uses the existing ``is_superuser`` flag. Once the RBAC table
    ships (see Role/Permission models in app/models/role.py), swap
    this to:
        from lumen_services.rbac_service import user_has_permission
        if not user_has_permission(u, "external_apps:manage"):
            raise HTTPException(403, "missing permission external_apps:manage")
    The contract is: superuser (admin role) has all permissions; viewer
    role gets only GET. This is what the role-mgmt UI already does for
    model_configs, so reuse the same role list when the RBAC upgrade
    lands.
    """
    if not getattr(u, "is_superuser", False):
        raise HTTPException(403, "missing permission external_apps:manage")


def _gen_app_key() -> str:
    return "lc_pub_" + secrets.token_hex(16)


def _gen_app_secret() -> str:
    return "sk_" + secrets.token_hex(32)


def _to_response(a: ExternalApp, agent_names: list, team_names: list) -> ExternalAppResponse:
    return ExternalAppResponse(
        id=a.id, tenant_id=a.tenant_id, name=a.name, app_key=a.app_key,
        allowed_origins=a.allowed_origins or [],
        allowed_agent_ids=a.allowed_agent_ids or [],
        allowed_team_ids=a.allowed_team_ids or [],
        scopes=a.scopes or "",
        rate_limit_per_min=a.rate_limit_per_min,
        is_active=a.is_active,
        description=a.description,
        created_by=a.created_by,
        last_used_at=a.last_used_at.isoformat() if a.last_used_at else None,
        created_at=a.created_at.isoformat() if a.created_at else "",
        updated_at=a.updated_at.isoformat() if a.updated_at else "",
        allowed_agent_names=agent_names,
        allowed_team_names=team_names,
    )


def _resolve_names(db: Session, app: ExternalApp) -> tuple[list, list]:
    """Resolve agent/team names for the allowed_*_ids on this app.

    Pydantic 2 silently drops joined columns on from_attributes=True
    (see MEMORY.md), so we MUST construct the response with these
    names explicitly. Returns (agent_names, team_names) as lists of str.
    """
    agent_names = (
        [n for (n,) in db.query(Agent.name).filter(Agent.id.in_(app.allowed_agent_ids or [])).all()]
        if app.allowed_agent_ids else []
    )
    team_names = (
        [n for (n,) in db.query(AgentTeam.name).filter(AgentTeam.id.in_(app.allowed_team_ids or [])).all()]
        if app.allowed_team_ids else []
    )
    return agent_names, team_names


@router.get("", response_model=PaginatedResponse[ExternalAppResponse])
async def list_apps(
    page: int = 1,
    page_size: int = 20,
    search: str | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_admin(current_user)
    q = db.query(ExternalApp).filter(ExternalApp.tenant_id == current_user.tenant_id)
    if search:
        q = q.filter(ExternalApp.name.like(f"%{search}%"))
    total = q.count()
    rows = q.order_by(ExternalApp.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
    # Resolve names in bulk to avoid N+1
    all_agent_ids = {i for r in rows for i in (r.allowed_agent_ids or [])}
    all_team_ids = {i for r in rows for i in (r.allowed_team_ids or [])}
    agent_name_map = {a.id: a.name for a in db.query(Agent).filter(Agent.id.in_(all_agent_ids)).all()} if all_agent_ids else {}
    team_name_map = {t.id: t.name for t in db.query(AgentTeam).filter(AgentTeam.id.in_(all_team_ids)).all()} if all_team_ids else {}
    out = [
        _to_response(r, [agent_name_map.get(i, str(i)) for i in (r.allowed_agent_ids or [])],
                              [team_name_map.get(i, str(i)) for i in (r.allowed_team_ids or [])])
        for r in rows
    ]
    return PaginatedResponse(data=out, total=total, page=page, page_size=page_size)


@router.post("", response_model=SingleResponse[ExternalAppCreated])
async def create_app(
    req: ExternalAppCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_admin(current_user)
    key = _gen_app_key()
    secret_plain = _gen_app_secret()
    a = ExternalApp(
        tenant_id=current_user.tenant_id,
        name=req.name, description=req.description,
        app_key=key, app_secret_hash=get_password_hash(secret_plain),
        allowed_origins=req.allowed_origins,
        allowed_agent_ids=req.allowed_agent_ids,
        allowed_team_ids=req.allowed_team_ids,
        scopes=req.scopes,
        rate_limit_per_min=req.rate_limit_per_min,
        created_by=current_user.id,
    )
    db.add(a)
    db.commit()
    db.refresh(a)
    get_cors_cache().invalidate()  # new origin may need to take effect immediately
    return SingleResponse(data=ExternalAppCreated(
        **_to_response(a, [], []).model_dump(), app_secret_plain=secret_plain
    ))


@router.get("/{app_id}", response_model=SingleResponse[ExternalAppResponse])
async def get_app(
    app_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_admin(current_user)
    a = db.get(ExternalApp, app_id)
    if not a or a.tenant_id != current_user.tenant_id:
        raise HTTPException(404, "not found")
    agent_names, team_names = _resolve_names(db, a)
    return SingleResponse(data=_to_response(a, agent_names, team_names))


@router.patch("/{app_id}", response_model=SingleResponse[ExternalAppResponse])
async def update_app(
    app_id: int,
    req: ExternalAppUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_admin(current_user)
    a = db.get(ExternalApp, app_id)
    if not a or a.tenant_id != current_user.tenant_id:
        raise HTTPException(404, "not found")
    if req.name is not None:
        a.name = req.name
    if req.description is not None:
        a.description = req.description
    if req.allowed_origins is not None:
        a.allowed_origins = req.allowed_origins
    if req.allowed_agent_ids is not None:
        a.allowed_agent_ids = req.allowed_agent_ids
    if req.allowed_team_ids is not None:
        a.allowed_team_ids = req.allowed_team_ids
    if req.scopes is not None:
        a.scopes = req.scopes
    if req.rate_limit_per_min is not None:
        a.rate_limit_per_min = req.rate_limit_per_min
    if req.is_active is not None:
        a.is_active = req.is_active
    db.commit()
    db.refresh(a)
    get_cors_cache().invalidate()  # origin list may have changed
    agent_names, team_names = _resolve_names(db, a)
    return SingleResponse(data=_to_response(a, agent_names, team_names))


@router.delete("/{app_id}", response_model=SingleResponse[None])
async def delete_app(
    app_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_admin(current_user)
    a = db.get(ExternalApp, app_id)
    if not a or a.tenant_id != current_user.tenant_id:
        raise HTTPException(404, "not found")
    # Reference protection — same pattern as M13 KB delete (CLAUDE.md §7)
    has_active = db.query(Conversation.id).filter(
        Conversation.external_app_id == a.id,
        Conversation.deleted_at.is_(None),
    ).first()
    if has_active:
        raise HTTPException(409, "app has active conversations, disable instead")
    db.delete(a)
    db.commit()
    get_cors_cache().invalidate()
    return SingleResponse(message="Deleted successfully")


@router.post("/{app_id}/regenerate-secret", response_model=SingleResponse[ExternalAppCreated])
async def regenerate_secret(
    app_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_admin(current_user)
    a = db.get(ExternalApp, app_id)
    if not a or a.tenant_id != current_user.tenant_id:
        raise HTTPException(404, "not found")
    secret_plain = _gen_app_secret()
    a.app_secret_hash = get_password_hash(secret_plain)
    db.commit()
    db.refresh(a)
    return SingleResponse(data=ExternalAppCreated(
        **_to_response(a, [], []).model_dump(), app_secret_plain=secret_plain
    ))


@router.get("/{app_id}/usage", response_model=SingleResponse[ExternalAppUsage])
async def get_usage(
    app_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_admin(current_user)
    a = db.get(ExternalApp, app_id)
    if not a or a.tenant_id != current_user.tenant_id:
        raise HTTPException(404, "not found")
    cutoff = datetime.utcnow() - timedelta(days=7)
    active_visitors = db.query(func.count(ExternalVisitor.id)).filter(
        ExternalVisitor.app_id == a.id,
        ExternalVisitor.last_seen_at >= cutoff,
    ).scalar() or 0
    total_conversations = db.query(func.count(Conversation.id)).filter(
        Conversation.external_app_id == a.id,
    ).scalar() or 0
    # token_issues_7d — not tracked in MVP; return 0 (TODO: add audit table)
    return SingleResponse(data=ExternalAppUsage(
        last_used_at=a.last_used_at.isoformat() if a.last_used_at else None,
        active_visitors_7d=active_visitors,
        total_conversations=total_conversations,
        token_issues_7d=0,
        last_7d_daily=[0] * 7,
    ))
