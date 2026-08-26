from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form
from sqlalchemy.orm import Session
from typing import List, Optional
import logging
from lumen_core.database import get_db

logger = logging.getLogger(__name__)
from lumen_api.v1.auth import get_current_user
from lumen_models.user import User
from lumen_schemas.knowledge import (
    KnowledgeBaseCreate, KnowledgeBaseUpdate, KnowledgeBaseResponse,
    DocumentResponse, ChunkResponse, RechunkRequest,
    FAQEntryCreate, FAQEntryUpdate, FAQEntryResponse,
    FAQBulkImportRequest, FAQBulkImportResult,
)
from lumen_schemas.common import SingleResponse, PaginatedResponse
from lumen_services.knowledge_service import KnowledgeService, KnowledgeBaseNotEmptyError
from lumen_tools.vector_store_factory import VectorStoreFactory
import os
import re
import json

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


def sanitize_filename(filename: str) -> str:
    """Sanitize filename to prevent path traversal"""
    # Remove path components, keep only basename
    filename = os.path.basename(filename)
    # Replace any remaining path separators
    filename = filename.replace('/', '').replace('\\', '')
    # Remove any non-alphanumeric characters except dot, dash, underscore
    filename = re.sub(r'[^\w\-.]', '_', filename)
    return filename or 'unnamed_file'


