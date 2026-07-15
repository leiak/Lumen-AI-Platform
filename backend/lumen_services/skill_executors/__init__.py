"""Skill executor dispatch (M16)."""
from lumen_services.skill_executors.base import BaseSkillExecutor
from lumen_services.skill_executors.registry import EXECUTOR_REGISTRY


def get_executor(skill_type: str) -> BaseSkillExecutor:
    if skill_type not in EXECUTOR_REGISTRY:
        raise ValueError(f"Unknown skill type: {skill_type}")
    return EXECUTOR_REGISTRY[skill_type]()


__all__ = ["BaseSkillExecutor", "EXECUTOR_REGISTRY", "get_executor"]
