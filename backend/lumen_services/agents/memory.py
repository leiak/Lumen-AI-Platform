"""Memory policy registry for the agent run path.

Each agent can choose one of several memory strategies that decide what
slice of the conversation history is forwarded to the LLM on a given turn:

    * NONE                 -> no history at all (only the system prompt + current message)
    * SLIDING_WINDOW       -> keep the last N user/assistant turns (default)
    * TOKEN_LIMIT          -> keep dropping the oldest messages until the
                              approximate token count is below the limit
    * SEMANTIC_COMPRESSION -> summarize older turns into a single "memory"
                              message, then keep the last N turns verbatim

The functions here work on plain Python dicts of the form
``{"role": "user" | "assistant" | "system", "content": str}`` — exactly the
shape produced by ``ChatMessage.model_dump()`` in
``backend/app/schemas/agent.py``. The agent run path is responsible for
converting these to LangChain message objects afterwards.

The public surface is intentionally small so the rest of the codebase can
import the policy without depending on LangChain types.
"""
from __future__ import annotations

import logging
from enum import Enum
from typing import Any, Dict, List, Mapping, Optional, Sequence

logger = logging.getLogger(__name__)


# A minimal alias to make type hints readable.
MessageDict = Dict[str, str]


class MemoryPolicy(str, Enum):
    """Per-agent memory policy."""

    NONE = "none"
    SLIDING_WINDOW = "sliding_window"
    TOKEN_LIMIT = "token_limit"
    SEMANTIC_COMPRESSION = "semantic_compression"

    @classmethod
    def all(cls) -> List[str]:
        return [p.value for p in cls]

    @classmethod
    def coerce(cls, value: Optional[str]) -> "MemoryPolicy":
        """Best-effort coercion from DB / JSON values.

        Accepts the enum's own ``value`` strings, the enum name, or None.
        Unknown values fall back to ``SLIDING_WINDOW`` to keep the agent
        runnable.
        """
        if value is None or value == "":
            return cls.SLIDING_WINDOW
        if isinstance(value, cls):
            return value
        s = str(value).strip().lower()
        for p in cls:
            if s == p.value or s == p.name.lower():
                return p
        logger.warning("Unknown memory policy %r; defaulting to sliding_window", value)
        return cls.SLIDING_WINDOW


# Approximate token counter. We avoid pulling in tiktoken here (extra dep)
# and just use the common "4 chars ≈ 1 token" heuristic, which is good
# enough to keep the LLM context within budget.
def _approx_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, len(text) // 4)


def _filter_valid(messages: Sequence[Mapping[str, Any]]) -> List[MessageDict]:
    """Keep only messages that look like valid chat dicts."""
    out: List[MessageDict] = []
    for m in messages or []:
        if not isinstance(m, Mapping):
            continue
        role = m.get("role")
        content = m.get("content")
        if role not in ("user", "assistant", "system") or content is None:
            continue
        out.append({"role": role, "content": str(content)})
    return out


def _sliding_window(messages: List[MessageDict], window: int) -> List[MessageDict]:
    """Keep the last ``window`` user/assistant turns.

    A "turn" is one user message + one assistant reply, so we approximate
    by counting messages and dropping from the head in pairs when the
    conversation starts with a user message.
    """
    if window is None or window <= 0 or len(messages) <= window:
        return list(messages)
    return list(messages[-window:])


def _token_limit(messages: List[MessageDict], max_tokens: int) -> List[MessageDict]:
    """Drop oldest messages until total tokens <= max_tokens.

    Always keeps the most recent message (the one we're replying to).
    """
    if not messages or max_tokens is None or max_tokens <= 0:
        return list(messages)
    total = sum(_approx_tokens(m["content"]) for m in messages)
    if total <= max_tokens:
        return list(messages)
    # Drop from the head until under budget; always keep the last message.
    kept = list(messages)
    while len(kept) > 1:
        head = kept[0]
        head_tokens = _approx_tokens(head["content"])
        if total - head_tokens <= max_tokens:
            break
        kept.pop(0)
        total -= head_tokens
    return kept


