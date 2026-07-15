"""LangGraph 1.0 StateGraph for AgentTeam multi-agent orchestration.

Replaces TeamService.run()'s 225-line hand-rolled if/else pipeline with
the official LangGraph 1.0 multi-agent pattern:

  START → load_context → decide_routing → [Send fan-out run_worker] →
           conditional (1 worker → skip, >1 → aggregate) → persist → END

State is a TypedDict (JSON-serializable; ORM objects are model_dump()'d
before entry). DB session is injected via config["configurable"]["db"]
to keep the state pure (LangGraph state must be JSON-serializable for
future checkpointer compatibility, even though we don't use one here).
See docs/superpowers/specs/2026-06-14-agent-team-state-graph-refactor-design.md
for full design rationale.
"""
from __future__ import annotations

import json
import logging
import operator
import uuid
from datetime import datetime
from typing import Annotated, Any, Dict, List, Optional

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send
from typing_extensions import TypedDict

from lumen_core.llm_call_context import LLMCallContext, set_call_context, reset_call_context
from lumen_models.agent import Agent
from lumen_models.chat import Conversation, Message
from lumen_services.agent_service import AgentService
from lumen_services.agents.manager import ManagerDecider, select_workers_by_policy
from lumen_services.agents.team import DEFAULT_AGGREGATOR_PROMPT

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# State schema
# ---------------------------------------------------------------------------

class TeamRunState(TypedDict, total=False):
    # --- input (TeamService.run injects) ---
    team_id: int
    tenant_id: int
    user_id: int
    user_message: str
    request_conversation_id: Optional[int]
    request_member_ids: Optional[List[int]]
    request_route_policy: Optional[str]

    # --- loaded (load_context) ---
    team: Dict[str, Any]
    manager: Dict[str, Any]
    # member_id -> {"member_id": int, "agent_dict": {...}, "role": str|None}
    workers_by_id: Dict[int, Dict[str, Any]]
    history: List[Dict[str, str]]
    manager_kb_history_entry: List[Dict[str, str]]
    conversation: Dict[str, Any]
    user_message_db_id: int

    # --- decided (decide_routing) ---
    policy: str
    chosen_member_ids: List[int]
    manager_reasoning: Optional[str]
    aggregator_prompt_override: Optional[str]

    # --- executed (run_worker fan-out, reducer-merged) ---
    worker_outputs: Annotated[List[Dict[str, Any]], operator.add]

    # --- aggregated (aggregate) ---
    final_answer: Optional[str]

    # --- output (TeamService.run reads) ---
    routing_decision: List[int]
    conversation_id: int


# ---------------------------------------------------------------------------
# Serialization helpers (ORM → JSON-safe dict)
# ---------------------------------------------------------------------------

def _agent_to_dict(agent: Agent) -> Dict[str, Any]:
    """ORM Agent → JSON-serializable dict.

    We deliberately do NOT round-trip every column — only the ones the
    nodes actually need. Anything missing can be re-fetched via the
    injected DB session when a node needs the live ORM (e.g. when
    ``AgentService.chat`` rebuilds the agent from DB).
    """
    return {
        "id": agent.id,
        "tenant_id": agent.tenant_id,
        "name": agent.name,
        "description": agent.description,
        "prompt_template": agent.prompt_template,
        "model_name": agent.model_name,
        "temperature": agent.temperature,
        "is_active": bool(agent.is_active),
        "memory_policy": agent.memory_policy,
        "tool_choice": agent.tool_choice,
        "allowed_tools": list(agent.allowed_tools or []),
    }


def _team_to_dict(team) -> Dict[str, Any]:
    return {
        "id": team.id,
        "tenant_id": team.tenant_id,
        "name": team.name,
        "description": team.description,
        "is_active": bool(team.is_active),
        "route_policy": team.route_policy,
        "aggregator_prompt": team.aggregator_prompt,
    }


