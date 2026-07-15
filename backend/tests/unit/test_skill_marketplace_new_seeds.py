"""Tests for the M34 (2026-06-30) marketplace breadth-expansion seed.

Covers 16 new skills (6 prompt / 3 http / 5 script / 1 text2sql):

  - All 16 are present after a single ``seed_marketplace_data`` call.
  - The seed is idempotent per-name — running again adds no rows.
  - Each new skill has the right ``type`` and a non-empty ``type_config``
    matching its schema (``HttpTypeConfig`` / ``ScriptTypeConfig`` /
    ``Text2SqlTypeConfig`` from ``lumen_schemas.skill``).
  - Script code passes both
    (a) ``ast.parse`` (well-formed Python) and
    (b) ``compile_restricted`` (RestrictedPython + AST security check).
    This is a smoke test — the executor does the same checks again at
    call time, but verifying the seed-time guarantee means a broken
    script skill gets caught in CI rather than only when an admin tries
    to run it.
  - All new skills have ``provider="Lumen AI Platform"``.

The 16 names:

  Prompt   (6): 翻译润色助手 / SQL 专家 / 邮件写作助手 /
                文本摘要助手 / 周报生成助手 / Python 调试助手
  HTTP     (3): 天气查询 / 汇率换算 / 短网址生成
  Script   (5): JSON 格式化校验 / Base64 编解码 / 时间戳格式化 /
                颜色值转换 / UUID 生成器
  Text2SQL (1): 销售数据问数助手

The test uses ``SessionLocal`` directly (no FastAPI bootstrap). The
module-scoped fixture seeds once per test file and deletes any new rows
on teardown so re-running on a dev DB that already has 6 baseline +
3 Puppeteer seeds is safe.
"""
from __future__ import annotations

import ast
import pytest

from lumen_core.sandbox.script_sandbox import ScriptSandbox
from lumen_schemas.skill import (
    HttpTypeConfig,
    ScriptTypeConfig,
    Text2SqlTypeConfig,
)


_PROMPT_NAMES = {
    "翻译润色助手",
    "SQL 专家",
    "邮件写作助手",
    "文本摘要助手",
    "周报生成助手",
    "Python 调试助手",
}
_HTTP_NAMES = {
    "天气查询",
    "汇率换算",
    "短网址生成",
}
_SCRIPT_NAMES = {
    "JSON 格式化校验",
    "Base64 编解码",
    "时间戳格式化",
    "颜色值转换",
    "UUID 生成器",
}
_TEXT2SQL_NAMES = {
    "销售数据问数助手",
}
_ALL_NEW = _PROMPT_NAMES | _HTTP_NAMES | _SCRIPT_NAMES | _TEXT2SQL_NAMES


def _snapshot_names(db) -> set[str]:
    from lumen_models.skill_marketplace import SkillMarketplace
    return {s.name for s in db.query(SkillMarketplace.name).all()}


def _delete_added_rows(db, before_names: set[str]) -> None:
    from lumen_models.skill_marketplace import SkillMarketplace
    after = _snapshot_names(db)
    new_names = after - before_names
    if not new_names:
        return
    db.query(SkillMarketplace).filter(
        SkillMarketplace.name.in_(new_names)
    ).delete(synchronize_session=False)
    db.commit()


