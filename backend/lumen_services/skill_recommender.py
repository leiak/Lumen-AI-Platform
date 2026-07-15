"""Skill recommendation: keyword matching + LLM semantic matching.

Two-stage approach:
1. Keyword match (fast, no LLM call) — match user message tokens against
   skill name/description keywords.
2. LLM refinement (slower, more accurate) — ask a small fast model to
   score the keyword candidates and return a final ranked list with reasons.

The caller (/chat/recommend-skills) merges both stages and returns up to
MAX_RECOMMENDATIONS ranked results.
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from dataclasses import dataclass
from typing import Any, List, Optional

from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy.orm import Session

from lumen_core.llm_call_context import LLMCallContext
from lumen_models.skill import Skill
from lumen_models.skill_marketplace import InstalledSkill, SkillMarketplace
from lumen_models.user import User
from lumen_services.model_loader import create_chat_model

logger = logging.getLogger(__name__)

MAX_RECOMMENDATIONS = 5
SKILL_RECOMMEND_CALL_TYPE = "chat.skill_recommend"

# Keyword-match system prompt (no LLM needed, pure text processing)
KEYWORD_EXTRACT_PROMPT = """\
你是一个技能关键词提取器。从用户消息中提取能匹配技能的关键信息。

技能列表：
{skill_list}

用户消息：{user_message}

请提取用户消息中与技能相关的关键词/实体（人名、技术名词、场景词等），返回JSON：
{{"matched_skills": [{"skill_id": id, "match_terms": ["词1", "词2"], "score": 0.0-1.0}]}}
score表示匹配置信度，考虑：
- 精确匹配技能名/别名 → 高分
- 技术栈/场景相关 → 中等
- 间接相关 → 低分

