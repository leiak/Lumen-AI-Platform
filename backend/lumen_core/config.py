import logging as _logging_secret_validator
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings
from typing import Optional


# Boot-time sentinel prefixes — placeholder strings shipped in-tree as
# defaults that must NEVER reach a production deploy. The
# ``_check_secret_hygiene`` ``model_validator`` below refuses to boot
# (``DEBUG=False``) or warns loudly (``DEBUG=True``) when any field
# whose name carries ``*_SECRET`` / ``*_KEY`` / ``*_TOKEN`` still holds
# a string beginning with one of these prefixes. Mirrors the historical
# ``EXTERNAL_JWT_SECRET`` guard in ``app.main`` (see M14 / external
# chat widget spec § 5) — this centralises the policy across every
# key-shaped field so future config additions get the same treatment
# for free. Empty / ``None`` values are NOT considered placeholders
# because several keys (``S3_SECRET_KEY`` / ``BROADCAST_INTERNAL_SECRET``
# / ``MINIMAX_API_KEY`` / ``OAUTH2_CLIENT_SECRET``) default to empty
# or ``None`` to represent "feature not configured" — refusing to
# boot in that case would block legitimate dev setups.
_SECRET_PLACEHOLDER_PREFIXES: tuple[str, ...] = (
    "your-secret-key-",
    "dev-secret-key-",
    "dev-only-",
    "external-dev-only-",
    "change-in-production-",
)

BACKEND_ROOT = Path(__file__).resolve().parents[2]  # backend/
DEFAULT_STORAGE_DIR = BACKEND_ROOT / "storage"