@router.get("/", response_model=PaginatedResponse[KnowledgeBaseResponse])
async def list_knowledge_bases(
    page: int = 1,
    page_size: int = 10,
    # M38.2: optional workspace filter. ``workspace_id=-1`` (default)
    # means "all KBs in this tenant regardless of workspace". Any
    # other value restricts to that workspace; ``0`` means "KBs
    # hanging directly off the tenant" (workspace_id IS NULL).
    workspace_id: int = Query(
        -1,
        description="M38.2 workspace 过滤;-1 = 全部;0 = 直属 tenant;>0 = 指定 workspace",
    ),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    from lumen_models.knowledge import KnowledgeBase
    service = KnowledgeService()
    # Service still returns all KBs in the tenant; we filter
    # here so the service signature stays simple and matches the
    # existing pattern in list_documents.
    kbs = service.list_knowledge_bases(db, current_user.tenant_id)
    if workspace_id == 0:
        kbs = [kb for kb in kbs if kb.workspace_id is None]
    elif workspace_id > 0:
        kbs = [kb for kb in kbs if kb.workspace_id == workspace_id]
    total = len(kbs)
    start = (page - 1) * page_size
    end = start + page_size
    return PaginatedResponse(
        data=[KnowledgeBaseResponse.model_validate(kb) for kb in kbs[start:end]],
        total=total,
        page=page,
        page_size=page_size
    )


@router.get("/parser-types")
async def get_parser_types(
    current_user: User = Depends(get_current_user)
):
    """Get available document parser types."""
    from lumen_services.parsers import DocumentParserFactory
    return {
        "parser_types": DocumentParserFactory.get_available_types(),
        "chunking_strategies": KnowledgeService().get_chunking_strategies()
    }


@router.post("/", response_model=SingleResponse[KnowledgeBaseResponse])
async def create_knowledge_base(
    data: KnowledgeBaseCreate,
    # M38.2: optional workspace binding. When set, the workspace
    # must belong to the caller's tenant. We validate here
    # rather than in the service so the 404/403 stays inside the
    # tenant-isolation contract.
    workspace_id: Optional[int] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if workspace_id is not None:
        from lumen_models.workspace import Workspace
        ws = db.get(Workspace, workspace_id)
        if ws is None:
            raise HTTPException(status_code=400, detail="workspace 不存在")
        if ws.tenant_id != current_user.tenant_id and not getattr(current_user, "is_superuser", False):
            raise HTTPException(
                status_code=403,
                detail="workspace 不属于当前租户",
            )
    service = KnowledgeService()
    kb = service.create_knowledge_base(db, current_user.tenant_id, data)
    if workspace_id is not None:
        kb.workspace_id = workspace_id
        db.commit()
        db.refresh(kb)
    return SingleResponse(data=KnowledgeBaseResponse.model_validate(kb))


@router.get("/{kb_id}", response_model=SingleResponse[KnowledgeBaseResponse])
async def get_knowledge_base(
    kb_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    from lumen_models.knowledge import KnowledgeBase
    kb = db.query(KnowledgeBase).filter(
        KnowledgeBase.id == kb_id,
        KnowledgeBase.tenant_id == current_user.tenant_id
    ).first()
    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    return SingleResponse(data=KnowledgeBaseResponse.model_validate(kb))


@router.put("/{kb_id}", response_model=SingleResponse[KnowledgeBaseResponse])
async def update_knowledge_base(
    kb_id: int,
    data: KnowledgeBaseUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    service = KnowledgeService()
    kb = service.update_knowledge_base(db, kb_id, current_user.tenant_id, data)
    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    return SingleResponse(data=KnowledgeBaseResponse.model_validate(kb))


@router.delete("/{kb_id}")
async def delete_knowledge_base(
    kb_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # M21: 引用计数 (agent + document) — 在走 service 之前先拦截,
    # 避免走到 DB 层才被 FK constraint 500。先做轻量 count,再走原逻辑。
    from sqlalchemy import func, select

    from lumen_models.agent import AgentKnowledgeBase
    from lumen_models.knowledge import Document

    # Count first (cheap) — but also pull the actual IDs/names of the
    # blockers so the frontend can tell the user "unbind agent X / delete
    # document Y first" instead of just a bare count. Capped at 10 per
    # category to bound response size; `truncated` flag tells the UI
    # there's more than what we sent.
    from lumen_models.agent import Agent

    agent_count = db.scalar(
        select(func.count())
        .select_from(AgentKnowledgeBase)
        .where(AgentKnowledgeBase.knowledge_base_id == kb_id)
    ) or 0
    document_count = db.scalar(
        select(func.count())
        .select_from(Document)
        .where(Document.knowledge_base_id == kb_id)
    ) or 0

    if agent_count > 0 or document_count > 0:
        blocking_agents: list[dict] = []
        if agent_count > 0:
            blocking_agents = [
                {"id": row[0], "name": row[1]}
                for row in db.execute(
                    select(Agent.id, Agent.name)
                    .join(AgentKnowledgeBase, AgentKnowledgeBase.agent_id == Agent.id)
                    .where(AgentKnowledgeBase.knowledge_base_id == kb_id)
                    .order_by(Agent.id)
                    .limit(10)
                ).all()
            ]
        blocking_documents: list[dict] = []
        if document_count > 0:
            blocking_documents = [
                {"id": row[0], "filename": row[1]}
                for row in db.execute(
                    select(Document.id, Document.filename)
                    .where(Document.knowledge_base_id == kb_id)
                    .order_by(Document.id)
                    .limit(10)
                ).all()
            ]
        raise HTTPException(
            status_code=422,
            detail={
                "message": (
                    f"KB 仍被 {agent_count} 个 agent 和 {document_count} 个文档引用,"
                    "需先解绑/删除"
                ),
                "agent_count": agent_count,
                "document_count": document_count,
                "blocking_agents": blocking_agents,
                "blocking_documents": blocking_documents,
                "truncated": agent_count > 10 or document_count > 10,
            },
        )

    service = KnowledgeService()
    try:
        success = service.delete_knowledge_base(db, kb_id, current_user.tenant_id)
    except KnowledgeBaseNotEmptyError as exc:
        # 400 instead of 404 so the frontend can distinguish "you
        # forgot to clean up first" from "this KB doesn't exist".
        raise HTTPException(status_code=400, detail=str(exc))
    if not success:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    return SingleResponse(message="Deleted successfully")


@router.post("/{kb_id}/documents")
async def upload_document(
    kb_id: int,
    file: UploadFile = File(...),
    chunking_strategy: str = Form("fixed", description="分块策略: fixed, semantic, document_structure"),
    chunking_params: str = Form("{}", description="分块参数 JSON"),
    doc_type: str = Form(None, description="文档类型: general, paper, qa, table, manual, laws (auto-detect if not specified)"),
    async_process: bool = Form(True, description="是否异步处理文档"),
    # M38.2: optional target folder. ``None`` = KB root
    # (backward-compatible default). Service-layer validation
    # ensures the folder belongs to the same KB.
    folder_id: Optional[int] = Form(None, description="M38.2 目标 folder id; 不传 = KB 根"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    from lumen_models.knowledge import KnowledgeBase, Document
    from lumen_models.tenant import Tenant  # Import Tenant to resolve SQLAlchemy relationship
    from lumen_core.config import settings

    kb = db.query(KnowledgeBase).filter(
        KnowledgeBase.id == kb_id,
        KnowledgeBase.tenant_id == current_user.tenant_id
    ).first()
    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge base not found")

    # M38.2: validate the optional target folder. Reuses the
    # service-layer helper so we don't duplicate the cycle /
    # deleted-folder checks.
    if folder_id is not None:
        from lumen_models.workspace import DocumentFolder
        folder = db.get(DocumentFolder, folder_id)
        if folder is None:
            raise HTTPException(status_code=400, detail="目标 folder 不存在")
        if folder.knowledge_base_id != kb_id:
            raise HTTPException(
                status_code=400,
                detail="目标 folder 不属于该 KB",
            )
        if folder.deleted_at is not None:
            raise HTTPException(status_code=400, detail="目标 folder 已软删")

    # M38.1: route the write through the storage backend abstraction.
    # The key shape is ``uploads/<tenant>/<kb>/<filename>`` — for the
    # default LocalBackend this resolves to the pre-M38.1 path
    # (``./data/uploads/...``) so parsers that still ``open(file_path)``
    # find the same bytes. ``file_path`` keeps the legacy shape for
    # backwards compatibility; ``asset_storage_key`` / ``storage_backend``
    # record the M38.1 source of truth.
    from lumen_services.storage import get_storage_backend
    storage = get_storage_backend()
    safe_filename = sanitize_filename(file.filename)
    asset_storage_key = f"uploads/{current_user.tenant_id}/{kb_id}/{safe_filename}"
    content = await file.read()
    storage.put_object(asset_storage_key, content)

    # file_path stays as the legacy ``data/uploads/<tenant>/<kb>/<filename>``
    # string — LocalBackend.root defaults to ``./data`` so parsers'
    # ``open(file_path)`` resolves to the same bytes storage put.
    # For s3 backend the file_path is a logical placeholder; the actual
    # bytes live in S3 and parsers must be refactored to read via
    # storage.get_object_stream (M38.x follow-up; see spec §10 risk).
    file_path = f"data/{asset_storage_key}"

    # Create document record
    doc = Document(
        filename=file.filename,
        file_path=file_path,
        file_type=(file.content_type or "application/octet-stream")[:100],
        file_size=len(content),
        status="pending",
        knowledge_base_id=kb_id,
        # M38.2: persist the optional folder binding so the doc
        # appears in the right place in the sidebar.
        folder_id=folder_id,
        created_by=current_user.id,
        # M38.1: record which backend produced the bytes + the key it
        # wrote under. ``asset_storage_key`` is the source of truth
        # for the storage layer; ``file_path`` is kept around for
        # parsers that still ``open(file_path)`` against the local
        # disk. See spec §5.4 for the read precedence rule.
        asset_storage_key=asset_storage_key,
        storage_backend=storage.backend_name,
        # Copy the KB's embedder FK onto the doc so the async worker
        # (and retry/rechunk/delete paths, all of which read
        # ``doc.embedding_model_config_id``) can resolve the embedder
        # without falling back to the KB row. See MEMORY.md /
        # 2026-06-08 incident: leaving this NULL produced
        # ``ValueError: ModelConfig None not found`` on first embed.
        embedding_model_config_id=kb.embedding_model_config_id,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    # Parse chunking params
    try:
        params = json.loads(chunking_params) if chunking_params else {}
    except json.JSONDecodeError:
        params = {}

    # Check if async processing is enabled
    async_enabled = settings.ASYNC_ENABLED and async_process

    if async_enabled:
        # Queue async task
        from lumen_tasks.document_tasks import process_document_task
        task_params = {
            "document_id": doc.id,
            "file_path": file_path,
            "file_content_type": file.content_type or "application/octet-stream",
            "tenant_id": current_user.tenant_id,
            "kb_id": kb_id,
            "chunking_strategy": chunking_strategy,
            "chunking_params": params,
            "doc_type": doc_type,
            "user_id": current_user.id,
        }
        task = process_document_task.delay(task_params)
        doc.status = "queued"
        doc.doc_metadata = {"doc_type": doc_type} if doc_type else {}
        db.commit()

        return SingleResponse(data={
            "document_id": doc.id,
            "task_id": task.id,
            "status": "queued",
            "message": "Document queued for processing"
        })
    else:
        # Sync processing (original behavior)
        from lumen_services.document_parser import DocumentParser
        parser = DocumentParser()
        parse_result = parser.parse(file_path, file.content_type, doc_type=doc_type)
        text_content = parse_result.get("text", "")
        parse_error = (parse_result.get("metadata") or {}).get("parse_error")

        if not text_content or parse_error:
            reason = parse_error or "parser produced no text"
            doc.status = "failed"
            doc.error_message = f"解析失败: {reason}"
            doc.chunk_count = 0
            db.commit()
            return SingleResponse(data=DocumentResponse.model_validate(doc))

        # Use chunks from parser if available
        chunks_data = parse_result.get("chunks", [])

        if chunks_data:
            # Create chunks from parser results
            from lumen_models.knowledge import DocumentChunk
            chunks = []
            for chunk_info in chunks_data:
                chunk = DocumentChunk(
                    content=chunk_info["content"],
                    chunk_index=chunk_info["chunk_index"],
                    document_id=doc.id,
                    chunk_metadata={
                        "tenant_id": current_user.tenant_id,
                        "strategy": chunk_info.get("strategy", "parser"),
                        "length": chunk_info.get("length", 0)
                    },
                    embedding_status="ok",
                )
                db.add(chunk)
                chunks.append(chunk)
            db.commit()
        else:
            # Fallback to manual chunking
            service = KnowledgeService()
            chunks = service.process_document(
                db, doc.id, text_content, current_user.tenant_id,
                chunking_strategy=chunking_strategy,
                chunking_params=params
            )
            for c in chunks:
                c.embedding_status = "ok"

        # Store in vector store
        try:
            vector_store = VectorStoreFactory.get_store(
                kb_id=kb_id,
                model_config_id=kb.embedding_model_config_id,
                db=db,
            )
            texts = [c.content for c in chunks]
            metadatas = [
                {"chunk_id": c.id, "document_id": doc.id, "tenant_id": current_user.tenant_id, "kb_id": kb_id}
                for c in chunks
            ]
            vector_ids = vector_store.add_texts(texts, metadatas)
            for chunk, vid in zip(chunks, vector_ids):
                chunk.vector_id = vid
            db.commit()
        except Exception as e:
            logger.warning("Vector store failed, chunks saved to DB only: %s", e)
            # Mirror the async-path failure: mark every chunk as
            # 'failed' so search won't return them, and surface the
            # error on the Document row.
            for chunk in chunks:
                chunk.embedding_status = "failed"
                chunk.vector_id = f"error_{chunk.id}"
            doc.status = "failed"
            doc.error_message = f"向量化失败: {type(e).__name__}: {e}"
            db.commit()
            return SingleResponse(data=DocumentResponse.model_validate(doc))

        doc.status = "completed"
        doc.chunk_count = len(chunks)
        db.commit()

        # Also feed chunks into the BM25 index via the new retrieval pipeline
        # so that hybrid (lexical + semantic) search is available. Failures
        # here are non-fatal: the vector path is already populated.
        try:
            from lumen_services.retrieval import get_retrieval_pipeline
            pipeline = get_retrieval_pipeline(
                kb_id=kb.id,
                model_config_id=kb.embedding_model_config_id,
                db=db,
            )
            bm25_metas = [
                {
                    "chunk_id": c.id,
                    "document_id": doc.id,
                    "tenant_id": current_user.tenant_id,
                    "kb_id": kb_id,
                }
                for c in chunks
            ]
            pipeline.bm25_index.add_texts(
                texts=texts, metadatas=bm25_metas
            )
            try:
                pipeline.bm25_index.save()
            except Exception:
                pass
        except Exception as e:
            logger.warning("BM25 index update failed (non-fatal): %s", e)

        return SingleResponse(data=DocumentResponse.model_validate(doc))


@router.get("/count")
async def count_knowledge_bases(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    from lumen_models.knowledge import KnowledgeBase
    count = db.query(KnowledgeBase).filter(
        KnowledgeBase.tenant_id == current_user.tenant_id
    ).count()
    return {"count": count}


@router.get("/{kb_id}/documents", response_model=SingleResponse[List[DocumentResponse]])
async def list_documents(
    kb_id: int,
    # M38.2: filter by folder. ``None`` (default) = KB root +
    # all sub-folders flattened. Pass ``?folder_id=0`` explicitly
    # for KB root only. The sentinel ``-1`` means "no filter"
    # (same as ``None``) — kept for backward compat with the
    # legacy sidebar that sent ``-1`` as "all".
    folder_id: Optional[int] = Query(
        None,
        description="M38.2 folder filter; 0 = KB root, -1/None = 全部",
    ),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    from lumen_models.knowledge import KnowledgeBase, Document
    kb = db.query(KnowledgeBase).filter(
        KnowledgeBase.id == kb_id,
        KnowledgeBase.tenant_id == current_user.tenant_id
    ).first()
    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge base not found")

    # M31: hide FAQ virtual docs from the "已上传文档" list.
    # They are stored as ``Document`` rows with
    # ``doc_metadata.doc_type == "qa_pair"`` so the FAQ CRUD
    # path can reuse the same chunk table, but a UI looking
    # at the documents tab doesn't want to see them.
    #
    # We use a raw ``JSON_UNQUOTE(JSON_EXTRACT(...))`` in a
    # NOT IN subquery rather than the SQLAlchemy ``.astext``
    # JSON operator because the latter raises
    # ``AttributeError: Neither 'BinaryExpression' object nor
    # 'Comparator' object has an attribute 'astext'`` on the
    # installed dialect version.
    #
    # ``JSON_UNQUOTE`` strips the JSON-string surrounding
    # quotes (``"qa_pair"`` → ``qa_pair``), so the comparison
    # can be a plain string equality.
    from sqlalchemy import text as sa_text
    faq_doc_ids_subq = (
        db.query(Document.id)
        .filter(Document.knowledge_base_id == kb_id)
        .filter(
            sa_text(
                "JSON_UNQUOTE(JSON_EXTRACT(documents.doc_metadata, '$.doc_type')) = 'qa_pair'"
            )
        )
    )
    doc_query = (
        db.query(Document)
        .filter(Document.knowledge_base_id == kb_id)
        .filter(~Document.id.in_(faq_doc_ids_subq))
    )
    # M38.2: folder filter. ``0`` = KB root only (folder_id IS NULL);
    # ``-1`` or ``None`` = no filter (return everything in this KB).
    # Positive folder ids = restrict to that folder.
    if folder_id is not None and folder_id >= 0:
        if folder_id == 0:
            doc_query = doc_query.filter(Document.folder_id.is_(None))
        elif folder_id > 0:
            doc_query = doc_query.filter(Document.folder_id == folder_id)
    docs = doc_query.order_by(Document.created_at.desc()).all()
    return SingleResponse(data=[DocumentResponse.model_validate(d) for d in docs])


@router.get("/documents/{document_id}/status")
async def get_document_status(
    document_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get document processing status."""
    from lumen_models.knowledge import Document
    doc = db.query(Document).filter(
        Document.id == document_id,
        Document.knowledge_base.has(tenant_id=current_user.tenant_id)
    ).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    return SingleResponse(data={
        "document_id": doc.id,
        "status": doc.status,
        "chunk_count": doc.chunk_count,
        "error_message": doc.error_message
    })


@router.post("/documents/{document_id}/retry", response_model=SingleResponse[DocumentResponse])
async def retry_document(
    document_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Re-queue a stuck document for processing.

    Valid for documents whose current status is ``pending``,
    ``queued``, or ``processing`` — i.e. documents that never made
    it to ``completed``. For ``completed`` or ``failed`` documents
    the user should delete and re-upload instead; re-running a
    completed document would duplicate its chunks in the vector
    store.

    Cleanup: any leftover ``DocumentChunk`` rows from a prior
    attempt are deleted (and their FAISS vector IDs are removed
    best-effort) so the worker doesn't write duplicates.
    """
    from lumen_models.knowledge import Document, DocumentChunk
    from lumen_tasks.document_tasks import process_document_task

    doc = db.query(Document).filter(
        Document.id == document_id,
        Document.knowledge_base.has(tenant_id=current_user.tenant_id)
    ).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    if doc.status not in ("pending", "queued", "processing"):
        raise HTTPException(
            status_code=400,
            detail=f"文档状态为 '{doc.status}'，不支持重试。请删除后重新上传。"
        )

    if not doc.file_path or not os.path.exists(doc.file_path):
        raise HTTPException(
            status_code=400,
            detail="原始文件已丢失，无法重试。请删除后重新上传。"
        )

    # Drop any leftover chunks/vectors from a prior attempt. The worker
    # doesn't check for existing chunks before writing, so leaving them
    # in place would result in duplicates on the next run.
    old_chunks = (
        db.query(DocumentChunk)
        .filter(DocumentChunk.document_id == doc.id)
        .all()
    )
    old_vector_ids = [c.vector_id for c in old_chunks if c.vector_id]
    for chunk in old_chunks:
        db.delete(chunk)
    if old_chunks:
        db.commit()
    if old_vector_ids:
        try:
            VectorStoreFactory.get_store(
                kb_id=doc.knowledge_base_id,
                model_config_id=doc.embedding_model_config_id,
                db=db,
            ).delete_by_ids(old_vector_ids)
        except Exception as e:
            # Stale vectors in the index are far less harmful than
            # failing the retry, so we log and continue. The BM25
            # index is not touched here (no delete API); stale BM25
            # entries will be re-written on success.
            logger.warning("failed to delete stale vectors for doc %s: %s", doc.id, e)

    # Reset doc state and re-enqueue. The original upload's chunking
    # strategy isn't persisted on the doc row, so we fall back to the
    # KB's chunk_size/chunk_overlap with a fixed strategy.
    doc.status = "pending"
    doc.error_message = None
    doc.chunk_count = None
    db.commit()
    db.refresh(doc)

    doc_type = (doc.doc_metadata or {}).get("doc_type")
    kb = doc.knowledge_base
    chunking_params: dict = {}
    if kb and kb.chunk_size:
        chunking_params["chunk_size"] = kb.chunk_size
    if kb and kb.chunk_overlap is not None:
        chunking_params["chunk_overlap"] = kb.chunk_overlap

    task_params = {
        "document_id": doc.id,
        "file_path": doc.file_path,
        "file_content_type": doc.file_type or "application/octet-stream",
        "tenant_id": current_user.tenant_id,
        "kb_id": doc.knowledge_base_id,
        "chunking_strategy": "fixed",
        "chunking_params": chunking_params,
        "doc_type": doc_type,
        "user_id": current_user.id,
    }
    process_document_task.delay(task_params)
    doc.status = "queued"
    db.commit()
    db.refresh(doc)

    return SingleResponse(data=DocumentResponse.model_validate(doc))


@router.get("/documents/{document_id}/chunks", response_model=SingleResponse[List[ChunkResponse]])
async def list_document_chunks(
    document_id: int,
    page: int = 1,
    page_size: int = 50,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """List the chunks of a document, paginated and ordered by index.

    Tenant-scoped via the doc's parent knowledge base. Returns
    ``[]`` (not 404) if the document has no chunks yet — a doc in
    ``pending``/``queued``/``processing`` state has rows in the
    ``documents`` table but its chunks haven't been written.
    """
    from lumen_models.knowledge import Document, DocumentChunk

    doc = db.query(Document).filter(
        Document.id == document_id,
        Document.knowledge_base.has(tenant_id=current_user.tenant_id)
    ).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    start = (page - 1) * page_size
    chunks = (
        db.query(DocumentChunk)
        .filter(DocumentChunk.document_id == document_id)
        .order_by(DocumentChunk.chunk_index.asc(), DocumentChunk.id.asc())
        .offset(start)
        .limit(page_size)
        .all()
    )
    return SingleResponse(data=[ChunkResponse.model_validate(c) for c in chunks])


@router.post("/documents/{document_id}/rechunk", response_model=SingleResponse[DocumentResponse])
async def rechunk_document(
    document_id: int,
    body: RechunkRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Re-process a document with user-supplied chunking settings.

    Unlike :func:`retry_document` — which is meant for documents
    stuck in ``pending``/``queued``/``processing`` and uses the
    parent KB's defaults — ``rechunk`` is for *any* state (typically
    ``completed``) and lets the caller override the chunking
    strategy, chunk size, chunk overlap, and doc type for this
    specific document.

    Cleanup is the same as ``retry``: existing chunks are deleted
    and their FAISS vector IDs are removed best-effort before the
    worker is enqueued.
    """
    from lumen_models.knowledge import Document, DocumentChunk
    from lumen_tasks.document_tasks import process_document_task

    doc = db.query(Document).filter(
        Document.id == document_id,
        Document.knowledge_base.has(tenant_id=current_user.tenant_id)
    ).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    if not doc.file_path or not os.path.exists(doc.file_path):
        raise HTTPException(
            status_code=400,
            detail="原始文件已丢失，无法重新分块。请删除后重新上传。"
        )

    # Drop existing chunks/vectors so the worker doesn't duplicate.
    old_chunks = (
        db.query(DocumentChunk)
        .filter(DocumentChunk.document_id == doc.id)
        .all()
    )
    old_vector_ids = [c.vector_id for c in old_chunks if c.vector_id]
    for chunk in old_chunks:
        db.delete(chunk)
    if old_chunks:
        db.commit()
    if old_vector_ids:
        try:
            VectorStoreFactory.get_store(
                kb_id=doc.knowledge_base_id,
                model_config_id=doc.embedding_model_config_id,
                db=db,
            ).delete_by_ids(old_vector_ids)
        except Exception as e:
            logger.warning("failed to delete stale vectors for doc %s: %s", doc.id, e)

    # Resolve final chunking settings: body overrides > KB defaults.
    kb = doc.knowledge_base
    chunk_size = body.chunk_size if body.chunk_size is not None else (kb.chunk_size if kb else 500)
    chunk_overlap = body.chunk_overlap if body.chunk_overlap is not None else (kb.chunk_overlap if kb else 50)
    chunking_strategy = body.chunking_strategy or "fixed"
    doc_type = body.doc_type if body.doc_type is not None else (doc.doc_metadata or {}).get("doc_type")

    # Reset doc state.
    doc.status = "pending"
    doc.error_message = None
    doc.chunk_count = None
    # Persist the new doc_type so future retries don't lose it.
    if doc_type is not None:
        existing_meta = dict(doc.doc_metadata or {})
        existing_meta["doc_type"] = doc_type
        doc.doc_metadata = existing_meta
    db.commit()
    db.refresh(doc)

    task_params = {
        "document_id": doc.id,
        "file_path": doc.file_path,
        "file_content_type": doc.file_type or "application/octet-stream",
        "tenant_id": current_user.tenant_id,
        "kb_id": doc.knowledge_base_id,
        "chunking_strategy": chunking_strategy,
        "chunking_params": {
            "chunk_size": chunk_size,
            "chunk_overlap": chunk_overlap,
        },
        "doc_type": doc_type,
        "user_id": current_user.id,
    }
    process_document_task.delay(task_params)
    doc.status = "queued"
    db.commit()
    db.refresh(doc)

    return SingleResponse(data=DocumentResponse.model_validate(doc))


@router.post("/documents/{document_id}/move", response_model=SingleResponse[dict])
async def move_document(
    document_id: int,
    # ``folder_id=None`` means "move to KB root". Use a JSON
    # body so the field name matches the spec; FastAPI's
    # ``Body(..., embed=True)`` keeps the wire shape flat.
    payload: Optional[dict] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """M38.2: move a document into a folder (or KB root when null).

    Body shape: ``{"folder_id": 5}`` or ``{"folder_id": null}``.
    Tenant isolation is enforced via the doc's parent KB.
    """
    from lumen_services.folder_service import folder_service
    target = (payload or {}).get("folder_id")
    moved = folder_service.move_document(
        db,
        document_id=document_id,
        target_folder_id=target,
        tenant_id=current_user.tenant_id,
        is_superuser=bool(getattr(current_user, "is_superuser", False)),
    )
    if not moved:
        raise HTTPException(status_code=404, detail="Document not found")
    return SingleResponse(data={"document_id": document_id, "folder_id": target})


@router.delete("/documents/{document_id}", response_model=SingleResponse[dict])
async def delete_document(
    document_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Delete a document, its chunks, and its FAISS vectors.

    Tenant-scoped via the doc's parent knowledge base. The uploaded
    file on disk is intentionally left in place because we don't
    track reference counts — if the same filename was uploaded
    multiple times, deleting the file would break sibling docs. A
    separate janitor pass can sweep orphaned files.

    FAISS cleanup is best-effort: a stale vector is far less harmful
    than failing the delete, so we log and continue. The BM25 index
    doesn't expose a delete API; stale BM25 entries will still match
    on raw terms but their ``document_id`` won't point to a valid doc
    row, so the user-facing search hits will be wrong (ranked but
    pointing at deleted text). Re-indexing the KB is the long-term
    fix; for now the symptom is a few extra junk hits.
    """
    from lumen_models.knowledge import Document, DocumentChunk

    doc = db.query(Document).filter(
        Document.id == document_id,
        Document.knowledge_base.has(tenant_id=current_user.tenant_id)
    ).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # Capture FAISS ids before deleting chunks.
    old_chunks = (
        db.query(DocumentChunk)
        .filter(DocumentChunk.document_id == doc.id)
        .all()
    )
    old_vector_ids = [c.vector_id for c in old_chunks if c.vector_id]
    deleted_chunks = len(old_chunks)

    for chunk in old_chunks:
        db.delete(chunk)
    db.delete(doc)
    db.commit()

    vector_cleanup_failed = False
    if old_vector_ids:
        try:
            VectorStoreFactory.get_store(
                kb_id=doc.knowledge_base_id,
                model_config_id=doc.embedding_model_config_id,
                db=db,
            ).delete_by_ids(old_vector_ids)
        except Exception as e:
            vector_cleanup_failed = True
            logger.warning("failed to delete FAISS vectors for doc %s: %s", document_id, e)

    return SingleResponse(data={
        "document_id": document_id,
        "deleted_chunks": deleted_chunks,
        "vector_cleanup_failed": vector_cleanup_failed,
    })


@router.get("/tasks/{task_id}")
async def get_task_status(
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get async task status from Celery."""
    from lumen_core.config import settings

    if not settings.ASYNC_ENABLED:
        raise HTTPException(status_code=404, detail="Async processing not enabled")

    from celery.result import AsyncResult
    from lumen_tasks.celery_app import celery_app

    result = AsyncResult(task_id, app=celery_app)

    response = {
        "task_id": task_id,
        "status": result.status,
        "ready": result.ready(),
        "successful": result.successful() if result.ready() else None
    }

    if result.ready():
        response["result"] = result.result
    else:
        # Check if task has started but not finished
        response["info"] = str(result.info) if result.info else None

    return response


@router.get("/{kb_id}/search")
async def search_knowledge_base(
    kb_id: int,
    query: str,
    k: int = 5,
    alpha: float = 0.5,
    rerank: bool = True,
    rerank_top_n: int = 10,
    field_weights: str = Form(None, description="JSON string of field weights, e.g. '{\"title\":10.0,\"text\":2.0}'"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    from lumen_models.knowledge import KnowledgeBase
    kb = db.query(KnowledgeBase).filter(
        KnowledgeBase.id == kb_id,
        KnowledgeBase.tenant_id == current_user.tenant_id
    ).first()
    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge base not found")

    # Parse field_weights if provided
    weights = None
    if field_weights:
        try:
            weights = json.loads(field_weights)
        except json.JSONDecodeError:
            pass  # Use default weights

    # Use the new retrieval pipeline (vector + BM25 -> RRF -> rerank -> top-K).
    # Falls back to the legacy vector_store.rerank_search path if the
    # pipeline cannot be built (e.g. FAISS/ES not available).
    from lumen_services.retrieval import get_retrieval_pipeline
    try:
        pipeline = get_retrieval_pipeline(
            kb_id=kb_id,
            model_config_id=kb.embedding_model_config_id,
            db=db,
        )
        # Honour the legacy ``alpha`` parameter by updating the combiner
        # weights for this call. The legacy parameter is still meaningful
        # because it controls the relative weight of vector vs BM25.
        try:
            pipeline.hybrid_retriever.vector_weight = float(alpha)
            pipeline.hybrid_retriever.bm25_weight = float(1.0 - alpha)
        except Exception:
            pass
        # Temporarily override rerank_top_n so the reranker can pull more
        # candidates than the legacy code did.
        original_top_n = pipeline.rerank_top_n
        try:
            pipeline.rerank_top_n = max(int(rerank_top_n), k)
        except Exception:
            pass
        try:
            filter_expr = f'tenant_id == {current_user.tenant_id} and kb_id == {kb_id}'
            # M28: per-request ``field_weights`` (ad-hoc override) wins over
            # the KB row's ``search_weights``. If neither is set, ES falls
            # back to its class defaults inside ``hybrid_search``.
            resolved_weights = weights if weights else kb.search_weights
            results = pipeline.search(
                query=query,
                k=k,
                filter_expr=filter_expr,
                rerank=rerank,
                search_weights=resolved_weights,
            )
        finally:
            try:
                pipeline.rerank_top_n = original_top_n
            except Exception:
                pass
    except Exception:
        # Defensive fallback to the previous behaviour
        vector_store = VectorStoreFactory.get_store(
            kb_id=kb_id,
            model_config_id=kb.embedding_model_config_id,
            db=db,
        )
        filter_expr = f'tenant_id == {current_user.tenant_id} and kb_id == {kb_id}'
        results = vector_store.rerank_search(
            query, k=k, alpha=alpha, filter_expr=filter_expr,
            rerank=rerank, rerank_top_n=rerank_top_n,
            field_weights=weights
        )

    return SingleResponse(data=results)


@router.get("/{kb_id}/search/compare")
async def compare_search_strategies(
    kb_id: int,
    query: str,
    k: int = 5,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Diagnostic endpoint: run the query through vector-only, hybrid, and
    hybrid+rerank and return the top-K from each so the caller can see how
    the new pipeline changes ranking. No state is mutated.
    """
    from lumen_models.knowledge import KnowledgeBase
    kb = db.query(KnowledgeBase).filter(
        KnowledgeBase.id == kb_id,
        KnowledgeBase.tenant_id == current_user.tenant_id
    ).first()
    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge base not found")

    from lumen_services.retrieval import get_retrieval_pipeline
    pipeline = get_retrieval_pipeline(
        kb_id=kb.id,
        model_config_id=kb.embedding_model_config_id,
        db=db,
    )
    filter_expr = f'tenant_id == {current_user.tenant_id} and kb_id == {kb_id}'

    def _truncate(results):
        out = []
        for r in (results or [])[:k]:
            out.append({
                "id": r.get("id"),
                "text": (r.get("text", "") or "")[:200],
                "metadata": r.get("metadata", {}),
                "rrf_score": r.get("rrf_score"),
                "bm25_score": r.get("bm25_score"),
                "distance": r.get("distance"),
                "relevance_score": r.get("relevance_score"),
            })
        return out

    # Vector-only
    try:
        vector_only = pipeline.vector_store.similarity_search(
            query=query, k=k, filter_expr=filter_expr
        )
    except Exception as exc:
        vector_only = [{"error": str(exc)}]

    # Hybrid (no rerank)
    try:
        hybrid = pipeline.hybrid_retriever.search(
            query=query, k=k, filter_expr=filter_expr
        )
    except Exception as exc:
        hybrid = [{"error": str(exc)}]

    # Hybrid + rerank
    try:
        hybrid_rerank = pipeline.search(
            query=query, k=k, filter_expr=filter_expr, rerank=True
        )
    except Exception as exc:
        hybrid_rerank = [{"error": str(exc)}]

    return SingleResponse(data={
        "query": query,
        "k": k,
        "pipeline": pipeline.describe(),
        "vector_only": _truncate(vector_only),
        "hybrid": _truncate(hybrid),
        "hybrid_rerank": _truncate(hybrid_rerank),
    })


# ---------------------------------------------------------------- M31: FAQ Q&A
#
# Q&A entries are stored as 1 virtual Document + 1 chunk + 1
# FAQEntry row. The CRUD endpoints below all funnel through
# FAQService; the API layer is responsible for tenant scoping
# (KB lookup) and the response envelope (SingleResponse /
# PaginatedResponse).
#
# Routes are mounted at ``/knowledge/{kb_id}/faq-entries`` so
# they sit alongside the existing document routes and inherit
# the same ``/knowledge`` prefix declared on the router.


def _resolve_kb_or_404(
    db: Session, kb_id: int, tenant_id: int
):
    """Look up a KnowledgeBase by id, scoped to a tenant.

    Returns the KB on success; raises ``HTTPException(404)``
    otherwise. Used by every FAQ endpoint to do the tenant
    check in one place.
    """
    from lumen_models.knowledge import KnowledgeBase

    kb = db.query(KnowledgeBase).filter(
        KnowledgeBase.id == kb_id,
        KnowledgeBase.tenant_id == tenant_id,
    ).first()
    if kb is None:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    return kb


@router.get(
    "/{kb_id}/faq-entries",
    response_model=PaginatedResponse[FAQEntryResponse],
)
async def list_faq_entries(
    kb_id: int,
    page: int = 1,
    page_size: int = 20,
    category: Optional[str] = None,
    search: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List Q&A entries for a KB with optional filters.

    All filters are AND-composed. ``search`` matches against
    question + answer with a case-insensitive substring
    (MySQL utf8mb4 default collation is case-insensitive).
    """
    from lumen_services.faq_service import FAQService

    _resolve_kb_or_404(db, kb_id, current_user.tenant_id)
    rows, total = FAQService().list_entries(
        db,
        kb_id=kb_id,
        tenant_id=current_user.tenant_id,
        page=page,
        page_size=page_size,
        category=category,
        search=search,
    )
    return PaginatedResponse(
        data=[FAQEntryResponse.model_validate(r) for r in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post(
    "/{kb_id}/faq-entries",
    response_model=SingleResponse[FAQEntryResponse],
)
async def create_faq_entry(
    kb_id: int,
    data: FAQEntryCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a single Q&A entry. The virtual Document + chunk
    + vector write are all-or-nothing — a vector failure
    surfaces as a 500 and the whole transaction rolls back.
    """
    from lumen_services.faq_service import FAQService

    kb = _resolve_kb_or_404(db, kb_id, current_user.tenant_id)
    faq = FAQService().create_entry(db, kb, data, current_user)
    return SingleResponse(data=FAQEntryResponse.model_validate(faq))


@router.post(
    "/{kb_id}/faq-entries/bulk",
    response_model=SingleResponse[FAQBulkImportResult],
)
async def bulk_import_faq_entries(
    kb_id: int,
    data: FAQBulkImportRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Bulk-create Q&A entries from a JSON array or CSV text.

    Validation errors are collected per row (returned in
    ``failed``); rows that pass validation get inserted
    even if others fail. A DB / vector failure mid-import
    raises 500 and rolls everything back — partial inserts
    are deliberately not allowed.
    """
    from lumen_services.faq_service import FAQService

    kb = _resolve_kb_or_404(db, kb_id, current_user.tenant_id)
    result = FAQService().bulk_import(db, kb, data, current_user)
    return SingleResponse(
        data=result,
        message=f"导入完成: 成功 {result.inserted} 条, 失败 {len(result.failed)} 条",
    )


@router.put(
    "/{kb_id}/faq-entries/{entry_id}",
    response_model=SingleResponse[FAQEntryResponse],
)
async def update_faq_entry(
    kb_id: int,
    entry_id: int,
    data: FAQEntryUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update an existing Q&A entry. PATCH-style: only the
    fields included in the body are changed. A question /
    answer change re-embedding the vector.
    """
    from lumen_services.faq_service import FAQService

    _resolve_kb_or_404(db, kb_id, current_user.tenant_id)
    service = FAQService()
    entry = service.get_entry(
        db, entry_id, kb_id=kb_id, tenant_id=current_user.tenant_id
    )
    if entry is None:
        raise HTTPException(status_code=404, detail="FAQ entry not found")
    updated = service.update_entry(db, entry, data)
    return SingleResponse(data=FAQEntryResponse.model_validate(updated))


@router.delete(
    "/{kb_id}/faq-entries/{entry_id}",
    response_model=SingleResponse[dict],
)
async def delete_faq_entry(
    kb_id: int,
    entry_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Hard delete a Q&A entry + its virtual Document + chunk
    + vector. The vector delete is best-effort; a stale
    vector is far less harmful than a 500 on the API path.
    """
    from lumen_services.faq_service import FAQService

    _resolve_kb_or_404(db, kb_id, current_user.tenant_id)
    service = FAQService()
    entry = service.get_entry(
        db, entry_id, kb_id=kb_id, tenant_id=current_user.tenant_id
    )
    if entry is None:
        raise HTTPException(status_code=404, detail="FAQ entry not found")
    service.delete_entry(db, entry)
    return SingleResponse(
        data={"entry_id": entry_id, "deleted": True},
        message="FAQ 已删除",
    )
