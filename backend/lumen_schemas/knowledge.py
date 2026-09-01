from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional, List, Dict, Literal


class KnowledgeBaseBase(BaseModel):
    name: str
    description: Optional[str] = None
    # Deprecated: stored on the row for backwards compatibility, but the
    # backend now drives embedding model from `embedding_model_config_id`.
    embedding_model: Optional[str] = Field(
        None,
        description="DEPRECATED: use embedding_model_config_id. Read-only fallback.",
    )
    embedding_model_config_id: Optional[int] = Field(
        None,
        description="Embedding ModelConfig id. Locked once the KB is created.",
    )
    search_weights: Optional[Dict[str, float]] = None  # e.g. {"title": 10.0, "text": 2.0}
    default_parser: Optional[str] = "general"
    chunk_size: int = 500
    chunk_overlap: int = 50
    # M38.4: 多模态开关。开启后,KB 内的 image 文档会同时写入独立的
    # multimodal FAISS 索引(`data/multimodal/kb-{id}-mm.faiss`),并
    # 支持 `POST /image-search`(image-to-image 检索)。
    multimodal_enabled: bool = Field(
        False,
        description="M38.4 多模态开关: True 后 KB 内的图片 chunk 会走独立 multimodal 向量库",
    )
    multimodal_config_id: Optional[int] = Field(
        None,
        description="M38.4 绑定的 multimodal config id,multimodal_enabled=True 时必填",
    )


class KnowledgeBaseCreate(KnowledgeBaseBase):
    embedding_model_config_id: int = Field(
        ...,
        description="Required: FK to ModelConfig.id. Locked after creation.",
    )


class KnowledgeBaseUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    # NOTE: embedding_model_config_id is intentionally absent. The PUT
    # endpoint also rejects changes defensively in case a future
    # schema drift reintroduces the field.
    search_weights: Optional[Dict[str, float]] = None
    default_parser: Optional[str] = None
    chunk_size: Optional[int] = None
    chunk_overlap: Optional[int] = None
    # M38.4: 多模态开关与绑定的 config id。两者互不影响 — 用户可
    # 单开 multimodal_enabled 后再绑 config(开但没 config 时新上传
    # image 文档不会被 multimodal 索引,gracefully degraded)。
    multimodal_enabled: Optional[bool] = None
    multimodal_config_id: Optional[int] = None


class KnowledgeBaseResponse(KnowledgeBaseBase):
    id: int
    tenant_id: int
    status: str
    created_at: datetime
    default_parser: Optional[str] = "general"
    chunk_size: int = 500
    chunk_overlap: int = 50
    # Number of documents in this KB. Populated by the service layer
    # via a single GROUP BY query — kept as a transient attribute on the
    # SQLAlchemy instance so Pydantic reads it via from_attributes.
    document_count: int = 0

    class Config:
        from_attributes = True


class DocumentResponse(BaseModel):
    id: int
    filename: str
    file_type: str
    file_size: int
    status: str
    chunk_count: Optional[int] = None
    error_message: Optional[str] = None
    created_at: datetime
    knowledge_base_id: Optional[int] = None

    class Config:
        from_attributes = True


class ChunkResponse(BaseModel):
    id: int
    content: str
    chunk_index: int
    vector_id: Optional[str] = None
    # Surfaced to the UI so it can show "10/14 chunks indexed" or
    # grey out rows that the embedder rejected. Frontend uses
    # string equality with the backend (currently 'ok' | 'failed').
    embedding_status: Optional[str] = None
    # M38.4: 模态字段 —— text / image / audio / video。默认 'text'
    # 让 legacy chunk 行为不变;Excel 走 'text' + sheet_name;PPT
    # 抽出图走 'image' + page_number + image_caption。frontend 用
    # modality 决定要不要走 image gallery 而不是 text diff view。
    modality: str = "text"
    sheet_name: Optional[str] = None
    page_number: Optional[int] = None
    image_caption: Optional[str] = None

    class Config:
        from_attributes = True


class RechunkRequest(BaseModel):
    """Body for POST /knowledge/documents/{id}/rechunk.

    All fields are optional — unset fields fall back to the doc's
    currently stored values (or the parent KB's chunk_size/overlap
    if the doc doesn't store them).
    """
    chunking_strategy: Optional[str] = "fixed"  # fixed | semantic | document_structure
    chunk_size: Optional[int] = None
    chunk_overlap: Optional[int] = None
    doc_type: Optional[str] = None  # general | paper | qa | table | manual | laws


# ------------------------------------------------------------------ M31: FAQ Q&A

