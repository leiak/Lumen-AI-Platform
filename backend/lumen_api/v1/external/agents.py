"""GET /api/v1/external/agents — return the whitelisted agents + teams
for the current app.

The response is denormalized into a single list with a ``type`` field
(``"agent"`` / ``"team"``) so the widget's agent switcher can render
one dropdown.

Note: the whitelist is read from the DB row (ExternalApp.allowed_agent_ids
/ allowed_team_ids), NOT from the JWT payload. The JWT only carries a
copy at token-issue time; the live DB row is the source of truth so
that admin edits to the whitelist take effect immediately on the next
request (no need to wait for token expiry).
"""
from typing import List
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from lumen_api.v1.deps import ExternalAppContext, get_current_external_app
from lumen_core.database import get_db
from lumen_models.agent import Agent
from lumen_models.agent_team import AgentTeam
from lumen_schemas.common import SingleResponse
from lumen_schemas.external import ExternalAgentKBRef, ExternalAgentSummary

router = APIRouter()


@router.get("/agents", response_model=SingleResponse[List[ExternalAgentSummary]])
async def list_agents(
    ctx: ExternalAppContext = Depends(get_current_external_app),
    db: Session = Depends(get_db),
):
    out: list[ExternalAgentSummary] = []
    if ctx.allowed_agent_ids:
        rows = db.query(Agent).filter(
            Agent.id.in_(ctx.allowed_agent_ids),
            Agent.is_active == True,  # noqa: E712
        ).all()
        for a in rows:
            out.append(ExternalAgentSummary(
                id=a.id,
                name=a.name,
                description=a.description,
                type="agent",
                knowledge_bases=[_kb_ref(b) for b in a.knowledge_bases],
            ))
    if ctx.allowed_team_ids:
        rows = db.query(AgentTeam).filter(
            AgentTeam.id.in_(ctx.allowed_team_ids),
            AgentTeam.is_active == True,  # noqa: E712
        ).all()
        for t in rows:
            out.append(ExternalAgentSummary(
                id=t.id, name=t.name, description=t.description, type="team"
            ))
    return SingleResponse(data=out)


def _kb_ref(binding) -> ExternalAgentKBRef:
    """Build a widget-friendly KB ref. See external/auth.py for rationale."""
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