def _conv_to_dict(conv: Conversation) -> Dict[str, Any]:
    return {
        "id": conv.id,
        "title": conv.title,
        "user_id": conv.user_id,
        "tenant_id": conv.tenant_id,
        "team_id": conv.team_id,
    }


# ---------------------------------------------------------------------------
# Node functions
# ---------------------------------------------------------------------------

def _get_db(config: RunnableConfig):
    """Read the DB session injected via config['configurable']['db']."""
    return config["configurable"]["db"]


def load_context(state: TeamRunState, config: RunnableConfig) -> dict:
    """Step 1-7: load team / manager / workers / conv / user_msg / history / KB context.

    Side effect: persists the user message to DB (mirrors the original
    ``TeamService.run`` L282-313). Throws ValueError on bad team / conv
    / no active workers so the endpoint layer can map to 400.
    """
    db = _get_db(config)
    from lumen_models.agent_team import AgentTeam  # local import to avoid cycle at module load
    from lumen_services.agent_rag import build_agent_kb_context

    team = db.query(AgentTeam).filter(
        AgentTeam.id == state["team_id"],
        AgentTeam.tenant_id == state["tenant_id"],
    ).first()
    if not team or not team.is_active:
        raise ValueError("Team not found or inactive")

    # --- resolve / create team conversation ---
    conv_id = state.get("request_conversation_id")
    if conv_id is None:
        conv = Conversation(
            title=state["user_message"][:50] or "新对话",
            user_id=state["user_id"],
            tenant_id=state["tenant_id"],
            team_id=state["team_id"],
        )
        db.add(conv)
        db.commit()
        db.refresh(conv)
    else:
        conv = db.query(Conversation).filter(
            Conversation.id == conv_id,
            Conversation.tenant_id == state["tenant_id"],
            Conversation.user_id == state["user_id"],
            Conversation.team_id == state["team_id"],
            Conversation.deleted_at.is_(None),
        ).first()
        if conv is None:
            raise ValueError("Conversation not found or not bound to this team")

    # --- persist user message ---
    user_msg = Message(
        conversation_id=conv.id, role="user", content=state["user_message"],
    )
    db.add(user_msg)
    db.commit()
    db.refresh(user_msg)

    # --- load history (exclude the just-persisted user msg) ---
    all_msgs = (
        db.query(Message)
        .filter(Message.conversation_id == conv.id)
        .order_by(Message.created_at.asc())
        .all()
    )
    history_payload: List[Dict[str, str]] = [
        {"role": m.role, "content": m.content}
        for m in all_msgs
        if m.id != user_msg.id
    ]

    # --- load manager ---
    manager = db.query(Agent).filter(
        Agent.id == team.manager_agent_id,
        Agent.tenant_id == state["tenant_id"],
    ).first()
    if not manager:
        raise ValueError("Manager agent not found")

    # --- M21: manager KB context (manager's KBs = team's shared facts) ---
    manager_kb_context = build_agent_kb_context(
        manager.id, state["user_message"], db,
    )
    manager_kb_history_entry: List[Dict[str, str]] = (
        [{"role": "system", "content": manager_kb_context}]
        if manager_kb_context else []
    )

    # --- load workers (active members only) ---
    members = [m for m in (team.members or []) if m.is_active]
    if state.get("request_member_ids"):
        wanted = set(state["request_member_ids"])
        members = [m for m in members if m.id in wanted]
    if not members:
        raise ValueError("Team has no active worker members")

    workers_by_id: Dict[int, Dict[str, Any]] = {}
    for m in members:
        agent = db.query(Agent).filter(
            Agent.id == m.agent_id,
            Agent.tenant_id == state["tenant_id"],
        ).first()
        if agent and agent.is_active:
            workers_by_id[m.id] = {
                "member_id": m.id,
                "agent_dict": _agent_to_dict(agent),
                "role": m.role,
            }
    if not workers_by_id:
        raise ValueError("None of the configured worker agents are available")

    return {
        "team": _team_to_dict(team),
        "manager": _agent_to_dict(manager),
        "workers_by_id": workers_by_id,
        "history": history_payload,
        "manager_kb_history_entry": manager_kb_history_entry,
        "conversation": _conv_to_dict(conv),
        "user_message_db_id": user_msg.id,
    }


