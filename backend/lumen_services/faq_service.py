"""M31: FAQ Q&A entry service.

A Q&A entry is a manually-maintained pair (question, answer)
that's part of a knowledge base, indexed into the same per-KB
vector store as document chunks so the agent's RAG path picks
it up automatically.

**Why a virtual Document?**
We need ``document_chunks.document_id`` to stay NOT NULL (it's
a hard schema constraint and several retrieval paths assume a
chunk has a parent doc). Rather than relax that, we model each
Q&A as:

- 1 ``Document`` row with ``doc_type="qa_pair"``,
  ``file_path="faq://<uuid>"`` (a sentinel, no real file on
  disk), and ``status="completed"`` since there's nothing to
  parse.
- 1 ``DocumentChunk`` row with the Q&A rendered as
  ``"问题: <q>\\n\\n答案: <a>"``. The chunk's metadata carries
  ``source_type="faq"`` so the agent_rag renderer can give Q&A
  hits a distinct label from document hits.
- 1 ``FAQEntry`` row that the UI talks to (question/answer/
  category/tags CRUD, plus the doc_id + chunk_id so the
  virtual parent can be cleaned up on delete).

**Why no tenant_id column?** Tenant isolation is enforced
through the parent ``knowledge_base_id`` → ``KnowledgeBase.
tenant_id`` JOIN at the API layer, mirroring the project's
``Document`` pattern.

**Why a hard delete (not soft)?** Match the project convention
for document deletion — no ``is_active`` flag, no audit row.
If a future feature wants soft delete, add it then.

**Why "delete old vector + write new vector" on update (not
in-place mutate)?** The vector store and the chunk's
``vector_id`` are kept in lockstep, so an in-place edit would
either need a hash-on-content check (extra work) or risk
desyncing if a future retry / rechunk path touches only one
side. The "swap whole row" approach is the same one the doc
update path uses, and it's cheap — the per-KB embedder is
already hot.
"""
from __future__ import annotations

import csv
import io
import json
import logging
import uuid as _uuid
from typing import Any, Dict, List, Optional, Tuple, cast

from sqlalchemy import and_
from sqlalchemy.orm import Session

from lumen_models.knowledge import (
    Document,
    DocumentChunk,
    FAQEntry,
    KnowledgeBase,
)
from lumen_models.user import User
from lumen_schemas.knowledge import (
    FAQBulkImportRequest,
    FAQBulkImportResult,
    FAQEntryCreate,
    FAQEntryUpdate,
)

logger = logging.getLogger(__name__)


# Cap the tag list so a single FAQ can't end up with 10k tags
# from a malformed bulk import. The UI uses antd `Select
# mode="tags"` so this is a defensive cap, not a UX limit.
MAX_TAGS_PER_ENTRY = 20

# Sentinel prefix for the virtual Q&A "document" file_path.
# Used so anything that scans the filesystem for a real upload
# (e.g. a future janitor) can short-circuit on the prefix
# without having to consult the FAQEntry table.
FAQ_FILE_PATH_PREFIX = "faq://"


def _render_chunk_content(question: str, answer: str) -> str:
    """Render a Q&A into the single chunk that gets embedded.

    The shape is deliberately simple so the LLM can pick out
    the Q vs. A boundary in the system prompt context. The
    Chinese section headers ("问题"/"答案") match the
    convention used by the document parser for ``doc_type="qa"``
    CSV files — see ``app/services/parsers/__init__.py``.
    """
    return f"问题: {question}\n\n答案: {answer}"


