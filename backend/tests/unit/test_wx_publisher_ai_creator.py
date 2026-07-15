"""M32 wx_publisher AI 创作 service tests (T18).

Spec: docs/superpowers/specs/2026-06-17-wx-publisher-design.md §4.2 / §8.1

4 tests, all mock ``create_chat_model`` (M26 ship 模式: 替换
``app.services.wx_publisher.ai_creator.create_chat_model`` 即可):

- test_outline_prompt_template_has_json_marker
  静态检查 OUTLINE prompt 含 JSON 输出要求 + 风格变量
- test_rewrite_prompt_includes_original_and_instruction
  静态检查 REWRITE prompt 含 ``{original}`` + ``{instruction}``
- test_expand_prompt_includes_ratio
  静态检查 EXPAND prompt 含 ``{expansion_ratio:.1f}``
- test_title_prompt_has_json_marker
  静态检查 TITLE prompt 含 JSON 输出要求

- test_generate_outline_writes_sections
  monkeypatch create_chat_model 返固定 JSON sections,验证 db 写入
  + sections 数量 + order_index 正确
- test_generate_titles_parses_json_and_dedups
  返 mock titles list,验证去重 + 去空 + 数量限制

- test_4_call_type_constants_defined
  4 个 WX_PUBLISHER_CALL_TYPE_* 常量都是字面字符串(spec §4.2)

- test_rewrite_returns_text_without_writing
  mock 返纯文本,验证返文本且不写 section.content_markdown

- test_expand_returns_text_with_expansion_ratio
  mock 返纯文本,验证返文本

不在范围:测 LLMCallContext 写库(M26 ship 的 LoggingChatModel 已
有 test_image_gen_logs_call.py 覆盖,本 service 仅在 wrapper 外
包一层 set/reset,跟 llm.py / agent_rag 同模式)。
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any, List, Optional

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

# FK targets must be registered before SQLAlchemy resolves the metadata.
from lumen_models import (  # noqa: F401
    agent as _agent,
    image_generation as _image_generation,
    knowledge as _knowledge,
    model_config as _model_config,
    user as _user_model,
)
from lumen_models.wx_publisher import WxDraft, WxDraftSection

from _wx_publisher_helpers import (
    cleanup_tracked,
    fresh_session,
    make_draft,
    make_tenant,
    make_user,
    make_section,
)


# ---------------------------------------------------------------------------
# Mock chat model
# ---------------------------------------------------------------------------

class _MockChatModel:
    """替代 ``create_chat_model`` 的 mock — 返预置的 ``content`` 字符串。

    真实 LoggingChatModel proxy 的 ``invoke`` 写 1 行 llm_call_logs,
    但本 mock 不写库(只过 set_call_context/reset_call_context 即可)。
    """

    def __init__(self, content: str):
        self._content = content
        self.calls: List[Any] = []

    def invoke(self, prompt: Any, **kwargs) -> Any:
        self.calls.append(prompt)
        # 返一个伪 AIMessage-like 对象(有 .content 属性)
        class _R:
            pass
        r = _R()
        r.content = self._content
        r.tool_calls = []
        r.usage_metadata = None
        r.response_metadata = {}
        return r

    def bind_tools(self, tools):
        return self


def _install_mock(monkeypatch, content: str) -> _MockChatModel:
    """Monkeypatch ``create_chat_model`` 让它返 _MockChatModel(content)。"""
    mock = _MockChatModel(content)
    from lumen_services.wx_publisher import ai_creator
    monkeypatch.setattr(ai_creator, "create_chat_model", lambda *a, **kw: mock)
    return mock


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db_session():
    db = fresh_session()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def track_tenant_ids():
    return []


@pytest.fixture
def track_user_ids():
    return []


@pytest.fixture
def track_draft_ids():
    return []


@pytest.fixture
def cleanup_rows(track_tenant_ids, track_user_ids, track_draft_ids):
    yield
    cleanup_tracked(
        tenant_ids=track_tenant_ids, user_ids=track_user_ids,
        draft_ids=track_draft_ids,
    )


@pytest.fixture
def setup(db_session, track_tenant_ids, track_user_ids):
    tenant = make_tenant(db_session)
    track_tenant_ids.append(tenant.id)
    user = make_user(db_session, tenant_id=tenant.id)
    track_user_ids.append(user.id)
    return tenant, user


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_4_call_type_constants_defined():
    """4 个 WX_PUBLISHER_CALL_TYPE_* 常量都按 spec §4.2 定义。"""
    from lumen_services.wx_publisher import ai_creator
    assert ai_creator.WX_PUBLISHER_CALL_TYPE_OUTLINE == "wx_publisher.outline"
    assert ai_creator.WX_PUBLISHER_CALL_TYPE_REWRITE == "wx_publisher.rewrite"
    assert ai_creator.WX_PUBLISHER_CALL_TYPE_EXPAND == "wx_publisher.expand"
    assert ai_creator.WX_PUBLISHER_CALL_TYPE_TITLE == "wx_publisher.title"


def test_outline_prompt_template_has_json_marker():
    """OUTLINE prompt 包含 JSON 输出要求 + 3 个 format 变量。"""
    from lumen_services.wx_publisher.ai_creator import WxAIPromptTemplates
    tpl = WxAIPromptTemplates.OUTLINE
    assert "{style}" in tpl
    assert "{section_count}" in tpl
    assert "{topic}" in tpl
    assert '"sections"' in tpl  # JSON output 要求
    assert "公众号" in tpl or "文章" in tpl  # 角色描述
    rendered = tpl.format(style="总-分-总", section_count=5, topic="AI Agent")
    assert "总-分-总" in rendered
    assert "5" in rendered
    assert "AI Agent" in rendered


def test_rewrite_prompt_includes_original_and_instruction():
    """REWRITE prompt 含 ``{original}`` + ``{instruction}`` + 输出 markdown 要求。"""
    from lumen_services.wx_publisher.ai_creator import WxAIPromptTemplates
    tpl = WxAIPromptTemplates.REWRITE
    assert "{original}" in tpl
    assert "{instruction}" in tpl
    assert "markdown" in tpl.lower()
    rendered = tpl.format(original="orig", instruction="更口语化")
    assert "orig" in rendered
    assert "更口语化" in rendered


def test_expand_prompt_includes_ratio_and_chars():
    """EXPAND prompt 含 ``{expansion_ratio:.1f}`` + ``{target_chars}`` + ``{original_chars}``。"""
    from lumen_services.wx_publisher.ai_creator import WxAIPromptTemplates
    tpl = WxAIPromptTemplates.EXPAND
    assert "{expansion_ratio" in tpl  # ``{expansion_ratio:.1f}``
    assert "{target_chars}" in tpl
    assert "{original_chars}" in tpl
    assert "markdown" in tpl.lower()
    rendered = tpl.format(
        original="orig", target_chars=300, original_chars=200, expansion_ratio=1.5,
    )
    assert "1.5" in rendered
    assert "300" in rendered
    assert "200" in rendered


def test_title_prompt_template_has_json_marker():
    """TITLE prompt 包含 JSON 输出要求 + ``{topic}`` + ``{summary}`` + ``{count}``。"""
    from lumen_services.wx_publisher.ai_creator import WxAIPromptTemplates
    tpl = WxAIPromptTemplates.TITLE
    assert '"titles"' in tpl
    assert "{topic}" in tpl
    assert "{summary}" in tpl
    assert "{count}" in tpl
    rendered = tpl.format(topic="AI Agent", summary="企业知识管理", count=5)
    assert "AI Agent" in rendered
    assert "企业知识管理" in rendered
    assert "5" in rendered


def test_generate_outline_writes_sections(
    monkeypatch, db_session, setup, cleanup_rows, track_draft_ids,
):
    """generate_outline 调 LLM 返 JSON sections,写 wx_draft_sections + 替换现有。"""
    from lumen_services.wx_publisher.ai_creator import WxAICreator

    tenant, user = setup
    draft = make_draft(
        db_session, tenant_id=tenant.id, user_id=user.id,
        content_markdown="原始内容",
    )
    track_draft_ids.append(draft.id)
    # 预存 1 个旧 section,验证「替换」语义
    old_section = make_section(
        db_session, tenant_id=tenant.id, draft_id=draft.id,
        order_index=0, heading="旧章节", content_markdown="旧内容",
    )

    payload = {
        "sections": [
            {"heading": "一、引言", "summary": "引出主题"},
            {"heading": "二、方案", "summary": "给出方案"},
            {"heading": "三、案例", "summary": "实际案例"},
        ]
    }
    mock = _install_mock(monkeypatch, json.dumps(payload, ensure_ascii=False))
    # Capture old_section id before generate_outline deletes it
    # (deleted ORM instances raise ObjectDeletedError on attribute access).
    old_section_id = int(old_section.id)

    creator = WxAICreator(db_session, user)
    sections = creator.generate_outline(
        draft, topic="AI Agent 应用", section_count=3, style="总-分-总",
    )

    # 1. 返 3 个 section,按 order_index 排
    assert len(sections) == 3
    assert sections[0].order_index == 0
    assert sections[2].order_index == 2
    assert sections[0].heading == "一、引言"

    # 2. mock 被调过
    assert len(mock.calls) == 1
    assert "AI Agent 应用" in mock.calls[0]
    assert "总-分-总" in mock.calls[0]

    # 3. 旧 section 已被替换
    db_session.expire_all()
    existing = db_session.query(WxDraftSection).filter(
        WxDraftSection.draft_id == draft.id,
    ).order_by(WxDraftSection.order_index.asc()).all()
    assert len(existing) == 3
    assert all(s.id != old_section_id for s in existing)
    assert existing[0].heading == "一、引言"
    # 4. content_markdown 含 heading + summary
    assert "## 一、引言" in existing[0].content_markdown
    assert "引出主题" in existing[0].content_markdown


def test_generate_titles_parses_json_and_dedups(
    monkeypatch, db_session, setup, cleanup_rows, track_draft_ids,
):
    """generate_titles 解析 JSON titles,去空 + 去重 + 限数量。"""
    from lumen_services.wx_publisher.ai_creator import WxAICreator

    tenant, user = setup
    draft = make_draft(
        db_session, tenant_id=tenant.id, user_id=user.id,
        content_markdown="AI 时代",
    )
    track_draft_ids.append(draft.id)

    payload = {
        "titles": [
            "AI 时代来临",
            "AI 时代来临",   # dup
            "",                # empty (deduped)
            "如何用好 AI",     # new
            "  ",              # whitespace
            "AI 改变世界",     # new
        ]
    }
    _install_mock(monkeypatch, json.dumps(payload, ensure_ascii=False))

    creator = WxAICreator(db_session, user)
    titles = creator.generate_titles(draft, count=3)

    # 去重 + 去空 + 限 3
    assert titles == ["AI 时代来临", "如何用好 AI", "AI 改变世界"]


def test_rewrite_returns_text_without_writing(
    monkeypatch, db_session, setup, cleanup_rows, track_draft_ids,
):
    """rewrite_section 返新文本,不自动写 section.content_markdown。"""
    from lumen_services.wx_publisher.ai_creator import WxAICreator

    tenant, user = setup
    draft = make_draft(db_session, tenant_id=tenant.id, user_id=user.id)
    track_draft_ids.append(draft.id)
    section = make_section(
        db_session, tenant_id=tenant.id, draft_id=draft.id,
        order_index=0, heading="h1", content_markdown="原始正文",
    )
    original_md = section.content_markdown

    _install_mock(monkeypatch, "改写后的新内容(更口语化)")

    creator = WxAICreator(db_session, user)
    new_md = creator.rewrite_section(section, instruction="更口语化")

    # 1. 返新文本
    assert "改写后" in new_md
    # 2. db 没改
    db_session.expire_all()
    section_now = db_session.query(WxDraftSection).filter(
        WxDraftSection.id == section.id,
    ).first()
    assert section_now.content_markdown == original_md
