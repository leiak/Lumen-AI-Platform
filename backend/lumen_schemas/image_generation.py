"""Pydantic schemas for /api/v1/image-generation.

Spec: §4.3
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional, Dict, Any
from pydantic import BaseModel, ConfigDict, Field


class ImageGenerationCreate(BaseModel):
    # model_config_id 触发 Pydantic v2 的 "model_" 保护命名空间警告;
    # protected_namespaces=() 显式禁用,让字段名带 "model_" 前缀。
    model_config = ConfigDict(protected_namespaces=())

    model_config_id: int
    prompt: str = Field(min_length=1, max_length=4000)
    negative_prompt: Optional[str] = Field(default=None, max_length=4000)
    size: str = "1024x1024"
    n: int = Field(default=1, ge=1, le=4)
    quality: Optional[str] = None
    style: Optional[str] = None
    extra_params: Optional[Dict[str, Any]] = None
    # M35: optional playbook id to inject style keywords into the prompt
    playbook_id: Optional[int] = None


class ImageGenerationListItem(BaseModel):
    # model_name / model_type 触发 Pydantic v2 "model_" 保护命名空间警告;
    # protected_namespaces=() 禁用掉。
    model_config = ConfigDict(protected_namespaces=())

    id: int
    prompt_preview: str
    model_config_id: int
    model_name: str
    model_type: str
    size: str
    status: str
    has_thumbnail: bool
    file_size: Optional[int]
    width: Optional[int]
    height: Optional[int]
    duration_ms: Optional[int]
    created_at: datetime


class ImageGenerationDetail(ImageGenerationListItem):
    prompt: str
    negative_prompt: Optional[str]
    quality: Optional[str]
    style: Optional[str]
    n: int
    params: Optional[Dict[str, Any]]
    error_message: Optional[str]
    updated_at: datetime


# --- M40.1 quick wins: 2 个 SingleResponse[dict] leak 补 schema ---

class ImageGenerationCreated(BaseModel):
    """M40.1: POST /image-generation/ 和 POST /{id}/regenerate 强类型响应。

    替代 ``SingleResponse[dict]``:同步返回行 id / status / batch_id /
    model_config_id / created_at,bytes 由 background task 后续落盘 + GET /{id}
    拉详情。``batch_id`` 在 n=1 时为 None,n>1 时同 batch 行共享。
    """
    id: int
    status: str
    batch_id: Optional[str] = None
    model_config_id: int
    created_at: datetime
