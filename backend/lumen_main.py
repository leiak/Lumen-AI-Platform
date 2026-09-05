import asyncio
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv

# 加载 backend/.env 到 os.environ,确保 lumen_services.storage 等用
# os.getenv 直接读 STORAGE_BACKEND / S3_* / DATABASE_URL 等模块能拿到值
# (Settings(BaseSettings, env_file=".env") 自己 parse .env 但不会 publish
# 到 os.environ;不显式 load_dotenv 的话改 .env 必须手动 export 才能生效)。
# 依赖 uvicorn 启动时 cwd 是 backend/(本仓库 dev 启动惯例)。
load_dotenv()

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from lumen_core.config import settings
from lumen_core.dynamic_cors import DynamicCORSMiddleware
from lumen_api.middleware.trace_id import TraceIdMiddleware  # Phase 0 Unit 5 4.2
from lumen_api.middleware.rate_limit import RateLimitMiddleware  # Phase 1 Group A 2.1
from lumen_api.middleware.prometheus import PrometheusMiddleware  # Phase 0 Unit 5 4.3
from lumen_core.database import (
    create_tables,
    ensure_workflow_runs_trigger_source,
    ensure_workflow_indexes,  # M30a: composite indexes for list pages
    ensure_document_chunks_embedding_status,
    ensure_workflow_model_refs_migrated,
    ensure_workflow_v2_migrated,
    ensure_documents_created_by,
    ensure_conversations_deleted_at,
    ensure_conversations_team_id,
    ensure_conversations_user_id_nullable,
    ensure_conversations_external_fks,
    ensure_external_apps_tables,
    ensure_model_configs_purpose_flags,
    ensure_embedding_model_config_migrated,
    ensure_global_memories_conversation_id,
    ensure_marketplace_type_column,
    ensure_agent_kb_retrieval_config,  # M21
    ensure_model_configs_image_flag,  # M22
    ensure_model_configs_tts_subtitle_flags,  # M35
    ensure_model_configs_video_flag,  # M36
    ensure_settings_model_fk_columns,  # M31
    ensure_generated_images_table,  # M22
    ensure_generated_audios_table,  # M35
    ensure_subtitles_table,  # M35
    ensure_playbooks_table,  # M35
    ensure_generated_videos_table,  # M36
    ensure_stock_assets_table,  # M36.2.1
    ensure_stock_musics_table,  # M36.2.2
    ensure_llm_call_logs_table,  # M26
    ensure_embedding_call_logs_table,  # M27
    ensure_soft_delete_columns,  # M27
    ensure_faq_entries_table,  # M31: Q&A entry feature
    # M32: 公众号助手 - 6 张新表 wx_accounts / wx_templates / wx_drafts /
    # wx_draft_sections / wx_materials / wx_publish_records
    ensure_wx_accounts_table,
    ensure_wx_templates_table,
    ensure_wx_drafts_table,
    ensure_wx_draft_sections_table,
    ensure_wx_materials_table,
    ensure_wx_publish_records_table,
    # M33: 客户管理(CRM) - 3 张新表 customers / customer_follow_ups /
    # customer_field_definitions
    ensure_customers_table,
    ensure_customer_follow_ups_table,
    ensure_customer_field_definitions_table,
    # M33: 智能问数(Text2SQL) - 2 张新表 text2sql_data_sources /
    # text2sql_queries
    ensure_text2sql_data_sources_table,
    ensure_text2sql_queries_table,
    # M34: 平台 KV 配置 - system_configs + 默认 skill_http_allowed_domains
    ensure_system_configs_table,
    # Skill 表租户隔离 - tenant_id 列 + 索引 + 回填
    ensure_skills_tenant_id,
    ensure_skill_type_column,
    # M37.1: RAG 评测集管理 - eval_datasets + eval_dataset_items
    ensure_eval_datasets_table,
    # M37.2: 评测运行器 - eval_runs + eval_run_results
    ensure_eval_runs_table,
    # M38.2.x v2: workspace RBAC grants table
    ensure_workspace_member_permissions_table,
    # Phase 1 Group A 1.5 (2026-09-03): failed_tasks DLQ table
    ensure_failed_tasks_table,
    # Phase 1 Group A 3.4 (2026-09-04): UNIQUE × soft-delete 冲突修复。
    # 给 9 张表(users × 2 / model_configs / multimodal_embedding_configs /
    # external_apps / wx_accounts / roles / skills /
    # customer_field_definitions)加 dedup VIRTUAL GENERATED 列 + 重建 UNIQUE,
    # 实现"软删后 identifier 可复用"。详见
    # docs-internal/roadmap/2026-09-04-phase-1-3-4-unique-softdelete-fix.md。
    ensure_users_unique_dedup,
    ensure_model_configs_unique_dedup,
    ensure_mec_unique_dedup,
    ensure_external_apps_unique_dedup,
    ensure_wx_accounts_unique_dedup,
    ensure_roles_unique_dedup,
    ensure_skills_unique_dedup,
    ensure_customer_field_definitions_unique_dedup,
    # M38.1: documents.asset_storage_key + storage_backend 列 + 索引
    ensure_documents_storage_columns,
    # M38.2: workspaces / document_folders 表 + knowledge_bases.workspace_id
    # / documents.folder_id 列。Order matters — workspace/folder 表先建,
    # 后两步才能 ALTER 加 FK 列。
    ensure_workspaces_table,
    ensure_document_folders_table,
    ensure_knowledge_bases_workspace_column,
    ensure_documents_folder_column,
    # M38.4: multimodal embedding configs + image_assets + documents /
    # document_chunks / knowledge_bases multimodal 列。Order matters —
    # multimodal_embedding_configs 表先建,knowledge_bases.multimodal_config_id
    # FK 才能解析;documents / document_chunks 列加完才能让 image_assets FK
    # 解析。
    ensure_multimodal_embedding_configs_table,
    ensure_image_assets_table,
    ensure_documents_multimodal_columns,
    ensure_document_chunks_multimodal_columns,
    ensure_knowledge_bases_multimodal_columns,
)
from lumen_core.notification_migration import ensure_notifications_table
from lumen_api.v1 import router as v1_router

