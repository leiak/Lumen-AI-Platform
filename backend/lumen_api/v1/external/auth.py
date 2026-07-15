"""POST /api/v1/external/auth/token — trade (app_key, Origin) for a JWT.

Spec: ``docs/superpowers/specs/2026-06-08-external-chat-widget-design.md`` § 5.

Flow:
  1. Validate body (Pydantic) — app_key 8-64 chars, visitor_id 8-64 chars
  2. Look up ExternalApp by app_key (only active rows) — 401 if not found
     (single generic message; don't reveal whether the key existed but
     was disabled vs. never existed)
  3. Read Origin header (fallback to Referer) and check it against
     ``app.allowed_origins`` — 403 if not whitelisted
  4. Check in-process rate limit — 429 if over the per-app threshold
     (the check happens BEFORE the visitor upsert so a rate-limited
     request does NOT pollute the visitor table)
  5. Get-or-create the ExternalVisitor row and bump last_seen_at
  6. Update ``app.last_used_at`` and commit
  7. Sign a short-lived JWT with the visitor's DB id + allowed
     agent/team IDs
  8. Resolve allowed_agents / allowed_teams to display summaries
  9. Return ``SingleResponse[TokenResponse]``

Deviation from the plan (2026-06-08): the service helpers
(``match_origin`` / ``check_rate_limit`` / ``create_external_token`` /
``upsert_visitor``) are imported as a **module**, not as named symbols,
so the test's ``monkey-patch`` of
``app.services.external_auth_service.check_rate_limit`` is visible to
this endpoint. The plan's literal ``from lumen_services.external_auth_service
import check_rate_limit, ...`` binds the function name at import time and
would make the monkey-patch a silent no-op.

TODO(security): the Origin-header fallback to Referer is a known soft spot
in spec § 5.3. The Referer can be spoofed/spoofed-by-redirect and only
enforces origin-style allowlisting by accident. Out-of-scope for the
current fix batch — follow up with a spec change that drops the fallback
or replaces it with a proper CORS preflight.
"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from lumen_core.database import get_db
from lumen_models.agent import Agent
from lumen_models.agent_team import AgentTeam
from lumen_models.external_app import ExternalApp
from lumen_schemas.common import SingleResponse
from lumen_schemas.external import ExternalAgentKBRef, ExternalAgentSummary, TokenRequest, TokenResponse
# IMPORTANT: import as a module (not as named symbols) so the rate-limit
# monkey-patch in the test sees the patched function. See module docstring.
from lumen_services import external_auth_service as auth_svc

router = APIRouter()


@router.post("/auth/token", response_model=SingleResponse[TokenResponse])
def issue_token(
    req: TokenRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    origin = request.headers.get("origin") or request.headers.get("referer", "")

    app = db.scalar(
        select(ExternalApp).where(
            ExternalApp.app_key == req.app_key,
            ExternalApp.is_active == True,  # noqa: E712
        )
    )
    if not app:
        # Generic message — don't reveal whether the key existed but
        # was disabled vs. never existed. The detail is logged.
        raise HTTPException(status_code=401, detail="invalid app_key")

    if not auth_svc.match_origin(origin, app.allowed_origins):
        raise HTTPException(status_code=403, detail="origin not allowed")

    # Rate-limit check runs BEFORE the visitor upsert so a 429 response
    # doesn't pollute the external_visitors table. Verified by
    # test_token_issue_rate_limited_after_threshold.
    if not auth_svc.check_rate_limit(
        app_id=app.id,
        endpoint_class="token",
        limit_per_min=app.rate_limit_per_min,
    ):
        # Spec § 5.6 requires a Retry-After header on 429. The sliding
        # window is 60s, so the client should wait at least that long
        # before retrying. FastAPI passes the ``headers`` kwarg of
        # HTTPException through to the response.
        raise HTTPException(
            status_code=429,
            detail="rate limited",
            headers={"Retry-After": "60"},
        )

    visitor = auth_svc.upsert_visitor(db, app.id, req.visitor_id)
    app.last_used_at = datetime.utcnow()
    db.commit()
    db.refresh(visitor)

    payload = {
        "app_id": app.id,
        "tenant_id": app.tenant_id,
        "visitor_id": visitor.id,
        "visitor_uuid": req.visitor_id,
        "allowed_agent_ids": app.allowed_agent_ids or [],
        "allowed_team_ids": app.allowed_team_ids or [],
        "scopes": [s for s in (app.scopes or "").split(",") if s],
    }
    token = auth_svc.create_external_token(payload)

    allowed_agents = _resolve_agent_summaries(db, app.allowed_agent_ids or [])
    allowed_teams = _resolve_team_summaries(db, app.allowed_team_ids or [])

    return SingleResponse(
        data=TokenResponse(
            token=token,
            expires_in=1800,  # matches settings.EXTERNAL_TOKEN_TTL_SECONDS
            allowed_agents=allowed_agents,
            allowed_teams=allowed_teams,
            visitor_id=visitor.id,
        )
    )


def _resolve_agent_summaries(db: Session, ids: list[int]) -> list[ExternalAgentSummary]:
    if not ids:
        return []
    rows = (
        db.query(Agent)
        .filter(Agent.id.in_(ids), Agent.is_active == True)  # noqa: E712
        .all()
    )
    return [
        ExternalAgentSummary(
            id=a.id,
            name=a.name,
            description=a.description,
            type="agent",
            knowledge_bases=[_kb_ref(binding) for binding in a.knowledge_bases],
        )
        for a in rows
    ]


def _resolve_team_summaries(db: Session, ids: list[int]) -> list[ExternalAgentSummary]:
    if not ids:
        return []
    rows = (
        db.query(AgentTeam)
        .filter(AgentTeam.id.in_(ids), AgentTeam.is_active == True)  # noqa: E712
        .all()
    )
    return [
        ExternalAgentSummary(
            id=t.id, name=t.name, description=t.description, type="team"
        )
        for t in rows
    ]


def _kb_ref(binding) -> ExternalAgentKBRef:
    """Build a widget-friendly KB ref from an AgentKnowledgeBase binding.

    Mirrors the internal ``_to_agent_response`` shape: a deleted KB still
    shows up in the list with a synthetic name + status="deleted" so the
    widget can warn the admin that the binding is dangling.
    """
    kb = binding.knowledge_base
    if kb is None:
        return ExternalAgentKBRef(
            id=binding.knowledge_base_id,
            name=f"(已删除 KB #{binding.knowledge_base_id})",
            status="deleted",
        )
    return ExternalAgentKBRef(
        id=kb.id,
        name=kb.name,
        status=kb.status or "active",
    )
