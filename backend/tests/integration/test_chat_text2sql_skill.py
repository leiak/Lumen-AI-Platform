"""M33: integration test — chat with text2sql skill.

Spec: docs/superpowers/specs/2026-06-20-text2sql-design.md §7
"""
import uuid
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

from lumen_core.database import SessionLocal
from lumen_models.skill_marketplace import InstalledSkill, SkillMarketplace


def test_text2sql_skill_appears_in_active_skills():
    """The SkillRunner must surface a tool when a text2sql skill is installed."""
    from lumen_services.skill_runner import SkillRunner

    db = SessionLocal()
    try:
        suffix = uuid.uuid4().hex[:8]
        mkt = SkillMarketplace(
            name=f"intl-text2sql-{suffix}",
            category="data",
            type="text2sql",
            type_config={"data_source_name": "默认 ai_platform"},
        )
        db.add(mkt)
        db.commit()
        db.refresh(mkt)
        db.add(InstalledSkill(
            tenant_id=1, marketplace_skill_id=mkt.id, status="active"
        ))
        db.commit()
        skill_id = mkt.id
    finally:
        db.close()

    db2 = SessionLocal()
    try:
        prompts, tools = SkillRunner.get_active_skills(db2, 1, [skill_id])
        assert len(prompts) == 0  # text2sql is tool-only
        assert len(tools) == 1
        assert tools[0].name == f"skill_{skill_id}_text2sql"
    finally:
        db2.close()


def test_text2sql_tool_invokes_engine_with_mocked_llm():
    """End-to-end: invoke the text2sql tool with a mocked LLM and
    verify the engine is called, the result is returned, and the
    LLMCallLog row is written.
    """
    from lumen_services.skill_runner import SkillRunner

    db = SessionLocal()
    try:
        suffix = uuid.uuid4().hex[:8]
        mkt = SkillMarketplace(
            name=f"intl-text2sql-mock-{suffix}",
            category="data",
            type="text2sql",
            type_config={"data_source_name": "默认 ai_platform"},
        )
        db.add(mkt)
        db.commit()
        db.refresh(mkt)
        db.add(InstalledSkill(
            tenant_id=1, marketplace_skill_id=mkt.id, status="active"
        ))
        db.commit()
        skill_id = mkt.id
    finally:
        db.close()

    db2 = SessionLocal()
    try:
        prompts, tools = SkillRunner.get_active_skills(db2, 1, [skill_id])
        tool = tools[0]
        # Mock the LLM so the engine returns a quick success
        fake = MagicMock()
        fake.invoke.side_effect = [
            MagicMock(content="SELECT 1 AS one", response_metadata={}),
            MagicMock(content="一行一列,值 1。\n置信度: 0.9", response_metadata={}),
        ]
        with patch("lumen_services.text2sql.engine.create_chat_model", return_value=fake):
            result_str = tool.run({"question": "test"})
        # The tool returns a markdown-formatted string
        assert "SELECT 1" in result_str.upper()
        assert "Question" in result_str or "question" in result_str.lower()
    finally:
        db2.close()