# Import all models to ensure they are registered with SQLAlchemy Base before create_tables()
# IMPORTANT: Tenant must be imported first because other models have relationships to it
from lumen_models.tenant import Tenant
from lumen_models.agent import Agent, AgentTool, AgentKnowledgeBase
from lumen_models.agent_team import AgentTeam, AgentTeamMember, AgentTeamRoute  # Multi-agent team
from lumen_models.external_app import ExternalApp, ExternalVisitor  # Must come before chat.py so FK refs resolve
from lumen_models.chat import Conversation, Message
from lumen_models.knowledge import KnowledgeBase, Document, DocumentChunk
from lumen_models.knowledge import FAQEntry  # M31
from lumen_models.memory import ConversationMemory, GlobalMemory  # New memory models
from lumen_models.model_config import ModelConfig
from lumen_models.nlp_training import NLPTrainingClassification, NLPAnnotation, NLPQA
from lumen_models.role import Role, Permission
from lumen_models.settings import SystemSettings as Settings, SecuritySettings
from lumen_models.skill import Skill
from lumen_models.tenant import Tenant
from lumen_models.user import User
from lumen_models.vision_training import VisionClassification, VisionImage
from lumen_models.workflow import Workflow, WorkflowRun, WorkflowSchedule
from lumen_models.workflow_template import WorkflowTemplate
from lumen_models.mcp import MCPServer, MCPTool, MCPToolExecution  # MCP models
from lumen_models.skill_marketplace import SkillMarketplace, InstalledSkill  # Skill marketplace models
from lumen_models.notification import Notification  # In-app notification model
from lumen_models.image_generation import GeneratedImage  # M22: image generation
from lumen_models.tts import GeneratedAudio  # M35: TTS
from lumen_models.subtitle import Subtitle  # M35: subtitle
from lumen_models.playbook import Playbook  # M35: playbook
from lumen_models.stock_asset import StockAsset  # M36.2.1: stock footage library
from lumen_models.stock_music import StockMusic  # M36.2.2: stock background music library
from lumen_models.eval_dataset import EvalDataset, EvalDatasetItem  # M37.1: RAG 评测集
from lumen_models.eval_run import EvalRun, EvalRunResult  # M37.2: 评测运行器
from lumen_models.wx_publisher import (  # M32: 公众号助手
    WxAccount,
    WxTemplate,
    WxDraft,
    WxDraftSection,
    WxMaterial,
    WxPublishRecord,
)
from lumen_models.customer import (  # M33: 客户管理(CRM)
    Customer,
    CustomerFollowUp,
    CustomerFieldDefinition,
)
from lumen_models.text2sql import (  # M33: 智能问数(Text2SQL)
    Text2SqlDataSource,
    Text2SqlQuery,
)
from lumen_models.system_config import SystemConfig  # M34: 平台 KV 配置
from lumen_models.llm_call_log import LLMCallLog  # M26: LLM call observability
from lumen_models.embedding_call_log import EmbeddingCallLog  # M27: Embedding call observability
from lumen_services.logging_service import AuditLog, OperationLog, QueryLog  # Logging models
from lumen_models.workspace import Workspace, DocumentFolder  # M38.2: 注册 workspaces / document_folders 表到 Base.metadata,否则 knowledge_bases.workspace_id 和 documents.folder_id FK 无法解析(M38.2 ship 漏项,2026-08-27 回归补)
from lumen_models.workspace_member_permission import WorkspaceMemberPermission  # M38.2.x v2: workspace RBAC grants
from lumen_models.multimodal_embedding_config import MultimodalEmbeddingConfig  # M38.4: multimodal embedding configs 表注册
from lumen_models.image_asset import ImageAsset  # M38.4: image_assets 表注册
from lumen_models.failed_task import FailedTask  # Phase 1 Group A 1.5 (2026-09-03): failed_tasks DLQ 表注册

