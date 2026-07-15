from pathlib import Path

from pydantic_settings import BaseSettings
from typing import Optional

BACKEND_ROOT = Path(__file__).resolve().parents[2]  # backend/
DEFAULT_STORAGE_DIR = BACKEND_ROOT / "storage"


class Settings(BaseSettings):
    # App
    APP_NAME: str = "Lumen AI Platform"
    DEBUG: bool = True

    # Database
    DATABASE_URL: str = "mysql+pymysql://ai_user:ai_password@localhost:3306/ai_platform"

    # Ollama (for embeddings and chat)
    OLLAMA_API_BASE: str = "http://localhost:11434"
    OLLAMA_EMBEDDING_MODEL: str = "nomic-embed-text"
    OLLAMA_CHAT_MODEL: str = "qwen2.5:7b"

    # FAISS Vector Store
    FAISS_INDEX_PATH: str = "./data/faiss/knowledge_base"

    # Elasticsearch Vector Store
    ES_HOST: str = "localhost"
    ES_PORT: int = 9200
    ES_INDEX_PREFIX: str = "knowledge"
    ES_ENABLED: bool = False  # Default off, use FAISS unless explicitly enabled

    # Redis (for async task queue)
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    ASYNC_ENABLED: bool = False  # Default off, sync processing unless explicitly enabled

    # JWT
    SECRET_KEY: str = "your-secret-key-change-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    # External (widget) JWT — independent secret so a leaked user-JWT
    # secret cannot forge widget tokens. The boot-time guard in
    # ``app.main`` refuses to start when this is still the dev
    # placeholder AND ``DEBUG`` is False (see M14 / external chat
    # widget spec § 5).
    EXTERNAL_JWT_SECRET: str = "external-dev-only-change-in-production-please"
    EXTERNAL_TOKEN_TTL_SECONDS: int = 1800  # 30 min — short-lived on purpose

    # Shared secret required for cross-process broadcasts to honor
    # target_user_id on /api/v1/electron/broadcast. When unset, the
    # route will refuse to filter — broadcasts always fan out to all
    # clients (Electron-compatible default).
    BROADCAST_INTERNAL_SECRET: str = ""

    # OAuth2
    OAUTH2_CLIENT_ID: Optional[str] = None
    OAUTH2_CLIENT_SECRET: Optional[str] = None

    # MiniMax API (optional)
    MINIMAX_BASE_URL: Optional[str] = "https://api.minimax.chat/v1"
    MINIMAX_API_KEY: Optional[str] = None

    # --- Hybrid retrieval + rerank (Task 3) ---
    # Weights for the RRF combiner. Both must be >= 0; their relative
    # magnitude controls the balance between semantic and lexical match.
    RETRIEVAL_VECTOR_WEIGHT: float = 0.5
    RETRIEVAL_BM25_WEIGHT: float = 0.5
    # Master switch for the rerank stage. When False, the pipeline stops
    # after RRF fusion and returns the top-K hybrid results directly.
    RERANK_ENABLED: bool = True
    # Rerank backend: "auto" (jina -> llm fallback), "jina", "llm", "noop".
    RERANK_TYPE: str = "auto"
    # Rerank model name. For jina: e.g. "jina-reranker-v2-base-multilingual".
    # For llm: the chat model name to use; falls back to OLLAMA_CHAT_MODEL.
    RERANK_MODEL: Optional[str] = None
    # Number of candidates to fetch from hybrid before reranking.
    RERANK_TOP_N: int = 20
    # Whether to use jieba for Chinese tokenisation in the BM25 index.
    BM25_USE_JIEBA: bool = True

    # --- Image generation storage (M22 / T3) ---
    # Empty → use STORAGE_DIR/generated_images. Override via env var
    # IMAGE_STORAGE_DIR=/some/absolute/path when the storage volume lives
    # outside the backend checkout (e.g. mounted disk in production).
    IMAGE_STORAGE_DIR: str = ""

    @property
    def STORAGE_DIR(self) -> Path:
        root = DEFAULT_STORAGE_DIR
        root.mkdir(parents=True, exist_ok=True)
        return root

    @property
    def GENERATED_IMAGES_DIR(self) -> Path:
        if self.IMAGE_STORAGE_DIR:
            d = Path(self.IMAGE_STORAGE_DIR)
        else:
            d = self.STORAGE_DIR / "generated_images"
        d.mkdir(parents=True, exist_ok=True)
        return d

    # --- WeChat publisher (M32) ---
    # Whether to use the real WeChat Open Platform API client. Default
    # False (dev safety — never auto-fire real posts). Flip on per-env
    # via WX_PUBLISHER_REAL_CLIENT_ENABLED=true.
    WX_PUBLISHER_REAL_CLIENT_ENABLED: bool = False
    # Fernet key for encrypting ``wx_accounts.app_secret_encrypted``.
    # MUST be overridden in production via env var. The default is a
    # 32-byte url-safe base64 sentinel — keep it that way for dev so
    # the first uvicorn boot doesn't crash on missing config.
    WX_PUBLISHER_FERNET_KEY: str = (
        "dev-only-fernet-key-do-not-use-in-prod-32b"
    )
    # Where wx_publisher assets (draft render artefacts, manual
    # material uploads) live. Empty → use STORAGE_DIR/wx_publisher.
    WX_PUBLISHER_STORAGE_DIR: str = ""

    @property
    def WX_PUBLISHER_DIR(self) -> Path:
        if self.WX_PUBLISHER_STORAGE_DIR:
            d = Path(self.WX_PUBLISHER_STORAGE_DIR)
        else:
            d = self.STORAGE_DIR / "wx_publisher"
        d.mkdir(parents=True, exist_ok=True)
        return d

    class Config:
        env_file = ".env"


settings = Settings()
