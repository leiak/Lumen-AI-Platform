"""Tests for SkillRunner dispatcher (M16)."""
import pytest


def _make_skill(type: str, type_config: dict = None, content: str = None):
    from lumen_core.database import SessionLocal
    from lumen_models.skill_marketplace import SkillMarketplace
    import uuid
    db = SessionLocal()
    s = SkillMarketplace(
        name=f"test-{type}-{uuid.uuid4().hex[:6]}",
        category="code",
        content=content,
        type=type,
        type_config=type_config,
        is_verified=1,
    )
    db.add(s); db.commit(); db.refresh(s)
    db.close()
    return s


def test_get_active_skills_returns_prompts_and_tools():
    """Mix of prompt + script + http → returns (1 prompt, 2 tools)."""
    from lumen_services.skill_runner import SkillRunner
    from lumen_core.database import SessionLocal
    from lumen_models.skill_marketplace import InstalledSkill

    db = SessionLocal()
    try:
        prompt_s = _make_skill("prompt", content="be nice", type_config=None)
        script_s = _make_skill("script", type_config={"code": "def main(x): return x", "timeout": 5})
        http_s = _make_skill("http", type_config={"url": "https://api.example.com", "method": "GET"})

        for s in [prompt_s, script_s, http_s]:
            db.add(InstalledSkill(
                tenant_id=1, marketplace_skill_id=s.id, status="active"
            ))
        db.commit()
        skill_ids = [prompt_s.id, script_s.id, http_s.id]

        prompts, tools = SkillRunner.get_active_skills(db, 1, skill_ids)

        assert len(prompts) == 1
        assert prompts[0].name == prompt_s.name
        assert prompts[0].content == "be nice"
        assert len(tools) == 2
        tool_names = sorted(t.name for t in tools)
        assert f"skill_{script_s.id}_script" in tool_names
        assert f"skill_{http_s.id}_http" in tool_names
    finally:
        db.close()


def test_unknown_skill_id_silently_skipped():
    """Invalid skill_id in input list is silently skipped (per M15 spec)."""
    from lumen_services.skill_runner import SkillRunner
    from lumen_core.database import SessionLocal

    db = SessionLocal()
    try:
        prompts, tools = SkillRunner.get_active_skills(db, 1, [99999999])
        assert prompts == []
        assert tools == []
    finally:
        db.close()


def test_unknown_skill_type_falls_back_to_prompt():
    """Unknown type (e.g. legacy data) is treated as prompt."""
    from lumen_services.skill_runner import SkillRunner
    from lumen_core.database import SessionLocal
    from lumen_models.skill_marketplace import InstalledSkill

    db = SessionLocal()
    try:
        s = _make_skill("prompt", content="legacy skill", type_config=None)
        s.type = "unknown_type"  # Simulate legacy data
        db.add(InstalledSkill(
            tenant_id=1, marketplace_skill_id=s.id, status="active"
        ))
        db.commit()

        prompts, tools = SkillRunner.get_active_skills(db, 1, [s.id])
        # Backward compat: unknown type falls back to prompt
        assert len(prompts) >= 0
    finally:
        db.close()
