"""Agent RAG context builder.

M21: per-KB top-k similarity_search → RRF fusion → markdown context.

Sync (matches existing AgentService.chat). Per-KB failures degrade
silently (log warning, skip). KB search_weights are NOT used here —
those are for RetrievalPipeline. We use plain vector_store.similarity_search.

M27: when called inside a ``/chat/stream`` request, the embedding
context is already set (the endpoint installs one when the trace_id is
generated). When called from a code path that hasn't set one (e.g.
direct dashboard probe), we install a fresh context so KB retrieval
embedding calls still get logged.

M27.1 (2026-06-15): fixed ContextVar propagation across the
per-KB ThreadPoolExecutor. ``contextvars`` don't auto-propagate to
worker threads in stdlib executors; we capture the parent context
with ``copy_context().run(...)`` so each per-KB thread sees the
active EmbeddingCallContext (otherwise the LoggingEmbeddings wrapper
in each thread is transparent and writes zero rows).
"""
from __future__ import annotations

import logging
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from lumen_core.embedding_call_context import (
    EmbeddingCallContext,
    get_embedding_context,
    set_embedding_context,
    reset_embedding_context,
)
from lumen_models.agent import Agent
from lumen_models.knowledge import KnowledgeBase
from lumen_tools.vector_store_factory import VectorStoreFactory

logger = logging.getLogger(__name__)


def _rrf_fuse(
    per_kb_chunks: Dict[int, List[Any]],
    rrf_k: int = 30,
    top_n: int = 10,
) -> List[Any]:
    """Reciprocal Rank Fusion across KBs.

    Each chunk is a dict (per VectorStoreBase.similarity_search contract) with
    a unique `"id"` key (str). Returns top_n chunks sorted by fused RRF
    score desc.
    """
    scores: Dict[str, float] = {}
    chunks_by_id: Dict[str, Any] = {}
    for kb_id, chunks in per_kb_chunks.items():
        for rank, chunk in enumerate(chunks, 1):
            cid = chunk["id"]
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (rrf_k + rank)
            if cid not in chunks_by_id:
                chunks_by_id[cid] = chunk
    sorted_ids = sorted(scores.keys(), key=lambda cid: scores[cid], reverse=True)
    return [chunks_by_id[cid] for cid in sorted_ids[:top_n]]


def _retrieve_kb_chunks_with_ctx(
    parent_ctx,
    kb: KnowledgeBase,
    query: str,
    top_k: int,
    tenant_id: int,
    db: Session,
) -> List[Any]:
    """M27.1: ThreadPoolExecutor worker wrapper.

    Stdlib executors don't propagate the parent's ContextVar to
    workers. Rather than wrestle with ``contextvars.copy_context()``
    (which has re-entrancy issues across multiple submits), we pass
    the EmbeddingCallContext as a regular arg and install it
    locally for the duration of the retrieval. Inside, the existing
    ``_retrieve_kb_chunks`` refines it with the per-KB
    ``knowledge_base_id`` and runs as before.
    """
    token = None
    if parent_ctx is not None:
        token = set_embedding_context(parent_ctx)
    try:
        return _retrieve_kb_chunks(
            kb, query, top_k, tenant_id, db,  # type: ignore[arg-type]
        )
    finally:
        if token is not None:
            reset_embedding_context(token)


def _retrieve_kb_chunks(
    kb: KnowledgeBase, query: str, top_k: int, tenant_id: int, db: Session
) -> List[Any]:
    """Retrieve top_k chunks for a single KB. Returns [] on any failure (graceful).

    M27: this is the inner loop that issues the actual ``embed_query``
    via the LoggingEmbeddings proxy. We refine the per-call context's
    ``knowledge_base_id`` field so the row points at the specific KB
    being searched (the outer ``build_agent_kb_context`` only knows
    the agent, not which of its bound KBs).
    """
    # Best-effort: tag the embedding row with this specific KB id.
    # The outer caller already set the context with agent_id/tenant_id,
    # but knowledge_base_id is per-KB. If no context is set, skip — the
    # wrapper will just no-op the row.
    ctx = get_embedding_context()
    own_token = None
    if ctx is not None:
        own_token = set_embedding_context(ctx._replace(
            call_id=str(uuid.uuid4()),
            knowledge_base_id=kb.id,  # type: ignore[arg-type]
            extra={**(ctx.extra or {}), "kb_name": kb.name},
        ))
    try:
        store = VectorStoreFactory.get_store(
            kb.id,  # type: ignore[arg-type]
            kb.embedding_model_config_id,  # type: ignore[arg-type]
            db,
        )
        chunks = store.similarity_search(
            query,
            k=top_k,
            filter_expr=f"tenant_id == {tenant_id} and kb_id == {kb.id}",
        )
        return chunks or []
    except Exception as e:  # noqa: BLE001
        logger.warning("KB %s retrieval failed: %s", kb.id, e)
        return []
    finally:
        if own_token is not None:
            reset_embedding_context(own_token)


