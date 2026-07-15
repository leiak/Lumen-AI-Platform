"""LLM-call logging context (ContextVar-based propagation).

M26 spec: a request boundary sets the per-request trace_id + module
identifiers once (e.g. /chat/stream endpoint), and every nested
ChatModel invocation inside that request reads the context to write
its LLMCallLog row.

Pattern mirrors stdlib ``contextvars.ContextVar``: ContextVar-based
state survives async/await boundaries (LangChain's astream/ainvoke
use asyncio.Task scopes) and per-request (FastAPI runs each request
in a fresh context).

Spec: docs/superpowers/specs/2026-06-14-llm-call-logging-design.md §"插桩策略"
"""
from __future__ import annotations

from contextvars import ContextVar
from typing import Any, Dict, NamedTuple, Optional


class LLMCallContext(NamedTuple):
    """Per-LLM-call context. Read inside create_chat_model wrapper."""

    # M30 P2-5: explicit __repr__ for trace log readability.
    # Default NamedTuple repr is `LLMCallContext(call_id='…', trace_id='…',
    # parent_call_id=None, call_type='chat', call_index=0, ...)` —
    # fine, but the 17-field dump clutters dev logs when the same
    # trace_id appears across many calls. Truncate to the 4 fields
    # that matter for log scanning.
    def __repr__(self) -> str:  # type: ignore[override]
        return (
            f"LLMCallContext(call_id={self.call_id[:8]}…, "
            f"trace_id={self.trace_id[:8]}…, "
            f"call_type={self.call_type!r}, "
            f"call_index={self.call_index})"
        )

    call_id: str
    trace_id: str
    parent_call_id: Optional[str]
    call_type: str  # e.g. "chat" / "widget" / "team.manager_decision" / "workflow.llm"
    call_index: int
    # Module-specific identifiers. All optional — different modules fill
    # different subsets. The wrapper reads whatever is present.
    conversation_id: Optional[int] = None
    message_id: Optional[int] = None
    agent_id: Optional[int] = None
    team_id: Optional[int] = None
    team_member_id: Optional[int] = None
    workflow_id: Optional[int] = None
    workflow_run_id: Optional[int] = None
    workflow_node_id: Optional[str] = None
    image_id: Optional[int] = None
    tenant_id: Optional[int] = None
    user_id: Optional[int] = None
    username: Optional[str] = None
    client_app: Optional[str] = None
    request_ip: Optional[str] = None
    user_agent: Optional[str] = None
    # Free-form metadata (visitor_id, kb_ids, etc.). Stored on the row's
    # ``extra`` JSON column.
    extra: Optional[Dict[str, Any]] = None


# Default is None — outside a logged request, the wrapper simply skips
# writing any row.
_llm_call_context: ContextVar[Optional[LLMCallContext]] = ContextVar(
    "llm_call_context", default=None,
)


def set_call_context(ctx: LLMCallContext) -> Any:
    """Set the active LLM-call context. Returns a token that can be
    passed to ``reset_call_context`` for nested save/restore."""
    return _llm_call_context.set(ctx)


def reset_call_context(token: Any) -> None:
    _llm_call_context.reset(token)


def get_call_context() -> Optional[LLMCallContext]:
    return _llm_call_context.get()