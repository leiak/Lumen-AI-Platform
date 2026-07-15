"""Look up installed marketplace skills for LLM call injection.

Single read path for /chat/stream and the workflow LLM node. Enforces
per-tenant ownership and active status; silently drops unknown /
unauthorized / inactive ids so callers can no-op cleanly without
needing per-call error handling.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable, List, Optional, Tuple

from langchain_core.tools import BaseTool
from sqlalchemy.orm import Session

from lumen_models.skill import Skill
from lumen_models.skill_marketplace import InstalledSkill, SkillMarketplace
from lumen_services.skill_executors import get_executor
from lumen_services.skill_executors.prompt import PromptExecutor

logger = logging.getLogger(__name__)

# Cap a single LLM call's skill budget. Each Skill.content is free-form
# text (often hundreds of chars). 5 keeps the system prompt bounded and
# matches the multi-select UI maxCount.
MAX_SKILLS_PER_REQUEST = 5


@dataclass(frozen=True)
class RenderedSkill:
    """A small view passed to callers — name is the marketplace display
    name (NOT the per-tenant-suffixed Skill.name) and content is the
    Skill.content the user authored or installed from marketplace."""

    name: str
    content: str


class SkillRunner:
    """Dispatcher: read installed marketplace skills, split into
    (system-prompt-injectable, LangChain tool-callable) buckets.

    Backward-compat: unknown skill types (legacy data) fall back to
    PromptExecutor so a row that pre-dates M16 still injects as a prompt.
    """

    @staticmethod
    def get_active_skills(
        db: Session, tenant_id: int, skill_ids: Iterable[int]
    ) -> Tuple[List[RenderedSkill], List[BaseTool]]:
        """Return (prompts, tools) for installed, active, in-tenant skills.

        Behavior contract:
          * None / empty input -> ([], []).
          * Dedupe input ids (first-seen order preserved) before cap.
          * Cap at MAX_SKILLS_PER_REQUEST (5).
          * Filter: InstalledSkill.tenant_id == tenant_id AND
                    InstalledSkill.status == 'active' AND
                    (InstalledSkill.skill_id IS NULL
                     OR Skill.is_active == True).
          * Result ordered by Skill.id ASC for stable tests.
          * Dropped ids (unknown / unauthorized / inactive) emit a single
            logger.warning with the dropped id list and the tenant.
          * Per-skill dispatch:
              - prompt executor -> goes into prompts bucket (or skipped
                if content is empty).
              - script / http / future types -> goes into tools bucket.
              - unknown type -> falls back to PromptExecutor (M16 §3.9).
          * RenderedSkill.content precedence:
              - Skill.content if the install has a linked Skill row,
              - else SkillMarketplace.content (M16 marketplace-only path).
          * Never raises. Returns ([], []) on no matches.
        """
        if not skill_ids:
            return [], []

        # Dedupe (first-seen order) and cap before the DB hit.
        ids = list(dict.fromkeys(int(i) for i in skill_ids))[:MAX_SKILLS_PER_REQUEST]
        if not ids:
            return [], []

        # M16: a marketplace skill can be installed without a per-tenant
        # Skill copy (InstalledSkill.skill_id IS NULL). In that case the
        # "active" signal is InstalledSkill.status='active' alone, and
        # SkillMarketplace.content is used for prompt injection. If a
        # Skill row IS linked, we honor Skill.is_active as the per-tenant
        # override (pre-M16 behavior) and use Skill.content for the prompt.
        rows_with_skill = (
            db.query(
                SkillMarketplace,
                Skill.id.label("skill_pk"),
                Skill.content.label("skill_content"),
            )
            .join(InstalledSkill, InstalledSkill.marketplace_skill_id == SkillMarketplace.id)
            .join(Skill, Skill.id == InstalledSkill.skill_id)
            .filter(
                InstalledSkill.tenant_id == tenant_id,
                InstalledSkill.skill_id.in_(ids),
                InstalledSkill.status == "active",
                Skill.is_active == True,  # noqa: E712
            )
            .order_by(Skill.id.asc())
            .all()
        )

        rows_market_only = (
            db.query(SkillMarketplace)
            .join(InstalledSkill, InstalledSkill.marketplace_skill_id == SkillMarketplace.id)
            .filter(
                InstalledSkill.tenant_id == tenant_id,
                InstalledSkill.skill_id.is_(None),
                InstalledSkill.marketplace_skill_id.in_(ids),
                InstalledSkill.status == "active",
            )
            .order_by(SkillMarketplace.id.asc())
            .all()
        )

        prompts: List[RenderedSkill] = []
        tools: List[BaseTool] = []

        for market, _skill_pk, skill_content in rows_with_skill:
            _dispatch_one(market, tenant_id, prompts, tools, content_override=skill_content)
        for market in rows_market_only:
            _dispatch_one(market, tenant_id, prompts, tools, content_override=None)

        # Dropped-ids accounting. The two resolution paths use different
        # id spaces (skill pk vs marketplace id) — accept both shapes.
        resolved_skill_ids = {pk for _market, pk, _c in rows_with_skill}
        resolved_market_ids = {m.id for m in rows_market_only}
        resolved = resolved_skill_ids | resolved_market_ids
        dropped = sorted(set(ids) - resolved)  # type: ignore[operator]
        if dropped:
            logger.warning(
                "get_active_skills: dropped ids %s (tenant=%s, unknown/inactive/unauthorized)",
                dropped, tenant_id,
            )

        return prompts, tools


# Backward-compat shim for callers that pre-date M16 (T7) and still
# import the module-level `get_active_skills` function. T8/T9 will
# migrate chat_features.py and workflow LLM node to consume the full
# (prompts, tools) tuple from SkillRunner.get_active_skills; until then
# the legacy function returns only the prompts list so existing
# `from lumen_services.skill_runner import get_active_skills` imports
# keep resolving. Tool injection will not be wired in for these legacy
# callers — that's the responsibility of T8/T9.
def get_active_skills(
    db: Session, tenant_id: int, skill_ids: Iterable[int]
) -> List[RenderedSkill]:
    """Deprecated module-level entry point — use SkillRunner.get_active_skills."""
    prompts, _tools = SkillRunner.get_active_skills(db, tenant_id, skill_ids)
    return prompts


def _dispatch_one(
    market: SkillMarketplace,
    tenant_id: int,
    prompts: List[RenderedSkill],
    tools: List[BaseTool],
    content_override: Optional[str],
) -> None:
    """Dispatch a single marketplace row to (prompts, tools) buckets.

    `content_override` is set to the linked Skill.content for the
    Skill-bound path (pre-M16 contract) and left as None for the
    marketplace-only M16 path (PromptExecutor will read market.content
    from the marketplace row directly).
    """
    try:
        executor = get_executor(market.type)  # type: ignore[arg-type]
    except ValueError:
        logger.warning(
            "get_active_skills: unknown skill type %r (marketplace_id=%s) — "
            "falling back to PromptExecutor",
            market.type, market.id,
        )
        executor = PromptExecutor()

    # PromptExecutor reads `skill.content` off the ORM object. Temporarily
    # bind the override for this dispatch without mutating the persistent
    # attribute on the live row (avoids leaking across iterations when
    # the session is reused).
    if content_override is not None:
        # Use object.__setattr__-style attribute access via a simple
        # local rebind: PromptExecutor will see whatever .content returns
        # at call time. We pass an in-memory shim that mirrors the ORM
        # row's other fields but exposes our override.
        type_cfg_override = None
        if market.type == "script":
            # For script-type skills, Skill.content holds the Python script code.
            # ScriptExecutor reads from type_config["code"], so provide it via shim.
            type_cfg_override = {"code": content_override}
        shim = _MarketplaceShim(market, content_override=content_override, type_config_override=type_cfg_override)
        market_for_dispatch = shim
    else:
        market_for_dispatch = market

    sp = executor.to_system_prompt(market_for_dispatch)  # type: ignore[arg-type]
    if sp:
        prompts.append(RenderedSkill(name=market.name, content=sp))  # type: ignore[arg-type]

    try:
        tool = executor.to_langchain_tool(market_for_dispatch, tenant_id)  # type: ignore[arg-type]
        if tool is not None:
            tools.append(tool)
    except Exception as e:
        logger.warning(
            "get_active_skills: failed to build tool for marketplace skill %s "
            "(type=%s): %s",
            market.id, market.type, e,
        )


@dataclass
class _MarketplaceShim:
    """Lightweight shim that mirrors the relevant fields of a
    SkillMarketplace row but exposes an override for `content` and/or
    `type_config`. Used by the PromptExecutor path when a Skill row
    is linked to the install; the rest of the executor's surface
    (to_langchain_tool) reads type/type_config/name/description off
    the underlying row unless overrides are provided."""

    market: SkillMarketplace
    content_override: Optional[str] = None
    type_config_override: Optional[dict] = None

    @property
    def id(self):
        return self.market.id

    @property
    def name(self):
        return self.market.name

    @property
    def type(self):
        return self.market.type

    @property
    def type_config(self) -> Optional[dict]:
        return self.type_config_override if self.type_config_override is not None else self.market.type_config

    @property
    def description(self):
        return self.market.description

    @property
    def content(self) -> str:
        return self.content_override if self.content_override is not None else self.market.content
