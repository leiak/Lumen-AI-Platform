"""Initialize a fresh dev database from business-code defaults.

Idempotent: safe to re-run on a partially-seeded DB. Every step checks
for an existing row (by name / code / unique field) before inserting.

Recovers (in order):
  1. All tables (create_tables + 18 ensure_* idempotent migrations)
  2. Demo external app (seed_dev_external_app)
  3. Default tenant (id=1, code="default", name="Default Tenant")
  4. Admin user (INIT_ADMIN_USERNAME / INIT_ADMIN_PASSWORD env,
     defaults admin / admin123) — only inserted if no users exist yet
  5. MCP demo server + 6 tools (seed_mcp_demo equivalent)
  6. Two MiniMax model configs (M2.7-highspeed as default + M3)
     to restore the chat + OpenClaw gateway wiring we had before
     the docker-desktop-data reset wiped docker volumes.
  7. (reserved — see git history for prior step numbering)
  8. 8 workflow marketplace templates (M30 ship follow-up)
  9. 15 wx-publisher system templates (M32 ship follow-up)

CANNOT recover (no fixture exists in code, was user-created data):
  - Agents, KB collections, KB documents
  - Conversations, messages
  - Workflows, schedules, workflow_runs
  - Installed skills, marketplace installs
  - Uploaded files (those live under ./data/ on the host, NOT in MySQL;
    the host path survived the reset, so uploads are still on disk)
  - Ollama models (need `docker exec lumen-platform-ollama ollama pull <model>`)

Usage:
    cd backend && python -m scripts.init_dev_db
    # override admin creds:
    INIT_ADMIN_USERNAME=alice INIT_ADMIN_PASSWORD=secret \\
        python -m scripts.init_dev_db
"""
from __future__ import annotations

import logging
import os
import sys

# Make ``app`` importable when invoked as a module.
_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from sqlalchemy import select  # noqa: E402

from lumen_core.database import (  # noqa: E402
    SessionLocal,
    create_tables,
    ensure_agent_kb_retrieval_config,
    ensure_conversations_deleted_at,
    ensure_conversations_external_fks,
    ensure_conversations_team_id,
    ensure_conversations_user_id_nullable,
    ensure_document_chunks_embedding_status,
    ensure_documents_created_by,
    ensure_embedding_model_config_migrated,
    ensure_external_apps_tables,
    ensure_generated_images_table,
    ensure_global_memories_conversation_id,
    ensure_marketplace_type_column,
    ensure_model_configs_image_flag,
    ensure_model_configs_purpose_flags,
    ensure_workflow_model_refs_migrated,
    ensure_workflow_runs_trigger_source,
    ensure_workflow_v2_migrated,
    ensure_text2sql_data_sources_table,  # M33
    ensure_text2sql_queries_table,  # M33
    ensure_system_configs_table,  # M34: 平台 KV + skill_http_allowed_domains
)
from lumen_core.notification_migration import ensure_notifications_table  # noqa: E402
from lumen_core.security import get_password_hash  # noqa: E402
# Register every model so FK resolution + create_tables work.
# `app/models/__init__.py` is empty, so importing submodules by hand
# is what main.py effectively does on uvicorn boot. Without these
# imports, `create_tables()` won't know about WorkflowRun /
# DocumentChunk / etc. and the subsequent ensure_* ALTERs will fail
# with "Table ... doesn't exist". List taken from `ls backend/app/models`.
from lumen_models import (  # noqa: E401,F401
    tenant,                # noqa: F401
    user,                  # noqa: F401
    role,
    settings,
    agent,
    agent_team,
    chat,
    knowledge,             # Document, DocumentChunk, KBChunk, KnowledgeBase
    memory,                # GlobalMemory
    mcp,
    model_config,
    notification,
    skill,
    skill_marketplace,
    workflow,              # Workflow, WorkflowRun, Schedule
    workflow_template,
    image_generation,      # GeneratedImage
    nlp_training,
    vision_training,
    external_app,
    text2sql,              # M33: Text2SqlDataSource + Text2SqlQuery
    system_config,         # M34: SystemConfig (platform-wide KV)
    ppt_task,              # M35: PptTask (PPT generation tasks)
)
from lumen_models.model_config import ModelConfig  # noqa: E402
from lumen_models.tenant import Tenant             # noqa: E402
from lumen_models.user import User                 # noqa: E402
from lumen_scripts.seed_external_app import seed_dev_external_app  # noqa: E402
from lumen_services.auth_service import AuthService  # noqa: E402
# M32 (2026-06-17): Puppeteer skills are added to the marketplace by
# importing the production seed function. It is idempotent per-name
# (existing names are skipped), so calling it on a DB that already has
# the 6 baseline prompt skills only adds the 3 Puppeteer ones.
from lumen_api.v1.skill_market import seed_marketplace_data  # noqa: E402
# M30 ship follow-up (2026-06-18): the workflow template marketplace
# UI shipped in M30b but the dev DB had no template rows, so the page
# opened empty. This seed inserts 8 curated starter templates (simple
# LLM / RAG / HTTP / condition / code / template / multi-step /
# parameter-extraction). Idempotent by name — re-running on a seeded
# DB only adds rows that don't already exist.
from scripts.seed_workflow_templates import seed_workflow_templates  # noqa: E402
# M32 ship follow-up (2026-06-18): the wx-publisher templates gallery
# shipped with 5 category tabs (极简/科技/杂志/文艺/商务) but the dev
# DB had zero ``wx_templates`` rows. This seed inserts 15 system
# templates (5 categories × 3 each). Idempotent by (tenant_id, name).
from scripts.seed_wx_templates import seed_wx_templates  # noqa: E402
# M32.1 follow-up: render Pillow thumbnails for the 15 system templates
# so the templates gallery is not "all empty PictureOutlined placeholders"
# on a fresh DB. Idempotent (skips rows that already have a thumbnail).
from scripts.seed_wx_template_thumbnails import seed_wx_template_thumbnails  # noqa: E402,E501