app = FastAPI(
    title=settings.APP_NAME,
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# Phase 1 Group B 2.4.4 (2026-09-04): OpenTelemetry SDK + FastAPI 自动 instrumentation。
# 模块级(不是 lifespan)原因:FastAPIInstrumentor.instrument_app(app) 必须在
# TracerProvider 设置之后才能拿到正确 tracer;两件事绑定在一起最干净。
# setup_tracing() 本身幂等(模块级 _initialized 守门),多次调用无副作用。
# OTEL_EXPORTER=none / off → noop,不污染 dev / pytest 输出。
#
# httpx 自动 instrumentation 也在 setup_tracing() 内部完成(HTTPXClientInstrumentor
# 是模块级 patch,无需 app 引用)。SQLAlchemy / Celery 自动 instrumentation
# 留 Day 2(跟 engine 创建顺序 / Celery worker_init 信号耦合)。
from lumen_core.otel import setup_tracing
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

if setup_tracing(
    service_name=settings.OTEL_SERVICE_NAME,
    deployment_environment=settings.DEPLOYMENT_ENV,
):
    # 只在 setup_tracing 真初始化了 TracerProvider 时才 instrument app;
    # OTEL_EXPORTER=none 时不挂中间件,免得 FastAPIInstrumentor 报"NoOp tracer"
    # warning + 0 收益开销。
    FastAPIInstrumentor.instrument_app(app)

# Phase 0 Unit 2 (2026-09-02):启动期标志。
# K8s readiness / startup probe 用,/startup 返 503 表示 uvicorn 进程在
# 跑但 startup_event 还没跑完(40+ ensure_* 迁移 + scheduler 启动),
# 等所有 migration 完成才 flip True。Phase 0 dev 用不上,但跟
# /live / /ready 一起 ship 免得后续 K8s 迁移再补。
_startup_complete: bool = False

# Refuse to boot if EXTERNAL_JWT_SECRET is still the dev placeholder.
# Mirrors the well-known dev-only-default check pattern from production
# frameworks; protects against deploying a build where the external
# widget would be wide-open because tokens are signed with a guessable
# key. Logging the warning is the actionable signal — the ValueError
# halts the process before it accepts traffic. In DEBUG mode (local
# dev + pytest) we only warn so the suite can still start.
import logging as _logging
if settings.EXTERNAL_JWT_SECRET.startswith("external-dev-only"):
    if not settings.DEBUG:
        raise ValueError(
            "EXTERNAL_JWT_SECRET is still the dev default; set a real value in production"
        )
    _logging.getLogger(__name__).warning(
        "EXTERNAL_JWT_SECRET is dev-only; OK for DEBUG, REFUSED in production"
    )

# Preload celery_app to break the celery_app <-> document_tasks
# circular import. celery_app.py:31 does
# `from lumen_tasks.document_tasks import process_document_task` at module
# bottom (to register the task), and document_tasks.py:5 does
# `from lumen_tasks.celery_app import celery_app` at module top (to use
# @celery_app.task). Together they form a cycle that only resolves
# when celery_app is loaded FIRST — at that point the partial
# celery_app module already exposes the `celery_app` Celery instance
# (line 5) so document_tasks:5's import succeeds. Without this preload,
# the FIRST endpoint call that lazy-imports `process_document_task`
# after a fresh uvicorn start hits the cycle and returns 500.
# Bug reproduced 2026-06-08 on POST
# /api/v1/knowledge/documents/22/rechunk (knowledge.py:527). The
# same workaround is already applied in tests/unit/conftest.py for
# the test environment.
#
# NOTE: `import lumen_X` REBINDS the local `app` name to the `app`
# package module (verified — this file's `app = FastAPI(...)` would
# get clobbered and the subsequent `app.add_middleware(...)` would
# raise AttributeError). Use `as _celery_preload` (or `from
# app.tasks import celery_app`) to load the submodule WITHOUT
# shadowing the local FastAPI instance bound to `app`.
import lumen_tasks.celery_app as _celery_preload  # noqa: F401,E402

# Dynamic CORS — static origins for the internal dashboard + DB-driven
# origins for the embeddable widget (60s cache; cache.invalidate() on admin
# edit flushes immediately). Replaces the hardcoded CORSMiddleware.
app.add_middleware(
    DynamicCORSMiddleware,
    static_origins=[
        "http://localhost:11334",
        "http://127.0.0.1:11334",
    ],
    cache_ttl_seconds=60,
)
# Phase 0 Unit 5 4.2 (2026-09-02):trace_id 全链路贯通。
# 必须**最外层**(最后 add_middleware,FIFO),让所有下游 middleware / endpoint
# / log / httpx 调用 / DB writer 都能从 contextvar 读到 trace_id。
# 优先级低于 CORS(放 CORS 后) — 因为浏览器 OPTIONS 预检没 trace_id,
# CORS 失败不应该挡 trace_id 注入。
app.add_middleware(
    TraceIdMiddleware,
)
# Phase 1 Group A 2.1 (2026-09-03): 全局限流 middleware。
# 紧贴 TraceId(同 contextvar 上下文),policy dict 覆盖关键高频路径
# (/auth/login, /chat, /knowledge/upload, /videos/compose 等)。
# Redis 挂走 fail-closed 503(Phase 0 行为保留);超限 429 + Retry-After。
# 顺序: TraceId → RateLimit → Prometheus — 限流挡无效流量,但保留 metrics
# 记录 429 / 503(让 Prometheus scrape 看得到限流事件)。
app.add_middleware(RateLimitMiddleware)
# Phase 0 Unit 5 4.3 (2026-09-02):Prometheus HTTP metrics 中间件。
# 紧贴 TraceIdMiddleware(同 contextvar 上下文),记录每个请求的
# counter + duration histogram。/metrics 端点本身**也被**记录(spec 注释
# 明确:不 skip —— 否则 scrape 自身不计入总请求数,debug 时困惑)。
# path label 用 route template(/users/{user_id})而非实际 URL,防
# cardinality 爆炸。
app.add_middleware(
    PrometheusMiddleware,
)

# Create tables on startup
def _should_run_scheduler_for_worker() -> bool:
    """Phase 1 Group A 1.1 (2026-09-03): scheduler 启动守门。

    决策:
    - RUN_SCHEDULER=false → 强制不启
    - RUN_SCHEDULER=true  → 强制启(单 worker 调试用)
    - RUN_SCHEDULER=auto(默认)→ 仅 WORKER_RANK=0 才启

    返回 bool:True = 这个 worker 应该启 scheduler。
    抽成 helper 是为了单测覆盖(整 lifespan 太重 —— 40+ ensure_* + DB 迁移)。
    """
    run_mode = os.getenv("RUN_SCHEDULER", "auto").lower()
    if run_mode == "false":
        return False
    if run_mode == "true":
        return True
    # auto:仅 worker 0 启
    try:
        worker_rank = int(os.getenv("WORKER_RANK", "0"))
    except ValueError:
        worker_rank = 0
    return worker_rank == 0


async def _shutdown_cleanup(
    started_scheduler: bool,
    celery_queue_monitor_task: "asyncio.Task | None" = None,
    celery_queue_monitor_shutdown: "asyncio.Event | None" = None,
    slo_budget_calculator_task: "asyncio.Task | None" = None,
    slo_budget_calculator_shutdown: "asyncio.Event | None" = None,
) -> None:
    """Phase 1 Group A 1.1 (2026-09-03): lifespan finally 块的清理逻辑。

    仅 `started_scheduler=True` 时调 scheduler.stop()(避免空 stop 抛错
    — _scheduler singleton 已 start 才能 shutdown);最后必 engine.dispose()
    防止 MySQL MDL 孤儿连接(2026-06-08 踩到,KILL 脚本恢复)。

    Phase 1 Group B 2.4.5 (2026-09-04):celery_queue_monitor 通过 Event + task
    传参优雅退出(set Event → 等 task 5s → 超时则 cancel),避免后台 task 在
    Redis 连接 close 后还在 tick。

    Phase 1 Group B B2b 4.6 (2026-09-04):slo_budget_calculator 同款 Event +
    task 优雅退出模式。

    抽成 helper 是为了单测 —— 整 lifespan 太重,直接调这个验 dispose 触发。
    """
    if started_scheduler:
        try:
            from lumen_services.workflow_scheduler import get_scheduler_service
            get_scheduler_service().stop()
        except Exception as e:  # noqa: BLE001
            import logging as _shutdown_logger
            _shutdown_logger.getLogger(__name__).warning(
                "scheduler stop failed: %s", e,
            )
    # Phase 1 Group B 2.4.5 (2026-09-04):celery_queue_monitor 优雅退出。
    # set Event 让 loop 退出 wait_for,最多等 5s,超时则 cancel —— 避免
    # 后台 task 在 Redis connection 已 close 后还在 tick 抛 ConnectionError。
    if celery_queue_monitor_task is not None and celery_queue_monitor_shutdown is not None:
        celery_queue_monitor_shutdown.set()
        try:
            await asyncio.wait_for(celery_queue_monitor_task, timeout=5.0)
        except asyncio.TimeoutError:
            celery_queue_monitor_task.cancel()
            import logging as _shutdown_logger
            _shutdown_logger.getLogger(__name__).warning(
                "celery_queue_monitor didn't exit in 5s; cancelled"
            )
        except Exception as e:  # noqa: BLE001
            import logging as _shutdown_logger
            _shutdown_logger.getLogger(__name__).warning(
                "celery_queue_monitor shutdown error: %s", e,
            )
    # Phase 1 Group B B2b 4.6 (2026-09-04):slo_budget_calculator 优雅退出。
    # 同 celery_queue_monitor 套路 —— Event + wait_for 5s + cancel。
    if slo_budget_calculator_task is not None and slo_budget_calculator_shutdown is not None:
        slo_budget_calculator_shutdown.set()
        try:
            await asyncio.wait_for(slo_budget_calculator_task, timeout=5.0)
        except asyncio.TimeoutError:
            slo_budget_calculator_task.cancel()
            import logging as _shutdown_logger
            _shutdown_logger.getLogger(__name__).warning(
                "slo_budget_calculator didn't exit in 5s; cancelled"
            )
        except Exception as e:  # noqa: BLE001
            import logging as _shutdown_logger
            _shutdown_logger.getLogger(__name__).warning(
                "slo_budget_calculator shutdown error: %s", e,
            )
    # 关闭 SQLAlchemy 连接池,避免 taskkill / SIGTERM 后 MySQL 留 Sleep
    # 连接持 MDL 导致下个 uvicorn 启动时 ensure_* ALTER 卡 MDL 等候链
    # (2026-06-08 第 5 次重启时踩到,KILL 孤儿连接后才恢复)。
    # Redis 客户端走 closure-based 模式(rate_limit.build_default_limiter),
    # 未维护全局 registry,Phase 0 不强行关;Phase 1 引入分布式锁后会
    # 跟 dist_lock 一起建全局 registry。
    # S3 (boto3) 不需要显式 close,内部 connection pool 随 GC 释放。
    from lumen_core.database import engine
    engine.dispose()


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """Phase 1 Group A 1.1 (2026-09-03): lifespan 上下文替代 @app.on_event。

    为什么不用 @app.on_event("startup")/("shutdown"):
    FastAPI 0.93+ 推荐 lifespan,语义更明确(上下文管理器 yield 前 = startup,
    yield 后 = shutdown),而且 gunicorn UvicornWorker 在 fork 后子进程触发
    lifespan startup —— 多 worker 模式下,所有 worker 都会跑一次 lifespan,
    所以 WORKER_RANK 守门是 scheduler 启动的核心。

    WORKER_RANK 守门逻辑:
    - "true":强制启 scheduler(单 worker dev / 调试用)
    - "false":强制不启
    - "auto"(默认):WORKER_RANK=0 才启,gunicorn 0..N-1 编号
    """
    # Phase 0 Unit 5 4.1 (2026-09-02):结构化 JSON 日志。
    # 必须在 ensure_* 迁移之前调,让迁移期间的 logger.error 也能 JSON 化。
    # LOG_FORMAT=json (生产 / ELK)  或 dev (中文 string, dev 友好);
    # 通过 LOG_LEVEL 控制全局级别。
    from lumen_core.logging_config import setup_default_logging, setup_json_logging
    fmt = settings.LOG_FORMAT.lower()
    if fmt == "json":
        setup_json_logging(level=settings.LOG_LEVEL)
    elif fmt == "dev":
        setup_default_logging(level=settings.LOG_LEVEL)
    else:
        # 未知值兜底走 json,避免 typo 静默走默认中文
        setup_json_logging(level=settings.LOG_LEVEL)
    create_tables()
    # Idempotent column migrations for tables that predate their current
    # schema. `Base.metadata.create_all` only creates missing tables, not
    # missing columns on existing tables. No Alembic yet.
    ensure_workflow_runs_trigger_source()
    ensure_workflow_indexes()  # M30a: composite indexes for list pages
    ensure_document_chunks_embedding_status()
    ensure_workflow_model_refs_migrated()
    ensure_workflow_v2_migrated()
    ensure_notifications_table()
    ensure_documents_created_by()
    ensure_documents_storage_columns()  # M38.1: storage backend abstraction
    # M38.2: Workspace + DocumentFolder navigation layer.
    # Order matters — workspaces / document_folders tables must
    # exist before the FK columns on knowledge_bases / documents
    # are added. All four functions are idempotent so re-running
    # on every uvicorn boot is a no-op.
    ensure_workspaces_table()
    ensure_document_folders_table()
    ensure_knowledge_bases_workspace_column()
    ensure_documents_folder_column()
    # M38.4: multimodal embedding configs + image_assets + documents /
    # document_chunks / knowledge_bases multimodal 列。Order matters:
    # multimodal_embedding_configs 表先建,knowledge_bases.multimodal_config_id
    # FK 才能解析。
    ensure_multimodal_embedding_configs_table()
    ensure_image_assets_table()
    ensure_documents_multimodal_columns()
    ensure_document_chunks_multimodal_columns()
    ensure_knowledge_bases_multimodal_columns()
    ensure_conversations_deleted_at()
    ensure_conversations_team_id()
    ensure_conversations_user_id_nullable()
    ensure_conversations_external_fks()
    # Must run AFTER ensure_conversations_external_fks: the FK on
    # conversations.external_app_id references external_apps(id), so
    # the parent table must exist before the FK is added.
    # ensure_conversations_external_fks already gates the FK on
    # _table_exists("external_apps"), so the order is robust either
    # way; this ordering keeps the "table → FK" mental model clean.
    ensure_external_apps_tables()
    ensure_model_configs_purpose_flags()
    ensure_embedding_model_config_migrated()
    ensure_global_memories_conversation_id()
    ensure_marketplace_type_column()
    ensure_agent_kb_retrieval_config()  # M21: agents.kb_retrieval_config
    ensure_model_configs_image_flag()  # M22: model_configs.is_image_generation
    ensure_model_configs_tts_subtitle_flags()  # M35: model_configs.is_tts + is_subtitle_generation
    ensure_model_configs_video_flag()  # M36: model_configs.is_video
    ensure_settings_model_fk_columns()  # M31: system_settings.default_model/embedding_model → INT FK
    ensure_generated_images_table()  # M22: generated_images
    ensure_generated_audios_table()  # M35: TTS
    ensure_subtitles_table()  # M35: subtitle
    ensure_playbooks_table()  # M35: playbook
    ensure_generated_videos_table()  # M36: generated_videos (composition)
    ensure_stock_assets_table()  # M36.2.1: stock_assets (video素材库)
    ensure_stock_musics_table()  # M36.2.2: stock_musics (背景音乐库)
    ensure_llm_call_logs_table()  # M26: llm_call_logs
    ensure_embedding_call_logs_table()  # M27: embedding_call_logs
    ensure_soft_delete_columns()  # M27: archived_at on llm + embedding logs
    ensure_faq_entries_table()  # M31: faq_entries (Q&A entry feature)
    # M32: 公众号助手 6 张新表(每张都靠 model __table_args__ 声明
    # 自己的 UNIQUE/INDEX 约束,create_all 一次性建好;不需额外补
    # _index_exists 守门,见 database.py:1451+)
    ensure_wx_accounts_table()
    ensure_wx_templates_table()
    ensure_wx_drafts_table()
    ensure_wx_draft_sections_table()
    ensure_wx_materials_table()
    ensure_wx_publish_records_table()
    # M33: 客户管理(CRM) 3 张新表(每张都靠 model __table_args__ 声明
    # 自己的 UNIQUE/INDEX 约束,create_all 一次性建好;不需额外补
    # _index_exists 守门,见 M32 wx_publisher 同模式)
    ensure_customers_table()
    ensure_customer_follow_ups_table()
    ensure_customer_field_definitions_table()
    # M33: 智能问数(Text2SQL) 2 张新表(data_sources 必须先建,queries
    # 表有 FK → data_sources.id)
    ensure_text2sql_data_sources_table()
    ensure_text2sql_queries_table()
    # M34: 平台 KV 配置 — system_configs 表 + 默认
    # skill_http_allowed_domains seed(3 个免费 API)。
    # Operator 可手工 UPDATE 该行加/删域名,ensure 只在行缺失时插入,
    # 不覆盖手工修改。
    ensure_system_configs_table()
    # Skill 表租户隔离：tenant_id 列 + 回填已安装自定义技能
    ensure_skills_tenant_id()
    ensure_skill_type_column()
    # M37.1: eval_datasets + eval_dataset_items(RAG 评测集管理)
    ensure_eval_datasets_table()
    # M37.2: eval_runs + eval_run_results(评测运行器 + 单条 item 结果)
    ensure_eval_runs_table()
    # M38.2.x v2: workspace RBAC grants table (workspace_member_permissions)
    ensure_workspace_member_permissions_table()
    # Phase 1 Group A 1.5 (2026-09-03): failed_tasks DLQ 表 — admin
    # 通过 /admin/tasks/failed 查 / 重派 / ack 失败任务
    ensure_failed_tasks_table()
    # Phase 1 Group A 3.4 (2026-09-04): UNIQUE × soft-delete 冲突修复。
    # 9 个 ensure_* 都 idempotent(以 dedup column 已存在为"完成"信号),
    # 后续 boot 是 no-op。
    ensure_users_unique_dedup()
    ensure_model_configs_unique_dedup()
    ensure_mec_unique_dedup()
    ensure_external_apps_unique_dedup()
    ensure_wx_accounts_unique_dedup()
    ensure_roles_unique_dedup()
    ensure_skills_unique_dedup()
    ensure_customer_field_definitions_unique_dedup()
    # Seed a demo ExternalApp for local dev (idempotent). Runs after
    # ensure_external_apps_tables() so the parent table is guaranteed
    # to exist, and before scheduler reload so the DB is fresh.
    from lumen_scripts.seed_external_app import seed_dev_external_app
    seed_dev_external_app()

    # Phase 1 Group A 1.1 (2026-09-03): scheduler 单 worker 守门。
    # gunicorn 多 worker 模式下,每个 worker 都会跑 lifespan startup。
    # scheduler 是单例 + 内存 job store —— 跑在 N 个 worker 会重复触发 +
    # race 写 DB。仅 WORKER_RANK=0 才启(其他 worker 跳过)。
    _should_run_scheduler = _should_run_scheduler_for_worker()
    if _should_run_scheduler:
        from lumen_services.workflow_scheduler import get_scheduler_service
        from lumen_core.database import SessionLocal
        scheduler_service = get_scheduler_service()
        scheduler_service.start()
        # Repopulate in-memory job store from the database. The in-memory
        # APScheduler store is wiped on every process restart, so without
        # this hook every active schedule would silently stop firing.
        db = SessionLocal()
        try:
            scheduler_service.reload_schedules(db)
        finally:
            db.close()
        # M27: register retention cron jobs on the SAME scheduler
        # (singleton from workflow_scheduler.get_scheduler()). Runs daily
        # at 02:17 (hard) and 02:27 (soft) per the M27 spec.
        from lumen_services.retention_scheduler import register_retention_jobs
        register_retention_jobs()
        import logging as _lifespan_logger
        _lifespan_logger.getLogger(__name__).info(
            "scheduler started (WORKER_RANK=%s RUN_SCHEDULER=%s)",
            os.getenv("WORKER_RANK", "0"), os.getenv("RUN_SCHEDULER", "auto"),
        )
    else:
        import logging as _lifespan_logger
        _lifespan_logger.getLogger(__name__).info(
            "scheduler SKIPPED (WORKER_RANK=%s RUN_SCHEDULER=%s)",
            os.getenv("WORKER_RANK", "0"), os.getenv("RUN_SCHEDULER", "auto"),
        )

    # Phase 1 Group B 2.4.5 (2026-09-04):启 Celery 队列深度后台监控。
    # 每 30s 一次 ``redis llen <queue>`` 更新 ``lumen_celery_queue_depth`` Gauge,
    # Grafana Overview 看板 + B2c Alertmanager 告警共用。
    # 注:**仅** WORKER_RANK=0 跑 —— gunicorn 多 worker 下每个 worker 都启会
    # 浪费 N 倍 Redis 连接;同时只有 1 个 worker 写 gauge 也避免冲突。
    celery_queue_monitor_task: "asyncio.Task | None" = None
    celery_queue_monitor_shutdown: "asyncio.Event | None" = None
    if _should_run_scheduler:  # 同 scheduler 守门规则
        try:
            from lumen_core.celery_queue_monitor import celery_queue_monitor_loop
            redis_url = (
                f"redis://{os.getenv('REDIS_HOST', 'localhost')}"
                f":{os.getenv('REDIS_PORT', '26380')}"
                f"/{os.getenv('REDIS_DB', '0')}"
            )
            celery_queue_monitor_shutdown = asyncio.Event()
            celery_queue_monitor_task = asyncio.create_task(
                celery_queue_monitor_loop(redis_url, celery_queue_monitor_shutdown),
                name="lumen.celery_queue_monitor",
            )
            import logging as _lifespan_logger
            _lifespan_logger.getLogger(__name__).info(
                "celery_queue_monitor started (redis=%s)", redis_url,
            )
        except Exception as e:  # noqa: BLE001
            import logging as _lifespan_logger
            _lifespan_logger.getLogger(__name__).warning(
                "celery_queue_monitor start failed (%s); metrics will stay at default 0", e,
            )

    # Phase 1 Group B B2b 4.6 (2026-09-04):启 SLO 错误预算后台计算器。
    # 每 30s 读本地 prometheus_client REGISTRY + slo_definitions.yaml,
    # 算 6 个 SLO 的 budget remaining + burn rate → 写 lumen_slo_* Gauge。
    # Grafana SLO 看板 status bar 直接读这两个 Gauge。
    # 注:同样仅 WORKER_RANK=0 跑 —— 避免多 worker 重复算同一个 SLO 写 Gauge 冲突。
    slo_budget_calculator_task: "asyncio.Task | None" = None
    slo_budget_calculator_shutdown: "asyncio.Event | None" = None
    if _should_run_scheduler:
        try:
            from lumen_core.slo_budget_calculator import slo_budget_calculator_loop
            slo_budget_calculator_shutdown = asyncio.Event()
            slo_budget_calculator_task = asyncio.create_task(
                slo_budget_calculator_loop(slo_budget_calculator_shutdown),
                name="lumen.slo_budget_calculator",
            )
            import logging as _lifespan_logger
            _lifespan_logger.getLogger(__name__).info(
                "slo_budget_calculator started",
            )
        except Exception as e:  # noqa: BLE001
            import logging as _lifespan_logger
            _lifespan_logger.getLogger(__name__).warning(
                "slo_budget_calculator start failed (%s); SLO gauges will stay at default", e,
            )

    # Phase 0 Unit 2 (2026-09-02):标记 startup 跑完。
    # 必须在所有 ensure_* / scheduler 启动之后才 flip,否则 readiness
    # probe 提前 200 但 DB 还没就绪 → K8s 派流量来挂首请求。
    global _startup_complete
    _startup_complete = True

    try:
        yield
    finally:
        # shutdown: 与原 @app.on_event("shutdown") 行为一致 —— 抽到
        # _shutdown_cleanup helper,单测可直调(整 lifespan 太重)。
        await _shutdown_cleanup(
            started_scheduler=_should_run_scheduler,
            celery_queue_monitor_task=celery_queue_monitor_task,
            celery_queue_monitor_shutdown=celery_queue_monitor_shutdown,
            slo_budget_calculator_task=slo_budget_calculator_task,
            slo_budget_calculator_shutdown=slo_budget_calculator_shutdown,
        )


# 注入 lifespan —— 必须在 app 创建后、所有中间件注册前设置(虽然技术上中间件
# 注册在 lifespan 后面也无副作用,但约定 lifespan 第一件事就注册)。FastAPI
# 0.93+ 推荐用 lifespan 参数或 router.lifespan_context 注入上下文管理器。
app.router.lifespan_context = _lifespan


# Include routers
app.include_router(v1_router, prefix="/api/v1")

# Serve the built widget bundle at /static/widget/lumen-chat.js.
# The widget's esbuild output is committed to widget/dist (gitignored
# the dist tree), and copied into backend/static/widget/ as part of
# the build step (see Task 34). If the directory is missing (e.g.
# before the first build), mount a no-op static handler.
_widget_dir = os.path.join(os.path.dirname(__file__), "..", "..", "widget", "dist")
if os.path.isdir(_widget_dir):
    app.mount("/static/widget", StaticFiles(directory=_widget_dir), name="widget")
else:
    @app.get("/static/widget/lumen-chat.js")
    def _widget_missing():
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=503,
            content={"code": 503, "message": "widget dist not built; run `cd widget && npm run build`"},
        )