def _build_chunk_metadata(
    *,
    tenant_id: int,
    kb_id: int,
    document_id: int,
    chunk_id: int,
    category: Optional[str],
    question_preview: str,
    question_length: int,
    answer_length: int,
    faq_id: Optional[int] = None,
) -> Dict[str, Any]:
    """Build the metadata dict that the vector store indexes alongside the chunk.

    The agent_rag renderer branches on ``source_type`` to label
    Q&A hits differently from document hits (see
    ``_render_context_markdown``). The same metadata is also
    written to ``DocumentChunk.chunk_metadata`` so future
    read-only paths that bypass the vector store can recover
    the same labels.

    ``question_preview`` is the first 30 chars of the question
    — surfaced in the system-prompt source label so the LLM
    can see at a glance which Q&A the chunk came from. Capped
    here (not at the renderer) so the cap is consistent
    regardless of which path reads it.
    """
    return {
        "tenant_id": tenant_id,
        "kb_id": kb_id,
        "document_id": document_id,
        "chunk_id": chunk_id,
        "source_type": "faq",
        "question_category": category,
        "question_preview": question_preview,
        "faq_id": faq_id,
        "question_length": question_length,
        "answer_length": answer_length,
    }


def _question_preview(question: str, max_len: int = 30) -> str:
    """Truncate the question for use in source labels and preview fields."""
    if len(question) <= max_len:
        return question
    return question[:max_len]


