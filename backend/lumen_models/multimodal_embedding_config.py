"""M38.4: Multimodal Embedding Config ORM.

知识库启用 multimodal 检索时,需要在 admin / 系统模型管理里配置一个
"multimodal embedding provider",KB 通过 ``multimodal_config_id`` 引用
本表。本表与 ``ModelConfig``(text embedding + chat 模型)是**平行**的两
类配置:``ModelConfig`` 走标准 text embedding / chat LLM 调用,本表
走 ``MultimodalEmbedder`` 抽象(text + image 同空间)。

字段对 spec 的影响:

- ``provider`` 值域(spec 原列 4 个: ``openai_vision`` / ``qwen_vl``
  / ``nomic_v15`` / ``azure_vision``,prototype 后扩到 6 个,新增
  ``jina_clip_v2`` + ``clip_base_32`` 走本地 HuggingFace
  transformers)
- ``dimension`` 必须与 embedder 输出一致(KB 切 multimodal 后所有
  chunks 走同一维度: jina-clip-v2=1024, CLIP-B/32=512, ...),索引
  重建需 dim 匹配
- ``tenant_id=NULL`` = 全局 builtin(同 ModelConfig / StockMusic /
  StockAsset 模式),对所有租户可见;租户级配置走 ``tenant_id=<own>``

参:
- spec: docs-internal/superpowers/specs/2026-08-26-kb-multimodal-parsing.md
- 选型: docs-internal/superpowers/plans/2026-08-31-m38-4-multimodal-embedding-selector.md
"""
from sqlalchemy import JSON, Boolean, Column, Computed, Index, Integer, String, Text

from lumen_models.base import BaseModel


class MultimodalEmbeddingConfig(BaseModel):
    __tablename__ = "multimodal_embedding_configs"

    # 人类可读名称,UI 列表展示用
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)

    # provider 枚举(详细见 selector 报告 §6.1):
    #   jina_clip_v2  — 本地 transformers, jina-clip-v2, 1024 dim(默认)
    #   clip_base_32  — 本地 transformers, CLIP-B/32, 512 dim(fallback)
    #   openai_vision — OpenAI 云端 vision embedding
    #   qwen_vl       — 阿里通义千问 VL
    #   nomic_v15     — ollama 本地 nomic-embed-vision(prototype 实测
    #                   ollama library 暂无该模型 manifest 500,留 enum
    #                   占位后续 ollama library 支持时启用)
    #   azure_vision  — Azure Computer Vision
    provider = Column(String(50), nullable=False, index=True)

    # 实际模型标识(与 provider 配套):jina_clip_v2 → "jinaai/jina-clip-v2",
    # clip_base_32 → "openai/clip-vit-base-patch32", openai_vision →
    # "gpt-4o" 等。提到顶层列便于 admin UI 列表展示 + 跟 ModelConfig.
    # model_name 命名一致
    model_name = Column(String(100), nullable=False, comment="HuggingFace id or cloud model name")

    # provider-specific 额外配置 JSON,例如 jina_clip_v2 存
    # {"revision": "<hash>", "device": "cpu|cuda"};clip_base_32 存
    # {"device": "cpu"};云端 provider 存 {"api_version": "...",
    # "deployment": "..."}
    config = Column(JSON, nullable=True)

    # 输出向量维度,初始化时由 embedder 上报固定值: jina-clip-v2=1024
    # / CLIP-B/32=512 / CLIP-L/14=768 / openai CLIP=...。KB 启用
    # multimodal 时,所有 chunks(text + image)必须 dim 一致,因此本
    # 列在 admin "test" 连通性接口成功后写入,后续不可改(只能新建)
    dimension = Column(Integer, nullable=True, comment="Vector dim; NULL until first successful embed")

    # 云端 provider 可能需要(本地 HF 走空字符串 / 占位即可)
    base_url = Column(String(500), nullable=True)
    # 加密存储,与 ModelConfig.api_key 同一约定
    api_key = Column(String(200), nullable=True)

    # admin UI 上的"启用 / 停用"开关;停用后 KB 不允许再选,但已被 KB
    # 引用的 config 不能删除(spec §10 risk 1: 引用保护)
    enabled = Column(Boolean, nullable=False, default=True)

    # 平台级默认:NULL 表示该 provider 没有"全局默认",非 NULL 表示
    # ``MultimodalEmbedderFactory`` 在没有 KB 显式指定 config_id 时
    # 走这个。同 provider 类型下多个 is_default 会在 factory 里取
    # id 最小的那个,DB 层不做 UNIQUE 约束是兼容多 provider 各保留
    # 一个 default
    is_default = Column(Boolean, nullable=False, default=False, index=True)

    # NULL = 全局 builtin,所有租户可见;非 NULL = 租户私有配置
    tenant_id = Column(Integer, nullable=True, index=True, comment="NULL = global builtin")

    # Phase 1 Group A 3.4 (2026-09-04):VIRTUAL GENERATED 列,active 行 =
    # 原 name,弱删行(``enabled=0``)= NULL;让 ``uq_mec_tenant_name``
    # UNIQUE 落在 dedup 列上,实现"弱删后 (tenant, name) 可复用"。
    # 注意:本表用 ``enabled`` 不用 ``is_active``(M38.4 step 2 设计如此)。
    mec_dedup_name = Column(
        String(255),
        Computed(
            "CASE WHEN enabled = 1 THEN name ELSE NULL END",
            persisted=False,
        ),
        nullable=True,
        comment="Phase 1 3.4 dedup key for soft-delete UNIQUE",
    )

    __table_args__ = (
        # 一个 provider 下同一租户不应该重名(全局 builtin 也算
        # ``tenant_id=NULL`` 这一组);删 KB 时如果引用了 config 不
        # 报错,只是把 config 留作"无人引用"状态由 admin 手动清理。
        # Phase 1 3.4:UNIQUE 实际列是 ``(tenant_id, mec_dedup_name)``
        # (见 ``lumen_core.database.ensure_mec_unique_dedup``),但
        # ORM 仍声明 ``(tenant_id, name)`` —— SQLAlchemy metadata
        # 跟 DB 实际列不同源,但 ORM 端 INSERT 时不指定 unique,实际
        # DB 端 UNIQUE 由 ensure_* 重建控制,二者不影响(``create_all``
        # 对已存在表不再 attempt DDL,只对新建表生效)。
        Index("uq_mec_tenant_name", "tenant_id", "name", unique=True),
        Index("ix_mec_provider_enabled", "provider", "enabled"),
    )