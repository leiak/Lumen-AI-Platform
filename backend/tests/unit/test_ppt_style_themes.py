"""Tests for M35 PPT 生成完善：风格主题差异化 + prompt + JSON 提取 + 修复重试。

覆盖:
  - 三种风格 StyleTheme 视觉字段差异
  - PPT_SYSTEM_PROMPT 含风格调性段 + 页数放开
  - build_schema 的 content_prompt 不再硬编码固定页数
  - _extract_json 处理 ```json``` 围栏 + 平衡括号
  - JSON 解析失败时的修复重试
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from lumen_models.chat import Conversation
from lumen_services.ppt_service import (
    PPT_SYSTEM_PROMPT,
    PptService,
    _extract_json,
)
from lumen_tasks.ppt_task import _style_theme, _format_page_number, _to_roman


# --- helpers ---

def _fake_message(content: str):
    m = MagicMock()
    m.role = "assistant"
    m.content = content
    return m


def _make_db(messages):
    """构造一个 MagicMock DB：Conversation 查询返回存在，Message 查询返回给定列表。"""
    db = MagicMock()
    conv = MagicMock()

    conv_query = MagicMock()
    conv_query.filter.return_value.first.return_value = conv

    msg_query = MagicMock()
    msg_query.filter.return_value = msg_query
    msg_query.order_by.return_value = msg_query
    msg_query.limit.return_value = msg_query
    msg_query.all.return_value = messages

    def _query(model):
        if model is Conversation:
            return conv_query
        return msg_query

    db.query.side_effect = _query
    return db


def _fake_cfg():
    cfg = MagicMock()
    cfg.model_type = "openai"
    cfg.model_name = "test-model"
    cfg.base_url = "http://x"
    cfg.api_key = "k"
    cfg.id = 1
    return cfg


class _FakeChat:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def invoke(self, messages):
        self.calls.append(messages)
        resp = self._responses[len(self.calls) - 1]
        m = MagicMock()
        m.content = resp
        return m


_VALID_SCHEMA_JSON = (
    '{"title":"t","subtitle":"s","author":"Lumen AI","slides":['
    '{"layout":"title_only","title":"封面"},'
    '{"layout":"title_content","title":"进展","content":["真实要点一"]},'
    '{"layout":"blank","content":["谢谢观看"]}]}'
)


# --- 1. 三风格主题差异 ---

def test_three_styles_distinct_themes():
    themes = [_style_theme("simple"), _style_theme("business"), _style_theme("academic")]
    fields = ["bg", "title", "title_font", "bullet_char", "show_top_bar", "chart_palette"]
    distinct = sum(1 for f in fields if len({getattr(t, f) for t in themes}) > 1)
    assert distinct >= 5


# --- 2. system prompt 含风格调性 + 页数放开 ---

def test_system_prompt_contains_style_tone_block():
    for kw in ["简约", "商务", "学术", "KPI", "学术化"]:
        assert kw in PPT_SYSTEM_PROMPT
    assert "7~10" in PPT_SYSTEM_PROMPT
    # 禁止占位符指令
    assert "占位" in PPT_SYSTEM_PROMPT


# --- 3. content_prompt 不再硬编码固定页数 ---

def test_no_num_slides_hardcoded_in_content_prompt():
    db = _make_db([_fake_message("讨论了本周工程进展和 KPI")])
    chat = _FakeChat([_VALID_SCHEMA_JSON])
    with patch("lumen_services.ppt_service._get_default_model_config", return_value=_fake_cfg()), \
         patch("lumen_services.ppt_service.create_chat_model", return_value=chat):
        PptService().build_schema(
            db=db, tenant_id=1, user_id=1, conversation_id=1,
            title="固定标题", content_range=10, include_charts=False, style="business",
        )
    # 拿到 schema-invoke 的 HumanMessage 内容
    human_prompt = chat.calls[0][1].content
    assert "7~10" in human_prompt
    assert "页左右" not in human_prompt


# --- 4 & 5. JSON 提取 ---

def test_json_extract_handles_fenced_block():
    assert _extract_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_json_extract_balanced_braces():
    out = _extract_json('说明文字\n{"a": 1, "b": [1, 2]}\n更多说明')
    assert out == {"a": 1, "b": [1, 2]}


# --- 6. 修复重试 ---

def test_repair_retry_on_json_failure():
    db = _make_db([_fake_message("对话内容")])
    # 第一次返回非法 JSON，第二次(修复)返回合法
    chat = _FakeChat(["这不是 JSON，只是一段文字。", _VALID_SCHEMA_JSON])
    with patch("lumen_services.ppt_service._get_default_model_config", return_value=_fake_cfg()), \
         patch("lumen_services.ppt_service.create_chat_model", return_value=chat):
        schema = PptService().build_schema(
            db=db, tenant_id=1, user_id=1, conversation_id=1,
            title="固定标题", content_range=10, include_charts=False, style="simple",
        )
    assert len(chat.calls) == 2  # 触发了修复重试
    assert schema.title == "固定标题"
    assert len(schema.slides) == 3


# --- 页码格式辅助 ---

def test_page_number_formats():
    assert _format_page_number("dotted", 3, 8) == "03."
    assert _format_page_number("slash", 3, 8) == "3/8"
    assert _format_page_number("roman", 3, 9) == "III / IX"
    assert _to_roman(4) == "IV"


def test_default_model_config_picks_chat_not_embedding():
    """回归：nomic-embed-text 不应被当作 chat 模型。

    历史 bug：_get_default_model_config 的 tenant_id=1 查询在 DB 里所有默认 chat 模型
    tenant_id=NULL 时不命中；fallback 又没 is_chat 过滤，结果选到了 id=123 nomic-embed-text
    (embedding)，Ollama 返 400 `does not support chat`。
    """
    from lumen_core.database import SessionLocal
    from lumen_services.ppt_service import _get_default_model_config

    db = SessionLocal()
    try:
        cfg = _get_default_model_config(db, tenant_id=1)
        assert cfg is not None, "应当能选到至少一个 chat 模型"
        assert cfg.is_chat is True, f"选到了非 chat 模型 (id={cfg.id}, name={cfg.model_name})"
    finally:
        db.close()


def test_chart_data_normalizes_legacy_format():
    """回归：LLM 常用 ``{type, data: [{name, value}, ...]}`` 格式输出 chart，
    需要自动 normalize 成 spec 要求的 ``{type, title, labels, datasets}`` 格式。
    """
    from lumen_schemas.ppt import ChartData, PptSchema

    legacy = {
        "type": "bar",
        "data": [
            {"name": "周一", "value": 78},
            {"name": "周二", "value": 92},
            {"name": "周三", "value": 65},
        ],
    }
    chart = ChartData.model_validate(legacy)
    assert chart.labels == ["周一", "周二", "周三"]
    assert chart.datasets == [{"name": "数值", "values": [78, 92, 65]}]
    assert chart.type == "bar"
    assert chart.title == "数据概览"  # 缺省兜底


def test_ppt_schema_accepts_legacy_chart_in_slide():
    """Slide 里含 legacy chart 格式时整张 PptSchema 应能正常解析。"""
    from lumen_schemas.ppt import PptSchema

    schema_dict = {
        "title": "测试",
        "slides": [
            {"layout": "title_only", "title": "封面"},
            {
                "layout": "chart",
                "title": "KPI 概览",
                "chart": {
                    "type": "line",
                    "data": [{"name": "1月", "value": 100}, {"name": "2月", "value": 120}],
                },
            },
            {"layout": "blank", "content": ["谢谢观看"]},
        ],
    }
    schema = PptSchema.model_validate(schema_dict)
    chart = schema.slides[1].chart
    assert chart is not None
    assert chart.title == "数据概览"  # ChartData 自己兜底；slide.title 仍在 slide 上
    assert schema.slides[1].title == "KPI 概览"
    assert chart.labels == ["1月", "2月"]
    assert chart.datasets[0]["values"] == [100, 120]
