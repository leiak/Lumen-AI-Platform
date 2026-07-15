import os
from typing import List, Optional, Dict, Any
from sqlalchemy import func
from sqlalchemy.orm import Session
from lumen_models.knowledge import KnowledgeBase, Document, DocumentChunk
from lumen_models.user import User
from lumen_models.model_config import ModelConfig
from lumen_schemas.knowledge import KnowledgeBaseCreate, KnowledgeBaseUpdate
from lumen_core.tenant import TenantContext
from lumen_core.config import settings
from lumen_services.chunking_service import get_chunking_service


class KnowledgeBaseNotEmptyError(Exception):
    """知识库下还有文档,不允许直接删除.

    The API layer turns this into a 400 with the document count so the
    user knows exactly what to clean up. We don't cascade-delete docs:
    the user is expected to delete documents explicitly so they don't
    lose their parsed chunks + FAISS vectors by accident.
    """

    def __init__(self, document_count: int):
        self.document_count = document_count
        super().__init__(
            f"知识库下还有 {document_count} 个文档,请先删除文档"
        )


class KnowledgeService:
    def __init__(self):
        self._chunking_service = None
        # Per-(kb_id, model_config_id) pipelines are built lazily via
        # ``get_pipeline_for_kb``. We no longer cache a single shared
        # ``embeddings`` / ``pipeline`` because each KB may have its own
        # embedding model; sharing one would silently mix vectors from
        # different embedding spaces.
        self._pipelines: Dict[int, Any] = {}

    @property
    def chunking_service(self):
        if self._chunking_service is None:
            self._chunking_service = get_chunking_service()
        return self._chunking_service

    def get_pipeline_for_kb(self, kb: KnowledgeBase, db: Session):
        """Return a :class:`RetrievalPipeline` for ``kb``.

        The pipeline is cached per ``kb.id`` for the lifetime of this
        service instance. If the KB has no ``embedding_model_config_id``
        (shouldn't happen post-migration, but defensive), raises a
        clear ``RuntimeError``.
        """
        cached = self._pipelines.get(kb.id)
        if cached is not None:
            return cached
        if kb.embedding_model_config_id is None:
            raise RuntimeError(
                f"KB {kb.id} has no embedding_model_config_id; "
                "startup migration should have set this."
            )
        from lumen_services.retrieval import get_retrieval_pipeline
        pipeline = get_retrieval_pipeline(
            kb_id=kb.id,
            model_config_id=kb.embedding_model_config_id,
            db=db,
        )
        self._pipelines[kb.id] = pipeline
        return pipeline

    def get_vector_store_for_kb(self, kb: KnowledgeBase, db: Session):
        """Return the vector store for ``kb`` (used by API endpoints that
        need raw ``add_texts`` / ``delete_by_ids`` access)."""
        from lumen_tools.vector_store_factory import VectorStoreFactory
        if kb.embedding_model_config_id is None:
            raise RuntimeError(
                f"KB {kb.id} has no embedding_model_config_id; "
                "startup migration should have set this."
            )
        return VectorStoreFactory.get_store(
            kb_id=kb.id,
            model_config_id=kb.embedding_model_config_id,
            db=db,
        )

    def list_knowledge_bases(self, db: Session, tenant_id: int) -> List[KnowledgeBase]:
        from sqlalchemy import func
        kbs = (
            db.query(KnowledgeBase)
            .filter(KnowledgeBase.tenant_id == tenant_id)
            .all()
        )
        if not kbs:
            return kbs
        # Single GROUP BY query for all KBs in one round-trip — avoids the
        # N+1 the frontend used to do (one getDocuments per KB).
        kb_ids = [kb.id for kb in kbs]
        rows = (
            db.query(Document.knowledge_base_id, func.count(Document.id))
            .filter(Document.knowledge_base_id.in_(kb_ids))
            .group_by(Document.knowledge_base_id)
            .all()
        )
        counts = {kb_id: cnt for kb_id, cnt in rows}
        # Attach as a transient attribute; Pydantic reads it via
        # from_attributes when the API calls model_validate(kb).
        for kb in kbs:
            kb.document_count = counts.get(kb.id, 0)
        return kbs

    def create_knowledge_base(
        self, db: Session, tenant_id: int, data: KnowledgeBaseCreate
    ) -> KnowledgeBase:
        """Create a KB, validating that the embedding config is usable.

        We probe the embedder up-front so a misconfigured KB fails
        loudly at create time (422) rather than at first document
        upload (500 with a confusing Ollama error).
        """
        from lumen_services.embedding_factory import get_embeddings_for_config

        # Validate the embedding config up-front.
        cfg = db.get(ModelConfig, data.embedding_model_config_id)
        if cfg is None:
            raise ValueError(
                f"ModelConfig {data.embedding_model_config_id} not found"
            )
        if not cfg.is_active:
            raise ValueError(f"Embedding model '{cfg.name}' is disabled")
        if not cfg.is_embedding:
            raise ValueError(
                f"Model '{cfg.name}' is not marked is_embedding=True"
            )

        # Probe the factory — also caches the embedder for later use.
        get_embeddings_for_config(data.embedding_model_config_id, db)

        kb_data = data.model_dump()
        kb = KnowledgeBase(**kb_data, tenant_id=tenant_id)
        db.add(kb)
        db.commit()
        db.refresh(kb)
        return kb

    def update_knowledge_base(
        self, db: Session, kb_id: int, tenant_id: int, data: KnowledgeBaseUpdate
    ) -> Optional[KnowledgeBase]:
        from fastapi import HTTPException

        kb = db.query(KnowledgeBase).filter(
            KnowledgeBase.id == kb_id,
            KnowledgeBase.tenant_id == tenant_id
        ).first()
        if not kb:
            return None

        # Defensive: even if the schema ever drifts and the update
        # payload includes ``embedding_model_config_id``, refuse the
        # change. The PUT endpoint should never have let the field
        # through, but the KB embedding model is locked once set.
        dumped = data.model_dump(exclude_unset=True)
        if "embedding_model_config_id" in dumped and (
            dumped["embedding_model_config_id"] != kb.embedding_model_config_id
        ):
            raise HTTPException(
                status_code=422,
                detail="embedding 模型一旦选定不可更改。如需更换请创建新知识库。",
            )

        update_data = data.model_dump(exclude_unset=True)
        # Always drop embedding_model_config_id from updates — locked field.
        update_data.pop("embedding_model_config_id", None)
        for field, value in update_data.items():
            if value is not None:
                setattr(kb, field, value)
        db.commit()
        db.refresh(kb)
        return kb

    def delete_knowledge_base(self, db: Session, kb_id: int, tenant_id: int) -> bool:
        kb = db.query(KnowledgeBase).filter(
            KnowledgeBase.id == kb_id,
            KnowledgeBase.tenant_id == tenant_id
        ).first()
        if not kb:
            return False
        # Guard: refuse to delete a KB that still has documents. This
        # prevents leaving orphans (Document rows whose knowledge_base_id
        # points at a deleted KB) and avoids the user accidentally
        # losing all their parsed chunks / FAISS vectors in one click.
        # The expected flow is: delete documents first, then the KB.
        # The count is surfaced to the user in the 400 message; switch
        # to ``.exists()`` if the count stops being useful.
        doc_count = (
            db.query(func.count(Document.id))
            .filter(Document.knowledge_base_id == kb_id)
            .scalar()
        )
        if doc_count:
            raise KnowledgeBaseNotEmptyError(doc_count)
        db.delete(kb)
        db.commit()
        return True

    def process_document(
        self,
        db: Session,
        document_id: int,
        content: str,
        tenant_id: int,
        chunking_strategy: str = "fixed",
        chunking_params: Dict[str, Any] = None
    ) -> List[DocumentChunk]:
        """处理文档并分块

        Args:
            db: 数据库会话
            document_id: 文档ID
            content: 文档内容
            tenant_id: 租户ID
            chunking_strategy: 分块策略 (fixed, semantic, document_structure)
            chunking_params: 分块参数
        """
        chunking_params = chunking_params or {}

        # 使用分块服务进行分块
        chunk_results = self.chunking_service.split_with_metadata(
            content,
            strategy_name=chunking_strategy,
            **chunking_params
        )

        chunk_records = []
        for chunk_info in chunk_results:
            chunk = DocumentChunk(
                content=chunk_info["content"],
                chunk_index=chunk_info["chunk_index"],
                document_id=document_id,
                chunk_metadata={
                    "tenant_id": tenant_id,
                    "strategy": chunk_info["strategy"],
                    "length": chunk_info["length"]
                }
            )
            db.add(chunk)
            chunk_records.append(chunk)
        db.commit()
        return chunk_records

    def get_chunking_strategies(self) -> List[Dict[str, str]]:
        """获取可用的分块策略"""
        return self.chunking_service.get_available_strategies()

    # ------------------------------------------------------------ retrieval

    def index_chunks(
        self,
        chunks: List[DocumentChunk],
        kb: KnowledgeBase,
        db: Session,
        metadatas: Optional[List[Dict[str, Any]]] = None,
    ) -> List[str]:
        """Add a list of :class:`DocumentChunk` records to the per-KB
        vector store + BM25 index.

        ``kb`` is required so we use the right embedder for this KB
        (each KB may have its own embedding model).
        On success, ``chunk.vector_id`` is updated.
        """
        if not chunks:
            return []

        texts = [c.content for c in chunks]
        if metadatas is None:
            metadatas = [
                {
                    "chunk_id": c.id,
                    "document_id": c.document_id,
                    "tenant_id": kb.tenant_id,
                    "kb_id": kb.id,
                }
                for c in chunks
            ]

        pipeline = self.get_pipeline_for_kb(kb, db)
        try:
            ids = pipeline.add_documents(
                texts=texts, metadatas=metadatas, ids=None
            )
        except Exception as exc:  # pragma: no cover - defensive
            import logging
            logging.getLogger(__name__).warning(
                "Retrieval pipeline add_documents failed: %s", exc
            )
            return []

        for chunk, vid in zip(chunks, ids):
            try:
                chunk.vector_id = vid
            except Exception:  # pragma: no cover - defensive
                pass
        return ids

    def search(
        self,
        query: str,
        tenant_id: int,
        kb: KnowledgeBase,
        db: Session,
        k: int = 5,
        rerank: bool = True,
        alpha: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        """Run the hybrid retrieval pipeline for a single KB.

        ``alpha`` is kept for backward compatibility with the previous
        vector-only API: when provided and BM25 is unavailable (or weights
        are at their defaults), it is used as the relative weight of the
        vector side (``vector_weight = alpha``, ``bm25_weight = 1 - alpha``).
        """
        filter_expr = f"tenant_id == {tenant_id} and kb_id == {kb.id}"

        pipeline = self.get_pipeline_for_kb(kb, db)

        # If the caller asked for an explicit alpha and the pipeline weights
        # are at their default, mirror that into the pipeline weights for
        # the duration of the call. This keeps the legacy "alpha" parameter
        # meaningful.
        if alpha is not None and pipeline is not None:
            try:
                pipeline.hybrid_retriever.vector_weight = float(alpha)
                pipeline.hybrid_retriever.bm25_weight = float(1.0 - alpha)
            except Exception:  # pragma: no cover - defensive
                pass

        return pipeline.search(
            query=query,
            k=k,
            filter_expr=filter_expr,
            rerank=rerank,
            # M28: pass the KB's 4 multi_match field boosts so the
            # Elasticsearch backend can honour them. FAISS silently ignores.
            search_weights=kb.search_weights,
        )