@app.get("/")
async def root():
    return {"message": "Lumen AI Platform API", "version": "0.1.0"}


@app.get("/health")
async def health():
    return {"status": "healthy"}


# Phase 0 Unit 2 (2026-09-02):K8s 三态 health probe。
# 跟原 /health(裸 200,前端无引用但兼容旧部署)并存,逐步切到三态模型。
#
# - /live   → 进程活着,只要 uvicorn 在 serve 就 200。K8s livenessProbe
#             用,挂了才需要重启;**不**查依赖,免得 DB 抖动误杀 pod。
# - /ready  → 依赖全可用(MySQL + Redis + Storage + Ollama,ES 走开关)。
#             任一不通返 503。K8s readinessProbe 用,从 service 摘流量。
#             Phase 1 1.4 ship:5 probe 用 asyncio.gather 并行,串行 ~10s
#             降到 max(timeout)≈2s;ES 走 `ES_ENABLED` 开关 — 默认关(项目
#             当前主要用 FAISS,关时 probe 返 skipped=True 不阻塞)。
# - /startup→ uvicorn 进程在跑但 startup_event(40+ ensure_* 迁移 +
#             scheduler reload)还没跑完时返 503;跑完后返 200。
#             K8s startupProbe 用,迁移没完不接 readinessProbe。
#
# 设计参考:roadmap §2 1.4 / Spring Boot Actuator 三态模型。
# Phase 1 计划已 ship,Phase 2 接 K8s 集群(sidecar 探活 + 自动摘流量)。
#
# 注意:不依赖 auth,部署 ingress 上做白名单限制(K8s pod 内网可达即可)。