logger = logging.getLogger("init_dev_db")
logging.basicConfig(level=logging.INFO, format="%(message)s")


# ---------------------------------------------------------------------------
# 1. Schema: create_tables + every ensure_* in the same order main.py uses
# ---------------------------------------------------------------------------


def ensure_schema() -> None:
    """Mirror main.py startup_event schema work, minus the scheduler."""
    create_tables()
    ensure_workflow_runs_trigger_source()
    ensure_document_chunks_embedding_status()
    ensure_workflow_model_refs_migrated()
    ensure_workflow_v2_migrated()
    ensure_notifications_table()
    ensure_documents_created_by()
    ensure_conversations_deleted_at()
    ensure_conversations_team_id()
    ensure_conversations_user_id_nullable()
    ensure_conversations_external_fks()
    ensure_external_apps_tables()
    ensure_model_configs_purpose_flags()
    ensure_embedding_model_config_migrated()
    ensure_global_memories_conversation_id()
    ensure_marketplace_type_column()
    ensure_agent_kb_retrieval_config()  # M21
    ensure_model_configs_image_flag()   # M22
    # (ensure_model_configs_openclaw_flag dropped — it lives on the
    # feat/openclaw-integration branch which we are not merging
    # into master per the M23 PoC design review.)
    ensure_generated_images_table()      # M22
    ensure_text2sql_data_sources_table()  # M33
    ensure_text2sql_queries_table()       # M33
    ensure_system_configs_table()         # M34
    print("[1/8] schema ensured (create_tables + 19 ensure_* migrations)")


# ---------------------------------------------------------------------------
# 2. Demo external app
# ---------------------------------------------------------------------------


def seed_external_app() -> None:
    seed_dev_external_app()
    print("[2/8] external app seeded (seed_dev_external_app)")


# ---------------------------------------------------------------------------
# 3. Default tenant
# ---------------------------------------------------------------------------


def ensure_default_tenant() -> int:
    """Mirror auth_service.create_default_tenant; return tenant.id."""
    db = SessionLocal()
    try:
        tenant = AuthService.create_default_tenant(db)
        print(f"[3/8] default tenant present (id={tenant.id}, code={tenant.code!r})")
        return tenant.id
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 4. Admin user (only if no users exist)
# ---------------------------------------------------------------------------


