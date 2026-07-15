"""Tests for BaseSkillExecutor abstraction + registry dispatch (M16)."""
import pytest


def test_registry_contains_all_m16_types():
    """Registry must have entries for prompt / script / http."""
    from lumen_services.skill_executors.registry import EXECUTOR_REGISTRY
    assert "prompt" in EXECUTOR_REGISTRY
    assert "script" in EXECUTOR_REGISTRY
    assert "http" in EXECUTOR_REGISTRY


def test_get_executor_returns_correct_instance():
    from lumen_services.skill_executors import get_executor
    from lumen_services.skill_executors.prompt import PromptExecutor
    from lumen_services.skill_executors.script import ScriptExecutor
    from lumen_services.skill_executors.http import HttpExecutor

    assert isinstance(get_executor("prompt"), PromptExecutor)
    assert isinstance(get_executor("script"), ScriptExecutor)
    assert isinstance(get_executor("http"), HttpExecutor)


def test_get_executor_unknown_type_raises():
    from lumen_services.skill_executors import get_executor
    with pytest.raises(ValueError, match="Unknown skill type"):
        get_executor("foo")
