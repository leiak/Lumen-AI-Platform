from sqlalchemy import Column, String, Text, Integer, ForeignKey, JSON
from sqlalchemy.orm import relationship
from lumen_models.base import BaseModel


class KnowledgeBase(BaseModel):
    __tablename__ = "knowledge_bases"

    name = Column(String(100), nullable=False)
    description = Column(Text)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    embedding_model = Column(String(50), default="nomic-embed-text")
    # FK to ModelConfig.id. Nullable during the migration period; will
    # be flipped to NOT NULL once all KBs are guaranteed to have a
    # config. ON DELETE RESTRICT protects against accidental
    # hard-delete of a config that's still in use.
    embedding_model_config_id = Column(
        Integer,
        ForeignKey("model_configs.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
        comment="Embedding ModelConfig id (locked after KB creation)",
    )
    status = Column(String(20), default="active")  # active, inactive
    # Field weights for hybrid search stored as JSON
    # e.g. {"title": 10.0, "important_kw": 30.0, "question_kw": 20.0, "text": 2.0}
    search_weights = Column(JSON)
    default_parser = Column(String(20), default="general")
    chunk_size = Column(Integer, default=500)
    chunk_overlap = Column(Integer, default=50)

    tenant = relationship("Tenant", backref="knowledge_bases")
    documents = relationship("Document", back_populates="knowledge_base", cascade="all, delete-orphan")


class Document(BaseModel):
    __tablename__ = "documents"

    filename = Column(String(255), nullable=False)
    file_path = Column(String(500), nullable=False)
    file_type = Column(String(100))
    file_size = Column(Integer)
    # --- M38.1 storage backend abstraction ---
    # ``asset_storage_key`` holds the storage-backend key (relative
    # path for LocalBackend, full key for S3Backend). NULL on legacy
    # rows — those still read via ``file_path`` on the local disk.
    # ``storage_backend`` is the backend that produced the key
    # (``local`` or ``s3``); NULL is interpreted as ``local`` so the
    # pre-M38.1 behaviour is preserved by default.
    asset_storage_key = Column(
        String(500),
        nullable=True,
        comment="M38.1 storage key (relative path for local, s3 key for S3); NULL for legacy rows",
    )
    storage_backend = Column(
        String(20),
        nullable=True,
        default="local",
        comment="M38.1 backend that produced asset_storage_key: local / s3",
    )
    content = Column(Text)
    doc_metadata = Column(JSON)
    status = Column(String(20), default="pending")  # pending, processing, completed, failed
    error_message = Column(Text)  # Error message if processing failed
    chunk_count = Column(Integer)  # Number of chunks after processing
    knowledge_base_id = Column(Integer, ForeignKey("knowledge_bases.id"), nullable=False, index=True)
    # User who uploaded the document. Used by the v1 completion-notification
    # feature to route a Notification row to the right user. Nullable so
    # legacy uploads (made before this column existed) can still exist; the
    # notification worker simply skips rows where `created_by` is NULL.
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    # FK to ModelConfig.id. Records which embedding model was used to
    # embed the document at ingest time. Nullable during the migration
    # period; the migration script backfills it from the parent KB.
    embedding_model_config_id = Column(
        Integer,
        ForeignKey("model_configs.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
        comment="Embedding ModelConfig id at ingest time",
    )

    knowledge_base = relationship("KnowledgeBase", back_populates="documents")
    chunks = relationship("DocumentChunk", back_populates="document", cascade="all, delete-orphan")


class DocumentChunk(BaseModel):
    __tablename__ = "document_chunks"

    content = Column(Text, nullable=False)
    chunk_index = Column(Integer)
    vector_id = Column(String(100), index=True)  # FAISS vector ID
    chunk_metadata = Column(JSON)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=False, index=True)
    # 'ok' = embedded and added to the vector store.
    # 'failed' = the embedder raised; the chunk has a placeholder
    # vector_id (e.g. "error_<i>") and must not be returned by search.
    # Default 'ok' so existing rows behave as before; the migration
    # helper in core/database.py backfills 'ok' on legacy rows.
    embedding_status = Column(String(20), default="ok", nullable=False, index=True)

    document = relationship("Document", back_populates="chunks")


class FAQEntry(BaseModel):
    """M31: a single Q&A pair manually entered into a knowledge base.

    Each FAQEntry points at a virtual ``Document`` (one row per FAQ
    with ``doc_type="qa_pair"`` and ``file_path="faq://<uuid>"`` —
    no real file on disk) and a single ``DocumentChunk`` (the Q&A
    rendered as ``问题: <q>\\n\\n答案: <a>``). This is the design
    choice that keeps the RAG retrieval path zero-change: FAQ
    chunks are first-class citizens of the per-KB vector store,
    and ``agent_rag._render_context_markdown`` distinguishes them
    from document chunks via the ``source_type="faq"`` marker in
    ``chunk_metadata``.

    See ``docs/superpowers/specs/2026-06-17-faq-entry.md`` for the
    full design rationale.
    """
    __tablename__ = "faq_entries"

    # The KB this FAQ belongs to. Tenant isolation is enforced
    # via JOIN on ``knowledge_bases.tenant_id`` at the API layer
    # (mirrors the project's ``Document`` pattern: ``Document``
    # also stores ``tenant_id`` on the row but the source of
    # truth for isolation is the parent KB).
    knowledge_base_id = Column(
        Integer,
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=False)
    # Free-form category like "退货政策" / "物流时效". Nullable
    # because the UI allows uncategorised Q&As.
    category = Column(String(50), nullable=True, index=True)
    # Free-form tags like ["急", "VIP"]. Stored as JSON list.
    tags = Column(JSON, nullable=True)
    # Vector store id (FAISS internal index). Captured at write
    # time so update / delete can target the right slot.
    vector_id = Column(String(100), nullable=True)
    # The virtual Document parent row (doc_type=qa_pair). ON
    # DELETE CASCADE so deleting the doc removes the FAQ row
    # automatically; the service layer also cleans the vector
    # store best-effort before the delete.
    document_id = Column(
        Integer,
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    # The single Q&A chunk. CASCADE so chunk removal cascades
    # up to this row (we never delete a chunk without its FAQ).
    chunk_id = Column(
        Integer,
        ForeignKey("document_chunks.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Embedder used at write time. Mirrors ``Document`` so the
    # /rechunk-style path could rebuild the vector from the chunk
    # text without re-resolving the embedder.
    embedding_model_config_id = Column(
        Integer,
        ForeignKey("model_configs.id", ondelete="RESTRICT"),
        nullable=True,
    )
    # Author. Nullable + SET NULL so deleting a user doesn't
    # cascade-delete the FAQ.
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)

    # Relationships are intentionally NOT defined here — FAQ
    # lookups go through the parent KB / Doc / Chunk and the
    # existing ``Document`` / ``DocumentChunk`` relationships
    # already cover the navigation. Adding them here would
    # create a circular relationship graph that the model
    # loader complains about.
