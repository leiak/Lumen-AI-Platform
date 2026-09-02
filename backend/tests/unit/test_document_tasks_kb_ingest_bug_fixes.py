"""Regression tests for the 3 KB-ingest bug fixes shipped 2026-09-02.

Three latent bugs surfaced during the KB 55 audit (2026-09-01):

A. ``/rechunk`` (and ``/retry``) on a docx file with no body
   overrides silently fell back to ``chunking_strategy="fixed"``
   even when the original upload used ``document_structure``,
   producing a different chunk count on retry (e.g. doc 969 went
   from 27 chunks → 7 chunks). Root cause: the chunking strategy
   wasn't persisted on the ``Document`` row.

B. ``OllamaEmbeddings`` / ``OpenAIEmbeddings`` constructed in
   ``embedding_factory.get_embeddings_for_config`` did not pass
   ``client_kwargs`` (Ollama) or ``http_client`` / ``http_async_client``
   (OpenAI) with the httpx proxy bypass, so on Windows dev boxes
   with a registry proxy the embed call 502'd for ``localhost:11434``.
   Same root cause as workflow 1148 (2026-08-31) but in the embed path.

C. ``process_document_task`` called ``db.commit()`` after adding
   chunks to the session. SQLAlchemy's default ``expire_on_commit=True``
   invalidated all attributes, so ``c.id`` accesses afterwards
   depended on a SELECT refresh that, under the worker's long-running
   session, occasionally came back NULL. Symptom: subsequent
   ``chunk.vector_id = vid; db.commit()`` issued ``UPDATE chunks SET
   vector_id=... WHERE id=NULL`` → 0 rows matched → silently lost
   ``vector_id`` linkage between FAISS/ES and the ``document_chunks``
   row.

Each test below pins one of these bugs by inspecting source text or
mocking the relevant seam, so a future regression of any of the three
fails one of these tests immediately.
"""
import inspect
import pytest


# ---------------------------------------------------------------------------
# Bug C — db.flush() not db.commit() at the chunk-insert point
# ---------------------------------------------------------------------------


def _strip_python_comments(src: str) -> str:
    """Drop ``# ...`` line comments so we can grep for call tokens
    without the explanatory text tripping the check.
    """
    out_lines = []
    for line in src.splitlines():
        # Skip comment-only lines outright; for code lines, strip the
        # trailing ``# ...`` if present. Crude but enough for the
        # static checks below — no string-literal awareness needed
        # because the source under test has no ``#`` inside strings.
        stripped = line.split("#", 1)[0] if "#" in line else line
        out_lines.append(stripped)
    return "\n".join(out_lines)


def test_process_document_task_uses_flush_after_chunk_insert():
    """Bug C regression: chunk insert must ``db.flush()`` not ``db.commit()``.

    The flow inside ``if chunks_data:`` is:

    1. Add every ``DocumentChunk`` to the session
    2. Persist IDs (``db.flush()`` → INSERT immediately, IDs assigned)
    3. Call ``vector_store.add_texts`` with metadatas that reference
       ``chunk.id``
    4. UPDATE chunks with ``vector_id`` matching the vector store
       entry

    Old code used ``db.commit()`` between (2) and (3) which, combined
    with SQLAlchemy's default ``expire_on_commit=True``, caused the
    worker's long-running session to occasionally return ``chunk.id=None``
    on the SELECT refresh. That made step (3)'s metadatas carry
    ``chunk_id=None`` and step (4) became ``UPDATE WHERE id=NULL`` →
    0 rows matched, silently losing the vector_id linkage.

    The fix swaps ``db.commit()`` → ``db.flush()`` so INSERT runs and
    IDs are populated without the expire/commit cycle. The final
    ``db.commit()`` later in the task commits everything atomically.
    """
    from lumen_tasks import document_tasks

    src = inspect.getsource(document_tasks.process_document_task)
    # The chunk-insert block must call flush, not commit. Use a
    # lookback window starting at the ``if chunks_data:`` block and
    # ending before the ``# Store in vector store`` log line — that
    # pins the exact "after the for-loop" point we want to assert.
    chunk_insert_block_start = src.index("if chunks_data:")
    chunk_insert_block_end = src.index("# Store in vector store", chunk_insert_block_start)
    block = _strip_python_comments(src[chunk_insert_block_start:chunk_insert_block_end])
    assert "db.flush()" in block, (
        "process_document_task 在 chunk INSERT 之后必须用 db.flush(),"
        "不能用 db.commit()(Bug C)。\n"
        "原 commit 触发 SQLAlchemy expire_on_commit → chunk.id 在后续"
        " vector_store.add_texts 时变 None → UPDATE 0 matched。"
    )
    # And commit must NOT be a real call (only comment mentions OK).
    assert "db.commit()" not in block, (
        "chunk INSERT 块里发现 db.commit() — Bug C 已 ship,"
        "回归会让 chunk.id 在 vector_store.add_texts 时变 None。"
    )


