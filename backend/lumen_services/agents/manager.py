"""Manager / routing helpers used by TeamService.

The manager is a regular Agent (already stored in the `agents` table) whose
job is to look at a user message + a roster of worker agents and decide
which worker(s) should handle it. We don't require any special training —
we just ask the manager to emit a JSON object describing the routing
decision, and we fall back to "all workers" if the JSON is malformed.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence

from sqlalchemy.orm import Session

from lumen_models.agent import Agent
from lumen_schemas.agent_team import RoutePolicy

logger = logging.getLogger(__name__)


@dataclass
class ManagerDecision:
    """What the manager asked us to do for one user turn."""

    chosen_agent_ids: List[int]
    reasoning: str
    aggregator_prompt: Optional[str] = None


def _build_roster_block(workers: Sequence[Agent]) -> str:
    lines = []
    for w in workers:
        desc = (w.description or "").strip()
        lines.append(f"- id={w.id} name={w.name!r} role={desc or 'worker'}")
    return "\n".join(lines) if lines else "(no workers available)"


def _extract_json_block(text: str) -> Optional[dict]:
    """Best-effort JSON object extraction from a free-form LLM response.

    Tries a few common shapes:
      1. A fenced ```json ... ``` block
      2. A raw {...} block (greedy match on the outermost braces)
    """
    if not text:
        return None

    # 1. fenced code block
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL | re.IGNORECASE)
    if fence:
        try:
            return json.loads(fence.group(1))
        except json.JSONDecodeError:
            pass

    # 2. outermost {...} block
    brace = re.search(r"\{.*\}", text, re.DOTALL)
    if brace:
        candidate = brace.group(0)
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass
    return None


class ManagerDecider:
    """Wraps the manager Agent and asks it to pick worker(s)."""

    def __init__(self, manager: Agent):
        self.manager = manager

    def ask(
        self,
        db: Session,
        tenant_id: int,
        user_message: str,
        workers: Sequence[Agent],
        history: Optional[Iterable[dict]] = None,
    ) -> ManagerDecision:
        from lumen_services.agent_service import AgentService

        roster = _build_roster_block(workers)
        decision_prompt = (
            "You are a team manager. Given the user message and a roster of "
            "worker agents, decide which worker(s) should handle it.\n\n"
            f"Workers:\n{roster}\n\n"
            f"User message:\n{user_message}\n\n"
            "Reply with STRICT JSON of the form:\n"
            '{"chosen_ids": [int, ...], "reasoning": "short string", '
            '"aggregator_prompt": "optional prompt to guide final synthesis"}\n'
            "Rules:\n"
            "- chosen_ids must reference ids from the roster; if unsure, return all of them.\n"
            "- reasoning is a one-sentence explanation shown to the user.\n"
            "- aggregator_prompt (optional) overrides the default final-synthesis prompt."
        )

        # Reuse the existing single-agent chat path. We pass a synthetic
        # history that includes the decision request as the user message so
        # the manager's system prompt + model config are honored.
        history_list = list(history) if history else []
        try:
            response_text = AgentService().chat(
                db=db,
                agent_id=self.manager.id,
                tenant_id=tenant_id,
                message=decision_prompt,
                history=history_list,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Manager decision call failed: %s", exc)
            return ManagerDecision(
                chosen_agent_ids=[w.id for w in workers],
                reasoning=f"manager error: {exc}; defaulting to all workers",
            )

        data = _extract_json_block(response_text) or {}
        chosen = data.get("chosen_ids") or [w.id for w in workers]
        # Sanitize: keep only ids that actually belong to the roster
        valid_ids = {w.id for w in workers}
        chosen = [int(x) for x in chosen if int(x) in valid_ids]
        if not chosen:
            chosen = [w.id for w in workers]

        return ManagerDecision(
            chosen_agent_ids=chosen,
            reasoning=str(data.get("reasoning") or "manager-decides"),
            aggregator_prompt=data.get("aggregator_prompt") or None,
        )


def select_workers_by_policy(
    policy: str,
    workers: Sequence[Agent],
    *,
    user_message: str,
    routes: Optional[Sequence] = None,
    member_id_to_agent_id: Optional[dict] = None,
) -> List[int]:
    """Apply a non-LM routing policy and return chosen agent ids.

    Used when `manager_decides` is not selected. Always returns at least one
    id (falling back to all workers) so the team never silently no-ops.
    """
    if not workers:
        return []

    if policy == RoutePolicy.ROUND_ROBIN:
        # No real per-turn state in the sync endpoint; default to priority order.
        sorted_workers = sorted(workers, key=lambda w: w.id)
        return [sorted_workers[0].id]

    if policy == RoutePolicy.FIRST_MATCH:
        text = (user_message or "").lower()
        if routes:
            for route in sorted(routes, key=lambda r: (r.priority, r.id)):
                kws = [str(k).lower() for k in (route.keywords or [])]
                if any(k in text for k in kws):
                    return [route.agent_id]
        return [workers[0].id]

    # Unknown policy -> all workers
    return [w.id for w in workers]
