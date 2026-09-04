"""Embedding call logging service + LoggingEmbeddings proxy.

M27 spec — mirrors M26 ``llm_call_logging.py`` but for embeddings:

- ``EmbeddingCallLoggingService.log_call`` — write one row to
  ``embedding_call_logs`` inside a fresh DB session (callers do not
  need to manage transactions; failures are swallowed so observability
  never breaks the actual embed path).
- ``LoggingEmbeddings`` — proxy that wraps a real
  ``langchain_core.embeddings.Embeddings`` and intercepts
  ``embed_query`` / ``embed_documents`` (sync + async variants). The
  proxy reads the active ``EmbeddingCallContext`` from the ContextVar
  and writes one row per call. When no context is set, the proxy is
  transparent (no row written, no extra latency beyond the attribute
  lookup).

Storage policy: text is truncated to 200 chars (``text_preview``); the
full character count is stored in ``text_chars``. Embedding vectors
themselves are NOT stored — only their dimension and byte count.

Spec: docs/superpowers/specs/2026-06-15-embedding-trace-retention.md §"插桩策略"
"""
from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime
from typing import Any, List, Optional

from sqlalchemy.orm import Session

from lumen_core.embedding_call_context import (
    EmbeddingCallContext,
    get_embedding_context,
)
from lumen_models.embedding_call_log import EmbeddingCallLog

logger = logging.getLogger(__name__)


def _observe_embedding_duration(model_name: str, t0: float, status: str) -> None:
    """Phase 1 Group B B2b 4.6 (2026-09-04): 把 embedding 调用耗时写进
    Prometheus Histogram,供 SLO ``embedding_latency`` (P95 < 200ms) 看板用。

    失败也记(避免 SLO 数据漏掉失败事件)。写入失败绝不影响主流程 —— 监
    控永远不应该让生产接口 fail。

    Args:
        model_name: model_config.model_name,作为 Histogram label。
        t0: 调用 ``time.monotonic()`` 的起点。
        status: ``"success"`` 或 ``"error"``。
    """
    try:
        # 局部 import 避免 import cycle:lumen_core.metrics 可能被
        # lumen_main 在 startup 时初始化,这条路径不能反过来依赖 metrics。
        from lumen_core.metrics import lumen_embedding_duration_seconds

        lumen_embedding_duration_seconds.labels(
            model=str(model_name),
            status=status,
        ).observe(time.monotonic() - t0)
    except Exception:  # noqa: BLE001
        # Histogram 写入失败不能让 embedding 主流程挂掉
        logger.debug("lumen_embedding_duration_seconds.observe failed", exc_info=True)


# Sentinel used by ``embedding_factory.py`` when probing the embedding
# dimension on cache cold-start. Rows whose text equals this constant
# carry ``extra.is_dim_probe = True`` so the UI can filter them out by
# default (they're noise but kept for full audit).
DIM_PROBE_TEXT = "dim-probe"


def _truncate_preview(text: str, limit: int = 200) -> str:
    if text is None:
        return ""
    if not isinstance(text, str):
        text = str(text)
    return text[:limit]


class EmbeddingCallLoggingService:
    """Persist a single EmbeddingCallLog row.

    Each call opens a fresh DB session — embedding calls happen on
    many code paths (chat stream, Celery worker, MCP tool) and we
    cannot assume the caller has a clean session.
    """

    def log_call(
        self,
        db: Session,
        *,
        ctx: EmbeddingCallContext,
        model_type: Optional[str],
        model_name: str,
        model_config_id: Optional[int],
        text_preview: str,
        text_chars: int,
        is_batch: bool,
        batch_size: Optional[int],
        embedding_dim: Optional[int],
        embedding_bytes: Optional[int],
        started_at: datetime,
        finished_at: Optional[datetime],
        duration_ms: int,
        status: str = "success",
        error_type: Optional[str] = None,
        error_message: Optional[str] = None,
        retry_count: int = 0,
    ) -> Optional[EmbeddingCallLog]:
        """Insert a single EmbeddingCallLog row.

        Returns the persisted row, or None on a hard failure (logged).
        Failure to write a log row MUST NOT bubble up to the caller —
        observability should not break embedding throughput.
        """
        try:
            row = EmbeddingCallLog(
                call_id=ctx.call_id,
                parent_call_id=ctx.parent_call_id,
                trace_id=ctx.trace_id,
                call_type=ctx.call_type,
                call_index=ctx.call_index,
                tenant_id=ctx.tenant_id,
                user_id=ctx.user_id,
                username=ctx.username,
                client_app=ctx.client_app,
                conversation_id=ctx.conversation_id,
                agent_id=ctx.agent_id,
                team_id=ctx.team_id,
                workflow_id=ctx.workflow_id,
                workflow_run_id=ctx.workflow_run_id,
                workflow_node_id=ctx.workflow_node_id,
                knowledge_base_id=ctx.knowledge_base_id,
                model_type=model_type,
                model_name=model_name,
                model_config_id=model_config_id,
                text_preview=text_preview,
                text_chars=text_chars,
                is_batch=is_batch,
                batch_size=batch_size,
                embedding_dim=embedding_dim,
                embedding_bytes=embedding_bytes,
                started_at=started_at,
                finished_at=finished_at,
                duration_ms=duration_ms,
                status=status,
                error_type=error_type,
                error_message=error_message,
                retry_count=retry_count,
                request_ip=ctx.request_ip,
                user_agent=ctx.user_agent,
                extra=ctx.extra,
            )
            db.add(row)
            db.commit()
            db.refresh(row)
            return row
        except Exception:  # noqa: BLE001
            try:
                db.rollback()
            except Exception:
                pass
            logger.exception(
                "EmbeddingCallLoggingService.log_call failed; observability row skipped"
            )
            return None