def ensure_admin_user(tenant_id: int) -> int | None:
    """Insert a bootstrap admin if the users table is empty.

    Credentials come from env so the script can be re-run safely
    (otherwise re-running with a different INIT_ADMIN_PASSWORD would
    silently leave a stale password for the first user).
    """
    username = os.getenv("INIT_ADMIN_USERNAME", "admin")
    password = os.getenv("INIT_ADMIN_PASSWORD", "admin123")
    db = SessionLocal()
    try:
        if db.query(User).count() > 0:
            print(f"[4/8] users already present ({db.query(User).count()} rows); skipping admin seed")
            return None
        user = User(
            username=username,
            email=f"{username}@local",
            full_name="Local Admin",
            hashed_password=get_password_hash(password),
            tenant_id=tenant_id,
            is_active=True,
            is_superuser=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        print(f"[4/8] admin user seeded (id={user.id}, username={username!r})")
        return user.id
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 5. MCP demo server + 6 tools
# ---------------------------------------------------------------------------


def seed_mcp_demo(tenant_id: int) -> None:
    """Run the same inserts as backend/scripts/seed_mcp_demo.py:main()."""
    from lumen_models.mcp import MCPServer, MCPTool  # noqa: E402

    db = SessionLocal()
    try:
        server = (
            db.query(MCPServer)
            .filter_by(tenant_id=tenant_id, name="local-demo")
            .first()
        )
        if not server:
            server = MCPServer(
                tenant_id=tenant_id, name="local-demo",
                url="http://127.0.0.1:8765/mcp", status="disconnected",
            )
            db.add(server)
        else:
            server.url = "http://127.0.0.1:8765/mcp"
            server.status = "disconnected"
        db.commit()
        db.refresh(server)

        # Mirror TOOL_SCHEMAS from seed_mcp_demo.py (kept inline here so
        # the init script is self-contained — no module import dance).
        tool_schemas = {
            "list_agents": {
                "description": "列出当前租户所有 Agent(按更新时间倒序)",
                "input_schema": {"type": "object", "properties": {}, "required": []},
            },
            "list_knowledge_bases": {
                "description": "列出当前租户所有知识库",
                "input_schema": {"type": "object", "properties": {}, "required": []},
            },
            "search_knowledge_base": {
                "description": "在指定知识库里做向量检索",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "kb_id": {"type": "integer"},
                        "query": {"type": "string"},
                        "top_k": {"type": "integer", "default": 5},
                    },
                    "required": ["kb_id", "query"],
                },
            },
            "list_chat_sessions": {
                "description": "列出当前租户最近 N 条 chat 会话",
                "input_schema": {
                    "type": "object",
                    "properties": {"limit": {"type": "integer", "default": 20}},
                },
            },
            "list_workflows": {
                "description": "列出当前租户所有工作流定义",
                "input_schema": {"type": "object", "properties": {}, "required": []},
            },
            "run_workflow": {
                "description": "同步执行一个工作流(返回最终状态)",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "workflow_id": {"type": "integer"},
                        "input": {"type": "object"},
                    },
                    "required": ["workflow_id"],
                },
            },
            # M33: 7th tool — 智能问数(Text2SQL)
            "query_database": {
                "description": "M33 智能问数(Text2SQL) — 自然语言查询业务数据库",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "question": {"type": "string"},
                        "db_alias": {"type": "string", "default": "ai_platform"},
                        "tenant_id": {"type": "integer"},
                    },
                    "required": ["question"],
                },
            },
        }
        for name, schema in tool_schemas.items():
            tool = (
                db.query(MCPTool)
                .filter_by(tenant_id=tenant_id, name=name)
                .first()
            )
            if not tool:
                tool = MCPTool(
                    tenant_id=tenant_id, server_id=server.id, name=name,
                    description=schema["description"],
                    input_schema=schema["input_schema"],
                    is_enabled=1,
                )
                db.add(tool)
            else:
                tool.description = schema["description"]
                tool.input_schema = schema["input_schema"]
                tool.server_id = server.id
                tool.is_enabled = 1
        db.commit()
        print(f"[5/8] MCP demo seeded (1 server + {len(tool_schemas)} tools for tenant {tenant_id})")
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 6. Marketplace skills (6 baseline prompt + 3 Puppeteer prompt, M32)
# ---------------------------------------------------------------------------