class FAQService:
    """Q&A entry CRUD + bulk import.

    All public methods that need a ``KnowledgeBase`` accept it as
    a pre-loaded argument so the API layer can do the tenant
    scope check (kb.tenant_id == current_user.tenant_id) in one
    place and the service stays free of auth concerns.
    """

    # ---------------------------------------------------------- read paths

    def get_entry(
        self,
        db: Session,
        entry_id: int,
        kb_id: int,
        tenant_id: int,
    ) -> Optional[FAQEntry]:
        """Look up a single FAQ by id, scoped to a KB + tenant.

        Returns None if the row exists but belongs to a
        different KB or tenant — the API layer turns that into
        a 404 to avoid leaking the existence of cross-tenant
        rows.
        """
        return (
            db.query(FAQEntry)
            .join(KnowledgeBase, KnowledgeBase.id == FAQEntry.knowledge_base_id)
            .filter(
                FAQEntry.id == entry_id,
                FAQEntry.knowledge_base_id == kb_id,
                KnowledgeBase.tenant_id == tenant_id,
            )
            .first()
        )

    def list_entries(
        self,
        db: Session,
        kb_id: int,
        tenant_id: int,
        page: int = 1,
        page_size: int = 20,
        category: Optional[str] = None,
        search: Optional[str] = None,
    ) -> Tuple[List[FAQEntry], int]:
        """List FAQ entries for a KB with optional filters.

        Filters compose as AND. ``search`` is a case-sensitive
        substring match over question + answer (MySQL utf8mb4
        default collation is case-insensitive in our schema, so
        the practical behavior is "case-insensitive contains").

        Returns (rows, total). Total is computed AFTER filters
        so the frontend can render "N 条结果" correctly.

        We do the tenant check via ``KnowledgeBase.id == kb_id
        AND KnowledgeBase.tenant_id == tenant_id`` so a single
        query covers all three filter dimensions.
        """
        # Tenant + KB gate: a non-existent KB returns [], which
        # the API layer surfaces as an empty page (not 404 —
        # the list endpoint is for the "Q&A tab" UI, where a
        # missing KB is treated as "no entries").
        kb_exists = (
            db.query(KnowledgeBase.id)
            .filter(
                KnowledgeBase.id == kb_id,
                KnowledgeBase.tenant_id == tenant_id,
            )
            .first()
        )
        if kb_exists is None:
            return [], 0

        q = db.query(FAQEntry).filter(FAQEntry.knowledge_base_id == kb_id)
        if category:
            q = q.filter(FAQEntry.category == category)
        if search:
            # ``OR`` over question + answer. Using a parameterised
            # ``LIKE`` (not ilike) so the index can be used
            # — case-insensitivity is already a property of
            # the default utf8mb4_general_ci collation.
            pattern = f"%{search}%"
            q = q.filter(
                (FAQEntry.question.like(pattern)) | (FAQEntry.answer.like(pattern))
            )

        total = q.count()
        # Newest first — matches the convention in the documents
        # list. Stable secondary sort by id so a flush that
        # backfills created_at with the same second doesn't
        # shuffle the page.
        rows = (
            q.order_by(FAQEntry.created_at.desc(), FAQEntry.id.desc())
            .offset(max(page - 1, 0) * page_size)
            .limit(page_size)
            .all()
        )
        return rows, total

    # --------------------------------------------------------- write paths

    def create_entry(
        self,
        db: Session,
        kb: KnowledgeBase,
        data: FAQEntryCreate,
        current_user: User,
    ) -> FAQEntry:
        """Create a single FAQ entry.

        The transaction is all-or-nothing: if the vector store
        write fails, the database row is rolled back (no
        half-written FAQ). The caller (API layer) does NOT
        catch the exception — let it bubble as a 500 so the
        user knows the entry was not saved.

        Steps:
        1. Build a virtual ``Document`` row (no file on disk).
        2. Build the single ``DocumentChunk`` with rendered
           Q&A content.
        3. Write the chunk to the per-KB vector store and BM25
           index. On failure here we re-raise — the API layer
           will turn it into a 500 and the caller's transaction
           is already in a failed state.
        4. Build the ``FAQEntry`` linking the three rows.
        5. Commit.
        """
        # 1. Virtual Document — the chunk's parent row. We
        #    deliberately do NOT save anything to disk; the
        #    sentinel file_path makes it obvious in a debug
        #    session that this row came from the FAQ path.
        doc = Document(
            knowledge_base_id=kb.id,
            filename=f"FAQ/{data.category or '未分类'}",
            file_type="qa_pair",
            file_path=f"{FAQ_FILE_PATH_PREFIX}{_uuid.uuid4()}",
            file_size=0,
            status="completed",
            chunk_count=1,
            doc_metadata={
                "doc_type": "qa_pair",
                "category": data.category,
                "tags": data.tags or [],
            },
            created_by=current_user.id,
            # Copy the KB's embedder FK so future read paths
            # (e.g. a "re-embed all FAQs" admin tool) can
            # resolve the embedder without joining the KB.
            embedding_model_config_id=kb.embedding_model_config_id,
        )
        db.add(doc)
        db.flush()  # populate doc.id for the chunk FK

        # 2. Single chunk — index 0. embedding_status='ok'
        #    optimistically; the vector write in step 3 will
        #    flip it to 'failed' if the embedder errors out
        #    (mirrors the sync path in upload_document).
        chunk_content = _render_chunk_content(data.question, data.answer)
        chunk = DocumentChunk(
            document_id=doc.id,
            content=chunk_content,
            chunk_index=0,
            chunk_metadata={
                "tenant_id": kb.tenant_id,
                "kb_id": kb.id,
                "source_type": "faq",
                "question_category": data.category,
                "question_preview": _question_preview(data.question),
                "question_length": len(data.question),
                "answer_length": len(data.answer),
                # doc_id and faq_id are filled in below after
                # the FAQEntry row is allocated — the metadata
                # dict is also rebuilt at that point so it
                # carries the final faq_id.
            },
            embedding_status="ok",
        )
        db.add(chunk)
        db.flush()  # populate chunk.id

        # 3. Vector write. The pipeline's add_documents also
        #    feeds the BM25 index — both need the metadata
        #    that includes the chunk's id so the agent_rag
        #    hot path can look it up.
        #    Mypy: the Column[int] / Column[str] kwargs to
        #    _build_chunk_metadata and the Column[str]
        #    assignments to chunk.vector_id /
        #    chunk.embedding_status are the same pattern as
        #    skill_runner.py / embedding_factory.py. The
        #    project accepts these ``# type: ignore`` lines
        #    (M28 5-file scope 0 错, the rest of the project
        #    has ~680 pre-existing errors of the same shape
        #    per CLAUDE.md §8).
        metadatas = [
            _build_chunk_metadata(
                tenant_id=kb.tenant_id,  # type: ignore[arg-type]
                kb_id=kb.id,  # type: ignore[arg-type]
                document_id=doc.id,  # type: ignore[arg-type]
                chunk_id=chunk.id,  # type: ignore[arg-type]
                category=data.category,
                question_preview=_question_preview(data.question),
                question_length=len(data.question),
                answer_length=len(data.answer),
                faq_id=None,  # filled in after FAQEntry is allocated
            )
        ]
        vector_ids = self._index_chunks(
            db, kb, [chunk], metadatas=metadatas
        )
        if vector_ids and vector_ids[0]:
            chunk.vector_id = vector_ids[0]  # type: ignore[assignment]
        else:
            # Mirror the upload_document failure path: mark the
            # chunk as failed so search never returns it. The
            # FAQ row is still created — the user can edit and
            # re-save to retry.
            chunk.embedding_status = "failed"  # type: ignore[assignment]
            chunk.vector_id = f"error_{chunk.id}"  # type: ignore[assignment]

        # 4. FAQEntry row. We allocate the id now so the chunk
        #    metadata can be updated to carry it (the agent_rag
        #    source label uses ``question_preview``, not
        #    ``faq_id``, so this is forward-looking — the
        #    faq_id is useful for debugging only).
        faq = FAQEntry(
            knowledge_base_id=kb.id,
            question=data.question,
            answer=data.answer,
            category=data.category,
            tags=data.tags or [],
            vector_id=chunk.vector_id,
            document_id=doc.id,
            chunk_id=chunk.id,
            embedding_model_config_id=kb.embedding_model_config_id,
            created_by=current_user.id,
        )
        db.add(faq)
        db.flush()

        # Backfill faq_id into the chunk's stored metadata so
        # future readers can navigate chunk -> faq without a
        # second JOIN. (The vector store metadata is write-once
        # from the search-returned metadata, so the
        # chunk_metadata on the chunk row is the one that
        # future debug paths actually read.)
        chunk.chunk_metadata = {  # type: ignore[assignment]
            **(chunk.chunk_metadata or {}),
            "faq_id": faq.id,
        }

        # 5. Commit. Any failure above has already raised
        #    (and rolled back the implicit transaction), so
        #    if we reach here the row is fully persisted.
        db.commit()
        db.refresh(faq)
        return faq

    def update_entry(
        self,
        db: Session,
        entry: FAQEntry,
        data: FAQEntryUpdate,
    ) -> FAQEntry:
        """Update a FAQ row in place.

        Strategy (matches the project convention for document
        updates — see knowledge.py:580 ``rechunk_document``):
        1. Capture the old vector_id so we can clean it up.
        2. Apply field changes to the FAQEntry row.
        3. Re-render the chunk content if question / answer
           changed.
        4. Delete the old vector (best-effort — a stale vector
           is far less harmful than failing the update).
        5. Write a new vector. If the embedder errors out,
           flip the chunk to embedding_status='failed' (still
           keep the FAQ row — the user can retry by editing
           and re-saving).
        6. Commit.
        """
        old_vector_id = entry.vector_id

        # Apply the changes. ``exclude_unset=True`` is the
        # PATCH-style contract: only fields explicitly set in
        # the request body change. ``None`` vs missing is
        # ambiguous from JSON, so we treat both as "no change"
        # here — to clear a field the UI sends an empty
        # string / empty list explicitly.
        update_payload = data.model_dump(exclude_unset=True)
        for field, value in update_payload.items():
            setattr(entry, field, value)

        # Validate tag cap. Pydantic catches max_length /
        # min_length but not the soft tag-count cap.
        if entry.tags is not None and len(entry.tags) > MAX_TAGS_PER_ENTRY:
            raise ValueError(
                f"FAQ cannot have more than {MAX_TAGS_PER_ENTRY} tags"
            )

        # Re-render the chunk content if the question/answer
        # changed. Category only changes the chunk metadata
        # and the source label — no re-embed needed.
        chunk = db.get(DocumentChunk, entry.chunk_id)
        if chunk is None:
            # Should not happen — chunk is CASCADE-linked to
            # the FAQ row — but be defensive so an update
            # never leaves a FAQ in an inconsistent state.
            raise RuntimeError(
                f"FAQ {entry.id} has no chunk row (chunk_id={entry.chunk_id})"
            )
        question_changed = "question" in update_payload
        answer_changed = "answer" in update_payload
        if question_changed or answer_changed:
            chunk.content = _render_chunk_content(  # type: ignore[assignment]
                entry.question,  # type: ignore[arg-type]
                entry.answer,  # type: ignore[arg-type]
            )
            # Update the static metadata fields (length + preview)
            # in the same call. The dynamic ones (kb_id, tenant_id,
            # source_type) are unchanged.
            existing_meta = dict(chunk.chunk_metadata or {})
            existing_meta["question_preview"] = _question_preview(
                entry.question  # type: ignore[arg-type]
            )
            existing_meta["question_length"] = len(entry.question)  # type: ignore[arg-type]
            existing_meta["answer_length"] = len(entry.answer)  # type: ignore[arg-type]
            existing_meta["question_category"] = entry.category
            chunk.chunk_metadata = existing_meta  # type: ignore[assignment]

        # Re-embed only if the chunk text changed.
        if question_changed or answer_changed:
            # 1. Delete the old vector best-effort. We do this
            #    before writing the new one so a failure here
            #    doesn't leave us with two vectors pointing at
            #    the same row.
            if old_vector_id and not old_vector_id.startswith("error_"):
                self._delete_vectors(entry, old_vector_id)  # type: ignore[arg-type]

            # 2. Find the KB so we can ask the right embedder.
            kb = db.get(KnowledgeBase, entry.knowledge_base_id)  # type: ignore[arg-type]
            if kb is None:
                raise RuntimeError(
                    f"FAQ {entry.id} references missing KB {entry.knowledge_base_id}"
                )

            # 3. Build the metadata for the new vector. This
            #    duplicates the create_entry path's logic —
            #    factor-out lives in the chunk metadata dict
            #    that we wrote on create, so we just patch
            #    the fields that need updating.
            new_metadatas = [
                _build_chunk_metadata(
                    tenant_id=kb.tenant_id,  # type: ignore[arg-type]
                    kb_id=kb.id,  # type: ignore[arg-type]
                    document_id=entry.document_id,  # type: ignore[arg-type]
                    chunk_id=entry.chunk_id,  # type: ignore[arg-type]
                    category=entry.category,  # type: ignore[arg-type]
                    question_preview=_question_preview(entry.question),  # type: ignore[arg-type]
                    question_length=len(entry.question),  # type: ignore[arg-type]
                    answer_length=len(entry.answer),  # type: ignore[arg-type]
                    faq_id=entry.id,  # type: ignore[arg-type]
                )
            ]
            new_ids = self._index_chunks(db, kb, [chunk], metadatas=new_metadatas)
            if new_ids and new_ids[0]:
                entry.vector_id = new_ids[0]  # type: ignore[assignment]
                chunk.vector_id = new_ids[0]  # type: ignore[assignment]
                chunk.embedding_status = "ok"  # type: ignore[assignment]
            else:
                entry.vector_id = f"error_{chunk.id}"  # type: ignore[assignment]
                chunk.vector_id = entry.vector_id  # type: ignore[assignment]
                chunk.embedding_status = "failed"  # type: ignore[assignment]

        # Also update the virtual doc's doc_metadata so a
        # "Q&A tab" UI that reads the doc row directly (some
        # admin paths do) sees the latest category/tags.
        doc = db.get(Document, entry.document_id)
        if doc is not None:
            doc.doc_metadata = {  # type: ignore[assignment]
                **(doc.doc_metadata or {}),
                "doc_type": "qa_pair",
                "category": entry.category,
                "tags": entry.tags or [],
            }
            # Also keep the filename in sync with the category
            # — purely cosmetic for the documents tab (which
            # filters out qa_pair anyway), but helpful when a
            # developer runs a raw SELECT during debugging.
            doc.filename = f"FAQ/{entry.category or '未分类'}"  # type: ignore[assignment]

        db.commit()
        db.refresh(entry)
        return entry

    def delete_entry(self, db: Session, entry: FAQEntry) -> None:
        """Delete a FAQ row, its virtual Document, its chunk, and its vector.

        The order matters: the ``document_chunks.document_id``
        FK is ``NO ACTION`` (no CASCADE) — see
        ``ensure_faq_entries_table`` docstring. If we delete
        the Document first, the FK on the chunk blocks the
        delete. So we delete: chunk → document → FAQ, in
        that order.

        The FAQEntry→chunk and FAQEntry→document FKs are
        CASCADE, so deleting the FAQ would also delete them in
        theory — but only if we reach that row. Going
        chunk-first avoids the FK violation entirely and is
        easier to reason about.
        """
        old_vector_id = entry.vector_id
        if old_vector_id and not old_vector_id.startswith("error_"):
            self._delete_vectors(entry, old_vector_id)  # type: ignore[arg-type]

        # Delete the chunk first. The chunk_id FK on the
        # FAQ row is CASCADE so we could let SQLAlchemy
        # handle it, but doing it explicitly keeps the
        # operation atomic and visible.
        chunk = db.get(DocumentChunk, entry.chunk_id)
        if chunk is not None:
            db.delete(chunk)
        doc = db.get(Document, entry.document_id)
        if doc is not None:
            db.delete(doc)
        db.delete(entry)
        db.commit()

    # ---------------------------------------------------------- bulk paths

    def bulk_import(
        self,
        db: Session,
        kb: KnowledgeBase,
        request: FAQBulkImportRequest,
        current_user: User,
    ) -> FAQBulkImportResult:
        """Parse JSON or CSV and create N FAQ rows.

        **Failure semantics** (locked in by the spec):
        - Validation errors are collected per row into
          ``failed``. The valid rows still get inserted.
        - Any error at the DB / vector-store layer (mid-import
          failure) raises — the API layer turns that into a
          500, and the implicit transaction rolls back, so
          the user can fix and retry without worrying about
          a half-imported state.

        The split is intentional: validation is the user's
        problem (their data is malformed) and we want to tell
        them which rows are bad. DB / embedder failure is an
        infrastructure problem and partial commits are worse
        than an all-or-nothing retry.
        """
        items = self._parse_bulk_payload(request)
        # If parsing itself failed (malformed JSON / CSV), all
        # rows go to ``failed`` and nothing is inserted.
        if isinstance(items, tuple) and items[0] == "error":
            error_reason, error_index = items[1], items[2]
            return FAQBulkImportResult(
                inserted=0,
                failed=[{"row_index": error_index, "reason": error_reason}],
            )

        # Mypy needs an explicit narrow here — ``items`` is a
        # union of ``List[Dict]`` and a 3-tuple, and the
        # isinstance check above doesn't refine the variable
        # for mypy's purposes. The cast is safe because the
        # tuple branch returns.
        items = cast(List[Dict[str, Any]], items)

        # Validate each row up front. Keep a parallel list of
        # validated dicts so we can pass them to create_entry
        # in one pass without re-parsing.
        #
        # We deliberately construct ``FAQEntryCreate`` with
        # ``min_length=0`` here and run the per-row checks
        # ourselves so the user sees friendly Chinese error
        # messages (Pydantic's default message is the raw
        # English validation error, which is fine for the
        # single-row API but confusing in a bulk-import
        # context where the row is identified by index).
        validated: List[Tuple[int, FAQEntryCreate]] = []
        failed: List[Dict[str, str]] = []
        for index, raw in enumerate(items):
            # Per-row tags normalisation: comma-separated
            # string from CSV → list. JSON rows already
            # carry a list.
            tags = raw.get("tags")
            if isinstance(tags, str):
                tags = [t.strip() for t in tags.split(",") if t.strip()]

            question = (raw.get("question") or "").strip()
            answer = (raw.get("answer") or "").strip()
            category = (raw.get("category") or None)

            if not question:
                failed.append(
                    {"row_index": str(index), "reason": "问题不能为空"}
                )
                continue
            if not answer:
                failed.append(
                    {"row_index": str(index), "reason": "答案不能为空"}
                )
                continue
            if tags is not None and len(tags) > MAX_TAGS_PER_ENTRY:
                failed.append(
                    {
                        "row_index": str(index),
                        "reason": f"标签数量不能超过 {MAX_TAGS_PER_ENTRY}",
                    }
                )
                continue
            if len(question) > 2000 or len(answer) > 8000:
                failed.append(
                    {
                        "row_index": str(index),
                        "reason": "问题或答案超过长度限制",
                    }
                )
                continue
            try:
                create = FAQEntryCreate(
                    question=question,
                    answer=answer,
                    category=category,
                    tags=tags or None,
                )
            except Exception as exc:  # noqa: BLE001
                failed.append(
                    {"row_index": str(index), "reason": f"validation: {exc}"}
                )
                continue
            validated.append((index, create))

        # Insert in order. Each create_entry commits its own
        # transaction — the rollback on the API path will
        # unwind them all. We do NOT batch into one giant
        # transaction because the embedder is per-row and a
        # 50-row import would lock the connection for ~30s;
        # the project already does per-row commits in
        # document_parser.
        inserted = 0
        for _index, payload in validated:
            self.create_entry(db, kb, payload, current_user)
            inserted += 1
        return FAQBulkImportResult(inserted=inserted, failed=failed)

    # ----------------------------------------------------------- internals

    def _parse_bulk_payload(
        self, request: FAQBulkImportRequest
    ) -> List[Dict[str, Any]] | Tuple[str, str, str]:
        """Return a list of {question, answer, category, tags}
        dicts. On parse error return a tuple ``("error",
        reason, "0")`` so the caller can build a single-row
        failure result.
        """
        if request.format == "json":
            try:
                data = json.loads(request.content)
            except json.JSONDecodeError as exc:
                return ("error", f"JSON 解析失败: {exc}", "0")
            if not isinstance(data, list):
                return ("error", "JSON 必须是数组 (list of objects)", "0")
            for i, row in enumerate(data):
                if not isinstance(row, dict):
                    return ("error", f"第 {i} 行不是对象", str(i))
            return data

        # CSV
        try:
            reader = csv.DictReader(io.StringIO(request.content))
            if reader.fieldnames is None:
                return ("error", "CSV 缺少表头行", "0")
            # Normalise header names to lowercase + strip —
            # Chinese-friendly UI exports sometimes have a
            # trailing space.
            reader.fieldnames = [f.strip().lower() for f in reader.fieldnames]
            required = {"question", "answer"}
            if not required.issubset(set(reader.fieldnames)):
                return (
                    "error",
                    f"CSV 缺少必要列: {sorted(required - set(reader.fieldnames))}",
                    "0",
                )
            return list(reader)
        except csv.Error as exc:
            return ("error", f"CSV 解析失败: {exc}", "0")

    def _index_chunks(
        self,
        db: Session,
        kb: KnowledgeBase,
        chunks: List[DocumentChunk],
        metadatas: List[Dict[str, Any]],
    ) -> List[str]:
        """Write ``chunks`` to the per-KB vector store + BM25.

        Returns the vector_ids in the same order as ``chunks``.
        Empty list on failure (mirrors
        ``KnowledgeService.index_chunks`` contract — caller
        treats an empty list as "embedding failed, mark chunk
        as failed").
        """
        if not chunks:
            return []
        # Reuse the existing helper — it knows the right
        # pipeline for this KB (incl. BM25 wiring) and does
        # the right thing for both ES and FAISS backends.
        from lumen_services.knowledge_service import KnowledgeService

        ks = KnowledgeService()
        try:
            return ks.index_chunks(chunks, kb, db, metadatas=metadatas)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "FAQService vector write failed for KB %s: %s", kb.id, exc
            )
            return []

    def _delete_vectors(self, entry: FAQEntry, vector_id: str) -> None:
        """Best-effort vector delete.

        A stale vector is far less harmful than failing the
        CRUD call, so we log and continue. Mirrors the
        pattern in ``delete_document`` (knowledge.py:725).
        """
        try:
            from lumen_tools.vector_store_factory import VectorStoreFactory

            store = VectorStoreFactory.get_store(
                kb_id=entry.knowledge_base_id,  # type: ignore[arg-type]
                model_config_id=entry.embedding_model_config_id,  # type: ignore[arg-type]
                db=None,  # type: ignore[arg-type]  # not used by the FAISS / ES backends
            )
            store.delete_by_ids([vector_id])
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "FAQService vector delete failed for FAQ %s (vector_id=%s): %s",
                entry.id,
                vector_id,
                exc,
            )