# ---------------------------------------------------------------------------
# Bug B — bypass_proxy_client_kwargs applied to embeddings
# ---------------------------------------------------------------------------


def test_embedding_factory_uses_httpx_bypass_helper():
    """Bug B regression: ``embedding_factory`` must call
    ``bypass_proxy_client_kwargs`` for both Ollama and OpenAI
    branches — without it the embed call 502s on dev boxes whose
    Windows registry proxy blocks ``localhost:11434``.

    Static source check because the helper is module-level
    ``import httpx``, easy to grep for, and the test won't break
    if someone replaces the helper body as long as the new helper
    is still imported under the same name.
    """
    from lumen_services import embedding_factory

    src = inspect.getsource(embedding_factory)
    assert "from lumen_core.httpx_bypass import bypass_proxy_client_kwargs" in src, (
        "embedding_factory 必须从 lumen_core.httpx_bypass import "
        "bypass_proxy_client_kwargs — Bug B 已 ship,回归会让 embed "
        "call 在 Windows registry proxy 下 502"
    )
    # Ollama branch
    assert "OllamaEmbeddings(" in src and "client_kwargs=bypass_proxy_client_kwargs()" in src, (
        "OllamaEmbeddings 必须带 bypass_proxy_client_kwargs() — "
        "否则 registry proxy 走 httpx 502"
    )
    # OpenAI branch
    assert (
        "http_client=httpx.Client(**_bypass)" in src
        and "http_async_client=httpx.AsyncClient(**_bypass)" in src
    ), (
        "OpenAIEmbeddings 必须把 bypass kwargs 喂给 sync + async "
        "httpx client — openai SDK 用 sync Client 走 embed_query、"
        "async Client 走 aembed_query,漏一个留半个 bug"
    )


# ---------------------------------------------------------------------------
# Bug A — /retry + /rechunk preserve chunking_strategy from doc.doc_metadata
# ---------------------------------------------------------------------------


def test_rechunk_document_preserves_chunking_strategy_from_metadata():
    """Bug A regression: ``rechunk_document`` must read
    ``chunking_strategy`` from ``doc.doc_metadata`` when the body
    doesn't supply one. Without this fallback, a rechunk with no
    body overrides silently drops to ``"fixed"`` even when the
    original upload used ``"document_structure"`` — producing a
    different chunk count (doc 969: 27 → 7).

    The fix is a source-level assertion that the endpoint inspects
    ``doc.doc_metadata`` for ``chunking_strategy`` before defaulting
    to ``"fixed"``. We don't mock the whole endpoint here — the
    previous tests already proved the chunking layer accepts the
    strategy; this pins the API contract.
    """
    from lumen_api.v1 import knowledge

    src = inspect.getsource(knowledge.rechunk_document)
    assert 'doc_metadata.get("chunking_strategy")' in src, (
        "rechunk_document 必须从 doc.doc_metadata 读 chunking_strategy "
        "fallback — Bug A 已 ship,回归会让 docx /rechunk 静默走 fixed "
        "策略,产生不同 chunk 数"
    )
    assert 'doc_metadata.get("chunking_params", {}).get("chunk_size")' in src, (
        "rechunk_document 必须从 doc.doc_metadata 读 chunk_size fallback"
    )
    assert 'doc_metadata.get("chunking_params", {}).get("chunk_overlap")' in src, (
        "rechunk_document 必须从 doc.doc_metadata 读 chunk_overlap fallback"
    )


def test_retry_document_preserves_chunking_strategy_from_metadata():
    """Bug A regression: ``retry_document`` (POST /retry) must read
    ``chunking_strategy`` from ``doc.doc_metadata``. Same root cause
    as ``rechunk`` — without this fallback, a retry that only triggers
    on a stuck doc silently re-chunks with the wrong strategy.
    """
    from lumen_api.v1 import knowledge

    src = inspect.getsource(knowledge.retry_document)
    assert 'doc_metadata.get("chunking_strategy")' in src, (
        "retry_document 必须从 doc.doc_metadata 读 chunking_strategy — "
        "Bug A 已 ship,回归会让 stuck doc 重试时切到 fixed 策略"
    )


def test_upload_document_persists_chunking_strategy():
    """Bug A regression: ``upload_document`` must persist
    ``chunking_strategy`` and ``chunking_params`` in
    ``doc.doc_metadata`` so future rechunk/retry can read them back.

    Before this fix only ``doc_type`` was persisted; the strategy
    was lost at the first retry.
    """
    from lumen_api.v1 import knowledge

    src = inspect.getsource(knowledge.upload_document)
    # The async upload branch persists doc_metadata at the end of
    # the queue-and-return block. We assert both new keys are there.
    assert '"chunking_strategy"' in src, (
        "upload_document 必须在 doc.doc_metadata 写 chunking_strategy "
        "— Bug A 已 ship,回归会让 retry/rechunk 拿不到原策略"
    )
    assert '"chunking_params"' in src, (
        "upload_document 必须在 doc.doc_metadata 写 chunking_params "
        "(chunk_size + chunk_overlap)"
    )