def seed_marketplace_skills() -> None:
    """Run the production marketplace seed on the dev DB.

    Delegates to ``app.api.v1.skill_market.seed_marketplace_data``,
    which is idempotent per-name: existing rows are left untouched,
    only new names are inserted. Calling it on a fresh DB seeds all 9
    (6 baseline + 3 Puppeteer); calling it again is a no-op. Mirrors
    the seed_mcp_demo() pattern above.
    """
    from lumen_models.skill_marketplace import SkillMarketplace  # noqa: E402

    db = SessionLocal()
    try:
        before = db.query(SkillMarketplace).count()
        seed_marketplace_data(db)
        after = db.query(SkillMarketplace).count()
        added = after - before
        print(f"[6/8] marketplace skills seeded ({added} new added; total {after})")
    finally:
        db.close()


def ensure_default_text2sql_datasource(tenant_id: int) -> int:
    """M33: seed a default Text2SqlDataSource for the tenant.

    Returns the data source id. Idempotent: re-running the script
    returns the existing row instead of inserting a duplicate.
    The seeded source has no allowlists (every business table is
    fair game) and the standard ``max_rows=100`` / ``timeout_ms=5000``
    caps.
    """
    from lumen_models.text2sql import Text2SqlDataSource  # noqa: E402

    db = SessionLocal()
    try:
        existing = (
            db.query(Text2SqlDataSource)
            .filter(
                Text2SqlDataSource.tenant_id == tenant_id,
                Text2SqlDataSource.is_active == 1,
            )
            .order_by(Text2SqlDataSource.id.asc())
            .first()
        )
        if existing is not None:
            return existing.id
        ds = Text2SqlDataSource(
            tenant_id=tenant_id,
            name="默认 ai_platform",
            db_name="ai_platform",
            table_allowlist=None,
            field_allowlist=None,
            max_rows=100,
            timeout_ms=5000,
            description="自动 seed 的默认数据源",
            is_active=1,
        )
        db.add(ds)
        db.commit()
        db.refresh(ds)
        return ds.id
    finally:
        db.close()


def ensure_text2sql_skill_marketplace(tenant_id: int) -> None:
    """M33: 1 条 text2sql SkillMarketplace + 自动给 tenant 安装 InstalledSkill。

    The chat path auto-resolves an active text2sql skill; the
    SkillRunner will discover it via ``get_active_skills(...)``.
    Idempotent per-name on the marketplace, and per-(tenant, skill)
    on the InstalledSkill.
    """
    from lumen_models.skill_marketplace import (  # noqa: E402
        InstalledSkill, SkillMarketplace,
    )

    db = SessionLocal()
    try:
        # 1. marketplace row
        existing_mkt = (
            db.query(SkillMarketplace)
            .filter(
                SkillMarketplace.category == "data",
                SkillMarketplace.name == "智能问数",
            )
            .first()
        )
        if existing_mkt is None:
            existing_mkt = SkillMarketplace(
                name="智能问数",
                category="data",
                type="text2sql",
                description=(
                    "自然语言转 SQL 智能问数。用户问业务问题,系统自动"
                    "生成 SELECT、试执行并返回结果 + 中文解释。"
                ),
                type_config={
                    "data_source_name": "默认 ai_platform",
                },
            )
            db.add(existing_mkt)
            db.commit()
            db.refresh(existing_mkt)
        # 2. installed skill
        installed = (
            db.query(InstalledSkill)
            .filter(
                InstalledSkill.tenant_id == tenant_id,
                InstalledSkill.marketplace_skill_id == existing_mkt.id,
            )
            .first()
        )
        if installed is None:
            installed = InstalledSkill(
                tenant_id=tenant_id,
                marketplace_skill_id=existing_mkt.id,
                status="active",
            )
            db.add(installed)
            db.commit()
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 7. Two MiniMax model configs (the chat LLM + the OpenClaw gateway model)
# ---------------------------------------------------------------------------