@app.get("/live", include_in_schema=False)
async def live():
    """Liveness probe: process is alive. Always 200 unless dying."""
    return {"status": "alive"}


# Phase 0 Unit 5 4.3 (2026-09-02):Prometheus scrape 端点。
# Prometheus server 定时 GET /metrics 拉取文本格式指标。
# Content-Type 用 prometheus_client.CONTENT_TYPE_LATEST(= text/plain;
# version=0.0.4; charset=utf-8),不要改 —— Prometheus 解析靠这个。
# include_in_schema=False 不让 /docs 里出现(运维端点,前端不调)。
@app.get("/metrics", include_in_schema=False)
async def metrics():
    """Prometheus scrape endpoint. Render all metrics as text format."""
    from fastapi.responses import Response
    from lumen_core.metrics import render_metrics

    body, content_type = render_metrics()
    return Response(content=body, media_type=content_type)


@app.get("/startup", include_in_schema=False)
async def startup():
    """Startup probe: in-progress while migrations run, 200 when complete."""
    if _startup_complete:
        return {"status": "ready"}
    # 503 让 K8s 知道"还在启动",不要急着 readinessProbe
    from fastapi.responses import JSONResponse
    return JSONResponse(
        status_code=503,
        content={"status": "starting", "migrations_complete": False},
    )