_singleton: Optional[EmbeddingCallLoggingService] = None


def get_embedding_logging_service() -> EmbeddingCallLoggingService:
    global _singleton
    if _singleton is None:
        _singleton = EmbeddingCallLoggingService()
    return _singleton


class LoggingEmbeddings:
    """Proxy that wraps a real ``Embeddings`` instance and writes one
    ``embedding_call_logs`` row per ``embed_query`` / ``embed_documents``
    call.

    Per M27 spec, this is the high-leverage single seam — wrapping in
    ``embedding_factory.get_embeddings_for_config`` means all callers
    (chat KB retrieval / agent_rag / KnowledgeService ingest /
    RetrievalPipeline / workflow knowledge_retrieval) flow through
    the same instrumentation without modifying their call sites.

    Transparent fall-through: if no ``EmbeddingCallContext`` is set on
    the current async/thread context, the proxy simply delegates to
    the inner Embeddings without writing a row. This means background
    paths (Celery worker startup probes, test fixtures) don't pollute
    the table with un-attributed rows.
    """

    def __init__(
        self,
        inner: Any,
        *,
        model_type: Optional[str],
        model_name: str,
        model_config_id: Optional[int],
    ):
        self._inner = inner
        self._model_type = model_type
        self._model_name = model_name
        self._model_config_id = model_config_id

    # ---- sync embed_query ----

    def embed_query(self, text: str) -> List[float]:
        ctx = get_embedding_context()
        from lumen_services.retry import call_sync_with_retry
        t0 = time.monotonic()
        if ctx is None:
            # Phase 1 Group A 2.5 (2026-09-03): 没有 ctx 时也走 retry,
            # 跟有 ctx 行为一致(observability 可选,retry 不可选)。
            # ``call_sync_with_retry`` 让 self._inner.embed_query transient
            # 异常(httpx.ConnectError / TimeoutException / RemoteProtocolError)
            # 重试 3 次 exponential 0.5/1/2s,reraise 原异常让上层 fail-fast。
            try:
                result = call_sync_with_retry(
                    lambda: self._inner.embed_query(text),
                    func_name="embedding.embed_query",
                )
                _observe_embedding_duration(self._model_name, t0, "success")
                return result
            except Exception:
                _observe_embedding_duration(self._model_name, t0, "error")
                raise

        started = datetime.utcnow()
        # Phase 1 Group A 2.5: retry 包 inner 调用,retry_count 写进 log。
        try:
            result = call_sync_with_retry(
                lambda: self._inner.embed_query(text),
                func_name="embedding.embed_query",
            )
            self._write_log(
                ctx=ctx,
                text=text,
                is_batch=False,
                batch_size=None,
                embedding_dim=len(result) if result else 0,
                embedding_bytes=(len(result) * 4) if result else 0,
                started_at=started,
                duration_ms=int((time.monotonic() - t0) * 1000),
                status="success",
            )
            _observe_embedding_duration(self._model_name, t0, "success")
            return result
        except Exception as e:
            self._write_log(
                ctx=ctx,
                text=text,
                is_batch=False,
                batch_size=None,
                embedding_dim=None,
                embedding_bytes=None,
                started_at=started,
                duration_ms=int((time.monotonic() - t0) * 1000),
                status="failure",
                error_type=type(e).__name__,
                error_message=str(e)[:1000],
            )
            _observe_embedding_duration(self._model_name, t0, "error")
            raise

    # ---- sync embed_documents ----

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        ctx = get_embedding_context()
        # Phase 1 Group A 2.5: retry 包 inner 调用(sync batch path)。
        from lumen_services.retry import call_sync_with_retry
        t0 = time.monotonic()
        if ctx is None:
            try:
                result = call_sync_with_retry(
                    lambda: self._inner.embed_documents(texts),
                    func_name="embedding.embed_documents",
                )
                _observe_embedding_duration(self._model_name, t0, "success")
                return result
            except Exception:
                _observe_embedding_duration(self._model_name, t0, "error")
                raise

        started = datetime.utcnow()
        # Preview is the first text (typical case is a chunk batch from
        # a single document). text_chars sums the whole batch so the
        # caller can see total ingestion volume.
        total_chars = sum(len(t or "") for t in (texts or []))
        first_preview = texts[0] if texts else ""
        try:
            result = call_sync_with_retry(
                lambda: self._inner.embed_documents(texts),
                func_name="embedding.embed_documents",
            )
            dim = len(result[0]) if result and len(result) > 0 else 0
            self._write_log_for_batch(
                ctx=ctx,
                preview=first_preview,
                total_chars=total_chars,
                batch_size=len(texts) if texts else 0,
                embedding_dim=dim,
                embedding_bytes=(dim * 4 * len(result)) if result else 0,
                started_at=started,
                duration_ms=int((time.monotonic() - t0) * 1000),
                status="success",
            )
            _observe_embedding_duration(self._model_name, t0, "success")
            return result
        except Exception as e:
            self._write_log_for_batch(
                ctx=ctx,
                preview=first_preview,
                total_chars=total_chars,
                batch_size=len(texts) if texts else 0,
                embedding_dim=None,
                embedding_bytes=None,
                started_at=started,
                duration_ms=int((time.monotonic() - t0) * 1000),
                status="failure",
                error_type=type(e).__name__,
                error_message=str(e)[:1000],
            )
            _observe_embedding_duration(self._model_name, t0, "error")
            raise

    # ---- async variants — pass through if inner supports it ----

    async def aembed_query(self, text: str) -> List[float]:
        ctx = get_embedding_context()
        aembed = getattr(self._inner, "aembed_query", None)
        # Phase 1 Group A 2.5: async retry 包 inner 调用。
        from lumen_services.retry import call_async_with_retry
        t0 = time.monotonic()
        if aembed is None:
            # langchain_core.Embeddings provides a default sync fallback
            return self.embed_query(text)
        if ctx is None:
            try:
                result = await call_async_with_retry(
                    lambda: aembed(text),
                    func_name="embedding.aembed_query",
                )
                _observe_embedding_duration(self._model_name, t0, "success")
                return result
            except Exception:
                _observe_embedding_duration(self._model_name, t0, "error")
                raise

        started = datetime.utcnow()
        try:
            result = await call_async_with_retry(
                lambda: aembed(text),
                func_name="embedding.aembed_query",
            )
            self._write_log(
                ctx=ctx,
                text=text,
                is_batch=False,
                batch_size=None,
                embedding_dim=len(result) if result else 0,
                embedding_bytes=(len(result) * 4) if result else 0,
                started_at=started,
                duration_ms=int((time.monotonic() - t0) * 1000),
                status="success",
            )
            _observe_embedding_duration(self._model_name, t0, "success")
            return result
        except Exception as e:
            self._write_log(
                ctx=ctx,
                text=text,
                is_batch=False,
                batch_size=None,
                embedding_dim=None,
                embedding_bytes=None,
                started_at=started,
                duration_ms=int((time.monotonic() - t0) * 1000),
                status="failure",
                error_type=type(e).__name__,
                error_message=str(e)[:1000],
            )
            _observe_embedding_duration(self._model_name, t0, "error")
            raise

    async def aembed_documents(self, texts: List[str]) -> List[List[float]]:
        ctx = get_embedding_context()
        aembed = getattr(self._inner, "aembed_documents", None)
        # Phase 1 Group A 2.5: async retry 包 inner 调用。
        from lumen_services.retry import call_async_with_retry
        t0 = time.monotonic()
        if aembed is None:
            return self.embed_documents(texts)
        if ctx is None:
            try:
                result = await call_async_with_retry(
                    lambda: aembed(texts),
                    func_name="embedding.aembed_documents",
                )
                _observe_embedding_duration(self._model_name, t0, "success")
                return result
            except Exception:
                _observe_embedding_duration(self._model_name, t0, "error")
                raise

        started = datetime.utcnow()
        total_chars = sum(len(t or "") for t in (texts or []))
        first_preview = texts[0] if texts else ""
        try:
            result = await call_async_with_retry(
                lambda: aembed(texts),
                func_name="embedding.aembed_documents",
            )
            dim = len(result[0]) if result and len(result) > 0 else 0
            self._write_log_for_batch(
                ctx=ctx,
                preview=first_preview,
                total_chars=total_chars,
                batch_size=len(texts) if texts else 0,
                embedding_dim=dim,
                embedding_bytes=(dim * 4 * len(result)) if result else 0,
                started_at=started,
                duration_ms=int((time.monotonic() - t0) * 1000),
                status="success",
            )
            _observe_embedding_duration(self._model_name, t0, "success")
            return result
        except Exception as e:
            self._write_log_for_batch(
                ctx=ctx,
                preview=first_preview,
                total_chars=total_chars,
                batch_size=len(texts) if texts else 0,
                embedding_dim=None,
                embedding_bytes=None,
                started_at=started,
                duration_ms=int((time.monotonic() - t0) * 1000),
                status="failure",
                error_type=type(e).__name__,
                error_message=str(e)[:1000],
            )
            _observe_embedding_duration(self._model_name, t0, "error")
            raise

    # ---- write helpers ----

    def _write_log(
        self,
        *,
        ctx: EmbeddingCallContext,
        text: str,
        is_batch: bool,
        batch_size: Optional[int],
        embedding_dim: Optional[int],
        embedding_bytes: Optional[int],
        started_at: datetime,
        duration_ms: int,
        status: str,
        error_type: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> None:
        from lumen_core.database import SessionLocal

        # M27.1: each embed call gets its OWN unique call_id even if
        # multiple embed calls happen under the same active context
        # (e.g. the factory's cold-start dim-probe + the actual
        # user query share the per-KB refined ctx). Without this,
        # the second call hits UNIQUE constraint uq_ecl_call_id.
        unique_call_id = str(uuid.uuid4())

        # Auto-flag dim probe rows so the UI can hide them.
        if text == DIM_PROBE_TEXT:
            extra = dict(ctx.extra or {})
            extra["is_dim_probe"] = True
            ctx_for_row = ctx._replace(call_id=unique_call_id, extra=extra)
        else:
            ctx_for_row = ctx._replace(call_id=unique_call_id)

        db = SessionLocal()
        try:
            get_embedding_logging_service().log_call(
                db,
                ctx=ctx_for_row,
                model_type=self._model_type,
                model_name=self._model_name,
                model_config_id=self._model_config_id,
                text_preview=_truncate_preview(text),
                text_chars=len(text or ""),
                is_batch=is_batch,
                batch_size=batch_size,
                embedding_dim=embedding_dim,
                embedding_bytes=embedding_bytes,
                started_at=started_at,
                finished_at=datetime.utcnow(),
                duration_ms=duration_ms,
                status=status,
                error_type=error_type,
                error_message=error_message,
            )
        finally:
            db.close()

    def _write_log_for_batch(
        self,
        *,
        ctx: EmbeddingCallContext,
        preview: str,
        total_chars: int,
        batch_size: int,
        embedding_dim: Optional[int],
        embedding_bytes: Optional[int],
        started_at: datetime,
        duration_ms: int,
        status: str,
        error_type: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> None:
        from lumen_core.database import SessionLocal

        # M27.1: same unique call_id reason as ``_write_log`` above.
        ctx_for_row = ctx._replace(call_id=str(uuid.uuid4()))

        db = SessionLocal()
        try:
            get_embedding_logging_service().log_call(
                db,
                ctx=ctx_for_row,
                model_type=self._model_type,
                model_name=self._model_name,
                model_config_id=self._model_config_id,
                text_preview=_truncate_preview(preview),
                text_chars=total_chars,
                is_batch=True,
                batch_size=batch_size,
                embedding_dim=embedding_dim,
                embedding_bytes=embedding_bytes,
                started_at=started_at,
                finished_at=datetime.utcnow(),
                duration_ms=duration_ms,
                status=status,
                error_type=error_type,
                error_message=error_message,
            )
        finally:
            db.close()

    # ---- pass-through for any attribute we didn't wrap ----

    def __getattr__(self, name: str) -> Any:
        # __getattr__ is ONLY called when the attribute is not found on
        # the instance — methods defined on this class (embed_query,
        # embed_documents, aembed_*) shadow this fall-through cleanly.
        return getattr(self._inner, name)
