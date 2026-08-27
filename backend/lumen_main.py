import os

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from lumen_core.config import settings
from lumen_core.dynamic_cors import DynamicCORSMiddleware
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

app = FastAPI(
    title=settings.APP_NAME,
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

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

# Create tables on startup
@app.on_event("startup")
async def startup_event():
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
    # Seed a demo ExternalApp for local dev (idempotent). Runs after
    # ensure_external_apps_tables() so the parent table is guaranteed
    # to exist, and before scheduler reload so the DB is fresh.
    from lumen_scripts.seed_external_app import seed_dev_external_app
    seed_dev_external_app()
    # Start workflow scheduler
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


@app.on_event("shutdown")
async def shutdown_event():
    from lumen_services.workflow_scheduler import get_scheduler_service
    scheduler_service = get_scheduler_service()
    scheduler_service.stop()


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