@app.get("/ready", include_in_schema=False)
async def ready():
    """Readiness probe: dependencies available. 200 if all OK, 503 otherwise.

    Phase 1 Group A 1.4 (2026-09-04):扩展到 5 个 probe,asyncio.gather 并行:
      - MySQL(SELECT 1,SQLAlchemy sync 走 to_thread)
      - Redis(PING,redis-py sync 走 to_thread)
      - Storage(走 storage backend 自己的 health_check,Local 检查 rwx、
        S3/MinIO 走 head_bucket,2s timeout)
      - Ollama(GET /api/tags,async httpx)
      - Elasticsearch(cluster.health,尊重 ES_ENABLED 开关 — 关时返
        skipped=True 不阻塞,避免 FAISS-only 部署被 ES 拖死)

    任一 probe 返回 {"ok": False} → 整体 degraded → 503。K8s readinessProbe
    据此摘流量。各 probe 内部 try/except,永远不会向上抛异常。
    """
    from fastapi.responses import JSONResponse

    # 未启动完直接 503(让 startupProbe 先决,不要 readinessProbe 提前 200)
    if not _startup_complete:
        return JSONResponse(
            status_code=503,
            content={"status": "starting", "checks": {}},
        )

    # 并行跑 5 个 probe。return_exceptions=True 防御性兜底:即使 probe
    # helper 自己有 bug 抛异常,readiness 也不会让其他 probe 的结果丢掉。
    # 正常路径下各 probe 已 swallow exception,这里其实不会拿到 exception。
    mysql_r, redis_r, storage_r, ollama_r, es_r = await asyncio.gather(
        _probe_mysql(),
        _probe_redis(),
        _probe_storage(),
        _probe_ollama(),
        _probe_elasticsearch(),
        return_exceptions=True,
    )

    # 极端兜底:helper bug 真的抛了 → 转成 ok:False 让 readiness 503,
    # 否则 debug 时看不到任何线索。
    def _coerce(r):
        if isinstance(r, BaseException):
            return {"ok": False, "error": f"{type(r).__name__}: {r}"[:120]}
        return r

    checks = {
        "mysql": _coerce(mysql_r),
        "redis": _coerce(redis_r),
        "storage": _coerce(storage_r),
        "ollama": _coerce(ollama_r),
        "elasticsearch": _coerce(es_r),
    }
    overall_ok = all(c["ok"] for c in checks.values())
    payload = {
        "status": "ready" if overall_ok else "degraded",
        "checks": checks,
    }
    return JSONResponse(
        status_code=200 if overall_ok else 503,
        content=payload,
    )


