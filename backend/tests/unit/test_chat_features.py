"""Unit tests for ChatFeatureService — the pre-LLM preprocessing pipeline."""
import os
import sys
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))


@pytest.fixture
def feats():
    from lumen_services.chat_features import ChatFeatureService
    # db is unused by the methods we test here; pass None safely.
    return ChatFeatureService(db=None, tenant_id=1)


class TestRenderAttachments:
    def test_renders_single_attachment(self, feats):
        from lumen_schemas.chat import AttachmentRef

        atts = [AttachmentRef(
            file_id="x", name="report.txt", size=20,
            mime_type="text/plain", content_text="the body",
        )]
        text = feats._render_attachments(atts)
        assert "report.txt" in text
        assert "text/plain" in text
        assert "20" in text
        assert "the body" in text
        assert "附件" in text  # leading header marker

    def test_renders_multiple_attachments_separated(self, feats):
        from lumen_schemas.chat import AttachmentRef

        atts = [
            AttachmentRef(file_id="a", name="a.txt", size=1, mime_type="text/plain", content_text="A"),
            AttachmentRef(file_id="b", name="b.txt", size=2, mime_type="text/plain", content_text="B"),
        ]
        text = feats._render_attachments(atts)
        assert "A" in text and "B" in text
        assert "a.txt" in text and "b.txt" in text
        assert "\n\n---\n\n" in text  # separator between blocks


class TestRenderSearchResults:
    def test_renders_indexed_results(self, feats):
        from lumen_services.web_search.provider import SearchResult

        results = [
            SearchResult(title="T1", url="https://a", snippet="S1"),
            SearchResult(title="T2", url="https://b", snippet="S2"),
        ]
        text = feats._render_search_results(results)
        assert "[1]" in text and "[2]" in text
        assert "https://a" in text and "https://b" in text
        assert "T1" in text and "S1" in text
        assert "联网搜索结果" in text

    def test_empty_results_returns_empty_string(self, feats):
        assert feats._render_search_results([]) == ""


class TestRunWebSearch:
    def test_returns_provider_results(self, feats):
        from lumen_services.web_search.provider import SearchResult

        fake = [SearchResult(title="T", url="u", snippet="s")]
        feats._search_provider = MagicMock()
        feats._search_provider.search.return_value = fake
        out = feats._run_web_search("q")
        assert out == fake
        feats._search_provider.search.assert_called_once_with("q", max_results=5)