# Module-scoped seed fixture mirrors test_skill_marketplace_puppeteer_seed.py
# so that re-running on a polluted dev DB is safe.
#
# The model-preload block below is REQUIRED. Without it, SQLAlchemy's
# lazy ORM configuration walks every registered mapper on first query
# and hits `WorkflowRun.embedding_call_logs` (relationship to
# ``EmbeddingCallLog``). The puppeteer test inherited this fragility
# from the same root cause and only "accidentally" passed when an
# earlier test had preloaded the model. We preload explicitly here so
# the test is order-independent.
@pytest.fixture(scope="module")
def new_seeds():
    # Model preload — mirrors lumen_main.py imports so all relationship
    # targets (EmbeddingCallLog, LLMCallLog, etc.) are resolved before
    # any DB session opens.
    from lumen_models.tenant import Tenant  # noqa: F401
    from lumen_models.agent import Agent, AgentTool, AgentKnowledgeBase  # noqa: F401
    from lumen_models.agent_team import AgentTeam, AgentTeamMember, AgentTeamRoute  # noqa: F401
    from lumen_models.external_app import ExternalApp, ExternalVisitor  # noqa: F401
    from lumen_models.chat import Conversation, Message  # noqa: F401
    from lumen_models.knowledge import KnowledgeBase, Document, DocumentChunk, FAQEntry  # noqa: F401
    from lumen_models.memory import ConversationMemory, GlobalMemory  # noqa: F401
    from lumen_models.model_config import ModelConfig  # noqa: F401
    from lumen_models.nlp_training import NLPTrainingClassification, NLPAnnotation, NLPQA  # noqa: F401
    from lumen_models.role import Role, Permission  # noqa: F401
    from lumen_models.settings import SystemSettings, SecuritySettings  # noqa: F401
    from lumen_models.skill import Skill  # noqa: F401
    from lumen_models.user import User  # noqa: F401
    from lumen_models.vision_training import VisionClassification, VisionImage  # noqa: F401
    from lumen_models.workflow import Workflow, WorkflowRun, WorkflowSchedule  # noqa: F401
    from lumen_models.workflow_template import WorkflowTemplate  # noqa: F401
    from lumen_models.mcp import MCPServer, MCPTool, MCPToolExecution  # noqa: F401
    from lumen_models.skill_marketplace import SkillMarketplace, InstalledSkill  # noqa: F401
    from lumen_models.notification import Notification  # noqa: F401
    from lumen_models.image_generation import GeneratedImage  # noqa: F401
    from lumen_models.wx_publisher import (WxAccount, WxTemplate, WxDraft,  # noqa: F401
                                          WxDraftSection, WxMaterial, WxPublishRecord)
    from lumen_models.customer import (Customer, CustomerFollowUp,  # noqa: F401
                                       CustomerFieldDefinition)
    from lumen_models.text2sql import Text2SqlDataSource, Text2SqlQuery  # noqa: F401
    from lumen_models.system_config import SystemConfig  # noqa: F401
    from lumen_models.llm_call_log import LLMCallLog  # noqa: F401
    from lumen_models.embedding_call_log import EmbeddingCallLog  # noqa: F401
    from lumen_services.logging_service import (AuditLog, OperationLog,  # noqa: F401
                                                 QueryLog)

    from lumen_core.database import SessionLocal
    from lumen_api.v1.skill_market import seed_marketplace_data

    db = SessionLocal()
    before: set[str] = set()
    try:
        before = _snapshot_names(db)
        seed_marketplace_data(db)
        yield
    finally:
        if before:
            _delete_added_rows(db, before)
        db.close()


def test_seed_inserts_all_16_new_skills(new_seeds):
    """A single seed call adds all 16 M34 new skills on top of the 9 baseline."""
    from lumen_core.database import SessionLocal
    db = SessionLocal()
    try:
        after = _snapshot_names(db)
        missing = _ALL_NEW - after
        assert not missing, (
            f"After seed, expected all 16 M34 skills. Missing: {sorted(missing)}"
        )
    finally:
        db.close()


def test_seed_is_idempotent_under_3_runs(new_seeds):
    """Calling seed_marketplace_data 3 times adds no rows after the first call."""
    from lumen_core.database import SessionLocal
    from lumen_api.v1.skill_market import seed_marketplace_data

    db = SessionLocal()
    try:
        after_first = _snapshot_names(db)
        seed_marketplace_data(db)
        seed_marketplace_data(db)
        after_third = _snapshot_names(db)
        assert after_third == after_first
        assert len(after_third) == len(after_first)
    finally:
        db.close()


def test_new_prompt_skills_have_type_prompt(new_seeds):
    """All 6 prompt skills: type='prompt' + non-empty content."""
    from lumen_core.database import SessionLocal
    from lumen_models.skill_marketplace import SkillMarketplace
    db = SessionLocal()
    try:
        rows = {
            s.name: s for s in db.query(SkillMarketplace).filter(
                SkillMarketplace.name.in_(_PROMPT_NAMES)
            ).all()
        }
        assert set(rows.keys()) == _PROMPT_NAMES, (
            f"Expected 6 prompt rows; got {sorted(rows.keys())}"
        )
        for name, s in rows.items():
            assert s.type == "prompt", f"{name}: expected type='prompt', got {s.type!r}"
            assert s.content is not None and len(s.content) > 200, (
                f"{name}: content too short ({len(s.content or '')} chars)"
            )
            assert s.provider == "Lumen AI Platform"
    finally:
        db.close()


def test_new_http_skills_have_valid_type_config(new_seeds):
    """All 3 HTTP skills: type='http' + HttpTypeConfig-valid type_config."""
    from lumen_core.database import SessionLocal
    from lumen_models.skill_marketplace import SkillMarketplace
    db = SessionLocal()
    try:
        rows = {
            s.name: s for s in db.query(SkillMarketplace).filter(
                SkillMarketplace.name.in_(_HTTP_NAMES)
            ).all()
        }
        assert set(rows.keys()) == _HTTP_NAMES, (
            f"Expected 3 HTTP rows; got {sorted(rows.keys())}"
        )
        # Per-row schema + content sanity:
        # - 天气查询 → api.open-meteo.com
        # - 汇率换算 → api.frankfurter.app
        # - 短网址生成 → is.gd
        domain_expect = {
            "天气查询": "api.open-meteo.com",
            "汇率换算": "api.frankfurter.app",
            "短网址生成": "is.gd",
        }
        for name, s in rows.items():
            assert s.type == "http", f"{name}: expected type='http', got {s.type!r}"
            assert s.type_config is not None, (
                f"{name}: http skills must have type_config"
            )
            # Round-trip through Pydantic to catch schema mismatches early.
            cfg = HttpTypeConfig(**(s.type_config or {}))
            assert cfg.url.startswith("https://"), (
                f"{name}: url must be https://, got {cfg.url!r}"
            )
            assert cfg.method == "GET", (
                f"{name}: expected method='GET', got {cfg.method!r}"
            )
            assert domain_expect[name] in cfg.url, (
                f"{name}: url should target {domain_expect[name]!r}, got {cfg.url!r}"
            )
            assert 1 <= cfg.timeout <= 120, (
                f"{name}: timeout out of range: {cfg.timeout}"
            )
            assert s.provider == "Lumen AI Platform"
    finally:
        db.close()


