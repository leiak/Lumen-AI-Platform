"""Agent execution subpackage.

This package holds multi-agent collaboration utilities (TeamService,
manager-decides routing, etc.) and is reserved for future agent internals
(memory policy, tool choice, executor) added by other tasks.
"""
from lumen_services.agents.team import (
    RoutePolicy,
    TeamService,
    ManagerDecision,
)
from lumen_services.agents.memory import (
    MemoryPolicy,
    apply_memory_policy,
    summarize_for_compression,
)
from lumen_services.agents.tool_choice import (
    ToolChoiceMode,
    select_tools,
    tool_choice_hint,
)

__all__ = [
    "RoutePolicy",
    "TeamService",
    "ManagerDecision",
    "MemoryPolicy",
    "apply_memory_policy",
    "summarize_for_compression",
    "ToolChoiceMode",
    "select_tools",
    "tool_choice_hint",
]
