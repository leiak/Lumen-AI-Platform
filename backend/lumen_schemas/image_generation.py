"""Pydantic schemas for /api/v1/image-generation.

Spec: §4.3
"""
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
