from sqlalchemy import Column, Computed, Integer, String, Boolean, Text, DateTime, Float
from sqlalchemy.sql import func
from lumen_models.base import BaseModel


class ModelConfig(BaseModel):
    """AI model configuration"""
    __tablename__ = "model_configs"

    name = Column(String(100), nullable=False, comment="Config name")
    model_type = Column(String(50), nullable=False, comment="ollama/openai/anthropic/zhipu/minimax")
    model_name = Column(String(100), nullable=False, comment="Model name like gpt-4o, qwen2.5")
    base_url = Column(String(500), nullable=True, comment="API base URL")
    api_key = Column(String(200), nullable=True, comment="API key (encrypted)")
    api_version = Column(String(50), nullable=True, comment="API version")
    temperature = Column(Float, default=0.7, comment="Default temperature")
    max_tokens = Column(Integer, default=4096, comment="Max output tokens")
    timeout = Column(Integer, default=120, comment="Request timeout in seconds")
    is_default = Column(Boolean, default=False, comment="Is default model")
    is_active = Column(Boolean, default=True, comment="Is active")
    is_chat = Column(Boolean, default=True, comment="Usable as a chat model")
    is_embedding = Column(Boolean, default=False, comment="Usable as an embedding model")
    is_image_generation = Column(Boolean, default=False, comment="Usable as an image generation model")
    is_tts = Column(Boolean, default=False, comment="M35: Usable as a TTS (text-to-speech) model")
    is_subtitle_generation = Column(Boolean, default=False, comment="M35: Usable as a subtitle generation model")
    is_video = Column(Boolean, default=False, comment="M36: Usable as a video generation model (Kling/Sora/Veo future)")
    tenant_id = Column(Integer, nullable=True, comment="Tenant ID (null for global)")
    description = Column(Text, nullable=True, comment="Model description")

    # Phase 1 Group A 3.4 (2026-09-04):VIRTUAL GENERATED 列,把
    # ``(tenant_id, model_type, model_name)`` 复合 UNIQUE 转成
    # ``(tenant_id, model_configs_dedup_key)`` —— active 行 =
    # ``<model_type>|<model_name>``,软删行 = NULL;UNIQUE on dedup 列
    # 实现"软删后 (type, model_name) 可复用"。VARCHAR(300) 留余量
    # (50 + 1 + 100 ≈ 151 字符)。
    model_configs_dedup_key = Column(
        String(300),
        Computed(
            "CASE WHEN is_active = 1 "
            "THEN CONCAT_WS('|', model_type, model_name) "
            "ELSE NULL END",
            persisted=False,
        ),
        nullable=True,
        comment="Phase 1 3.4 dedup key for soft-delete UNIQUE",
    )