def decide_routing(state: TeamRunState, config: RunnableConfig) -> dict:
    """Step 8-9: ManagerDecider OR policy, defensive fallback to all members."""
    db = _get_db(config)
    policy = (
        state.get("request_route_policy")
        or state["team"].get("route_policy")
        or "manager_decides"
    )

    workers_seq: List[Agent] = [
        Agent(**w["agent_dict"]) for w in state["workers_by_id"].values()
    ]

    # M26: route the manager call (whether ManagerDecider.ask or the
    # deterministic policy path) through an LLMCallContext so the
    # LoggingChatModel wrapper in model_loader writes an LLMCallLog row.
    # The root trace_id is read from config["configurable"]["trace_id"],
    # set by the graph entry-point (TeamService.run or api/v1/agent_team.py).
    trace_id = config["configurable"].get("trace_id") or str(uuid.uuid4())
    parent_call_id = config["configurable"].get("root_call_id") or trace_id
    manager_agent_id = state["manager"].get("id") if state.get("manager") else None
    ctx_token = set_call_context(LLMCallContext(
        call_id=str(uuid.uuid4()),
        trace_id=trace_id,
        parent_call_id=parent_call_id,
        call_type="team.manager_decision",
        call_index=0,
        tenant_id=state["tenant_id"],
        user_id=state.get("user_id"),
        team_id=state["team_id"],
        agent_id=manager_agent_id,
        conversation_id=state.get("request_conversation_id"),
    ))
    try:
        if policy == "manager_decides":
            manager = Agent(**state["manager"])
            manager_history = (
                state["manager_kb_history_entry"] + (state["history"] or [])
            )
            decision = ManagerDecider(manager).ask(
                db=db,
                tenant_id=state["tenant_id"],
                user_message=state["user_message"],
                workers=workers_seq,
                history=manager_history or None,
            )
            chosen_set = set(decision.chosen_agent_ids)
            chosen_member_ids = [
                mid for mid, w in state["workers_by_id"].items()
                if w["agent_dict"]["id"] in chosen_set
            ]
            manager_reasoning = decision.reasoning
            aggregator_prompt_override = decision.aggregator_prompt
        else:
            # Deterministic policy (first_match / round_robin / unknown).
            chosen_agent_ids = select_workers_by_policy(
                policy, workers_seq,
                user_message=state["user_message"],
                routes=[],
            )
            chosen_member_ids = [
                mid for mid, w in state["workers_by_id"].items()
                if w["agent_dict"]["id"] in set(chosen_agent_ids)
            ]
            manager_reasoning = f"policy={policy}"
            aggregator_prompt_override = None
    finally:
        reset_call_context(ctx_token)

    # Defensive: never produce an empty routing decision
    if not chosen_member_ids:
        chosen_member_ids = list(state["workers_by_id"].keys())

    return {
        "policy": policy,
        "chosen_member_ids": chosen_member_ids,
        "manager_reasoning": manager_reasoning,
        "aggregator_prompt_override": aggregator_prompt_override,
    }


