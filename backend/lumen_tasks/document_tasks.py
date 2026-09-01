import logging
import os
import uuid
from typing import Dict, Any, List

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


def _persist_ppt_image_assets(
    db,
    parse_result: Dict[str, Any],
    document_id: int,
    tenant_id: int,
    kb_id: int,
) -> List[int]:
    """M38.4: 把 PPT/Image parser 抽出的图落到 image_assets 表 + storage。

    每张抽出的图:
    1. ``storage.put_object`` 写到 ``uploads/<tenant>/<kb>/images/<doc>/<slide_dedup_key>.<ext>``
    2. 写 ``ImageAsset`` row,``chunk_id`` 暂时 NULL(worker 在 chunks 创建
       之后会按 ``page_number`` 回填)
    3. 返回 ``original_doc_page`` 列表(给 worker 后段 image chunks 配对用)

    失败:storage 写不进去时整个 doc 不卡(已失败有其他原因兜底),但
    ``ImageAsset`` row 会落 ``embedding_status='failed'`` + 留 storage_key
    方便后续 retry。
    """
    metadata = parse_result.get("metadata") or {}
    image_assets_meta = metadata.get("image_assets") or []
    if not image_assets_meta:
        return []

    from lumen_models.image_asset import ImageAsset
    from lumen_services.storage import get_storage_backend

    storage = get_storage_backend()
    pages: List[int] = []

    for asset_meta in image_assets_meta:
        try:
            dedup_key = asset_meta.get("slide_dedup_key", "img")
            ext = asset_meta.get("extension", "png")
            storage_key = (
                f"uploads/{tenant_id}/{kb_id}/images/{document_id}/"
                f"{dedup_key}.{ext}"
            )
            image_bytes = asset_meta.get("bytes")
            if not image_bytes:
                logger.warning(
                    "[doc %s] image asset %s missing bytes — skipping storage upload",
                    document_id, dedup_key,
                )
                continue
            storage.put_object(storage_key, image_bytes)

            asset_row = ImageAsset(
                document_id=document_id,
                chunk_id=None,  # 后面 worker 用 page_number 回填
                original_doc_page=asset_meta.get("page_number"),
                storage_key=storage_key,
                width=asset_meta.get("width"),
                height=asset_meta.get("height"),
                mime_type=asset_meta.get("mime"),
                file_size=asset_meta.get("size_bytes"),
                caption=dedup_key.replace("_", " "),
                embedding_status="pending",
            )
            db.add(asset_row)
            pages.append(asset_meta.get("page_number"))
        except Exception as exc:
            logger.warning(
                "[doc %s] failed to persist PPT image asset: %s",
                document_id, exc,
            )
            continue

    try:
        db.commit()
    except Exception as exc:
        logger.warning(
            "[doc %s] image_assets commit failed (non-fatal): %s",
            document_id, exc,
        )
        db.rollback()
    return pages