def _summarize_old(
    messages: List[MessageDict],
    summarizer: Optional[Any] = None,
) -> MessageDict:
    """Best-effort summarization of older turns.

    If no ``summarizer`` is provided (or it raises), returns a single
    condensed "memory" message that concatenates truncated snippets.
    """
    if not messages:
        return {"role": "system", "content": "[memory] (empty)"}
    if summarizer is None:
        # No LLM available; produce a simple compressed "memory" message
        # by concatenating short previews. This is enough to keep the
        # policy meaningful even without a chat model call.
        snippets = []
        for m in messages:
            preview = (m.get("content") or "").strip().replace("\n", " ")
            if len(preview) > 80:
                preview = preview[:77] + "..."
            snippets.append(f"{m['role']}: {preview}")
        body = " | ".join(snippets)
        return {"role": "system", "content": f"[memory] {body}"}

    try:
        text = summarizer(messages)
        if not text:
            raise RuntimeError("empty summary")
        return {"role": "system", "content": f"[memory] {text}"}
    except Exception as exc:  # noqa: BLE001
        logger.warning("semantic_compression summarizer failed: %s", exc)
        return _summarize_old(messages, summarizer=None)


def apply_memory_policy(
    messages: Optional[Sequence[Mapping[str, Any]]],
    policy: Optional[str],
    *,
    window_size: Optional[int] = None,
    max_tokens: Optional[int] = None,
    compression: Optional[bool] = None,
    summarizer: Optional[Any] = None,
) -> List[MessageDict]:
    """Apply a memory policy to a chat history and return the kept messages.

    Parameters
    ----------
    messages:
        The full chat history (most recent last). May be None.
    policy:
        One of the values in :class:`MemoryPolicy` (str/enum/None).
    window_size:
        For ``sliding_window`` / ``semantic_compression``: how many of the
        most-recent messages to keep verbatim.
    max_tokens:
        For ``token_limit``: approximate token budget.
    compression:
        For ``semantic_compression``: if true, summarize the older portion.
    summarizer:
        Optional callable ``(messages) -> str`` used to compress the
        older history. If not provided we use a deterministic fallback
        so the policy is still observable in tests.
    """
    msgs = _filter_valid(messages or [])
    pol = MemoryPolicy.coerce(policy)

    if pol == MemoryPolicy.NONE:
        return []

    if pol == MemoryPolicy.SLIDING_WINDOW:
        return _sliding_window(msgs, window_size if window_size is not None else 20)

    if pol == MemoryPolicy.TOKEN_LIMIT:
        limit = max_tokens if max_tokens is not None else 4000
        return _token_limit(msgs, limit)

    if pol == MemoryPolicy.SEMANTIC_COMPRESSION:
        window = window_size if window_size is not None else 20
        if not compression:
            # Compression disabled -> behave like sliding_window
            return _sliding_window(msgs, window)
        if len(msgs) <= window:
            return list(msgs)
        older = msgs[:-window]
        recent = msgs[-window:]
        memory_msg = _summarize_old(older, summarizer=summarizer)
        return [memory_msg, *recent]

    # Defensive fallback — should not be reachable because ``coerce``
    # defaults to SLIDING_WINDOW for unknown values.
    return list(msgs)


def summarize_for_compression(
    db_session: Any,
    agent: Any,
    messages: Sequence[Mapping[str, Any]],
) -> str:
    """Optional LLM-backed summarizer used by SEMANTIC_COMPRESSION.

    Tries to use the agent's own model to compress the older messages
    into a short paragraph. Returns the LLM text on success, or raises
    on failure (caller falls back to the deterministic summarizer).
    """
    # Imported lazily to avoid a hard dependency at module import time.
    from lumen_services.model_loader import create_chat_model
    from langchain_core.messages import HumanMessage, SystemMessage

    if not messages:
        return ""

    convo = "\n".join(
        f"{m['role']}: {m['content']}" for m in messages if m.get("content")
    )
    system = (
        "You are a memory compressor. Summarize the following conversation "
        "into a concise paragraph (max 6 sentences) that preserves any "
        "facts, decisions, or commitments that may matter later."
    )
    prompt = f"Conversation to compress:\n{convo}\n\nCompressed memory:"

    model_config = None
    if hasattr(agent, "_get_model_config"):
        model_config = agent._get_model_config(db_session, agent.model_name, agent.tenant_id)
    if not model_config or not model_config.base_url or not model_config.api_key:
        raise RuntimeError("no usable model config for summarizer")

    llm = create_chat_model(
        model_type=model_config.model_type,
        model_name=agent.model_name,
        base_url=model_config.base_url.strip() if model_config.base_url else None,
        api_key=model_config.api_key,
        temperature=0,
        timeout=model_config.timeout,
    )
    response = llm.invoke(
        [SystemMessage(content=system), HumanMessage(content=prompt)]
    )
    return (response.content or "").strip()
