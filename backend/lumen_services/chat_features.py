"""Chat feature preprocessing pipeline.

Sits in front of ChatService.stream_chat_messages. Layers four optional
system prompts onto the messages list before the LLM sees it:

    1. Skills (if any)             — installed per-tenant skills
    2. Attachments (if any)         — user-uploaded file contents
    3. Web search results (if on)  — top-5 from the configured provider
    4. Deep thinking (if on)       — system prompt asking for <think> blocks

Each layer is independent and degrades silently on failure.
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from lumen_schemas.chat import AttachmentRef, ChatRequest, Message as MessageSchema
from lumen_services.agent_rag import build_agent_kb_context
from lumen_services.web_search import (
    SearchResult,
    WebSearchProvider,
    get_web_search_provider,
)
from lumen_services import skill_runner
from lumen_services.skill_runner import SkillRunner
from lumen_models.user import User

logger = logging.getLogger(__name__)


THINKING_SYSTEM_PROMPT = """\
请以"深度思考"模式回答:先在 <think>...</think> 块中写出完整的分析步骤、\
推理链和可能的反例,然后再给出最终答案。think 块中的内容对用户可见,\
请用清晰、有条理的中文表述。"""


class PreparedContext(BaseModel):
    """Result of ChatFeatureService.prepare().

    The caller (/chat/stream) uses `messages` to drive the LLM and
    `sources` + `search_status` to write the assistant message's
    msg_metadata. `search_status` lets the frontend surface a notice
    when web search was on but produced no usable results.
    `skill_names` lists the marketplace display names of installed
    skills that were applied to this request.
    """

    messages: List[BaseMessage] = Field(default_factory=list)
    sources: List[SearchResult] = Field(default_factory=list)
    search_status: str = "disabled"  # disabled | ok | empty | error
    # M16: tools (LangChain BaseTool) for non-prompt skills
    # (script / http / etc.). chat_service.py binds these to the LLM
    # for function calling (per M16 §3.3 tool calling integration).
    tools: List = Field(default_factory=list)
    # Names of installed marketplace skills applied to this request,
    # in the same order as the skill_ids in the request.
    skill_names: List[str] = Field(default_factory=list)

    class Config:
        arbitrary_types_allowed = True


class ChatFeatureService:
    def __init__(
        self,
        db: Optional[Session],
        tenant_id: int,
        user: Optional[User] = None,
    ):
        self.db = db
        self.tenant_id = tenant_id
        # M38.2.x v2: 透传到 build_agent_kb_context 做 per-KB RBAC 过滤;
        # ``None`` 保留 pre-M38.2 行为(widget visitor / cron / fixture)。
        self.user = user
        self._search_provider: WebSearchProvider = get_web_search_provider()

    def prepare(
        self,
        history: List[Dict[str, str]],
        request: ChatRequest,
        *,  # M21: keyword-only
        agent_id: Optional[int] = None,
    ) -> PreparedContext:
        system_messages: List[BaseMessage] = []
        tools: List = []  # M16: populated by SkillRunner, bound to LLM in chat_service
        skill_names: List[str] = []  # Marketplace display names of applied skills

        # 0) Installed skills (per-message selection). Goes FIRST so the
        # persona is established before attachments / search / thinking.
        # M16: SkillRunner returns (prompts, tools) tuple. Prompts go into
        # the system message; tools are surfaced via PreparedContext for
        # chat_service.py to bind_tools() and enable function calling.
        if request.skill_ids:
            prompts, tools = SkillRunner.get_active_skills(
                self.db, self.tenant_id, request.skill_ids
            )
            skill_names = [p.name for p in prompts]
            if prompts:
                system_messages.append(
                    SystemMessage(content=self._render_skill_block(prompts))
                )

        # 1) Attachments
        if request.attachments:
            text = self._render_attachments(request.attachments)
            if text:
                system_messages.append(SystemMessage(content=text))

        # 2) Web search
        sources: List[SearchResult] = []
        search_status: str = "disabled"
        if request.enable_web_search:
            try:
                results = self._run_web_search(request.message)
            except Exception as e:  # noqa: BLE001
                logger.warning("Web search provider error: %s", e)
                results = []
                search_status = "error"
            else:
                if results:
                    sources = list(results)
                    rendered = self._render_search_results(results)
                    if rendered:
                        system_messages.append(SystemMessage(content=rendered))
                    search_status = "ok"
                else:
                    search_status = "empty"

        # 3) Deep thinking
        if request.enable_thinking:
            system_messages.append(SystemMessage(content=THINKING_SYSTEM_PROMPT))

        # 4) M21: Agent KB RAG context — append LAST so it sits right
        # before the user message (per spec §6.2 position decision).
        # M38.2.x v2: 透传 self.user 做 per-KB ``kb.read`` 过滤。
        if agent_id is not None:
            kb_context = build_agent_kb_context(
                agent_id, request.message, self.db, user=self.user,  # type: ignore[arg-type]
            )
            if kb_context:
                system_messages.append(SystemMessage(content=kb_context))

        # Assemble final messages
        messages: List[BaseMessage] = list(system_messages)
        for h in history:
            role = h.get("role")
            content = h.get("content", "")
            if role == "user":
                messages.append(HumanMessage(content=content))
            elif role == "assistant":
                messages.append(AIMessage(content=content))
            # "system" history entries are dropped — we only inject our own
        messages.append(HumanMessage(content=request.message))

        return PreparedContext(
            messages=messages, sources=sources, search_status=search_status,
            tools=tools, skill_names=skill_names,
        )

    # —— Internal helpers (public for unit testing) ——

    @staticmethod
    def _render_skill_block(skills: list[skill_runner.RenderedSkill]) -> str:
        """Render a list of RenderedSkill into one system message body.

        Format: each skill wrapped in 【技能:{name}】, joined by
        ``\\n\\n---\\n\\n`` (matches _render_attachments). Order is
        whatever SkillRunner returned (stable by Skill.id ASC).
        """
        blocks = [f"【技能:{s.name}】\n{s.content}" for s in skills]
        return "\n\n---\n\n".join(blocks)

    def _render_attachments(self, atts: List[AttachmentRef]) -> str:
        blocks = []
        for a in atts:
            blocks.append(
                f"【附件:{a.name} ({a.mime_type}, {a.size} bytes)】\n{a.content_text}"
            )
        return (
            "以下是用户随消息上传的附件内容,请在回答中参考这些信息。\n\n"
            + "\n\n---\n\n".join(blocks)
        )

    def _run_web_search(self, query: str) -> List[SearchResult]:
        # Provider exceptions propagate. prepare() catches and sets
        # search_status="error" so the frontend can show a notice.
        return self._search_provider.search(query, max_results=5)

    @staticmethod
    def _render_search_results(results: List[SearchResult]) -> str:
        if not results:
            return ""
        lines = ["联网搜索结果(供参考,回答时用 [1] [2] 等编号引用):", ""]
        for i, r in enumerate(results, 1):
            lines.append(f"[{i}] {r.title}")
            lines.append(f"    URL: {r.url}")
            lines.append(f"    摘要: {r.snippet}")
            lines.append("")
        return "\n".join(lines)
