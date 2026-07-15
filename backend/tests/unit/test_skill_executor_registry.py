"""M33: tests for the skill executor registry.

Verifies the Text2SqlExecutor is wired up correctly.
"""
from lumen_services.skill_executors.registry import EXECUTOR_REGISTRY
from lumen_services.skill_executors.text2sql import Text2SqlExecutor


def test_text2sql_registered_in_executor_registry():
    """The ``text2sql`` key must point to ``Text2SqlExecutor``."""
    assert "text2sql" in EXECUTOR_REGISTRY
    assert EXECUTOR_REGISTRY["text2sql"] is Text2SqlExecutor


def test_executor_registry_has_six_types():
    """Sanity check — registry must include all 6 ship'd types."""
    expected = {"prompt", "script", "http", "knowledge_retrieval", "tool", "text2sql"}
    actual = set(EXECUTOR_REGISTRY.keys())
    assert expected.issubset(actual), (
        f"Missing executor types: {expected - actual}"
    )
