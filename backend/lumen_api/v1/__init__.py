from fastapi import APIRouter

from . import auth, knowledge, agent, agent_team, workflow, workflow_template, mcp, users, chat, roles, skills, memory, models, notifications, settings, dashboard, document, skill_market, electron_ws, nlp, vision, logs, screen, workflow_nodes, admin_skills, export
from . import image_generation  # M22 /api/v1/image-generation/* (Task 11)
from . import external as external_public  # public /external/* widget routes (Task 7)
from . import external_apps  # admin /external-apps/* routes (placeholder, Task 16 fills in CRUD)

router = APIRouter()

router.include_router(auth.router)
router.include_router(knowledge.router)
router.include_router(agent.router)
router.include_router(agent_team.router)
router.include_router(workflow.router)
router.include_router(workflow_template.router)
router.include_router(mcp.router)
router.include_router(users.router)
router.include_router(chat.router)
router.include_router(roles.router)
router.include_router(skills.router)
router.include_router(memory.router)
router.include_router(models.router)
router.include_router(notifications.router)
router.include_router(settings.router)
router.include_router(dashboard.router)
router.include_router(document.router)
router.include_router(skill_market.router)
router.include_router(electron_ws.router)
router.include_router(nlp.router)
router.include_router(vision.router)
router.include_router(logs.router)
router.include_router(screen.router)
router.include_router(workflow_nodes.router)
router.include_router(admin_skills.router)  # /api/v1/admin/skills/* (M17)
router.include_router(image_generation.router)  # /api/v1/image-generation/* (M22 / T11)
router.include_router(external_public.router)  # /api/v1/external/* (widget)
router.include_router(external_apps.router)  # /api/v1/external-apps/* (admin placeholder, Task 16)
router.include_router(export.router)  # /api/v1/export/* (chat markdown → PDF/MD export)

# M32: 公众号助手 - 5 个 router (T13 + T22)
#   /api/v1/wx-publisher/accounts/*    (T6, 6 endpoint)
#   /api/v1/wx-publisher/templates/*   (T8, 6 endpoint)
#   /api/v1/wx-publisher/drafts/*      (T10, 9 endpoint + T17, 5 AI/render endpoint)
#   /api/v1/wx-publisher/materials/*   (T12, 4 endpoint)
#   /api/v1/wx-publisher/publish/*     (T22, 2 endpoint)
from .wx_publisher import accounts, templates, drafts, materials, publish
router.include_router(accounts.router)
router.include_router(templates.router)
router.include_router(drafts.router)
router.include_router(materials.router)
router.include_router(publish.router)

# M33: 客户管理(CRM) - 2 个 router
#   /api/v1/customers/*          (CP1 10 endpoint + CP2 跟进 + CP3 AI)
#   /api/v1/customer-fields/*    (CP1 字段定义 4 endpoint)
from . import customer
router.include_router(customer.router)
router.include_router(customer.fields_router)

# M33: 智能问数(Text2SQL) - 2 个 router
#   /api/v1/text2sql/*             (ask / history / schema, 5 endpoint)
#   /api/v1/text2sql/datasources/* (data source CRUD, 4 endpoint)
from . import text2sql, text2sql_datasources
router.include_router(text2sql.router)
router.include_router(text2sql_datasources.router)

# M35: PPT 生成
from . import ppt
router.include_router(ppt.router)  # /api/v1/ppt/*

# M35: 多模态创作基础 - TTS / Subtitle / Playbook
#   /api/v1/tts/*        (TTS jobs + voices + audio streaming)
#   /api/v1/subtitles/*  (SRT generation + download)
#   /api/v1/playbooks/*  (YAML-driven style tokens CRUD)
from . import tts, subtitles, playbooks
router.include_router(tts.router)
router.include_router(subtitles.router)
router.include_router(playbooks.router)

# M36: 视频合成(image + audio + subtitle → mp4)
#   /api/v1/videos/*  (compose / list / detail / download / cancel / delete)
from . import videos
router.include_router(videos.router)

# M36.2.1: 股票素材库(全局 builtin + per-tenant 上传,只读)
#   /api/v1/stock-assets/*  (list / detail / image proxy with Bearer auth)
from . import stock_assets
router.include_router(stock_assets.router)

# M36.2.2: 视频背景音乐库(全局 builtin + per-tenant 上传预留,只读)
#   /api/v1/stock-musics/*  (list / detail / audio file proxy with Bearer auth)
from . import stock_musics
router.include_router(stock_musics.router)

# M37.1: RAG 评测集管理
#   /api/v1/eval/datasets/*  (CRUD + items + bulk-import with partial_errors)
from . import eval_datasets
router.include_router(eval_datasets.router)

# M37.2: RAG 评测 run 管理
#   /api/v1/eval/runs/*  (run lifecycle + 详情 + cancel + compare)
from . import eval_runs
router.include_router(eval_runs.router)

# M38.1: storage backend abstraction
#   /api/v1/storage/health   (probe)
#   /api/v1/storage/local/*  (bearer-auth local proxy)
#   /api/v1/storage/migrate-to-s3  (admin-only cold migration)
from . import storage
router.include_router(storage.router)

# M38.2: workspace + document folder navigation layer
#   /api/v1/workspaces/*            (workspace CRUD + tree)
#   /api/v1/knowledge/{kb_id}/folders  (per-KB folder list + create)
#   /api/v1/folders/{id}/*          (folder single + patch + soft-delete + restore)
#   /api/v1/knowledge/documents/{id}/move  (document move endpoint)
from . import workspace, folders
router.include_router(workspace.router)
router.include_router(folders.router)

# M38.2.x v2: workspace member management (RBAC)
#   /api/v1/workspaces/{id}/members              (GET list / POST invite)
#   /api/v1/workspaces/{id}/members/{user_id}    (PUT update / DELETE remove)
#   /api/v1/workspaces/{id}/transfer-ownership   (POST transfer)
from . import workspace_members  # noqa: E402
router.include_router(workspace_members.router)

# M38.4: Multimodal embedding config CRUD
#   /api/v1/multimodal-configs/*  (list / get / create / update / delete / test)
from . import multimodal_configs  # noqa: E402
router.include_router(multimodal_configs.router)

# Phase 1 Group A 1.5 (2026-09-03): Celery failed tasks DBQ admin endpoints
#   /api/v1/admin/tasks/failed   (list with tenant_id / task_name / acknowledged filters)
#   /api/v1/admin/tasks/{id}/retry (re-dispatch via celery_app.send_task)
#   /api/v1/admin/tasks/{id}/ack  (mark acknowledged)
from . import admin_tasks  # noqa: E402
router.include_router(admin_tasks.router)