# These values were observed in the DB before docker-desktop-data was
# reset. The key is read from .env at runtime so the script does not
# commit a long-lived secret. ``base_url`` has a leading space in the
# original rows (cosmetic, but the strip matches the schema).
_MINIMAX_BASE_URL = "https://api.minimax.chat/v1"
_MINIMAX_KEY_FROM_ENV = "MINIMAX_API_KEY"  # falls back to a literal below
_MINIMAX_FALLBACK_KEY = (
    "sk-cp-64adXzrp1NxzrFxWlEIZ3Ia5Xpo1sgo6GX4nYg-Itk7du9F527Nkk4PMYpD_G0Cd7lOfVa6xooUzGoUqrNs0FZUuKONcxZ1XkTBIwBr1Gn5Gq33Qmrb4ykI"
)


def _get_minimax_key() -> str:
    return os.getenv(_MINIMAX_KEY_FROM_ENV, _MINIMAX_FALLBACK_KEY)


def upsert_default_model_configs() -> None:
    """Insert/update three rows mirroring the pre-reset DB state.

    - Row 1: MiniMax-M2.7-highspeed, is_default=1, is_chat=1,
      is_openclaw=1 (the OpenClaw gateway talks to this one).
    - Row 2: MiniMax-M3, is_default=0, is_chat=1, is_openclaw=0
      (kept as a chat fallback / multi-model pick).
    - Row 3: qwen2.5:0.5b, is_default=0, is_chat=1, is_openclaw=0.
      Points at the local Ollama (no api_key). Many dev tests
      (e.g. ``tests/integration/test_memory_api.py::test_post_agent_chat
      _persists_conversation_id_to_global``) patch this row's base_url
      in place; the seed ensures the row exists at all so the test
      has something to query.
    """
    db = SessionLocal()
    try:
        rows = [
            {
                "name": "MiniMax-M2.7-highspeed",
                "model_type": "openai",
                "model_name": "MiniMax-M2.7-highspeed",
                "base_url": _MINIMAX_BASE_URL,
                "api_key": _get_minimax_key(),
                "is_default": True,
                "is_chat": True,
                "is_openclaw": True,
            },
            {
                "name": "MiniMax-M3",
                "model_type": "minimax",
                "model_name": "MiniMax-M3",
                "base_url": _MINIMAX_BASE_URL,
                "api_key": _get_minimax_key(),
                "is_default": False,
                "is_chat": True,
                "is_openclaw": False,
            },
            {
                "name": "qwen2.5:0.5b",
                "model_type": "ollama",
                "model_name": "qwen2.5:0.5b",
                "base_url": "http://localhost:11434",
                "api_key": "ollama",  # Ollama ignores; required by schema
                "is_default": False,
                "is_chat": True,
                "is_openclaw": False,
            },
        ]
        for cfg in rows:
            existing = db.scalar(
                select(ModelConfig).where(ModelConfig.name == cfg["name"])
            )
            if existing is None:
                row = ModelConfig(
                    name=cfg["name"],
                    model_type=cfg["model_type"],
                    model_name=cfg["model_name"],
                    base_url=cfg["base_url"],
                    api_key=cfg["api_key"],
                    temperature=0.7,
                    max_tokens=4096,
                    timeout=120,
                    is_default=cfg["is_default"],
                    is_active=True,
                    is_chat=cfg["is_chat"],
                    is_embedding=False,
                    is_image_generation=False,
                    # is_openclaw field lives on the
                    # feat/openclaw-integration branch (M23 PoC) and
                    # is not on master; skip it here.
                    # tenant_id=1 (not NULL) so that test fixtures which
                    # filter by ``ModelConfig.tenant_id == 1`` pick up
                    # the seeded row.
                    tenant_id=1,
                )
                db.add(row)
            else:
                existing.base_url = cfg["base_url"]
                existing.api_key = cfg["api_key"]
                existing.is_default = cfg["is_default"]
                existing.is_chat = cfg["is_chat"]
                existing.tenant_id = 1
                existing.is_active = True
        db.commit()
        # Also clear is_default on any other row so our M2.7-highspeed is
        # the unambiguous default. (Idempotent: safe to re-run.)
        db.query(ModelConfig).filter(
            ModelConfig.name != "MiniMax-M2.7-highspeed",
            ModelConfig.is_default == True,  # noqa: E712
        ).update({ModelConfig.is_default: False})
        db.commit()
        print(
            "[7/8] default model configs upserted "
            "(MiniMax-M2.7-highspeed=default+openclaw, "
            "MiniMax-M3=fallback, qwen2.5:0.5b=ollama-dev)"
        )
    finally:
        db.close()


