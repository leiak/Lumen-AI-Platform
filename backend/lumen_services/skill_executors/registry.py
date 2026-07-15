"""Registry of skill type → executor class (M16 + M17)."""
from typing import Dict, Type
from lumen_services.skill_executors.base import BaseSkillExecutor
from lumen_services.skill_executors.prompt import PromptExecutor
from lumen_services.skill_executors.script import ScriptExecutor  # noqa: E402
from lumen_services.skill_executors.http import HttpExecutor  # noqa: E402
from lumen_services.skill_executors.knowledge_retrieval import KnowledgeRetrievalExecutor  # noqa: E402
from lumen_services.skill_executors.tool import ToolExecutor  # noqa: E402
from lumen_services.skill_executors.text2sql import Text2SqlExecutor  # noqa: E402

EXECUTOR_REGISTRY: Dict[str, Type[BaseSkillExecutor]] = {
    "prompt": PromptExecutor,
    "script": ScriptExecutor,
    "http": HttpExecutor,
    "knowledge_retrieval": KnowledgeRetrievalExecutor,
    "tool": ToolExecutor,
    "text2sql": Text2SqlExecutor,  # M33 6th executor type
    # M18:
    # "workflow": WorkflowExecutor,
    # "composite": CompositeExecutor,
}
