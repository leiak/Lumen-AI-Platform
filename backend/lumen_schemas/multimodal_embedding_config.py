"""M38.4: Multimodal Embedding Config schemas.

Pydantic shapes for ``MultimodalEmbeddingConfig`` (admin 列表 / CRUD)
+ ``POST /test`` 连通性 probe response。镜像 ``lumen_schemas/model_config``
的形态以保持 API 风格一致:Base / Create / Update / Response / TestResponse。

字段语义详见 ``lumen_models/multimodal_embedding_config.py``。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, Field


# Mirror the enum on the ORM. The admin UI uses this set to validate the
# "provider" dropdown. Order matches the docstring on the ORM class — keep
# the two in sync when adding new providers.
MultimodalProviderName = Literal[
    "jina_clip_v2",
    "clip_base_32",
    "openai_vision",
    "qwen_vl",
    "nomic_v15",
    "azure_vision",
]


class MultimodalEmbeddingConfigBase(BaseModel):
    """Shared shape for Create / Update / Response."""

    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=2000)
    provider: MultimodalProviderName
    model_name: str = Field(..., min_length=1, max_length=100)
    # ``config`` 是 provider-specific JSON(例 ``{"revision": "...", "device":
    # "cpu"}`` for jina_clip_v2)。不强制 schema,各 provider 自己解析。
    config: Optional[Dict[str, Any]] = None
    base_url: Optional[str] = Field(None, max_length=500)
    api_key: Optional[str] = Field(None, max_length=200)
    enabled: bool = True
    is_default: bool = False


class MultimodalEmbeddingConfigCreate(MultimodalEmbeddingConfigBase):
    """Body for ``POST /multimodal-configs/`` (admin only)."""


class MultimodalEmbeddingConfigUpdate(BaseModel):
    """Body for ``PUT /multimodal-configs/{id}`` (admin only).

    Every field is optional — PATCH-style. Only present fields are
    written to the DB; the rest stays unchanged. ``provider`` and
    ``model_name`` triggers a cache invalidation downstream.
    """

    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=2000)
    provider: Optional[MultimodalProviderName] = None
    model_name: Optional[str] = Field(None, min_length=1, max_length=100)
    config: Optional[Dict[str, Any]] = None
    base_url: Optional[str] = Field(None, max_length=500)
    api_key: Optional[str] = Field(None, max_length=200)
    enabled: Optional[bool] = None
    is_default: Optional[bool] = None


class MultimodalEmbeddingConfigResponse(MultimodalEmbeddingConfigBase):
    """Full row shape for list / get / create / update endpoints.

    ``tenant_id`` is exposed for parity with the ORM even though
    multimodal configs are global builtin (tenant_id=NULL) — admin
    UI may want to surface "shared across all tenants".
    """

    id: int
    dimension: Optional[int] = Field(
        None,
        description="Vector dim; NULL until first successful embed (POST /test)",
    )
    tenant_id: Optional[int] = Field(
        None,
        description="NULL = global builtin (all tenants); non-NULL = tenant-private",
    )
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class MultimodalConfigTestResponse(BaseModel):
    """Response shape for ``POST /multimodal-configs/{id}/test``.

    Always 200 — probe success/failure surfaces in ``ok``. This is
    deliberate so the UI can show a specific failure reason ("API key
    invalid" / "model unreachable") without forcing the admin to read
    the 500 detail.
    """

    ok: bool
    dim: Optional[int] = Field(
        None,
        description="Vector dim reported by the embedder; None on failure",
    )
    elapsed_ms: Optional[int] = Field(
        None,
        description="Wall-clock time for the dim-probe; None on failure",
    )
    error: Optional[str] = Field(
        None,
        description="Human-readable failure reason; None on success",
    )


__all__ = [
    "MultimodalProviderName",
    "MultimodalEmbeddingConfigBase",
    "MultimodalEmbeddingConfigCreate",
    "MultimodalEmbeddingConfigUpdate",
    "MultimodalEmbeddingConfigResponse",
    "MultimodalConfigTestResponse",
]