# ===== Probe helpers (Phase 1 1.4 扩展) =====
#
# 每个 helper 必须:
#   1. swallow 全部 exception,只返 dict(never raises)
#   2. 带 timeout 避免 readiness 卡死
#   3. 2-3s 内返回(否则 readinessProbe 频繁超时)
#
# 同步 client(MySQL/Redis/Storage/ES 的 elasticsearch-py 客户端都是
# blocking)用 asyncio.to_thread 切到默认 ThreadPoolExecutor,不阻塞
# event loop。async 路径(Ollama httpx)直接 await。
#
# 命名风格:probe = 资源名,内部 try/except 包一切,失败也返 ok:False + error。

_PROBE_TIMEOUT_S = 2.5  # 单 probe 超时阈值,readiness 总耗时上限


async def _probe_mysql() -> dict:
    """MySQL probe:SELECT 1,SQLAlchemy engine。

    SELECT 1 是工业标准探活,不动业务数据,InnoDB 共享锁级别最低,不影响
    正常 query。
    """
    def _sync() -> None:
        from sqlalchemy import text
        from lumen_core.database import engine
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    try:
        await asyncio.wait_for(asyncio.to_thread(_sync), timeout=_PROBE_TIMEOUT_S)
        return {"ok": True}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)[:120]}


