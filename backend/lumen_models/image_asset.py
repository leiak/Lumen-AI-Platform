"""M38.4: Image Asset ORM.

从文档中抽出的图片元数据 + 独立上传的图片(``Document.doc_type='image'``)。
每张图片生成一个 ``DocumentChunk`` (``modality='image'``),由 multimodal
embedder 把 caption 转成向量;同时本表记录原始图片的元数据 + storage_key
+ 嵌入状态,UI gallery 直接读本表(无需先 JOIN chunks)。

来源两类:

1. **独立上传**(用户在 KB 下直接拖图上传):``document.doc_type='image'``,
   本表 row 与之 1:1,``chunk_id`` 指向该 image 的唯一 chunk
2. **从 PPT / PDF 抽出**:多张图同源一个 doc,``document_id`` 指向原 PPT,
   ``original_doc_page`` 填抽出的页码(用于 UI 「此图来自 PPT 第 X 页」
   提示,spec §10 risk 1)

Spec § 3.3, docs-internal/superpowers/specs/2026-08-26-kb-multimodal-parsing.md.
"""
from sqlalchemy import Column, ForeignKey, Index, Integer, String, Text

from lumen_models.base import BaseModel


class ImageAsset(BaseModel):
    __tablename__ = "image_assets"

    # 来源 doc(独立 image doc 或 PPT 抽出图)。ON DELETE CASCADE:删 doc
    # 时抽出图一并清掉(避免孤儿图片 + chunk 引用)
    document_id = Column(
        Integer,
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Source Document.id; CASCADE on delete",
    )

    # 关联的 image chunk(独立 image doc 时 = 它的唯一 chunk,PPT 抽出
    # 时 = 该图片对应的 chunk)。ON DELETE SET NULL:chunk 被独立删除
    # 时(例如 re-chunk)只是清掉 FK,不影响图片记录
    chunk_id = Column(
        Integer,
        ForeignKey("document_chunks.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="DocumentChunk.id (modality='image'); SET NULL on delete",
    )

    # PPT/PDF 抽出时填页码,NULL 表示独立上传的图片
    original_doc_page = Column(
        Integer,
        nullable=True,
        comment="Source page when extracted from PPT/PDF; NULL = standalone upload",
    )

    # 对象存储 key,走 M38.1 storage_service 读取(``local`` backend 走
    # ``STORAGE_DIR / storage_key``,``s3`` 走 bucket key)。与
    # ``documents.asset_storage_key`` 同构
    storage_key = Column(String(500), nullable=False, comment="Storage backend key (relative for local, s3 key for S3)")

    # 原始像素信息(供前端按比例缩放 + EXIF 提取)。nullable:某些
    # 解析器(如纯文本格式的 SVG)拿不到尺寸
    width = Column(Integer, nullable=True)
    height = Column(Integer, nullable=True)

    # MIME(image/jpeg / image/png / image/webp / image/svg+xml)
    mime_type = Column(String(50), nullable=True)
    # 文件字节数,UI gallery 列表展示用
    file_size = Column(Integer, nullable=True)

    # 描述文本(multimodal embedder 输入)。M38.4 v1 用文件名派生的
    # caption(例 "chart_bar.png" → "bar chart"),M38.4.x v2 接入 LLM
    # 生成更丰富的描述。可空:embedder 失败时这一行是 fallback 上下文
    caption = Column(Text, nullable=True, comment="Multimodal embedder input text")

    # pending / ok / failed:同 DocumentChunk.embedding_status 语义
    # (spec §10 risk 3: image embedding 失败时 UI 仍能展示原图但搜不到)
    embedding_status = Column(
        String(20),
        nullable=False,
        default="pending",
        comment="pending / ok / failed; mirrors DocumentChunk.embedding_status",
    )

    __table_args__ = (
        # 复合索引:gallery 按 doc + 抽出顺序展示(PPT 翻页场景)
        Index("idx_image_assets_doc_created", "document_id", "created_at"),
    )