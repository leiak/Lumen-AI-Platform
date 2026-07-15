"""Embedding-call logging context (ContextVar-based propagation).

M27 mirrors M26 ``llm_call_context.py``: a request boundary sets the
per-request trace_id + module identifiers once (e.g. /chat/stream
endpoint or KB reindex worker), and every nested ``embed_query`` call
inside that scope reads the context to write its EmbeddingCallLog row.

Default is ``None`` — outside a logged scope, the LoggingEmbeddings
wrapper transparently passes through to the inner Embeddings object
without writing a row. This makes the proxy safe for code paths
without explicit instrumentation (background tasks, test fixtures, etc).

Spec: docs/superpowers/specs/2026-06-15-embedding-trace-retention.md §"插桩策略"
"""
from __future__ import annotations

from contextvars import ContextVar
from typing import Any, Dict, NamedTuple, Optional


class EmbeddingCallContext(NamedTuple):
    """Per-embedding-call context. Read inside LoggingEmbeddings wrapper."""

    # M30 P2-5: see llm_call_context.py — explicit __repr__ keeps
    # dev log noise down (kb_id, kb_name, is_batch, etc. are useful
    # in DB but not in stdout). Show the 5 fields that matter.
    def __repr__(self) -> str:  # type: ignore[override]
        kb = f" kb_id={self.knowledge_base_id}" if self.knowledge_base_id else ""
        return (
            f"EmbeddingCallContext(call_id={self.call_id[:8]}…, "
            f"trace_id={self.trace_id[:8]}…, "
            f"call_type={self.call_type!r},{kb})"
        )

    call_id: str
    trace_id: str
    parent_call_id: Optional[str]
    # e.g. "kb_retrieval" / "kb_ingest" / "workflow_kb" / "system.kb_ingest"
    call_type: str
    call_index: int
    # Module-specific identifiers. All optional — different scopes fill
    # different subsets.
    tenant_id: Optional[int] = None
    user_id: Optional[int] = None
    username: Optional[str] = None
    conversation_id: Optional[int] = None
    agent_id: Optional[int] = None
    team_id: Optional[int] = None
    workflow_id: Optional[int] = None
    workflow_run_id: Optional[int] = None
    workflow_node_id: Optional[str] = None
    knowledge_base_id: Optional[int] = None
    client_app: Optional[str] = None
    request_ip: Optional[str] = None
    user_agent: Optional[str] = None
    # Free-form metadata (top_k, filter_expr, is_dim_probe).
    extra: Optional[Dict[str, Any]] = None


_embedding_context: ContextVar[Optional[EmbeddingCallContext]] = ContextVar(
    "embedding_call_context", default=None,
)


def set_embedding_context(ctx: EmbeddingCallContext) -> Any:
    """Set the active embedding-call context. Returns a token that can be
    passed to ``reset_embedding_context`` for nested save/restore."""
    return _embedding_context.set(ctx)


def reset_embedding_context(token: Any) -> None:
    _embedding_context.reset(token)


def get_embedding_context() -> Optional[EmbeddingCallContext]:
    return _embedding_context.get()