只返回JSON，不要其他文字。"""


@dataclass
class SkillRecommendation:
    skill_id: int
    marketplace_skill_id: int
    name: str
    description: str
    reason: str
    confidence: float  # 0.0-1.0
    match_type: str  # "keyword" | "llm"


def _normalize(text: str) -> str:
    """Lowercase + strip Chinese punctuation for token matching."""
    text = text.lower().strip()
    # Remove Chinese punctuation, keep letters/numbers/Chinese chars
    text = re.sub(r"[^\w\u4e00-\u9fff]", " ", text)
    return text


def _strip_tenant_suffix(name: str) -> str:
    """Strip the _{tenant_id} suffix added at install time.

    Installed skill names are stored as '{marketplace_name}_{tenant_id}'
    (e.g. '周报生成器_1') to satisfy the per-tenant unique-name constraint.
    We match against the base name so the user's message doesn't need
    to include the tenant suffix.
    """
    return re.sub(r"_\d+$", "", name)


def keyword_match(
    user_message: str,
    installed_skills: List[tuple],
) -> List[SkillRecommendation]:
    """Fast keyword-based matching without LLM.

    installed_skills: list of (Skill or SkillMarketplace, marketplace_skill_id)
    Returns list of matched SkillRecommendation (match_type="keyword").
    """
    norm_msg = _normalize(user_message)
    msg_words = set(norm_msg.split())

    results: List[SkillRecommendation] = []

    for skill, marketplace_skill_id in installed_skills:
        # Strip tenant suffix for matching (e.g. "周报生成器_1" → "周报生成器")
        base_name = _strip_tenant_suffix(skill.name)
        name_norm = _normalize(base_name)
        desc_norm = _normalize(skill.description or "")

        # Compute word overlap
        name_words = set(name_norm.split())
        desc_words = set(desc_norm.split())

        matched_terms: List[str] = []
        score = 0.0

        # Exact name match — highest weight
        if name_norm in norm_msg:
            score = 0.9
            matched_terms.append(base_name)
        else:
            # Word-level overlap
            overlap = msg_words & name_words
            if overlap:
                matched_terms.extend(overlap)
                score = 0.4 + 0.1 * min(len(overlap), 3)

            # Description overlap (lower weight)
            desc_overlap = msg_words & desc_words
            if desc_overlap:
                matched_terms.extend(desc_overlap)
                score = max(score, 0.2 + 0.05 * min(len(desc_overlap), 5))

        # Skip no-match
        if score <= 0:
            continue

        results.append(SkillRecommendation(
            skill_id=getattr(skill, "id", 0),
            marketplace_skill_id=marketplace_skill_id,
            name=skill.name,
            description=skill.description or "",
            reason=f"关键词匹配：{', '.join(matched_terms[:3])}",
            confidence=min(score, 1.0),
            match_type="keyword",
        ))

    # Sort by confidence desc
    results.sort(key=lambda x: x.confidence, reverse=True)
    return results


def llm_refine(
    user_message: str,
    candidates: List[SkillRecommendation],
    db: Session,
    user: User,
    tenant_id: int,
) -> List[SkillRecommendation]:
    """Use a fast LLM to re-rank keyword candidates and add reasoning.

    Returns updated list with match_type="llm" and richer reason text.
    """
    if not candidates:
        return []

    # Use the default fast model (MiniMax id=3)
    try:
        chat = create_chat_model(model_config_id=3)
    except Exception as e:
        logger.warning("Failed to create chat model for skill recommend: %s", e)
        return candidates

    skill_list_text = "\n".join(
        f'- id={c.marketplace_skill_id} 名称="{c.name}" 描述="{c.description}"'
        for c in candidates[:10]
    )

    prompt = KEYWORD_EXTRACT_PROMPT.format(
        skill_list=skill_list_text,
        user_message=user_message,
    )

    trace_id = str(uuid.uuid4())
    call_id = str(uuid.uuid4())
    ctx = LLMCallContext(
        call_id=call_id,
        trace_id=trace_id,
        parent_call_id=None,
        call_type=SKILL_RECOMMEND_CALL_TYPE,
        call_index=0,
        tenant_id=tenant_id,
        user_id=user.id,
        username=user.username,
        extra={"candidate_count": len(candidates)},
    )

    try:
        messages = [HumanMessage(content=prompt)]
        raw = chat.invoke(messages)

        # Parse JSON from response
        content = raw.content if hasattr(raw, "content") else str(raw)
        # Try to extract JSON block
        match = re.search(r"\{[\s\S]*\}", content)
        if match:
            parsed = json.loads(match.group())
            id_to_reason = {}
            for item in parsed.get("matched_skills", []):
                sid = item.get("skill_id")
                score = item.get("score", 0)
                if sid is not None:
                    id_to_reason[sid] = {
                        "reason": item.get("reason", "LLM分析推荐"),
                        "score": score,
                    }

            # Update candidates with LLM reasoning
            for c in candidates:
                if c.marketplace_skill_id in id_to_reason:
                    c.match_type = "llm"
                    c.confidence = min(id_to_reason[c.marketplace_skill_id]["score"], 1.0)
                    c.reason = id_to_reason[c.marketplace_skill_id]["reason"]
                else:
                    # Not confirmed by LLM — downgrade
                    c.confidence *= 0.5

        candidates.sort(key=lambda x: x.confidence, reverse=True)
    except Exception as e:
        logger.warning("LLM refinement failed: %s — falling back to keyword results", e)

    return candidates


def get_installed_skills_for_tenant(
    db: Session,
    tenant_id: int,
) -> List[tuple]:
    """Return list of (Skill or SkillMarketplace, marketplace_skill_id) for tenant."""
    # Skills that have an installed record: prefer Skill row (per-tenant copy)
    rows_with_skill = (
        db.query(Skill, SkillMarketplace.id.label("ms_id"))
        .join(InstalledSkill, InstalledSkill.skill_id == Skill.id)
        .join(SkillMarketplace, SkillMarketplace.id == InstalledSkill.marketplace_skill_id)
        .filter(
            InstalledSkill.tenant_id == tenant_id,
            InstalledSkill.status == "active",
            Skill.is_active == True,
        )
        .all()
    )

    # Marketplace-only installs (no Skill copy)
    rows_market_only = (
        db.query(SkillMarketplace, SkillMarketplace.id.label("ms_id"))
        .join(InstalledSkill, InstalledSkill.marketplace_skill_id == SkillMarketplace.id)
        .filter(
            InstalledSkill.tenant_id == tenant_id,
            InstalledSkill.skill_id.is_(None),
            InstalledSkill.status == "active",
        )
        .all()
    )

    return [(r.Skill, r.ms_id) for r in rows_with_skill] + rows_market_only


class SkillRecommender:
    """Two-stage skill recommender: keyword → LLM refinement."""

    def __init__(self, db: Session, user: User):
        self.db = db
        self.user = user
        self.tenant_id = user.tenant_id

    def recommend(
        self,
        user_message: str,
        top_k: int = MAX_RECOMMENDATIONS,
    ) -> List[SkillRecommendation]:
        """Return up to top_k recommended skills for the given user message."""
        if not user_message or not user_message.strip():
            return []

        installed = get_installed_skills_for_tenant(self.db, self.tenant_id)
        if not installed:
            return []

        # Stage 1: keyword match
        keyword_results = keyword_match(user_message, installed)

        # Stage 2: LLM refine top candidates
        top_candidates = keyword_results[: min(10, len(keyword_results))]
        if top_candidates:
            top_candidates = llm_refine(
                user_message, top_candidates, self.db, self.user, self.tenant_id
            )

        # Sort and cap
        top_candidates.sort(key=lambda x: x.confidence, reverse=True)
        return top_candidates[:top_k]