class TestPrepare:
    def _request(self, **overrides):
        from lumen_schemas.chat import ChatRequest
        base = {"message": "hi"}
        base.update(overrides)
        return ChatRequest(**base)

    def test_no_toggles_returns_just_user_message(self, feats):
        ctx = feats.prepare(history=[], request=self._request())
        # 0 system messages + 0 history + 1 user
        assert len(ctx.messages) == 1
        from langchain_core.messages import HumanMessage
        assert isinstance(ctx.messages[0], HumanMessage)
        assert ctx.messages[0].content == "hi"
        assert ctx.sources == []

    def test_thinking_injects_system_prompt(self, feats):
        ctx = feats.prepare(history=[], request=self._request(enable_thinking=True))
        from langchain_core.messages import SystemMessage
        sys_msgs = [m for m in ctx.messages if isinstance(m, SystemMessage)]
        assert len(sys_msgs) == 1
        assert "<think>" in sys_msgs[0].content
        assert "深度思考" in sys_msgs[0].content

    def test_attachments_inject_system_message(self, feats):
        from lumen_schemas.chat import AttachmentRef
        ctx = feats.prepare(
            history=[],
            request=self._request(attachments=[
                AttachmentRef(file_id="x", name="a.txt", size=1,
                              mime_type="text/plain", content_text="BODY"),
            ]),
        )
        from langchain_core.messages import SystemMessage, HumanMessage
        assert isinstance(ctx.messages[0], SystemMessage)
        assert "BODY" in ctx.messages[0].content
        assert isinstance(ctx.messages[-1], HumanMessage)
        assert ctx.messages[-1].content == "hi"

    def test_web_search_injects_system_and_returns_sources(self, feats):
        from lumen_services.web_search.provider import SearchResult
        feats._run_web_search = MagicMock(return_value=[
            SearchResult(title="T", url="u", snippet="s"),
        ])
        ctx = feats.prepare(
            history=[],
            request=self._request(enable_web_search=True),
        )
        from langchain_core.messages import SystemMessage
        sys_msgs = [m for m in ctx.messages if isinstance(m, SystemMessage)]
        assert len(sys_msgs) == 1
        assert "T" in sys_msgs[0].content
        assert len(ctx.sources) == 1
        assert ctx.sources[0].title == "T"

    def test_history_is_appended_after_system_messages(self, feats):
        ctx = feats.prepare(
            history=[
                {"role": "user", "content": "old-q"},
                {"role": "assistant", "content": "old-a"},
            ],
            request=self._request(enable_thinking=True),
        )
        from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
        # 1 system + 1 human + 1 ai + 1 human(user message)
        assert isinstance(ctx.messages[0], SystemMessage)
        assert isinstance(ctx.messages[1], HumanMessage)
        assert isinstance(ctx.messages[2], AIMessage)
        assert isinstance(ctx.messages[3], HumanMessage)
        assert ctx.messages[1].content == "old-q"
        assert ctx.messages[2].content == "old-a"
        assert ctx.messages[3].content == "hi"

    def test_toggles_stack_in_order_attachments_then_search_then_thinking(self, feats):
        from lumen_schemas.chat import AttachmentRef
        from lumen_services.web_search.provider import SearchResult
        feats._run_web_search = MagicMock(return_value=[
            SearchResult(title="T", url="u", snippet="s"),
        ])
        ctx = feats.prepare(
            history=[],
            request=self._request(
                enable_thinking=True,
                enable_web_search=True,
                attachments=[AttachmentRef(
                    file_id="x", name="a.txt", size=1,
                    mime_type="text/plain", content_text="BODY",
                )],
            ),
        )
        from langchain_core.messages import SystemMessage
        sys_msgs = [m for m in ctx.messages if isinstance(m, SystemMessage)]
        assert len(sys_msgs) == 3
        # Verify order: attachments first, search second, thinking third
        assert "BODY" in sys_msgs[0].content
        assert "T" in sys_msgs[1].content and "[1]" in sys_msgs[1].content
        assert "深度思考" in sys_msgs[2].content

    def test_prepare_includes_kb_context_when_agent_id_provided(self, feats, monkeypatch):
        """M21: agent_id 传入时,prepare 把 KB context 塞进 system message 末尾。"""
        from lumen_services.chat_features import ChatFeatureService
        from lumen_schemas.chat import ChatRequest

        # Mock build_agent_kb_context 返固定字符串
        monkeypatch.setattr(
            "lumen_services.chat_features.build_agent_kb_context",
            lambda agent_id, query, db: "## Knowledge Context\n[Source: Test KB]\ntest content",
        )

        service = ChatFeatureService(db=None, tenant_id=1)
        request = ChatRequest(
            message="user question",
        )
        ctx = service.prepare(
            history=[],
            request=request,
            agent_id=42,
        )
        # 验证 KB context 是最后一个 system message
        from langchain_core.messages import SystemMessage
        sys_messages = [m for m in ctx.messages if isinstance(m, SystemMessage)]
        assert len(sys_messages) >= 1
        assert "Knowledge Context" in sys_messages[-1].content
        assert "[Source: Test KB]" in sys_messages[-1].content

    def test_skills_inject_first(self, feats):
        """Skills (layer 0) are prepended as the FIRST SystemMessage in
        prepare(), before attachments / web search / thinking.
        """
        from lumen_services.skill_runner import RenderedSkill, SkillRunner

        fake_skills = [
            RenderedSkill(name="代码优化专家", content="优化代码"),
            RenderedSkill(name="测试工程师", content="写测试"),
        ]
        # M16: chat_features.py now calls SkillRunner.get_active_skills
        # (class method) rather than the module-level shim, so patch the
        # class method directly. Return a (prompts, tools) tuple.
        with patch.object(
            SkillRunner, "get_active_skills", return_value=(fake_skills, [])
        ):
            ctx = feats.prepare(history=[], request=self._request(skill_ids=[11, 12]))

        from langchain_core.messages import SystemMessage, HumanMessage

        # At least 1 system + 1 user message
        assert len(ctx.messages) >= 2
        # Layer 0: the very first message is a SystemMessage
        assert isinstance(ctx.messages[0], SystemMessage)
        content = ctx.messages[0].content
        # Both skill names and contents are rendered, in input order
        assert "【技能:代码优化专家】" in content
        assert "优化代码" in content
        assert "【技能:测试工程师】" in content
        # Skills joined by the standard separator
        assert "\n\n---\n\n" in content
        # The user message is still last
        assert isinstance(ctx.messages[-1], HumanMessage)
        assert ctx.messages[-1].content == "hi"


class TestSearchStatus:
    """`PreparedContext.search_status` distinguishes 4 outcomes so the
    frontend can show the right notice when search did not return results.
    """

    def _request(self, **overrides):
        from lumen_schemas.chat import ChatRequest
        base = {"message": "hi"}
        base.update(overrides)
        return ChatRequest(**base)

    def test_disabled_when_toggle_off(self, feats):
        ctx = feats.prepare(history=[], request=self._request())
        assert ctx.search_status == "disabled"

    def test_empty_when_provider_returns_no_results(self, feats):
        feats._run_web_search = MagicMock(return_value=[])
        ctx = feats.prepare(
            history=[],
            request=self._request(enable_web_search=True),
        )
        assert ctx.search_status == "empty"
        assert ctx.sources == []

    def test_ok_when_provider_returns_results(self, feats):
        from lumen_services.web_search.provider import SearchResult
        feats._run_web_search = MagicMock(return_value=[
            SearchResult(title="T", url="u", snippet="s"),
        ])
        ctx = feats.prepare(
            history=[],
            request=self._request(enable_web_search=True),
        )
        assert ctx.search_status == "ok"
        assert len(ctx.sources) == 1

    def test_error_when_provider_raises(self, feats):
        # Drive provider to raise (not mock _run_web_search, which now
        # propagates exceptions per the new contract).
        feats._search_provider = MagicMock()
        feats._search_provider.search.side_effect = RuntimeError("ddg down")
        ctx = feats.prepare(
            history=[],
            request=self._request(enable_web_search=True),
        )
        assert ctx.search_status == "error"
        assert ctx.sources == []


class TestRunWebSearchContract:
    """Contract change: _run_web_search now propagates provider exceptions
    so prepare() can distinguish "0 results" from "errored out" via
    search_status. Callers (prepare) own the try/except.
    """

    def test_provider_failure_now_raises(self, feats):
        feats._search_provider = MagicMock()
        feats._search_provider.search.side_effect = RuntimeError("ddg down")
        with pytest.raises(RuntimeError):
            feats._run_web_search("q")
