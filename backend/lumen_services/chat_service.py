from typing import AsyncGenerator, Optional, List, Dict, Any
import json
import logging
import uuid
import warnings
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langchain_ollama import ChatOllama
from lumen_core.config import settings
from lumen_core.llm_call_context import LLMCallContext, set_call_context, reset_call_context
from lumen_services.model_loader import create_chat_model

logger = logging.getLogger(__name__)


class ChatService:
    def __init__(self):
        model_name = getattr(settings, "CHAT_MODEL", "qwen2.5:7b")
        self.chat_model = ChatOllama(model=model_name)

    def set_model(
        self,
        model_type: str = "ollama",
        model_name: str = "qwen2.5:7b",
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        temperature: float = 0.7,
        timeout: int = 120,
    ):
        """Set the chat model based on configuration."""
        self.chat_model = create_chat_model(
            model_type=model_type,
            model_name=model_name,
            base_url=base_url,
            api_key=api_key,
            temperature=temperature,
            timeout=timeout,
        )

    async def stream_chat_messages(
        self,
        messages: List[Any],
        tools: Optional[List[Any]] = None,
    ) -> AsyncGenerator[str, None]:
        """Stream LLM tokens for a fully-constructed messages list.

        Use this from /chat/stream after ChatFeatureService.prepare() has
        assembled system + history + user messages. It does not know about
        features, history, or agents — that's the caller's job.

        M16: if `tools` is non-empty, binds them to the chat model for
        function calling. When the LLM emits tool_calls, executes them
        (cap: 5 rounds) and re-invokes with the results, then streams
        the final response. Tools are LangChain BaseTool instances from
        SkillRunner.get_active_skills(...).tools.

        When `tools` is None (no tool calling needed), falls back to the
        original `astream` token-streaming path for backward compat.
        """
        # M16 tool calling path: only when tools are provided
        if tools:
            chat_model = self.chat_model.bind_tools(tools)
            try:
                max_tool_rounds = 5
                current_messages = list(messages)
                from langchain_core.messages import ToolMessage
                response = None
                for _ in range(max_tool_rounds + 1):
                    response = chat_model.invoke(current_messages)

                    tool_calls = getattr(response, "tool_calls", None) or []
                    if not tool_calls:
                        content = getattr(response, "content", "") or ""
                        if content:
                            yield content
                        return

                    for tool_call in tool_calls:
                        tool_name = tool_call.get("name") if isinstance(tool_call, dict) else getattr(tool_call, "name", None)
                        tool_args = tool_call.get("args") if isinstance(tool_call, dict) else getattr(tool_call, "args", {}) or {}
                        tool_id = tool_call.get("id") if isinstance(tool_call, dict) else getattr(tool_call, "id", None)
                        tool = next((t for t in tools if t.name == tool_name), None) if tools else None
                        if tool is None:
                            tool_result = f"Tool {tool_name} not found"
                        else:
                            try:
                                tool_result = tool.run(tool_args)
                            except Exception as e:
                                tool_result = f"Tool error: {e}"
                        current_messages.append(ToolMessage(
                            content=str(tool_result),
                            tool_call_id=tool_id or "",
                        ))

                # Max rounds exceeded
                if response is not None:
                    content = getattr(response, "content", "") or ""
                    if content:
                        yield content
            except Exception as e:
                logger.error("LLM streaming error: %s", e)
                yield f"Error: {str(e)}"
            return

        # Original token-streaming path (no tools, backward compat)
        try:
            async for chunk in self.chat_model.astream(messages):
                if chunk.content:
                    yield chunk.content
        except Exception as e:
            logger.error("LLM streaming error: %s", e)
            yield f"Error: {str(e)}"

    async def stream_chat(
        self,
        message: str,
        history: List[Dict[str, str]],
        tenant_id: int,
        agent_id: Optional[int] = None,
    ) -> AsyncGenerator[str, None]:
        """DEPRECATED: kept for backward compatibility with agent_team / etc.

        New code should call stream_chat_messages with pre-built messages
        from ChatFeatureService.prepare().
        """
        warnings.warn(
            "ChatService.stream_chat is deprecated; use stream_chat_messages "
            "with ChatFeatureService-prepared messages",
            DeprecationWarning,
            stacklevel=2,
        )
        msgs: List[Any] = []
        for h in history:
            if h.get("role") == "user":
                msgs.append(HumanMessage(content=h.get("content", "")))
            else:
                msgs.append(AIMessage(content=h.get("content", "")))
        msgs.append(HumanMessage(content=message))
        async for chunk in self.stream_chat_messages(msgs):
            yield chunk

    # ----- External (widget) chat — mirrors /chat/stream but binds
    #       the conversation to an ExternalApp + ExternalVisitor instead
    #       of a User. SSE event schema is identical (see _build_done_event
    #       in api/v1/chat.py:69). The conversation is supplied by the
    #       caller (the endpoint resolved / created it via
    #       get_or_create_external_conversation).

    async def stream_for_external(
        self,
        ctx,  # ExternalAppContext — type hinted as a string to avoid circular import (see deps.py)
        req,  # ExternalChatRequest — same reason
    ):
        """Async generator that yields raw SSE ``data: ...\\n\\n`` strings.

        Mirrors the structure of /chat/stream's inner generate() (see
        api/v1/chat.py:168) but with no user-bound fetches; the
        conversation is already loaded by the caller.

        Cross-module import from ``app.api.v1.chat`` for
        ``_build_assistant_meta`` and ``_build_done_event`` is a known
        code smell (service layer -> API layer) — a future refactor could
        move these helpers to a shared module (e.g.
        ``app/services/sse_events.py``). The MVP path doesn't use
        ``_build_assistant_meta``; we still import it so future web
        search / RAG wiring lands in one place.
        """
        from lumen_core.database import SessionLocal
        from lumen_models.chat import Conversation, Message as MessageModel
        from lumen_models.agent import Agent
        from lumen_models.model_config import ModelConfig
        from lumen_api.v1.chat import _build_assistant_meta, _build_done_event
        from lumen_services.memory_service import memory_service
        # ``memory_service`` and ``_build_assistant_meta`` are imported
        # for future use (web search + memory persistence parity with
        # /chat/stream); the MVP path doesn't invoke them.

        # Open a fresh session so the async generator's lifetime is
        # decoupled from the request's DB session.
        db = SessionLocal()
        try:
            conv = db.get(Conversation, req.conversation_id)
            if conv is None:
                yield f"data: {json.dumps({'content': 'conversation not found', 'done': True}, ensure_ascii=False)}\n\n"
                return

            # Persist the user message
            user_msg = MessageModel(
                conversation_id=conv.id, role="user", content=req.message
            )
            db.add(user_msg)
            db.commit()

            # Build history for the LLM
            history = [
                {"role": m.role, "content": m.content}
                for m in db.query(MessageModel)
                .filter(MessageModel.conversation_id == conv.id)
                .order_by(MessageModel.created_at.asc()).all()
            ][:-1]  # exclude the just-added user msg

            # Resolve the model from the bound agent (or tenant default)
            model_type = "ollama"
            model_name = "qwen2.5:7b"
            base_url = None
            api_key = None
            temperature = 0.7
            agent = None  # initialize so the M16 system-prompt block can safely read it
            if conv.agent_id:
                agent = db.get(Agent, conv.agent_id)
                if agent:
                    model_name = agent.model_name or model_name
                    # Agent.temperature is Integer; ensure proper type handling for float
                    temperature = float(agent.temperature) if agent.temperature is not None else 0.7
                    cfg = db.query(ModelConfig).filter(
                        ModelConfig.tenant_id == ctx.tenant_id,
                        ModelConfig.model_name == model_name,
                    ).first()
                    if cfg:
                        model_type = cfg.model_type or model_type
                        base_url = cfg.base_url
                        api_key = cfg.api_key
            self.set_model(
                model_type=model_type, model_name=model_name,
                base_url=base_url, api_key=api_key, temperature=temperature,
            )

            # Stream
            full = ""
            try:
                # M16 (2026-06-10): inject the agent's prompt_template as a
                # system message so widget conversations actually use the
                # configured role. Skipped when the agent is unbound, the
                # template is empty, or it's whitespace-only — those three
                # branches are covered by regression tests in
                # tests/unit/test_external_chat_service.py.
                system_messages: list[dict] = []
                if agent and agent.prompt_template and agent.prompt_template.strip():
                    system_messages.append({"role": "system", "content": agent.prompt_template})

                # M21 (2026-06-11): widget KB RAG context — mirror the
                # /chat/stream path's step 4 inline because the widget path
                # does not go through ChatFeatureService.prepare() (it
                # builds its own system_messages block above). When the
                # bound agent has active KBs, fetch top-k chunks via
                # RRF fusion and append a markdown block to the system
                # messages. ``build_agent_kb_context`` returns None when
                # the agent has no active KBs or all KBs returned 0
                # chunks — same as the /chat/stream step 4 contract.
                if conv.agent_id:
                    from lumen_services.agent_rag import build_agent_kb_context
                    kb_context = build_agent_kb_context(
                        conv.agent_id, req.message, db,
                    )
                    if kb_context:
                        system_messages.append(
                            {"role": "system", "content": kb_context}
                        )

                llm_messages = system_messages + history + [{"role": "user", "content": req.message}]
                # M26: set an LLMCallContext for the widget stream so the
                # LoggingChatModel wrapper writes one row to llm_call_logs.
                # External chats have no user_id (visitor_id goes in
                # ctx.extra), so we leave user_id NULL and rely on tenant_id.
                ctx_token = set_call_context(LLMCallContext(
                    call_id=str(uuid.uuid4()),
                    trace_id=str(uuid.uuid4()),
                    parent_call_id=None,
                    call_type="widget",
                    call_index=0,
                    tenant_id=ctx.tenant_id,
                    conversation_id=conv.id,
                    agent_id=conv.agent_id,
                    client_app="widget",
                    extra={"visitor_id": ctx.visitor_id},
                ))
                try:
                    async for chunk in self.stream_chat_messages(llm_messages):
                        full += chunk
                        yield f"data: {json.dumps({'content': chunk, 'done': False}, ensure_ascii=False)}\n\n"
                except Exception as e:
                    yield f"data: {json.dumps({'content': f'LLM error: {e}', 'done': True}, ensure_ascii=False)}\n\n"
                    return
                finally:
                    reset_call_context(ctx_token)
            except Exception as e:
                # Catch-all for the message-building section (system_messages
                # construction, KB context, model resolution) — keep the
                # SSE stream alive with a friendly error event.
                yield f"data: {json.dumps({'content': f'LLM error: {e}', 'done': True}, ensure_ascii=False)}\n\n"
                return

            # Persist assistant
            assistant_msg = MessageModel(
                conversation_id=conv.id, role="assistant", content=full,
            )
            db.add(assistant_msg)
            db.commit()

            # done event (no search_status / sources in MVP external path)
            done = _build_done_event({}, conv.id)
            yield f"data: {json.dumps(done, ensure_ascii=False)}\n\n"
        finally:
            db.close()
