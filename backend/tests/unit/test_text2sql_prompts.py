"""M33: tests for the prompt template helpers.

Spec: docs/superpowers/specs/2026-06-20-text2sql-design.md §5

The prompts are deterministic; a regression in template variables
(schema_text / max_rows / question) would silently degrade LLM
quality without breaking any test. We lock the shape here.
"""
from lumen_services.text2sql.prompts import (
    parse_explanation,
    render_explanation_system,
    render_explanation_user,
    render_regeneration_user,
    render_sql_generation_system,
    render_sql_generation_user,
)


def test_render_sql_generation_system_includes_schema_and_limit():
    out = render_sql_generation_system(schema_text="# users\n#   id BIGINT", max_rows=42)
    assert "# users" in out
    assert "42" in out  # max_rows placeholder
    assert "SELECT" in out.upper() or "select" in out


def test_render_sql_generation_user_passes_through():
    out = render_sql_generation_user("近 7 天新增用户?")
    assert "近 7 天新增用户?" in out


def test_render_regeneration_user_includes_error_and_last_sql():
    out = render_regeneration_user(
        question="x", last_sql="SELECT * FROM bad", error="table not found"
    )
    assert "SELECT * FROM bad" in out
    assert "table not found" in out


def test_render_explanation_user_includes_question_sql_and_rows():
    out = render_explanation_user(
        question="客户总数", sql="SELECT COUNT(*)", rows=[{"count": 42}], row_count=1,
    )
    assert "客户总数" in out
    assert "SELECT COUNT(*)" in out
    assert "count" in out
    assert "1" in out  # row_count


def test_render_explanation_user_caps_preview():
    out = render_explanation_user(
        question="x",
        sql="SELECT 1",
        rows=[{"v": i} for i in range(50)],
        row_count=50,
        preview_cap=5,
    )
    # The preview shows "total 50 rows" and "...", but only 5 actual rows
    assert "total 50" in out
    assert "..." in out


def test_parse_explanation_extracts_confidence():
    parsed = parse_explanation("查出来 1 个用户。\n置信度: 0.85")
    assert "1" in parsed["explanation"]
    assert parsed["confidence"] == 0.85


def test_parse_explanation_handles_chinese_colon():
    parsed = parse_explanation("查出来 1 个用户。\n置信度：0.72")
    assert parsed["confidence"] == 0.72


def test_parse_explanation_missing_confidence_returns_none():
    parsed = parse_explanation("只是解释,没有写置信度。")
    assert parsed["confidence"] is None
    assert parsed["explanation"] == "只是解释,没有写置信度。"


def test_parse_explanation_clamps_to_unit_interval():
    """Out-of-range confidence values are clamped to [0, 1]."""
    parsed = parse_explanation("bad\n置信度: 5.0")
    assert parsed["confidence"] == 1.0
    parsed = parse_explanation("bad\n置信度: -0.5")
    assert parsed["confidence"] == 0.0


def test_few_shot_examples_have_required_fields():
    """The 3 few-shot examples are referenced from the system prompt;
    each must have a question and a sql field."""
    from lumen_services.text2sql.prompts import FEW_SHOT_EXAMPLES
    assert len(FEW_SHOT_EXAMPLES) >= 3
    for ex in FEW_SHOT_EXAMPLES:
        assert "question" in ex
        assert "sql" in ex
        assert "SELECT" in ex["sql"].upper()