async def _probe_redis() -> dict:
    """Redis probe:PING,新建临时 client(不抢 rate_limit 的 connection)。

    短超时防止 probe 自己卡 readinessProbe(原 K8s 默认 1s 探活,K8s 1.4+ 可调,
    但 readiness 总耗时我们控制住 < 3s)。
    """
    def _sync() -> None:
        import redis as redis_lib  # local: keep top-level import lean
        from lumen_core.config import settings
        probe_client = redis_lib.Redis(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            db=settings.REDIS_DB,
            socket_connect_timeout=1,
            socket_timeout=1,
            decode_responses=True,
        )
        try:
            probe_client.ping()
        finally:
            probe_client.close()
    try:
        await asyncio.wait_for(asyncio.to_thread(_sync), timeout=_PROBE_TIMEOUT_S)
        return {"ok": True}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)[:120]}


async def _probe_storage() -> dict:
    """Storage probe:走 backend 自己的 health_check()。

    Local 模式检查 ./data 可读可写,S3/MinIO 模式 head_bucket。backend
    已经统一返 ``{backend, ok, detail, latency_ms}`` 结构 — 我们把 ok 透传,
    整 dict 并入 result,方便运维看到 backend 名 + 延迟。
    """
    def _sync() -> dict:
        from lumen_services.storage import get_storage_backend
        return get_storage_backend().health_check()
    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(_sync), timeout=_PROBE_TIMEOUT_S
        )
        return {
            "ok": bool(result.get("ok")),
            "backend": result.get("backend"),
            "latency_ms": result.get("latency_ms"),
            "detail": result.get("detail") if not result.get("ok") else None,
        }
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)[:120]}


async def _probe_ollama() -> dict:
    """Ollama probe:GET /api/tags,Ollama 自身标准探活端点。

    /api/tags 列出本地模型,不需要 auth,Ollama 进程死了就立刻 connection
    refused。**默认端口 11434**(项目配置 OLLAMA_API_BASE,见 config.py)。
    """
    try:
        import httpx  # local: 仅 readiness 路径需要,顶层 import 浪费 startup
        from lumen_core.config import settings
        base_url = settings.OLLAMA_API_BASE.rstrip("/")
        async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT_S) as client:
            resp = await client.get(f"{base_url}/api/tags")
            # 2xx 视为 ok;5xx / 4xx / connection error → 失败
            resp.raise_for_status()
        return {"ok": True}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)[:120]}


async def _probe_elasticsearch() -> dict:
    """ES probe:cluster.health,尊重 ``ES_ENABLED`` 开关。

    ``ES_ENABLED=False`` 时项目用 FAISS,运维特意关 ES,readiness 不能因此
    阻塞 — 返 ``skipped=True`` 且 ``ok=True``。开了就真探活,要求 status
    in (green, yellow);red 集群返 degraded。
    """
    from lumen_core.config import settings
    if not getattr(settings, "ES_ENABLED", False):
        return {"ok": True, "skipped": True, "reason": "ES_ENABLED=false"}

    def _sync() -> dict:
        from elasticsearch import Elasticsearch
        host = settings.ES_HOST
        port = settings.ES_PORT
        client = Elasticsearch(
            hosts=[{"host": host, "port": port, "scheme": "http"}],
            request_timeout=2,
        )
        return dict(client.cluster.health())  # {status, ...}
    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(_sync), timeout=_PROBE_TIMEOUT_S
        )
        status = result.get("status", "unknown")
        return {
            "ok": status in ("green", "yellow"),
            "status": status,
        }
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)[:120]}
