import logging
import os
import uuid
from typing import Dict, Any

from lumen_tasks.celery_app import celery_app
from lumen_core.config import settings
from lumen_core.embedding_call_context import (
    EmbeddingCallContext,
    set_embedding_context,
    reset_embedding_context,
)
from lumen_services.electron_service import broadcast_event_sync
from lumen_services.notification_service import NotificationService

# M33.5 (2026-06-26): pre-load the imports that ``process_document_task``
# triggers on first invocation. Without this, the celery worker boots
# without ``lumen_schemas`` / ``lumen_services.knowledge_service`` /
# ``lumen_tools.vector_store_factory`` in ``sys.modules`` (because the
# top-level imports above don't transitively pull them in), and the
# first task that runs raises ``ModuleNotFoundError: No module named
# 'lumen_schemas'`` (or ``lumen_tools`` on the next layer) even though
# a manual ``python -c "from lumen_services.knowledge_service import
# KnowledgeService"`` from the same container works fine. Pre-loading
# here costs nothing at boot (the modules would be loaded by the first
# task anyway) and prevents the stuck-"queued" state where 3+ docs
# silently failed to enqueue for hours because the worker errored
# before any DB status update.
import lumen_schemas  # noqa: F401
import lumen_schemas.knowledge  # noqa: F401
import lumen_services.knowledge_service  # noqa: F401
import lumen_services.document_parser  # noqa: F401
import lumen_tools  # noqa: F401
import lumen_tools.vector_store_factory  # noqa: F401

logger = logging.getLogger(__name__)


def _emit_notification(db, task_params, doc, error: bool = False) -> None:
    """Write a notifications row and broadcast it. Called by
    process_document_task at success and failure points. If
    task_params lacks user_id (legacy queued task) we log and skip —
    doc.status is still set correctly elsewhere, so the user can
    see the result on the KB page even without a notification."""
    user_id = task_params.get("user_id")
    if not user_id:
        logger.warning(
            "process_document_task: skipping notification, no user_id in task_params"
        )
        return
    type_ = "knowledge_parse_failed" if error else "knowledge_parse_completed"
    title = (
        f"文档「{doc.filename}」处理失败"
        if error else
        f"文档「{doc.filename}」处理完成"
    )
    NotificationService.publish_event(
        db,
        user_id=user_id,
        type=type_,
        title=title,
        body=doc.error_message if error else None,
        resource_type="document",
        resource_id=doc.id,
        metadata={
            "kb_id": doc.knowledge_base_id,
            "filename": doc.filename,
            "status": "failed" if error else "completed",
        },
    )


