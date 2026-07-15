"""Unit tests for ChatService.stream_chat_messages."""
import os
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))


class TestStreamChatMessages:
    @pytest.mark.asyncio
    async def test_yields_chunks_from_model_astream(self):
        """stream_chat_messages should iterate self.chat_model.astream and yield chunk.content."""
        from langchain_core.messages import HumanMessage
        from lumen_services.chat_service import ChatService

        service = ChatService()
        # Fake astream that yields 3 chunks
        async def fake_astream(messages):
            for c in ["He", "llo", "!"]:
                chunk = MagicMock()
                chunk.content = c
                yield chunk
        service.chat_model = MagicMock()
        service.chat_model.astream = fake_astream

        msgs = [HumanMessage(content="hi")]
        out = []
        async for chunk in service.stream_chat_messages(msgs):
            out.append(chunk)
        assert out == ["He", "llo", "!"]

    @pytest.mark.asyncio
    async def test_skips_chunks_with_no_content(self):
        """Some LangChain chunks have content=None (e.g. tool-call-only). Skip them."""
        from langchain_core.messages import HumanMessage
        from lumen_services.chat_service import ChatService

        service = ChatService()
        async def fake_astream(messages):
            for c in [None, "ok", ""]:
                chunk = MagicMock()
                chunk.content = c
                yield chunk
        service.chat_model = MagicMock()
        service.chat_model.astream = fake_astream

        msgs = [HumanMessage(content="hi")]
        out = [c async for c in service.stream_chat_messages(msgs)]
        assert out == ["ok"]


class TestStreamChatLegacyStillWorks:
    @pytest.mark.asyncio
    async def test_legacy_stream_chat_delegates_to_new_method(self):
        """Old stream_chat should still produce output (for agent_team backward compat).
        It must emit a DeprecationWarning inside the generator body — we verify the
        deprecation message string is in the source by introspecting.
        """
        from langchain_core.messages import HumanMessage
        from lumen_services.chat_service import ChatService
        import inspect

        service = ChatService()
        # The legacy method should call stream_chat_messages internally
        src = inspect.getsource(service.stream_chat)
        assert "deprecated" in src.lower()
        assert "stream_chat_messages" in src

        # And it should still produce output end-to-end
        async def fake_astream(messages):
            for c in ["legacy-ok"]:
                chunk = MagicMock()
                chunk.content = c
                yield chunk
        service.chat_model = MagicMock()
        service.chat_model.astream = fake_astream

        out = [c async for c in service.stream_chat(message="x", history=[], tenant_id=1)]
        assert out == ["legacy-ok"]