# Backwards-compat alias for older commit messages / scripts.
upsert_minimax_model_configs = upsert_default_model_configs


# ---------------------------------------------------------------------------
# 8. Workflow template marketplace seed (M30 ship follow-up, 2026-06-18)
# ---------------------------------------------------------------------------


def seed_workflow_templates_step() -> None:
    """Insert 8 curated starter templates into the workflow_templates
    table. Idempotent: re-running skips templates whose name is already
    present. No-op on the very first call to ensure_schema() if no
    admin user exists yet — the seed is keyed off the first superuser
    (the bootstrap admin from step 4), so we run it AFTER
    ``ensure_admin_user``.
    """
    inserted, skipped = seed_workflow_templates()
    print(f"[8/9] workflow templates seeded ({inserted} new added; {skipped} skipped)")


# ---------------------------------------------------------------------------
# 9. Wx-publisher system templates seed (M32 ship follow-up, 2026-06-18)
# ---------------------------------------------------------------------------


def seed_wx_templates_step() -> None:
    """Insert 15 system templates (5 categories × 3 each) into
    ``wx_templates``. Idempotent by ``(tenant_id, name)``. Depends on
    step 4 having produced the bootstrap admin (the seed uses the
    first superuser as the author).
    """
    inserted, skipped = seed_wx_templates()
    print(f"[9/10] wx templates seeded ({inserted} new added; {skipped} skipped)")


def seed_wx_template_thumbnails_step() -> None:
    """Render default Pillow thumbnails for the 15 system templates so the
    gallery is not "all empty placeholders" on a fresh DB. Idempotent —
    rows with a non-null ``thumbnail`` are skipped unless ``--force`` is
    passed to init_dev_db.py (we don't expose that, so reruns are safe).
    """
    rendered, skipped, failed = seed_wx_template_thumbnails()
    print(
        f"[10/10] wx template thumbnails generated "
        f"({rendered} rendered, {skipped} skipped, {failed} failed)"
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> int:
    print("=== init_dev_db ===")
    ensure_schema()
    # Default tenant must exist before external_app / mcp demo seeds —
    # both look up the first tenant in the DB to attach their rows to.
    tenant_id = ensure_default_tenant()
    seed_external_app()
    ensure_admin_user(tenant_id)
    seed_mcp_demo(tenant_id)
    seed_marketplace_skills()
    upsert_minimax_model_configs()
    # M30 ship follow-up: seed 8 workflow templates so the marketplace
    # page (templates/page.tsx) is not empty on a fresh DB. Depends on
    # step 4 having produced at least one user (the seed uses the first
    # superuser as the author).
    seed_workflow_templates_step()
    # M32 ship follow-up: seed 15 wx-publisher system templates so the
    # templates gallery (templates/page.tsx) is not empty on a fresh
    # DB. Depends on step 4 having produced the bootstrap admin.
    seed_wx_templates_step()
    # M32.1 follow-up: render default Pillow thumbnails for the 15
    # system templates. Idempotent (re-runs are no-op). Depends on
    # seed_wx_templates_step having produced the rows.
    seed_wx_template_thumbnails_step()
    # M33: 智能问数 — seed default Text2SqlDataSource + skill marketplace
    # entry. Both are idempotent.
    ensure_default_text2sql_datasource(tenant_id)
    ensure_text2sql_skill_marketplace(tenant_id)
    print()
    print("Dev DB bootstrap done. Reminder: business data (agents / KB /")
    print("conversations / workflows / skills installs) cannot be recovered")
    print("from code — re-create them by hand or by re-running your dev")
    print("workflow. Ollama models also need `docker exec lumen-platform-ollama")
    print("ollama pull <name>` to be repopulated.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