class Settings(BaseSettings):
    # App
    APP_NAME: str = "Lumen AI Platform"
    DEBUG: bool = True

    # --- Phase 0 Unit 5 (2026-09-02) Logging ---
    # LOG_FORMAT: "json" (default — single-line JSON for ELK / Loki) or
    # "dev" (中文 string, dev 期 tail 直读友好)。
    LOG_FORMAT: str = "json"
    # LOG_LEVEL: Python logging level(DEBUG / INFO / WARNING / ERROR)。
    # dev 默认 INFO;prod 可升 WARNING 减噪。
    LOG_LEVEL: str = "INFO"

    # --- Phase 1 Group B 2.4.4 (2026-09-04) OpenTelemetry ---
    # OTEL_EXPORTER: "console"(dev 默认 — span 打到 stdout)/ "otlp"(OTLP
    # gRPC)/ "otlp_http"(OTLP HTTP/protobuf)/ "none"(完全关闭)。
    # dev 设 "none" 或 "none" 让 uvicorn 启动不报 OTel warning。
    OTEL_EXPORTER: str = "console"
    # OTEL_ENDPOINT: exporter URL。gRPC 默认 localhost:4317,HTTP 默认
    # localhost:4318/v1/traces(Day 4 docker-compose 加 jaeger / otel-
    # collector 后改成容器 DNS,例如 http://lumen-platform-otel-collector:4317)。
    OTEL_ENDPOINT: str = "http://localhost:4317"
    # OTEL_SERVICE_NAME: 覆盖默认 "lumen-backend"。生产可设环境特定名。
    OTEL_SERVICE_NAME: str = "lumen-backend"
    # --- Phase 1 Group B 4.4 Day 4 (2026-09-05) 采样率 ---
    # OTEL_SAMPLE_RATIO: 0.0~1.0,root span 采样比例。0.0 = 不采(等价
    # ALWAYS_OFF),1.0 = 全采(等价 ALWAYS_ON),中间值用 ParentBased
    # TraceIdRatioBased(ratio)。dev 默认 1.0 保留全量 trace 给调试;
    # prod 高流量场景降到 0.05~0.1 减 collector 压力。
    # 注意:0.0/1.0 边界走 ALWAYS_OFF/ALWAYS_ON sampler 而不是
    # TraceIdRatioBased(0/1) —— 后者在部分 SDK 版本会因 ratio arg 报错。
    OTEL_SAMPLE_RATIO: float = 1.0
    # DEPLOYMENT_ENV: "dev" / "staging" / "prod"。影响 OTel resource
    # deployment.environment label + 后续 SLO / 告警路由。
    DEPLOYMENT_ENV: str = "dev"

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

    # --- M38.1 Storage backend abstraction ---
    # Selects the backend used by ``lumen_services.storage``. Default
    # ``local`` keeps the pre-M38.1 behaviour of writing under
    # ``backend/storage/``. Switch to ``s3`` to route through boto3
    # against any S3-compatible service (MinIO / AWS S3 / Aliyun OSS).
    STORAGE_BACKEND: str = "local"
    # Override the LocalBackend root (default: ./storage). Useful when
    # uvicorn / celery runs in a different working directory from the
    # backend checkout, or when the volume is bind-mounted from a
    # different path inside the Docker container.
    STORAGE_LOCAL_ROOT: str = ""
    # --- S3 backend (only consulted when STORAGE_BACKEND=s3) ---
    # Endpoint URL for S3-compatible services (MinIO defaults to
    # http://localhost:9000). Leave empty for AWS S3.
    S3_ENDPOINT: str = ""
    S3_REGION: str = "us-east-1"
    S3_BUCKET: str = ""
    S3_ACCESS_KEY: str = ""
    S3_SECRET_KEY: str = ""
    # Use HTTPS for the endpoint. MinIO local dev wants this off;
    # AWS / production wants it on.
    S3_USE_SSL: bool = True
    # Path-style addressing (``http://host/bucket/key``) is required by
    # MinIO; AWS uses virtual-hosted (``bucket.host/key``) by default.
    S3_PATH_STYLE: bool = False
    # How long presigned URLs remain valid (seconds).
    S3_PRESIGNED_URL_EXPIRY: int = 3600

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

    # --- Phase 1 Group B 2.4.7 / B2c (2026-09-04) Alertmanager webhook ---
    # 关掉后 /api/v1/alerts/webhook 返 503(让 AM 重试,不走静默丢)。
    # dev 默认开;生产可关用于演练。
    ALERTS_WEBHOOK_ENABLED: bool = True

    @property
    def ALERTS_DIR(self) -> Path:
        """Phase 1 Group B 2.4.7 / B2c (2026-09-04):Alertmanager webhook 落盘目录。

        每个 firing alert 一个 JSON 文件,文件名 = fingerprint(同名覆盖,便于
        外部脚本聚合)。默认在 ``backend/storage/alerts/`` 下。
        """
        d = self.STORAGE_DIR / "alerts"
        d.mkdir(parents=True, exist_ok=True)
        return d

    # --- Phase 1 Group A 2.1 (2026-09-03) Rate-limit middleware ---
    # 关闭后 RateLimitMiddleware 跳过所有路径,等价于"无限流"。
    # dev 默认开(Phase 0 已 ship fail-closed 限流);生产环境
    # 关掉需要在 startup 注入 RATE_LIMIT_ENABLED=false 关闭保护。
    RATE_LIMIT_ENABLED: bool = True

    # --- M39 LangGraph Checkpoint (2026-09-29) ---
    # POSTGRES_URL: PostgresSaver 连接串,空串代表未配置(unittest 可
    # 在不依赖 PG 的情况下构造 Settings)。lifespan startup 检查
    # LANGGRAPH_CHECKPOINT_ENABLED 为真时才会真连;Service 自身 get()
    # 也会再次防御性检查,空串 → RuntimeError,避免 PostgresSaver
    # 内部静默 AttributeError。
    # dev: postgresql://lumen:lumenpw@localhost:15432/lumen_checkpoints
    POSTGRES_URL: str = ""
    # LANGGRAPH_CHECKPOINT_ENABLED: 主开关。False 时 lifespan 完全跳过
    # CheckpointerService.setup() / close();TeamRunner 走 in-memory
    # saver(后续 T1.13+ 实现)。dev 默认 False,显式开才能用 PG 持久化。
    LANGGRAPH_CHECKPOINT_ENABLED: bool = False
    # LangGraph Checkpointer pool sizing(M39 T1.3 v2 fix):min_size 控制
    # 启动预热连接数,max_size 控制并发上限。dev 默认 2/20 满足单测 + 小
    # 流量;prod 视 QPS 调到 5/50 之类。改完无需重启 pool,需重启
    # uvicorn / celery 才生效(lifespan close + new init)。
    CHECKPOINTER_POOL_MIN_SIZE: int = 2
    CHECKPOINTER_POOL_MAX_SIZE: int = 20

    class Config:
        env_file = ".env"

    @model_validator(mode="after")
    def _check_secret_hygiene(self) -> "Settings":
        """Refuse to boot if SECRET / KEY / TOKEN fields still hold dev placeholders.

        Centralises the historical ``EXTERNAL_JWT_SECRET`` guard that
        used to live in ``app.main`` (M14 spec § 5) so every
        ``*_SECRET`` / ``*_KEY`` / ``*_TOKEN`` field on ``Settings`` is
        enforced with the same policy. ``DEBUG=True`` only emits a
        WARNING so the pytest suite can still boot; ``DEBUG=False``
        raises ``ValueError`` to halt the process before it accepts
        traffic — deploying with a guessable JWT signing key or a
        hard-coded WX app_secret cipher is a P0 exposure (see
        ``docs/reviews/2026-10-04-nitpick.md`` C1 + C2).
        """
        # Scan all declared fields. Only string-typed key-shaped names
        # are inspected; ``Optional[str] = None`` keys (e.g. OAuth
        # client secret) and ``str = ""`` defaults representing
        # "feature disabled" are deliberately skipped via the
        # ``not value`` short-circuit.
        bad: list[tuple[str, str]] = []
        for name in type(self).model_fields:
            uname = name.upper()
            if not (
                "_SECRET" in uname
                or uname.endswith("_KEY")
                or "_KEY_" in uname
                or "_TOKEN" in uname
                or uname.endswith("_TOKEN")
            ):
                continue
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                continue
            if any(value.startswith(p) for p in _SECRET_PLACEHOLDER_PREFIXES):
                preview = value[:24] + ("..." if len(value) > 24 else "")
                bad.append((name, preview))
        if not bad:
            return self
        summary = ", ".join(f"{n}={v}" for n, v in bad)
        if self.DEBUG:
            _logging_secret_validator.getLogger("lumen_core.config").warning(
                "SECRET/KEY/TOKEN 字段仍为 dev placeholder (%s); "
                "DEBUG=True 仅 WARN,生产 (DEBUG=False) 会拒绝启动。",
                summary,
            )
        else:
            raise ValueError(
                "SECRET/KEY/TOKEN 字段仍为 dev placeholder,生产环境拒绝启动: "
                f"{summary}; 请通过环境变量覆盖 (例 SECRET_KEY=...)"
            )
        return self


settings = Settings()
