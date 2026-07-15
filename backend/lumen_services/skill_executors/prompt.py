"""Prompt skill executor — injects content as system prompt (existing behavior)."""
import logging
from typing import Optional
from langchain_core.tools import BaseTool
from lumen_models.skill_marketplace import SkillMarketplace
from lumen_services.skill_executors.base import BaseSkillExecutor

logger = logging.getLogger(__name__)


class PromptExecutor(BaseSkillExecutor):
    type = "prompt"

    def to_system_prompt(self, skill: SkillMarketplace) -> Optional[str]:
        """Return content for system prompt injection.

        Returns None if skill.content is NULL or empty — prompt skills
        without content are silently skipped (graceful degradation per
        M16 §3.9 backward compatibility).
        """
        if not skill.content:
            logger.warning(
                f"Prompt skill {skill.id} ('{skill.name}') has no content; "
                f"skipping system prompt injection"
            )
            return None
        return skill.content  # type: ignore[return-value]

    def to_langchain_tool(
        self, skill: SkillMarketplace, tenant_id: int
    ) -> Optional[BaseTool]:
        # Prompt skills are auto-injected, not tool-callable.
        return None