def _dispatch_multimodal_embeddings(
    db,
    image_chunks: List,
    kb_id: int,
    tenant_id: int,
    document_id: int,
    mm_config_id: int,
) -> None:
    """M38.4: 给 image chunks 跑 multimodal embedder,写到独立向量库。

    失败语义:不影响 doc.status('completed' 仍保留);失败的 image
    asset / chunk 的 ``embedding_status`` 翻 ``'failed'``,搜不到但
    UI 仍能展示原图(spec §10 risk 3)。

    caption 走 ``embed_text``(同向量空间;Step 3 ABC 确认 text + image
    共享 dim)。这意味着 caption 质量决定搜索精度,v2 接 LLM 生成。
    """
    if not image_chunks:
        return

    from lumen_services.multimodal_embedders import (
        get_multimodal_embedder,
        MultimodalEmbeddingError,
        UnsupportedProviderError,
    )
    from lumen_services.multimodal_vector_store_factory import (
        MultimodalVectorStoreFactory,
    )

    try:
        embedder, dim = get_multimodal_embedder(mm_config_id, db)
    except (MultimodalEmbeddingError, UnsupportedProviderError, NotImplementedError) as exc:
        logger.warning(
            "[doc %s] multimodal embedder load failed: %s",
            document_id, exc,
        )
        for c in image_chunks:
            c.embedding_status = "failed"
        db.commit()
        return

    captions = [c.image_caption or c.content or "" for c in image_chunks]
    try:
        vectors = [embedder.embed_text(cap) for cap in captions]
    except Exception as exc:
        logger.warning(
            "[doc %s] multimodal embed_text failed: %s",
            document_id, exc,
        )
        for c in image_chunks:
            c.embedding_status = "failed"
        db.commit()
        return

    try:
        mm_store = MultimodalVectorStoreFactory.get_store(kb_id, dim)
        metadatas = [
            {
                "chunk_id": c.id,
                "document_id": document_id,
                "tenant_id": tenant_id,
                "kb_id": kb_id,
                "modality": "image",
            }
            for c in image_chunks
        ]
        mm_store.add_texts(captions, metadatas, vectors=vectors)

        # 落库 embedding_status='ok' + 同步 ImageAsset
        from lumen_models.image_asset import ImageAsset
        for c in image_chunks:
            c.embedding_status = "ok"
            asset = (
                db.query(ImageAsset)
                .filter(ImageAsset.chunk_id == c.id)
                .first()
            )
            if asset:
                asset.embedding_status = "ok"
        db.commit()
    except Exception as exc:
        logger.warning(
            "[doc %s] multimodal vector store write failed: %s",
            document_id, exc,
        )
        for c in image_chunks:
            c.embedding_status = "failed"
        db.commit()


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
    # M38.2 (2026-08-26): Workspace + DocumentFolder are FK targets of
    # ``documents.folder_id`` / ``workspaces.owner_id`` etc. The
    # Document row's ``knowledge_base`` relationship lazy-loads its
    # related rows, and SQLAlchemy will refuse to configure the mapper
    # if a referenced table hasn't been registered. Result if you
    # skip this import: ``Foreign key associated with column
    # 'documents.folder_id' could not find table 'document_folders'``
    # raised inside ``doc.knowledge_base`` access — exactly what
    # happened to doc 939 after M38.2 shipped (2026-08-31 incident:
    # upload returned "queued" but doc stuck in pending because the
    # celery worker raised before any status update).
    from lumen_models.workspace import DocumentFolder, Workspace  # noqa: F401  # M38.2: documents.folder_id / workspaces.owner_id
    # M38.4 (2026-09-01): MultimodalEmbeddingConfig is a FK target of
    # ``knowledge_bases.multimodal_config_id`` and ImageAsset holds
    # ``document_id`` / ``chunk_id`` FKs to documents/document_chunks.
    # Without these imports the KB's multimodal relationship lookup
    # (during parser dispatch for PPT-extracted images) raises
    # ``InvalidRequestError: Mapper 'mapped class ImageAsset' has no
    # property 'document'`` at mapper-configure time. Extend this
    # block whenever a new FK or relationship on multimodal models
    # is added — the M38.2 incident with ``DocumentFolder`` is the
    # cautionary tale (forgotten import → queued-but-stuck doc).
    from lumen_models.multimodal_embedding_config import MultimodalEmbeddingConfig  # noqa: F401  # M38.4: KB.multimodal_config_id
    from lumen_models.image_asset import ImageAsset  # noqa: F401  # M38.4: image_assets.document_id / .chunk_id
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
        # M38.1 follow-up: when the originating endpoint set
        # ``asset_storage_key`` (post-MinIO switch this is every
        # doc), forward it as ``storage_key`` so the parser routes
        # through ``storage.resolve_to_local_path``. Without this,
        # S3-backed docs would hit FileNotFoundError when parsers
        # try to ``open(file_path)`` against the local disk. Falls
        # back to ``file_path`` when ``storage_key`` is missing /
        # fails to resolve, so pre-M38.1 docs keep working.
        parse_result = parser.parse(
            file_path,
            file_content_type,
            doc_type=doc_type,
            storage_key=task_params.get("asset_storage_key"),
        )
        text_content = parse_result.get("text", "")
        parse_error = (parse_result.get("metadata") or {}).get("parse_error")

        # M38.4 (2026-09-01): PPT/Image parser 抽出的图先落 storage + image_assets。
        # 必须在 chunk 创建之前跑,因为 image chunk 之后要按 page_number 回填
        # asset.chunk_id。失败不阻塞 — doc 仍然能处理 text chunks。
        if doc_type in ("ppt", "pptx") or doc_type == "image":
            try:
                _persist_ppt_image_assets(
                    db=db,
                    parse_result=parse_result,
                    document_id=document_id,
                    tenant_id=tenant_id,
                    kb_id=kb_id,
                )
            except Exception as exc:
                logger.warning(
                    "[Task %s] image asset persistence failed (non-fatal): %s",
                    task_id, exc,
                )

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
                    # M38.4 (2026-09-01) — multimodal chunk fields. The
                    # legacy 6 parsers (general/paper/qa/table/manual/laws)
                    # never set these so ``.get(..., default)`` leaves
                    # them at the SQLAlchemy column defaults (text / NULL /
                    # NULL / NULL) — which matches pre-M38.4 row shape
                    # exactly. The 3 new parsers (excel/ppt/image) pass
                    # modality / sheet_name / page_number / image_caption
                    # through ``chunk_info`` directly so cross-modal search
                    # and the Excel/PPT detail pages can filter on these.
                    modality=chunk_info.get("modality", "text"),
                    sheet_name=chunk_info.get("sheet_name"),
                    page_number=chunk_info.get("page_number"),
                    image_caption=chunk_info.get("image_caption"),
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

        # M38.4 (2026-09-01): image chunks 配对 image_assets + multimodal
        # embedding dispatch。配对策略:image chunk 按 ``page_number`` 升
        # 序,asset 列表也按 ``original_doc_page`` 升序,按 index 一一对应
        # (PPT 抽出图在 parser 里按 (page, shape) 顺序产出,跟 chunks
        # 顺序一致)。
        image_chunks = [c for c in chunks if c.modality == "image"]
        if image_chunks:
            from lumen_models.image_asset import ImageAsset
            assets = (
                db.query(ImageAsset)
                .filter(
                    ImageAsset.document_id == document_id,
                    ImageAsset.chunk_id.is_(None),
                )
                .order_by(ImageAsset.original_doc_page.asc(), ImageAsset.id.asc())
                .all()
            )
            # 按 (page, id) 排好 image chunks,逐个回填
            sorted_image_chunks = sorted(
                image_chunks,
                key=lambda c: (c.page_number or 0, c.id or 0),
            )
            for chunk, asset in zip(sorted_image_chunks, assets):
                asset.chunk_id = chunk.id
            try:
                db.commit()
            except Exception as exc:
                logger.warning(
                    "[Task %s] image_asset.chunk_id backfill failed: %s",
                    task_id, exc,
                )
                db.rollback()

            # multimodal dispatch(KB 启用了 multimodal 才跑)
            kb_row = doc.knowledge_base
            if kb_row and kb_row.multimodal_enabled and kb_row.multimodal_config_id:
                try:
                    _dispatch_multimodal_embeddings(
                        db=db,
                        image_chunks=sorted_image_chunks,
                        kb_id=kb_id,
                        tenant_id=tenant_id,
                        document_id=document_id,
                        mm_config_id=kb_row.multimodal_config_id,
                    )
                except Exception as exc:
                    logger.warning(
                        "[Task %s] multimodal dispatch failed (non-fatal): %s",
                        task_id, exc,
                    )

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