def run_worker(state: TeamRunState, config: RunnableConfig) -> dict:
    """Step 10: Run ONE worker. Called once per chosen_member_id via Send API.

    `state["chosen_member_id"]` is injected by `route_to_workers` conditional
    edge (one Send per chosen worker). Returns a list with ONE WorkerOutput
    dict; the reducer (operator.add) will concat all parallel results.

    Errors are caught and returned as a sentinel response so the graph
    does not abort on a single worker failure (mirrors current behavior).
    """
    db = _get_db(config)
    member_id = state["chosen_member_id"]
    worker = state["workers_by_id"][member_id]
    agent = Agent(**worker["agent_dict"])

    # M26: per-worker LLMCallContext. All workers share the same trace_id
    # (under the root call) but each gets its own call_id so the UI can
    # distinguish them. call_index encodes the worker's position in the
    # fan-out order (member_id order in state["chosen_member_ids"]).
    trace_id = config["configurable"].get("trace_id") or str(uuid.uuid4())
    parent_call_id = config["configurable"].get("root_call_id") or trace_id
    chosen_ids = state.get("chosen_member_ids") or []
    call_index = (
        chosen_ids.index(member_id) + 1 if member_id in chosen_ids else 0
    )

    ctx_token = set_call_context(LLMCallContext(
        call_id=str(uuid.uuid4()),
        trace_id=trace_id,
        parent_call_id=parent_call_id,
        call_type="team.worker",
        call_index=call_index,
        tenant_id=state["tenant_id"],
        user_id=state.get("user_id"),
        team_id=state["team_id"],
        team_member_id=member_id,
        agent_id=agent.id,
        conversation_id=state.get("request_conversation_id"),
    ))
    try:
        try:
            response_text = AgentService().chat(
                db=db,
                agent_id=agent.id,
                tenant_id=state["tenant_id"],
                message=state["user_message"],
                history=state["history"],
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Worker %s failed: %s", agent.id, exc)
            response_text = f"[worker error: {type(exc).__name__}: {exc}]"
    finally:
        reset_call_context(ctx_token)

    return {
        "worker_outputs": [{
            "member_id": member_id,
            "agent_id": agent.id,
            "agent_name": agent.name,
            "role": worker.get("role"),
            "response": response_text,
        }],
    }


def aggregate(state: TeamRunState, config: RunnableConfig) -> dict:
    """Step 11: 1 worker → as-is; >1 worker → manager LLM synthesize."""
    if len(state["worker_outputs"]) == 1:
        return {"final_answer": state["worker_outputs"][0]["response"]}

    db = _get_db(config)
    manager = Agent(**state["manager"])
    workers_block = "\n".join(
        f"- {wo['agent_name'] or wo['agent_id']} (role={wo['role'] or 'worker'})"
        for wo in state["worker_outputs"]
    )
    answers_block = "\n\n".join(
        f"### {wo['agent_name'] or wo['agent_id']}\n{wo['response']}"
        for wo in state["worker_outputs"]
    )

    prompt_template = (
        state.get("aggregator_prompt_override")
        or state["team"].get("aggregator_prompt")
        or DEFAULT_AGGREGATOR_PROMPT
    )
    synth_message = prompt_template.format(
        workers=workers_block,
        user_message=state["user_message"],
        answers=answers_block,
    )

    agg_history: Optional[List[Dict[str, str]]] = (
        list(state["manager_kb_history_entry"])
        if state["manager_kb_history_entry"]
        else None
    )

    # M26: aggregator call gets its own row under the same trace.
    trace_id = config["configurable"].get("trace_id") or str(uuid.uuid4())
    parent_call_id = config["configurable"].get("root_call_id") or trace_id
    n_workers = len(state.get("chosen_member_ids") or [])
    ctx_token = set_call_context(LLMCallContext(
        call_id=str(uuid.uuid4()),
        trace_id=trace_id,
        parent_call_id=parent_call_id,
        call_type="team.aggregate",
        call_index=n_workers + 1,  # index after all workers
        tenant_id=state["tenant_id"],
        user_id=state.get("user_id"),
        team_id=state["team_id"],
        agent_id=manager.id,
        conversation_id=state.get("request_conversation_id"),
    ))
    try:
        try:
            final_answer = AgentService().chat(
                db=db,
                agent_id=manager.id,
                tenant_id=state["tenant_id"],
                message=synth_message,
                history=agg_history,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Aggregation failed: %s", exc)
            # Fall back to naive concat so the user still gets an answer.
            final_answer = "\n\n".join(
                f"[{wo['agent_name'] or wo['agent_id']}] {wo['response']}"
                for wo in state["worker_outputs"]
            )
    finally:
        reset_call_context(ctx_token)
    return {"final_answer": final_answer}


def persist(state: TeamRunState, config: RunnableConfig) -> dict:
    """Step 12: Write assistant_message + msg_metadata JSON, bump conv.updated_at.

    msg_metadata JSON schema is intentionally unchanged from the original
    ``TeamService.run`` L465-470 so the frontend can keep reading the
    same shape (routing_decision / worker_outputs / policy_used /
    manager_reasoning).
    """
    db = _get_db(config)
    routing_decision = [wo["agent_id"] for wo in state["worker_outputs"]]
    # `final_answer` is only set by the `aggregate` node. When the graph
    # takes the `should_aggregate == "skip"` path (single worker) we
    # synthesise it from the lone worker output here. This keeps the
    # skip-aggregate optimization without the persist node reading
    # `state["final_answer"]` out of the blue.
    final_answer = state.get("final_answer")
    if final_answer is None:
        final_answer = state["worker_outputs"][0]["response"]
    assistant_meta = {
        "routing_decision": routing_decision,
        "worker_outputs": list(state["worker_outputs"]),
        "policy_used": state["policy"],
        "manager_reasoning": state["manager_reasoning"],
    }
    assistant_msg = Message(
        conversation_id=state["conversation"]["id"],
        role="assistant",
        content=final_answer,
        msg_metadata=json.dumps(assistant_meta, ensure_ascii=False),
    )
    db.add(assistant_msg)
    # Force updated_at bump so list ordering reflects the latest turn
    # even if no other Conversation field changed.
    db.query(Conversation).filter(
        Conversation.id == state["conversation"]["id"]
    ).update({Conversation.updated_at: datetime.utcnow()})
    db.commit()

    return {
        "routing_decision": routing_decision,
        "conversation_id": state["conversation"]["id"],
        "final_answer": final_answer,
    }


# ---------------------------------------------------------------------------
# Conditional edges + graph builder
# ---------------------------------------------------------------------------

def route_to_workers(state: TeamRunState) -> List[Send]:
    """Fan-out: one Send per chosen_member_id, injecting chosen_member_id
    into the per-invocation state.

    LangGraph's scheduler invokes the target node (``run_worker``) once
    per Send in the returned list. The reducer on ``worker_outputs``
    then concatenates the per-invocation results back into the shared
    state.
    """
    return [
        Send("run_worker", {**state, "chosen_member_id": mid})
        for mid in state["chosen_member_ids"]
    ]


def should_aggregate(state: TeamRunState) -> str:
    """1 worker → skip aggregate (the single response IS the final answer);
    >1 worker → run aggregate to synthesize.

    Reads ``chosen_member_ids`` (set by ``decide_routing``) rather than
    ``len(worker_outputs)`` because LangGraph 1.0 evaluates conditional
    edges *between* Send invocations, so the reducer-merged
    ``worker_outputs`` is not yet stable when this is called. The
    routing decision is set in ``decide_routing`` and does not change
    across fan-out, making it a stable signal for "how many workers
    are we processing?".
    """
    if len(state.get("chosen_member_ids", [])) <= 1:
        return "skip"
    return "aggregate"


def build_team_graph():
    """Construct and compile the multi-agent StateGraph.

    Returns a CompiledStateGraph ready for ``.invoke()`` or ``.stream()``.
    """
    g = StateGraph(TeamRunState)
    g.add_node("load_context", load_context)
    g.add_node("decide_routing", decide_routing)
    g.add_node("run_worker", run_worker)
    g.add_node("aggregate", aggregate)
    g.add_node("persist", persist)

    g.add_edge(START, "load_context")
    g.add_edge("load_context", "decide_routing")
    g.add_conditional_edges("decide_routing", route_to_workers, ["run_worker"])
    g.add_conditional_edges(
        "run_worker", should_aggregate,
        {"skip": "persist", "aggregate": "aggregate"},
    )
    g.add_edge("aggregate", "persist")
    g.add_edge("persist", END)

    return g.compile()
