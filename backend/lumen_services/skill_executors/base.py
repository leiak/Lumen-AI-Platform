"""Base class for all skill executors (M16)."""
from abc import ABC, abstractmethod
from typing import Optional
from langchain_core.tools import BaseTool
from lumen_models.skill_marketplace import SkillMarketplace


class BaseSkillExecutor(ABC):
    """Each subclass handles one skill type.

    Two responsibilities:
      1. to_system_prompt: For prompt-type skills, return text to inject.
         For other types, return None.
      2. to_langchain_tool: For tool-callable types, return a LangChain BaseTool.
         For prompt-type, return None.
    """

    type: str  # Subclass sets (e.g. "prompt", "script", "http")

    @abstractmethod
    def to_system_prompt(self, skill: SkillMarketplace) -> Optional[str]:
        ...

    @abstractmethod
    def to_langchain_tool(
        self, skill: SkillMarketplace, tenant_id: int
    ) -> Optional[BaseTool]:
        ...