@celery_app.task(bind=True, name="process_document")
def process_document_task(self, task_params: Dict[str, Any]) -> Dict[str, Any]:
    """Async document processing task.

    Args:
        task_params: {
            "document_id": int,
            "file_path": str,
            "file_content_type": str,
            "tenant_id": int,
            "kb_id": int,
            "chunking_strategy": str,
            "chunking_params": dict,
            "doc_type": str (optional)
        }

    Returns:
        {"status": "completed" | "failed", "document_id": int, "chunk_count": int, "error": str}
    """
    from lumen_core.database import SessionLocal
    from lumen_models.knowledge import Document, DocumentChunk
    from lumen_models.tenant import Tenant  # Import Tenant to resolve SQLAlchemy relationship
    # The Celery worker boots via app.tasks.celery_app and never
    # touches app.main, so main.py's model registration doesn't
    # run for this process. The worker has to register the FK
    # target + relationship target models for embedding_call_logs
    # ITSELF, or every embed call during ingest fails with:
    #   NoReferencedTableError: Foreign key associated with column
    #     'embedding_call_logs.workflow_id' could not find table
    #     'workflows' ...
    # plus a mapper-configure error on Workflow import:
    #   InvalidRequestError: expression 'Tenant' failed to locate
    #     a name (Workflow.tenant relationship)
    # Caught and logged (m27-safety), so KB ingest still completes
    # correctly, but observability rows are silently dropped. The
    # M27 follow-up initially imported just Agent (one FK target);
    # M30a (2026-06-16) added Workflow / WorkflowRun + their
    # relationship targets — extend the block whenever a new FK or
    # relationship on embedding_call_logs or its neighbours is added.
    # Import order matters: relationship targets must be registered
    # before the model that references them so SQLAlchemy can resolve
    # the string class name at mapper-configure time.
    from lumen_models.tenant import Tenant  # already imported above, listed for ordering clarity
    from lumen_models.user import User  # noqa: F401  # embedding_call_logs.user_id
    from lumen_models.chat import Conversation  # noqa: F401  # .conversation_id
    from lumen_models.agent import Agent  # noqa: F401  # .agent_id
    from lumen_models.agent_team import AgentTeam  # noqa: F401  # .team_id
    from lumen_models.model_config import ModelConfig  # noqa: F401  # .model_config_id
    from lumen_models.llm_call_log import LLMCallLog  # noqa: F401  # WorkflowRun.llm_call_logs relationship
    from lumen_models.embedding_call_log import EmbeddingCallLog  # noqa: F401  # self + WorkflowRun.embedding_call_logs
    from lumen_models.workflow import Workflow, WorkflowRun  # noqa: F401  # M30a: .workflow_id / .workflow_run_id
    from lumen_models.workflow import WorkflowNodeRun  # noqa: F401  # WorkflowRun.node_runs relationship
    from lumen_services.document_parser import DocumentParser
    from lumen_services.knowledge_service import KnowledgeService
    from lumen_tools.vector_store_factory import VectorStoreFactory

    task_id = self.request.id
    logger.info(f"[Task {task_id}] Starting document processing")

    # M27: install an EmbeddingCallContext for the duration of this
    # Celery task. The worker runs in a separate process from the
    # FastAPI request, so the ContextVar inherited from the parent
    # request scope is gone — we have to set it locally. ``user_id``
    # is intentionally None (background path); ``tenant_id`` is read
    # from task_params; ``call_type`` is the ``system.kb_ingest``
    # marker so the UI can distinguish backend reindex rows from
    # foreground chat-driven retrieval rows.
    trace_id = task_id or str(uuid.uuid4())
    emb_ctx_token = set_embedding_context(EmbeddingCallContext(
        call_id=str(uuid.uuid4()),
        trace_id=trace_id,
        parent_call_id=None,
        call_type="system.kb_ingest",
        call_index=0,
        tenant_id=task_params.get("tenant_id"),
        user_id=task_params.get("user_id"),
        knowledge_base_id=task_params.get("kb_id"),
        client_app="celery_worker",
        extra={
            "document_id": task_params.get("document_id"),
            "doc_type": task_params.get("doc_type"),
        },
    ))

    db = SessionLocal()
    try:
        document_id = task_params["document_id"]
        file_path = task_params["file_path"]
        file_content_type = task_params["file_content_type"]
        tenant_id = task_params["tenant_id"]
        kb_id = task_params["kb_id"]
        chunking_strategy = task_params.get("chunking_strategy", "fixed")
        chunking_params = task_params.get("chunking_params", {})
        doc_type = task_params.get("doc_type")  # New parameter

        # Update document status to processing
        doc = db.query(Document).filter(Document.id == document_id).first()
        if not doc:
            logger.error(f"[Task {task_id}] Document {document_id} not found")
            return {"status": "failed", "document_id": document_id, "error": "Document not found"}

        doc.status = "processing"
        doc.doc_metadata = {"doc_type": doc_type} if doc_type else {}
        # Backfill doc.embedding_model_config_id from the parent KB
        # when the doc row has no FK. Documents uploaded before
        # 2026-06-08's ``upload_document`` fix were created with
        # ``embedding_model_config_id=NULL``, which made the embed
        # step below raise ``ValueError: ModelConfig None not found``.
        # Filling it here lets both new uploads (the fix in
        # ``app.api.v1.knowledge`` keeps this branch a no-op) and
        # retry/reprocess of legacy docs find the embedder.
        if (
            doc.embedding_model_config_id is None
            and doc.knowledge_base is not None
            and doc.knowledge_base.embedding_model_config_id is not None
        ):
            doc.embedding_model_config_id = doc.knowledge_base.embedding_model_config_id
            db.commit()

        # Parse document using new multi-parser
        logger.info(f"[Task {task_id}] Parsing document: {file_path} (type: {doc_type or 'auto-detect'})")
        parser = DocumentParser()
        parse_result = parser.parse(file_path, file_content_type, doc_type=doc_type)
        text_content = parse_result.get("text", "")
        parse_error = (parse_result.get("metadata") or {}).get("parse_error")

        if not text_content or parse_error:
            # Docling fell back to a raw text read and either produced
            # nothing usable (e.g. binary PDF read as latin-1) or
            # recorded a specific reason. Either way, don't commit
            # garbage chunks and don't enqueue them into FAISS/BM25 —
            # the user can fix the file and retry.
            reason = parse_error or "parser produced no text"
            doc.status = "failed"
            doc.error_message = f"解析失败: {reason}"
            db.commit()
            logger.warning(f"[Task {task_id}] Parse failed: {reason}")
            try:
                _emit_notification(db, task_params, doc, error=True)
            except Exception as notify_err:
                logger.warning(f"[Task notification] Failed: {notify_err}")

            return {"status": "failed", "document_id": document_id, "error": doc.error_message}

        # Use chunks from parser if available, otherwise chunk manually
        chunks_data = parse_result.get("chunks", [])

        if chunks_data:
            # Use pre-chunked results from parser
            logger.info(f"[Task {task_id}] Using {len(chunks_data)} chunks from parser")
            chunks = []
            for chunk_info in chunks_data:
                chunk = DocumentChunk(
                    content=chunk_info["content"],
                    chunk_index=chunk_info["chunk_index"],
                    document_id=document_id,
                    chunk_metadata={
                        "tenant_id": tenant_id,
                        "strategy": chunk_info.get("strategy", "parser"),
                        "length": chunk_info.get("length", 0)
                    },
                    # New chunks are 'ok' until the embedder runs; the
                    # block below flips them to 'failed' if embedding
                    # raises. Don't rely on the SQLAlchemy default
                    # because a worker crash between commit and
                    # embedder can leave the row in the wrong state.
                    embedding_status="ok",
                )
                db.add(chunk)
                chunks.append(chunk)
            db.commit()
        else:
            # Fallback to manual chunking
            logger.info(f"[Task {task_id}] Chunking document manually")
            service = KnowledgeService()
            chunks = service.process_document(
                db, document_id, text_content, tenant_id,
                chunking_strategy=chunking_strategy,
                chunking_params=chunking_params
            )
            # Manual chunking also doesn't go through the embedder
            # yet — mark 'ok' so the post-embed failure path can flip
            # to 'failed' if the vector_store.add_texts call raises.
            for c in chunks:
                c.embedding_status = "ok"

        # Store in vector store
        logger.info(f"[Task {task_id}] Storing {len(chunks)} chunks in vector store")
        try:
            vector_store = VectorStoreFactory.get_store(
                kb_id=kb_id,
                model_config_id=doc.embedding_model_config_id,
                db=db,
            )
            texts = [c.content for c in chunks]
            metadatas = [
                {
                    "chunk_id": c.id,
                    "document_id": document_id,
                    "tenant_id": tenant_id,
                    "kb_id": kb_id,
                    "doc_type": doc_type
                }
                for c in chunks
            ]
            vector_ids = vector_store.add_texts(texts, metadatas)

            # Update chunk vector IDs (embedding_status stays 'ok')
            for chunk, vid in zip(chunks, vector_ids):
                chunk.vector_id = vid
            db.commit()
        except Exception as e:
            logger.error(f"[Task {task_id}] Vector store error (non-fatal): {e}")
            # Embedding failed for the whole batch. Mark every chunk
            # 'failed' and assign a placeholder vector_id so it can be
            # uniquely identified (a chunk_id is enough — the prefix
            # marks it as a no-op entry in FAISS, which it isn't).
            # Search filters out 'failed' rows; the Document row's
            # error_message surfaces the underlying cause to the user.
            for chunk in chunks:
                chunk.embedding_status = "failed"
                chunk.vector_id = f"error_{chunk.id}"
            doc.error_message = f"向量化失败: {type(e).__name__}: {e}"
            doc.status = "failed"
            db.commit()

        # Also feed the BM25 index so hybrid (lexical + semantic) search works
        # after async ingestion. The underlying FAISS vector store already
        # maintains its own BM25 corpus; this is the second, dedicated index
        # used by the new retrieval pipeline. Failures here are non-fatal.
        try:
            from lumen_services.retrieval import get_retrieval_pipeline
            pipeline = get_retrieval_pipeline(kb_id, doc.embedding_model_config_id, db)
            bm25_metas = [
                {
                    "chunk_id": c.id,
                    "document_id": document_id,
                    "tenant_id": tenant_id,
                    "kb_id": kb_id,
                    "doc_type": doc_type,
                }
                for c in chunks
            ]
            pipeline.bm25_index.add_texts(texts=texts, metadatas=bm25_metas)
            try:
                pipeline.bm25_index.save()
            except Exception:
                pass
        except Exception as e:
            logger.warning(f"[Task {task_id}] BM25 index update failed (non-fatal): {e}")

        # Update document status to completed — but don't clobber the
        # 'failed' status set above when embedding raised.
        if doc.status != "failed":
            doc.status = "completed"
        doc.chunk_count = len(chunks)
        db.commit()

        final_status = doc.status
        logger.info(
            f"[Task {task_id}] Document processing {final_status}: {len(chunks)} chunks"
        )

        # Emit a persistent notification row + cross-process broadcast
        # targeted at the uploader. The Celery worker is in a different
        # process from the FastAPI WS handler, so we go through
        # NotificationService.publish_event → broadcast_event_sync →
        # POST /api/v1/electron/broadcast (with the internal secret
        # header) → ElectronService.broadcast_event_async(target_user_id).
        try:
            _emit_notification(db, task_params, doc, error=(doc.status == "failed"))
        except Exception as notify_err:
            logger.warning(f"[Task notification] Failed: {notify_err}")

        return {
            "status": final_status,
            "document_id": document_id,
            "chunk_count": len(chunks),
            "doc_type": doc_type
        }

    except Exception as e:
        logger.error(f"[Task {task_id}] Document processing failed: {e}")
        # Try to update document status
        doc_id_for_broadcast = task_params.get("document_id")
        try:
            doc = db.query(Document).filter(Document.id == doc_id_for_broadcast).first()
            if doc:
                doc.status = "failed"
                doc.error_message = str(e)
                db.commit()
        except Exception:
            pass

        # Emit failure notification if we managed to load the doc.
        try:
            doc = db.query(Document).filter(Document.id == doc_id_for_broadcast).first()
            if doc:
                _emit_notification(db, task_params, doc, error=True)
        except Exception as notify_err:
            logger.warning(f"[Task notification] Failed: {notify_err}")

        return {"status": "failed", "document_id": doc_id_for_broadcast, "error": str(e)}

    finally:
        db.close()
        reset_embedding_context(emb_ctx_token)
