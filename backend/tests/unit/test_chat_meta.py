"""Unit tests for chat.py's assistant-message metadata assembly.

The /chat/stream endpoint persists a small JSON object into
`messages.msg_metadata`. The shape of that object is the contract
the frontend depends on for citations and the search-failure notice,
so it must be tested directly.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))


class TestBuildAssistantMeta:
    def _ctx(self, sources=None, search_status="disabled", skill_names=None):
        from lumen_services.chat_features import PreparedContext
        return PreparedContext(
            messages=[], sources=sources or [], search_status=search_status,
            skill_names=skill_names or [],
        )

    def _request(self, **overrides):
        from lumen_schemas.chat import ChatRequest
        base = {"message": "hi"}
        base.update(overrides)
        return ChatRequest(**base)

    def test_returns_empty_dict_when_no_features_used(self):
        from lumen_api.v1.chat import _build_assistant_meta
        meta = _build_assistant_meta(
            ctx=self._ctx(),
            request=self._request(),
        )
        assert meta == {}

    def test_writes_search_status_when_toggle_on(self):
        from lumen_api.v1.chat import _build_assistant_meta
        meta = _build_assistant_meta(
            ctx=self._ctx(search_status="empty"),
            request=self._request(enable_web_search=True),
        )
        assert meta["search_status"] == "empty"

    def test_omits_search_status_when_toggle_off(self):
        from lumen_api.v1.chat import _build_assistant_meta
        meta = _build_assistant_meta(
            ctx=self._ctx(search_status="ok"),
            request=self._request(),  # enable_web_search default False
        )
        assert "search_status" not in meta

    def test_writes_sources_normalized_to_dicts(self):
        from lumen_api.v1.chat import _build_assistant_meta
        from lumen_services.web_search.provider import SearchResult

        sources = [
            SearchResult(title="T1", url="https://a", snippet="S1"),
        ]
        meta = _build_assistant_meta(
            ctx=self._ctx(sources=sources),
            request=self._request(enable_web_search=True),
        )
        # SearchResult is a dataclass — must be converted to dict so
        # json.dumps works (it would raise on dataclass instances).
        assert meta["sources"] == [{"title": "T1", "url": "https://a", "snippet": "S1"}]
        assert meta["search_status"] == "disabled"  # default ctx

    def test_writes_skill_names_when_present(self):
        from lumen_api.v1.chat import _build_assistant_meta
        meta = _build_assistant_meta(
            ctx=self._ctx(skill_names=["SQL 专家", "周报生成助手"]),
            request=self._request(),
        )
        assert meta["skills"] == ["SQL 专家", "周报生成助手"]

    def test_omits_skills_when_empty(self):
        from lumen_api.v1.chat import _build_assistant_meta
        meta = _build_assistant_meta(
            ctx=self._ctx(skill_names=[]),
            request=self._request(),
        )
        assert "skills" not in meta


class TestBuildDoneEvent:
    """The final SSE event of /chat/stream carries the assistant
    metadata so the frontend can patch its local message state without
    a DB re-fetch. The frontend MessageBubble reads `search_status` /
    `sources` off `message.metadata`; if those aren't in the live state,
    the user never sees the "search failed" notice.
    """

    def test_carries_search_status_when_present(self):
        from lumen_api.v1.chat import _build_done_event
        ev = _build_done_event(
            assistant_meta={"search_status": "empty"},
            conversation_id=42,
        )
        assert ev["done"] is True
        assert ev["conversation_id"] == 42
        assert ev["search_status"] == "empty"
        assert ev["content"] == ""

    def test_carries_sources_when_present(self):
        from lumen_api.v1.chat import _build_done_event
        meta = {
            "sources": [{"title": "T", "url": "u", "snippet": "s"}],
        }
        ev = _build_done_event(assistant_meta=meta, conversation_id=1)
        assert ev["sources"] == [{"title": "T", "url": "u", "snippet": "s"}]

    def test_omits_keys_when_meta_empty(self):
        from lumen_api.v1.chat import _build_done_event
        ev = _build_done_event(assistant_meta={}, conversation_id=1)
        assert "search_status" not in ev
        assert "sources" not in ev
        assert "skills" not in ev
        # The base payload keys are still there.
        assert ev == {"content": "", "done": True, "conversation_id": 1}

    def test_carries_skills_when_present(self):
        from lumen_api.v1.chat import _build_done_event
        ev = _build_done_event(
            assistant_meta={"skills": ["SQL 专家"]},
            conversation_id=1,
        )
        assert ev["skills"] == ["SQL 专家"]