class FAQEntryBase(BaseModel):
    """Common shape shared by FAQEntryCreate / FAQEntryUpdate.

    Field-length limits are chosen to match the underlying
    schema (question/answer stored as TEXT — soft caps protect
    against accidental 10MB inputs from the UI textareas).
    """
    question: str = Field(..., min_length=1, max_length=2000)
    answer: str = Field(..., min_length=1, max_length=8000)
    # Free-form category like "退货政策" / "物流时效". Stored
    # as VARCHAR(50) in the FAQEntry table.
    category: Optional[str] = Field(None, max_length=50)
    # Free-form tags list (e.g. ["急", "VIP"]). Not bounded by
    # a fixed max_items here; FAQService.create_entry enforces
    # < 20 tags to match the bulk-import validator.
    tags: Optional[List[str]] = None


class FAQEntryCreate(FAQEntryBase):
    """Body for POST /knowledge/{kb_id}/faq-entries (single create)."""
    pass


class FAQEntryUpdate(BaseModel):
    """Body for PUT /knowledge/{kb_id}/faq-entries/{id}.

    Every field is optional — the UI sends a PATCH-style update
    with only the changed fields. The service layer treats None
    as "leave unchanged" and only updates fields that are
    present in the payload.
    """
    question: Optional[str] = Field(None, min_length=1, max_length=2000)
    answer: Optional[str] = Field(None, min_length=1, max_length=8000)
    category: Optional[str] = Field(None, max_length=50)
    tags: Optional[List[str]] = None


class FAQEntryResponse(FAQEntryBase):
    """Response shape for a single FAQ row.

    Mirrors the FAQEntry ORM model 1:1 — vector_id, document_id,
    chunk_id are exposed so the UI can navigate to the related
    resources if needed (e.g. for debugging chunk-level issues).
    """
    id: int
    knowledge_base_id: int
    vector_id: Optional[str] = None
    document_id: int
    chunk_id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class FAQBulkImportRequest(BaseModel):
    """Body for POST /knowledge/{kb_id}/faq-entries/bulk.

    Two formats are supported:
    - ``"json"``: a JSON array of objects with the same shape
      as FAQEntryCreate (question, answer, category?, tags?).
    - ``"csv"``: CSV text with header row
      ``question,answer,category,tags`` (tags is a comma-separated
      string within the cell).
    """
    format: Literal["json", "csv"]
    content: str = Field(
        ...,
        description="JSON array or CSV text. For CSV use header row: question,answer,category,tags.",
    )


class FAQBulkImportResult(BaseModel):
    """Result of a bulk import call.

    Two failure surfaces:
    - ``failed`` collects per-row validation errors (empty
      question, malformed JSON, etc.). These are non-fatal — the
      valid rows still get inserted.
    - Anything that fails at the DB / vector-store layer raises
      a 500 and the whole transaction is rolled back. We don't
      try to "best-effort" partial inserts because the failure
      mode is typically "embedder down" and a half-written
      transaction is worse than an all-or-nothing one.
    """
    inserted: int
    failed: List[Dict[str, str]] = Field(
        default_factory=list,
        description="Per-row validation errors: [{row_index, reason}, ...]",
    )


# -------------------------------------------------------------- M38.4: Images


class ImageAssetResponse(BaseModel):
    """One image row for the gallery endpoint.

    镜像 ``ImageAsset`` ORM 1:1 + ``doc_filename`` 通过 JOIN Document
    填进来,前端 gallery 直接渲染。``embedding_status`` 让 UI 知道
    「暂未索引」(multimodal embedder 失败时设 'failed')。
    """
    id: int
    document_id: int
    chunk_id: Optional[int] = None
    # PPT 抽出图时存源页码(1-based);独立上传的图片为 NULL。
    original_doc_page: Optional[int] = None
    storage_key: str
    width: Optional[int] = None
    height: Optional[int] = None
    mime_type: Optional[str] = None
    file_size: Optional[int] = None
    caption: Optional[str] = None
    embedding_status: str = "pending"  # pending | ok | failed
    doc_filename: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class ImageSearchHit(BaseModel):
    """One hit returned by ``POST /knowledge/{kb_id}/image-search``."""
    asset_id: Optional[int] = None
    chunk_id: Optional[int] = None
    document_id: Optional[int] = None
    doc_filename: Optional[str] = None
    image_caption: Optional[str] = None
    storage_key: Optional[str] = None
    # 内积距离(FAISS IndexFlatIP)。score = -distance,值越大越相似。
    distance: Optional[float] = None
    score: Optional[float] = None


class ImageSearchResponse(BaseModel):
    """Body of ``POST /knowledge/{kb_id}/image-search``.

    ``search_mode`` 区分走的是 multimodal embedding(真 image-to-image
    检索)还是 text fallback —— fallback 时 admin UI 应提示用户「多模态
    模型未就绪,已用文字描述匹配」,但不抛 503(graceful degradation)。
    """
    search_mode: str  # "multimodal" | "text_fallback"
    query_caption: Optional[str] = None
    results: List[ImageSearchHit] = Field(default_factory=list)


class ImageUploadResponse(BaseModel):
    """Body of ``POST /knowledge/{kb_id}/images/upload``."""
    document_id: int
    task_id: Optional[str] = None
    status: str
