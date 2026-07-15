"""TeamService: orchestrates a multi-agent team run.

Pipeline for one user turn:
    1.  Load team + manager + members + (optional) routes.
    2.  Decide which workers handle the message:
          - "manager_decides" -> ask the manager Agent (via ManagerDecider)
          - "first_match" / "round_robin" -> deterministic rule
    3.  Run each selected worker through the existing single-agent chat
        path (`AgentService.chat`).
    4.  Aggregate: if more than one worker responded, call the manager
        (or a fixed aggregator prompt) once more to synthesize a final
        answer. If only one worker responded, return its output as-is.
    5.  Persist: write the user + assistant messages into a team-scoped
        Conversation (created on first turn, reused on subsequent
        turns) so the frontend can show history on the next open.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Sequence

from sqlalchemy.orm import Session

from lumen_models.agent import Agent
from lumen_models.agent_team import (
    AgentTeam,
    AgentTeamMember,
    AgentTeamRoute,
)
from lumen_models.chat import Conversation, Message
from lumen_models.user import User
from lumen_schemas.agent_team import (
    AgentTeamChatRequest,
    AgentTeamChatResponse,
    AgentTeamCreate,
    AgentTeamMemberCreate,
    AgentTeamResponse,
    AgentTeamRouteCreate,
    AgentTeamSummary,
    AgentTeamUpdate,
    RoutePolicy,
    WorkerOutput,
)
from lumen_services.agent_service import AgentService
from lumen_services.agents.manager import (
    ManagerDecider,
    ManagerDecision,
    select_workers_by_policy,
)

logger = logging.getLogger(__name__)


# Default aggregator prompt when more than one worker responds. Used when
# the team has no `aggregator_prompt` configured and the manager didn't
# return one in its decision.
DEFAULT_AGGREGATOR_PROMPT = (
    "You are the team manager. Below are independent answers from your "
    "worker agents. Read them carefully, reconcile any disagreements, and "
    "produce a single, concise final answer to the user's original "
    "message. If the workers disagree, prefer the most specific / best-"
    "supported answer. Do not mention the workers in your reply.\n\n"
    "Workers:\n{workers}\n\n"
    "Original user message:\n{user_message}\n\n"
    "Worker answers:\n{answers}\n\n"
    "Final answer:"
)


@dataclass
class TeamRunResult:
    final_answer: str
    manager_reasoning: Optional[str]
    routing_decision: List[int]
    worker_outputs: List[WorkerOutput]
    policy_used: str
    # DB id of the team-scoped conversation this turn belongs to.
    # Echoed back to the frontend so it can update the sidebar.
    conversation_id: int


class TeamService:
    """CRUD + orchestration for AgentTeam."""

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------
    def list_teams(
        self,
        db: Session,
        tenant_id: int,
        page: int = 1,
        page_size: int = 10,
    ) -> tuple[List[AgentTeamSummary], int]:
        # P0-4 (2026-06-20): outer-join agents to surface manager_agent_name
        # so the frontend list view doesn't have to render raw FK ids.
        # LEFT OUTER JOIN because manager_agent_id is non-nullable in the
        # schema, but we keep the join nullable-safe in case of a corrupt
        # row (deleted agent).
        from lumen_models.agent import Agent

        rows = (
            db.query(AgentTeam, Agent.name)
            .outerjoin(Agent, Agent.id == AgentTeam.manager_agent_id)
            .filter(AgentTeam.tenant_id == tenant_id)
            .order_by(AgentTeam.created_at.desc())
            .all()
        )
        total = len(rows)
        start = (page - 1) * page_size
        end = start + page_size
        summaries: List[AgentTeamSummary] = []
        for t, mgr_name in rows[start:end]:
            summaries.append(
                AgentTeamSummary(
                    id=t.id,
                    name=t.name,
                    description=t.description,
                    manager_agent_id=t.manager_agent_id,
                    manager_agent_name=mgr_name,
                    is_active=t.is_active,
                    route_policy=t.route_policy or RoutePolicy.MANAGER_DECIDES,
                    aggregator_prompt=t.aggregator_prompt,
                    config=t.config,
                    tenant_id=t.tenant_id,
                    created_at=t.created_at,
                    member_count=len(t.members or []),
                )
            )
        return summaries, total

    def get_team(
        self, db: Session, team_id: int, tenant_id: int
    ) -> Optional[AgentTeam]:
        return (
            db.query(AgentTeam)
            .filter(AgentTeam.id == team_id, AgentTeam.tenant_id == tenant_id)
            .first()
        )

    def create_team(
        self,
        db: Session,
        tenant_id: int,
        data: AgentTeamCreate,
        current_user: User,
    ) -> AgentTeam:
        # Validate manager + member agents exist within the tenant.
        self._validate_agents_in_tenant(
            db,
            tenant_id,
            [data.manager_agent_id] + [m.agent_id for m in (data.members or [])]
            + [r.agent_id for r in (data.routes or [])],
        )

        policy = data.route_policy or RoutePolicy.MANAGER_DECIDES
        if policy not in RoutePolicy.ALL:
            raise ValueError(f"Invalid route_policy: {policy}")

        team = AgentTeam(
            name=data.name,
            description=data.description,
            manager_agent_id=data.manager_agent_id,
            tenant_id=tenant_id,
            is_active=data.is_active,
            route_policy=policy,
            aggregator_prompt=data.aggregator_prompt,
            config=data.config,
        )
        db.add(team)
        db.flush()  # need team.id for FKs

        for m in data.members or []:
            db.add(AgentTeamMember(team_id=team.id, **_as_dict(m)))
        for r in data.routes or []:
            db.add(AgentTeamRoute(team_id=team.id, **_as_dict(r)))

        db.commit()
        db.refresh(team)
        return team

    def update_team(
        self,
        db: Session,
        team_id: int,
        tenant_id: int,
        data: AgentTeamUpdate,
    ) -> Optional[AgentTeam]:
        team = self.get_team(db, team_id, tenant_id)
        if not team:
            return None
        update = data.model_dump(exclude_unset=True)
        if "route_policy" in update and update["route_policy"] not in RoutePolicy.ALL:
            raise ValueError(f"Invalid route_policy: {update['route_policy']}")
        if "manager_agent_id" in update:
            self._validate_agents_in_tenant(db, tenant_id, [update["manager_agent_id"]])
        for field, value in update.items():
            setattr(team, field, value)
        db.commit()
        db.refresh(team)
        return team

    def delete_team(self, db: Session, team_id: int, tenant_id: int) -> bool:
        team = self.get_team(db, team_id, tenant_id)
        if not team:
            return False
        db.delete(team)
        db.commit()
        return True

    # ------------------------------------------------------------------
    # Members
    # ------------------------------------------------------------------
    def add_member(
        self,
        db: Session,
        team_id: int,
        tenant_id: int,
        data: AgentTeamMemberCreate,
    ) -> Optional[AgentTeamMember]:
        team = self.get_team(db, team_id, tenant_id)
        if not team:
            return None
        self._validate_agents_in_tenant(db, tenant_id, [data.agent_id])
        member = AgentTeamMember(team_id=team.id, **_as_dict(data))
        db.add(member)
        db.commit()
        db.refresh(member)
        return member

    def remove_member(
        self, db: Session, team_id: int, member_id: int, tenant_id: int
    ) -> bool:
        team = self.get_team(db, team_id, tenant_id)
        if not team:
            return False
        member = (
            db.query(AgentTeamMember)
            .filter(AgentTeamMember.id == member_id, AgentTeamMember.team_id == team.id)
            .first()
        )
        if not member:
            return False
        db.delete(member)
        db.commit()
        return True

    # ------------------------------------------------------------------
    # Run / orchestration
    # ------------------------------------------------------------------
    def chat(
        self,
        db: Session,
        team_id: int,
        tenant_id: int,
        request: AgentTeamChatRequest,
        user_id: int,
    ) -> AgentTeamChatResponse:
        result = self.run(db, team_id, tenant_id, request, user_id)
        return AgentTeamChatResponse(
            team_id=team_id,
            final_answer=result.final_answer,
            manager_reasoning=result.manager_reasoning,
            routing_decision=result.routing_decision,
            worker_outputs=result.worker_outputs,
            policy_used=result.policy_used,
            conversation_id=result.conversation_id,
        )

    def run(
        self,
        db: Session,
        team_id: int,
        tenant_id: int,
        request: AgentTeamChatRequest,
        user_id: int,
    ) -> TeamRunResult:
        """Run a team chat turn via the LangGraph 1.0 StateGraph.

        M25+ refactor (2026-06-14): the previous 225-line hand-rolled
        pipeline (load → decide → for-loop workers → maybe aggregate →
        persist) is now delegated to ``app.services.agents.state_graph``.
        All behavioural semantics (KB RAG, ManagerDecider routing,
        worker fan-out, aggregation, msg_metadata persistence) live in
        the graph nodes. This method just adapts the request/result
        shapes around ``graph.invoke()``.

        The msg_metadata JSON schema written by ``persist`` is
        **unchanged** from the pre-refactor implementation, so the
        frontend keeps reading the same shape (routing_decision /
        worker_outputs / policy_used / manager_reasoning).
        """
        from lumen_services.agents.state_graph import build_team_graph

        graph = build_team_graph()
        initial_state: dict = {
            "team_id": team_id,
            "tenant_id": tenant_id,
            "user_id": user_id,
            "user_message": request.message,
            "request_conversation_id": request.conversation_id,
            "request_member_ids": list(request.member_ids) if request.member_ids else None,
            "request_route_policy": request.route_policy,
        }
        # M26: propagate trace_id + root_call_id via config so the
        # state_graph nodes can write per-call LLMCallLog rows under the
        # same trace. team_id call_type is "agent_team" (the per-node
        # call_types are "team.manager_decision" / "team.worker" /
        # "team.aggregate", derived from this trace).
        import uuid as _uuid
        trace_id = str(_uuid.uuid4())
        final_state = graph.invoke(
            initial_state,
            config={
                "configurable": {
                    "db": db,
                    "trace_id": trace_id,
                    "root_call_id": trace_id,
                },
            },
        )

        return TeamRunResult(
            final_answer=final_state["final_answer"],
            manager_reasoning=final_state.get("manager_reasoning"),
            routing_decision=list(final_state["routing_decision"]),
            worker_outputs=[WorkerOutput(**wo) for wo in final_state["worker_outputs"]],
            policy_used=final_state["policy"],
            conversation_id=final_state["conversation_id"],
        )

    def _resolve_team_conversation(
        self,
        *,
        db: Session,
        team_id: int,
        tenant_id: int,
        user_id: int,
        conversation_id: Optional[int],
        title_seed: str,
    ) -> Conversation:
        """Find or create the Conversation row for this turn.

        When ``conversation_id`` is None, create a new team-scoped
        conversation. When provided, look it up under
        (id, tenant, user, team) — the 4-tuple enforces ownership and
        the team binding in one query. A miss is raised as ValueError
        so the endpoint layer can map it to a 400.
        """
        if conversation_id is None:
            conv = Conversation(
                title=title_seed or "新对话",
                user_id=user_id,
                tenant_id=tenant_id,
                team_id=team_id,
            )
            db.add(conv)
            db.commit()
            db.refresh(conv)
            return conv

        conv = (
            db.query(Conversation)
            .filter(
                Conversation.id == conversation_id,
                Conversation.tenant_id == tenant_id,
                Conversation.user_id == user_id,
                Conversation.team_id == team_id,
                Conversation.deleted_at.is_(None),
            )
            .first()
        )
        if conv is None:
            raise ValueError(
                "Conversation not found or not bound to this team"
            )
        return conv

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _aggregate(
        self,
        *,
        db: Session,
        tenant_id: int,
        manager: Agent,
        user_message: str,
        worker_outputs: List[WorkerOutput],
        prompt_override: Optional[str],
        manager_kb_history_entry: Optional[List[Dict[str, str]]] = None,
    ) -> str:
        workers_block = "\n".join(
            f"- {wo.agent_name or wo.agent_id} (role={wo.role or 'worker'})"
            for wo in worker_outputs
        )
        answers_block = "\n\n".join(
            f"### {wo.agent_name or wo.agent_id}\n{wo.response}"
            for wo in worker_outputs
        )
        if prompt_override:
            prompt = prompt_override.format(
                workers=workers_block,
                user_message=user_message,
                answers=answers_block,
            )
            synth_message = prompt
        else:
            synth_message = DEFAULT_AGGREGATOR_PROMPT.format(
                workers=workers_block,
                user_message=user_message,
                answers=answers_block,
            )

        # M21: when manager has KB context, prepend it as a system role
        # history entry so AgentService.chat's [Memory] wrapper pulls
        # it into the system prompt slot. Same wire-up as the
        # routing-decision call above.
        agg_history: Optional[List[Dict[str, str]]] = (
            list(manager_kb_history_entry) if manager_kb_history_entry else None
        )

        try:
            return AgentService().chat(
                db=db,
                agent_id=manager.id,
                tenant_id=tenant_id,
                message=synth_message,
                history=agg_history,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Aggregation failed: %s", exc)
            # Fall back to a naive concatenation so the user still gets an answer.
            return "\n\n".join(
                f"[{wo.agent_name or wo.agent_id}] {wo.response}" for wo in worker_outputs
            )

    def _validate_agents_in_tenant(
        self, db: Session, tenant_id: int, agent_ids: List[int]
    ) -> None:
        agent_ids = [int(a) for a in agent_ids if a is not None]
        if not agent_ids:
            return
        rows = (
            db.query(Agent.id)
            .filter(Agent.id.in_(agent_ids), Agent.tenant_id == tenant_id)
            .all()
        )
        found = {row[0] for row in rows}
        missing = [aid for aid in agent_ids if aid not in found]
        if missing:
            raise ValueError(
                f"Agent(s) not found in current tenant: {missing}"
            )


def _as_dict(obj) -> dict:
    """Pydantic v2 .model_dump helper that drops None values to avoid
    clobbering defaults in SQLAlchemy columns."""
    if hasattr(obj, "model_dump"):
        return obj.model_dump(exclude_unset=True)
    return dict(obj)