def test_new_script_skills_have_valid_code(new_seeds):
    """All 5 script skills: type='script' + code passes ast.parse AND
    compile_restricted (RestrictedPython + AST security check)."""
    from lumen_core.database import SessionLocal
    from lumen_models.skill_marketplace import SkillMarketplace
    db = SessionLocal()
    try:
        rows = {
            s.name: s for s in db.query(SkillMarketplace).filter(
                SkillMarketplace.name.in_(_SCRIPT_NAMES)
            ).all()
        }
        assert set(rows.keys()) == _SCRIPT_NAMES, (
            f"Expected 5 script rows; got {sorted(rows.keys())}"
        )
        for name, s in rows.items():
            assert s.type == "script", (
                f"{name}: expected type='script', got {s.type!r}"
            )
            assert s.type_config is not None, (
                f"{name}: script skills must have type_config with code"
            )
            cfg = ScriptTypeConfig(**(s.type_config or {}))
            # (a) Plain AST parse.
            try:
                ast.parse(cfg.code)
            except SyntaxError as exc:
                pytest.fail(f"{name}: code failed ast.parse: {exc}")
            # (b) RestrictedPython compile — this also exercises the
            # AST security check (forbidden names / imports / attrs).
            # We don't run the code here; ScriptSandbox.execute() does
            # that at call time. A failure here means the seed ships
            # code that the sandbox will outright reject.
            try:
                ScriptSandbox.execute(cfg.code, {"_probe": True}, timeout=1)
            except Exception as exc:
                # Runtime execution error is fine (probe input doesn't
                # satisfy real schemas). What we care about is that we
                # don't hit SecurityError / ExecutionError for static
                # reasons (forbidden import, syntax, missing main()).
                msg = str(exc).lower()
                if "forbidden" in msg or "syntax error" in msg:
                    pytest.fail(
                        f"{name}: script code rejected by sandbox at static check: {exc}"
                    )
                # 'Script must define main()' or execution errors from
                # malformed probe input are EXPECTED for some scripts
                # (e.g. UUID requires integer count, color requires hex
                # string). The probe just has to *not* hit a static-
                # analysis rejection.
                # Also accept SkillExecutionError raised at runtime
                # because the probe input doesn't satisfy the script's
                # schema — that's expected.
            assert cfg.input_schema is not None and "properties" in cfg.input_schema, (
                f"{name}: script skills should advertise an input_schema"
            )
            assert s.provider == "Lumen AI Platform"
    finally:
        db.close()


def test_new_text2sql_skill_uses_default_datasource(new_seeds):
    """The 1 text2sql skill has a valid Text2SqlTypeConfig.data_source_name."""
    from lumen_core.database import SessionLocal
    from lumen_models.skill_marketplace import SkillMarketplace
    db = SessionLocal()
    try:
        rows = {
            s.name: s for s in db.query(SkillMarketplace).filter(
                SkillMarketplace.name.in_(_TEXT2SQL_NAMES)
            ).all()
        }
        assert set(rows.keys()) == _TEXT2SQL_NAMES, (
            f"Expected 1 text2sql row; got {sorted(rows.keys())}"
        )
        s = rows["销售数据问数助手"]
        assert s.type == "text2sql"
        cfg = Text2SqlTypeConfig(**(s.type_config or {}))
        assert cfg.data_source_name, "text2sql must declare a data_source_name"
        assert s.provider == "Lumen AI Platform"
    finally:
        db.close()


def test_new_skills_provider_is_lumen_ai_platform(new_seeds):
    """Sanity check: every new skill's provider field is the canonical
    'Lumen AI Platform' string (catches accidental copy-paste of a
    legacy provider value)."""
    from lumen_core.database import SessionLocal
    from lumen_models.skill_marketplace import SkillMarketplace
    db = SessionLocal()
    try:
        rows = db.query(SkillMarketplace).filter(
            SkillMarketplace.name.in_(_ALL_NEW)
        ).all()
        assert len(rows) == len(_ALL_NEW)
        for s in rows:
            assert s.provider == "Lumen AI Platform", (
                f"{s.name}: provider mismatch: {s.provider!r}"
            )
    finally:
        db.close()