def _render_context_markdown(
    chunks: List[Any],
    kbs: List[KnowledgeBase],
    kb_id_to_name: Dict[int, str],
) -> str:
    """Render fused chunks into markdown string for LLM system prompt.

    M31: Q&A entries (FAQ) carry ``source_type="faq"`` in their
    chunk metadata and get a distinct source label
    (``Q&A: <category>``) so the LLM can tell a hand-curated
    Q&A hit from a generic document chunk. The category falls
    back to "未分类" if the entry was created without one.
    """
    if not chunks:
        return ""
    n_kbs = len(
        {
            (c.get("metadata") or {}).get("kb_id")
            for c in chunks
            if c.get("metadata")
        }
    )
    n_kbs = n_kbs or len(kbs)
    lines = [
        "## Knowledge Context",
        f"The following context was retrieved from {n_kbs} knowledge base(s):",
        "",
    ]
    for chunk in chunks:
        # 从 chunk metadata 取 kb_id 和 doc info
        meta = chunk.get("metadata") or {}
        kb_id = meta.get("kb_id")
        kb_name = kb_id_to_name.get(kb_id, "Unknown KB")  # type: ignore[arg-type]
        # M31: branch on source_type. FAQ hits get
        # ``[Source: <KB> | Q&A: <category>] <question preview>``
        # — the preview is the first 30 chars of the question,
        # which the FAQService writes into chunk_metadata at
        # create time. Document hits keep the legacy
        # ``Document: <filename> | Chunk #<idx>`` shape so
        # any existing test / prompt relying on it is
        # unaffected.
        if meta.get("source_type") == "faq":
            category = meta.get("question_category") or "未分类"
            q_preview = (meta.get("question_preview") or "").strip() or "(no question)"
            lines.append(
                f"[Source: {kb_name} | Q&A: {category}] {q_preview}"
            )
        else:
            doc_filename = (
                meta.get("filename") or meta.get("source") or "Unknown Document"
            )
            chunk_idx = meta.get("chunk_index", "?")
            lines.append(
                f"[Source: {kb_name} | Document: {doc_filename} | Chunk #{chunk_idx}]"
            )
        lines.append(chunk["text"])
        lines.append("")
        lines.append("---")
        lines.append("")
    return "\n".join(lines).rstrip()


def build_agent_kb_context(
    agent_id: int,
    query: str,
    db: Session,
) -> Optional[str]:
    """Build RAG context string from agent's bound KBs.

    None = no active KB / all KBs returned 0 results / agent not found.
    """
    agent = db.get(Agent, agent_id)
    if agent is None:
        return None

    cfg = agent.kb_retrieval_config or {"top_k": 3, "rrf_k": 30}
    if cfg is None:
        cfg = {}
    top_k = int(cfg.get("top_k", 3))  # type: ignore[arg-type]
    rrf_k = int(cfg.get("rrf_k", 30))  # type: ignore[arg-type]

    # 读 active KBs
    active_kbs = [
        b.knowledge_base
        for b in agent.knowledge_bases
        if b.knowledge_base and b.knowledge_base.status == "active"
    ]
    if not active_kbs:
        return None

    # M27: install an EmbeddingCallContext if the caller hasn't already.
    # The /chat/stream endpoint installs one (with the trace_id from the
    # LLM context); calling sites that hit this directly (debug page,
    # tests, future ad-hoc retrievals) get a fresh context so their
    # embed_query calls still write rows. The local context is reset on
    # function exit; an outer context set by the endpoint is left alone.
    own_token = None
    if get_embedding_context() is None:
        own_token = set_embedding_context(EmbeddingCallContext(
            call_id=str(uuid.uuid4()),
            trace_id=str(uuid.uuid4()),
            parent_call_id=None,
            call_type="kb_retrieval",
            call_index=0,
            tenant_id=agent.tenant_id,
            agent_id=agent_id,
            extra={"top_k": top_k, "rrf_k": rrf_k},
        ))

    try:
        # M27.1: stdlib ``ThreadPoolExecutor`` workers don't inherit
        # the parent's ContextVar state. The LoggingEmbeddings wrapper
        # inside ``_retrieve_kb_chunks`` reads the context to write
        # observability rows — without an active context there, the
        # wrapper is transparent and zero rows are written.
        #
        # Solution: capture the parent's EmbeddingCallContext here
        # (if any) and pass it explicitly to each worker as a regular
        # argument. The worker installs the context locally for the
        # duration of the retrieval — no ContextVar inheritance
        # magic, no re-entrancy issues, and the per-KB refine that
        # ``_retrieve_kb_chunks`` does still works.
        #
        # See M27 chat smoke test 2026-06-15 — first run hit the
        # "no embedding rows" bug (no propagation at all); second
        # run hit "cannot enter context: ... is already entered"
        # (shared snapshot re-entrancy). Pass-as-arg is the
        # simplest fix that avoids both.

        parent_emb_ctx = get_embedding_context()

        # 并发 per-KB similarity_search
        per_kb_chunks: Dict[int, List[Any]] = {}
        with ThreadPoolExecutor(max_workers=min(4, len(active_kbs))) as executor:
            def _run_in_worker(kb):
                return _retrieve_kb_chunks_with_ctx(
                    parent_emb_ctx, kb, query, top_k, agent.tenant_id, db,  # type: ignore[arg-type]
                )

            futures = {
                executor.submit(_run_in_worker, kb): kb
                for kb in active_kbs
            }
            for future in futures:
                kb = futures[future]
                try:
                    chunks = future.result(timeout=30)
                except Exception as e:  # noqa: BLE001
                    logger.warning("KB %s future failed: %s", kb.id, e)
                    chunks = []
                if chunks:
                    per_kb_chunks[kb.id] = chunks
    finally:
        if own_token is not None:
            reset_embedding_context(own_token)

    if not per_kb_chunks:
        return None

    # RRF 融合
    fused = _rrf_fuse(per_kb_chunks, rrf_k=rrf_k, top_n=10)
    if not fused:
        return None

    # 拼 markdown
    kb_id_to_name = {kb.id: kb.name for kb in active_kbs}
    return _render_context_markdown(fused, active_kbs, kb_id_to_name)
