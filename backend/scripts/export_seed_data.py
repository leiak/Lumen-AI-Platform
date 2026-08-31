"""Export a clean ``scripts/sql/data.sql`` snapshot of system default rows.

Idempotent / reproducible. Strategy:

1. Drop + recreate a throwaway schema ``ai_platform_seed_export`` (separate
   from the dev DB so we start from zero — the dev DB has accumulated
   test fixtures, user data, and stale service-account rows that we
   don't want in the "out of the box" snapshot).
2. ``mysql`` (via pymysql) loads ``scripts/sql/schema.sql`` to materialise
   all 70 tables.
3. Run, in order, the project's own seed scripts with ``DATABASE_URL``
   pointed at the throwaway schema and ``STORAGE_DIR`` pointed at a
   throwaway directory (so Pillow PNG / audio generation doesn't
   pollute the dev ``storage/`` tree). The seeds are exactly what
   ``backend/scripts/init_dev_db.py`` orchestrates, plus
   ``lumen_scripts/seed_stock_*`` which ``init_dev_db`` does NOT call
   (they are auto-run on app ``startup_event`` instead — see
   ``lumen_main.py``). ``seed_eval_dataset_default`` is intentionally
   NOT run here because it requires a KB with >= 5 documents to
   generate ``expected_doc_ids``; importers should run it after
   they have ingested documents into a KB.
4. Walk every table in ``information_schema.tables`` for the temp
   schema and emit ``INSERT INTO ... VALUES (...);`` statements,
   ordered with ``FOREIGN_KEY_CHECKS=0`` so any FK miss inside a
   missing sub-row (e.g. marketplace_skills joined to a deleted
   skill row) doesn't block the dump.
5. Post-process:
   - ``model_configs.api_key``  -> ``YOUR_<PROVIDER>_API_KEY_HERE``
     placeholder; top-of-file banner tells the importer to override.
   - ``wx_templates.thumbnail`` -> ``NULL``; importer must run
     ``python -m scripts.seed_wx_template_thumbnails`` to render
     Pillow thumbnails.
6. DROP the throwaway schema, remove the throwaway ``STORAGE_DIR``.

Why not just ``mysqldump`` the dev DB? Because the dev DB has
~550 fixture tenants, ~110 external_apps, 1441+ user rows, and
"global builtin" rows that are actually test service accounts
(e.g. ``svc_test_global_mc_74134b``). Going through the seed
scripts guarantees we ship only what a fresh dev environment
would have after one ``init_dev_db`` pass.

Usage:
    cd backend && python -m scripts.export_seed_data
    # or with custom output path:
    python -m scripts.export_seed_data --output ../scripts/sql/data.sql
"""
from __future__ import annotations

import argparse
import io
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import date, datetime, time
from pathlib import Path
from typing import Any, Iterable, List, Sequence

import pymysql  # type: ignore[import-untyped]

# ─── Path constants ──────────────────────────────────────────────────────

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
_REPO = _BACKEND.parent
_SCHEMA_SQL = _REPO / "scripts" / "sql" / "schema.sql"
_DEFAULT_OUTPUT = _REPO / "scripts" / "sql" / "data.sql"

# Default admin (matches init_dev_db.py / env override defaults).
_ADMIN_USERNAME = "admin"
_ADMIN_PASSWORD = "admin123"

# Throwaway targets.
_TEMP_SCHEMA = "ai_platform_seed_export"
_TEMP_STORAGE_DIR_NAME = "sql_export_storage"

# Tables whose rows we never want in data.sql (BLOBs regenerated
# on first boot, or transient runtime state).  ``wx_templates`` is
# fully exported but with the ``thumbnail`` column scrubbed (see
# ``_SCRUB_BLOB_COLUMNS``).
_DUMP_SKIP_TABLES: set[str] = {
    # empty in dev after init_dev_db + stock_assets/musics/eval_dataset seeds
    "alembic_version",
    "query_logs",       # logging table; runtime data
    "operation_logs",   # logging table
    "audit_logs",       # logging table
    "notifications",    # runtime data
}

# Per-table, per-column scrubbing (set to None on output).
_SCRUB_BLOB_COLUMNS: dict[str, set[str]] = {
    "wx_templates": {"thumbnail"},
}

# Tables whose rows we keep ONLY if they look like seeds.  Anything
# else (e.g. test residue) is dropped.
#
# ``model_configs`` is NOT in this set: ``init_dev_db.py`` intentionally
# creates chat/embedding/image model rows with ``tenant_id=1`` (a
# 2026-08-07 hack so test fixtures that filter strictly by
# ``ModelConfig.tenant_id == 1`` pick them up — see the comment at
# ``init_dev_db.py:566-569``).  Filtering by ``tenant_id IS NULL``
# would drop those rows and leave the system with no LLM.  The seed
# scripts only ever produce ~6 model rows total, so exporting all
# of them is safe.
_GLOBAL_TENANT_TABLES: set[str] = {
    "stock_assets",
    "stock_musics",
    "playbooks",
    "skill_marketplace",
}

# Provider placeholder map (case-insensitive substring match on
# ``base_url`` or ``model_type``).
_API_KEY_PLACEHOLDERS = (
    ("minimax", "YOUR_MINIMAX_API_KEY_HERE"),
    ("openai", "YOUR_OPENAI_API_KEY_HERE"),
    ("anthropic", "YOUR_ANTHROPIC_API_KEY_HERE"),
    ("dashscope", "YOUR_DASHSCOPE_API_KEY_HERE"),
    ("zhipu", "YOUR_ZHIPU_API_KEY_HERE"),
)
_OLLAMA_API_KEY = "ollama"  # schema NOT NULL; Ollama ignores the value

# Insert batch size — emit multi-row INSERT to keep file compact.
_BATCH = 200

logger = logging.getLogger("export_seed_data")
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


# ─── MySQL helpers ──────────────────────────────────────────────────────


def _parse_dsn(url: str) -> dict[str, Any]:
    """Parse a SQLAlchemy-style ``mysql+pymysql://user:pwd@host:port/db``."""
    m = re.match(
        r"^mysql\+pymysql://(?P<user>[^:]+):(?P<pwd>[^@]*)@(?P<host>[^:/]+):(?P<port>\d+)/?(?P<db>.*)$",
        url,
    )
    if not m:
        raise ValueError(f"Cannot parse DATABASE_URL: {url!r}")
    return m.groupdict()


def _connect(db: str | None = None) -> pymysql.connections.Connection:
    cfg = _parse_dsn(os.environ["DATABASE_URL"])
    return pymysql.connect(
        host=cfg["host"],
        port=int(cfg["port"]),
        user=cfg["user"],
        password=cfg["pwd"],
        database=db,
        charset="utf8mb4",
        autocommit=False,
        local_infile=False,
    )


def _split_sql_statements(sql: str) -> List[str]:
    """Split a schema.sql-style file into single statements.

    Strips ``--`` line comments (no ``/* */`` block comments in
    schema.sql).  Respects ``;`` only at end-of-line so embedded
    semicolons in strings (none in this file) would not break —
    but we keep it simple.
    """
    out: List[str] = []
    buf: List[str] = []
    for line in sql.splitlines():
        s = line.strip()
        if not s or s.startswith("--"):
            continue
        buf.append(line)
        if s.endswith(";"):
            stmt = "\n".join(buf).rstrip().rstrip(";").strip()
            if stmt:
                out.append(stmt)
            buf = []
    # Trailing partial (shouldn't happen with valid schema.sql).
    if buf:
        leftover = "\n".join(buf).strip()
        if leftover:
            out.append(leftover)
    return out


# ─── SQL value formatting ──────────────────────────────────────────────


def _sql_value(v: Any) -> str:
    """Format a Python value as a MySQL literal."""
    if v is None:
        return "NULL"
    # bool BEFORE int (bool is subclass of int in Python)
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, (int,)):
        return str(v)
    if isinstance(v, float):
        return repr(v)
    if isinstance(v, datetime):
        return f"'{v.strftime('%Y-%m-%d %H:%M:%S')}'"
    if isinstance(v, date):
        return f"'{v.isoformat()}'"
    if isinstance(v, time):
        return f"'{v.isoformat()}'"
    if isinstance(v, (bytes, bytearray, memoryview)):
        b = bytes(v)
        return f"X'{b.hex().upper()}'"
    if isinstance(v, (dict, list, tuple)):
        return _sql_value(json.dumps(v, ensure_ascii=False, default=str))
    s = str(v)
    # MySQL string escape: backslash, single-quote, NUL, newline, CR, CTRL+Z
    s = s.replace("\\", "\\\\").replace("'", "\\'")
    s = s.replace("\x00", "\\0").replace("\n", "\\n").replace("\r", "\\r")
    s = s.replace("\x1a", "\\Z")
    return f"'{s}'"


def _row_dict(cursor: Any, row: tuple) -> dict[str, Any]:
    return dict(zip([d[0] for d in cursor.description], row))


# ─── Dump walk ─────────────────────────────────────────────────────────


def _is_global_row(table: str, row: dict[str, Any]) -> bool:
    """Return True if a row should be exported based on tenant policy."""
    if table not in _GLOBAL_TENANT_TABLES:
        return True
    return row.get("tenant_id") is None


def _is_scrubbed(table: str, col: str) -> bool:
    return col in _SCRUB_BLOB_COLUMNS.get(table, set())


def _placeholder_api_key(row: dict[str, Any]) -> str:
    """Pick the right ``YOUR_*_API_KEY_HERE`` placeholder based on
    ``base_url``/``model_type``.  Ollama rows keep the literal
    ``ollama`` (schema NOT NULL, ignored by the Ollama server)."""
    base = (row.get("base_url") or "").lower()
    mtype = (row.get("model_type") or "").lower()
    for needle, placeholder in _API_KEY_PLACEHOLDERS:
        if needle in base or needle in mtype:
            return placeholder
    if "ollama" in base or mtype == "ollama":
        return _OLLAMA_API_KEY
    return "YOUR_API_KEY_HERE"


def _dump_table(cur: Any, table: str) -> Iterable[str]:
    """Yield INSERT statements for one table."""
    cur.execute(f"SHOW COLUMNS FROM `{table}`")
    cols = [r[0] for r in cur.fetchall()]
    if not cols:
        return
    select_cols = ", ".join(f"`{c}`" for c in cols)
    cur.execute(f"SELECT {select_cols} FROM `{table}`")
    rows = cur.fetchall()
    if not rows:
        logger.debug("  %-40s (0 rows)", table)
        return

    scrub_for_table = _SCRUB_BLOB_COLUMNS.get(table, set())

    kept_rows: list[dict[str, Any]] = []
    for r in rows:
        d = _row_dict(cur, r)
        if not _is_global_row(table, d):
            continue
        kept_rows.append(d)
    if not kept_rows:
        return

    # Emit
    col_list = ", ".join(f"`{c}`" for c in cols)
    logger.info("  %-40s %3d rows", table, len(kept_rows))
    batch: list[str] = []
    for d in kept_rows:
        vals: list[str] = []
        for c in cols:
            if _is_scrubbed(table, c):
                vals.append("NULL")
                continue
            if table == "model_configs" and c == "api_key":
                vals.append(_sql_value(_placeholder_api_key(d)))
                continue
            vals.append(_sql_value(d[c]))
        batch.append(f"({', '.join(vals)})")
        if len(batch) >= _BATCH:
            yield f"INSERT INTO `{table}` ({col_list}) VALUES\n  " + ",\n  ".join(batch) + ";\n"
            batch = []
    if batch:
        yield f"INSERT INTO `{table}` ({col_list}) VALUES\n  " + ",\n  ".join(batch) + ";\n"


# ─── Orchestration ──────────────────────────────────────────────────────


def _run_seed_scripts() -> None:
    """Run every seed script with the throwaway ``DATABASE_URL``."""
    env = os.environ.copy()
    env["DATABASE_URL"] = f"{_DSN_BASE}/{_TEMP_SCHEMA}"
    # Throwaway STORAGE_DIR so Pillow writes PNGs there, not into
    # the dev ``backend/storage`` tree.
    tmp_storage = _BACKEND / "data" / _TEMP_STORAGE_DIR_NAME
    tmp_storage.mkdir(parents=True, exist_ok=True)
    env["STORAGE_DIR"] = str(tmp_storage)
    env.setdefault("INIT_ADMIN_USERNAME", _ADMIN_USERNAME)
    env.setdefault("INIT_ADMIN_PASSWORD", _ADMIN_PASSWORD)
    env.setdefault("MINIMAX_API_KEY", "sk-placeholder")

    # Pre-register every model before running seeds that may declare
    # FKs to other tables.  M35 ``seed_m35_default_models`` only
    # imports ``lumen_models.model_config`` and ``lumen_models.playbook``;
    # without tenant/user already mapped, SQLAlchemy raises
    # ``NoReferencedTableError: Foreign key associated with column
    # 'playbooks.tenant_id' could not find table 'tenants'``.  This
    # import side-effect is a no-op on the schema (already loaded).
    _PRE_IMPORT_MODELS = (
        "lumen_models.tenant",
        "lumen_models.user",
        "lumen_models.role",
        "lumen_models.settings",
        "lumen_models.agent",
        "lumen_models.agent_team",
        "lumen_models.chat",
        "lumen_models.knowledge",
        "lumen_models.memory",
        "lumen_models.mcp",
        "lumen_models.model_config",
        "lumen_models.notification",
        "lumen_models.skill",
        "lumen_models.skill_marketplace",
        "lumen_models.workflow",
        "lumen_models.workflow_template",
        "lumen_models.image_generation",
        "lumen_models.nlp_training",
        "lumen_models.vision_training",
        "lumen_models.external_app",
        "lumen_models.text2sql",
        "lumen_models.system_config",
        "lumen_models.ppt_task",
        "lumen_models.playbook",
        "lumen_models.stock_asset",
        "lumen_models.stock_music",
        "lumen_models.llm_call_log",
        "lumen_models.embedding_call_log",
        "lumen_models.eval_dataset",
        "lumen_models.eval_run",
        "lumen_models.wx_publisher",
        "lumen_models.video",
        "lumen_models.tts",
        "lumen_models.subtitle",
        "lumen_models.customer",
    )
    import_stmt = "; ".join(f"import {m}" for m in _PRE_IMPORT_MODELS)
    bootstrap = (
        "import sys, os; "
        "sys.path.insert(0, os.path.join(os.getcwd())); "
        f"{import_stmt}; "
        # touch BaseModel so the mapper config evaluates
        "from lumen_models.base import BaseModel"
    )

    scripts: Sequence[tuple[str, str]] = [
        # (module path, label)
        ("scripts.init_dev_db", "init_dev_db (schema + tenant + admin + mcp + skills + models + templates + text2sql)"),
        ("lumen_scripts.seed_stock_assets", "seed_stock_assets (30 stock images)"),
        ("lumen_scripts.seed_stock_musics", "seed_stock_musics (5 BGM tracks)"),
        ("lumen_scripts.seed_m35_default_models", "seed_m35_default_models (TTS + playbooks)"),
        ("lumen_scripts.seed_m37_default_eval_config", "seed_m37_default_eval_config"),
        # NOT called: seed_eval_dataset_default — requires a KB with >=5
        # documents to populate expected_doc_ids; importer should run
        # it after ingesting documents.
    ]
    for mod, label in scripts:
        logger.info("Running %s ...", label)
        result = subprocess.run(
            [sys.executable, "-c", f"{bootstrap}\nimport {mod}; {mod}.main()"],
            cwd=str(_BACKEND),
            env=env,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"Seed script {mod!r} exited with {result.returncode}; "
                f"see output above for traceback."
            )


def _load_schema_sql(conn: pymysql.connections.Connection) -> None:
    logger.info("Loading %s ...", _SCHEMA_SQL.relative_to(_REPO))
    sql = _SCHEMA_SQL.read_text(encoding="utf-8")
    stmts = _split_sql_statements(sql)
    logger.info("  %d CREATE TABLE statements", len(stmts))
    with conn.cursor() as cur:
        for stmt in stmts:
            cur.execute(stmt)
    conn.commit()


def _reset_auto_increments(conn: pymysql.connections.Connection) -> None:
    """Force every table's AUTO_INCREMENT to 1.

    ``schema.sql`` was produced by ``SHOW CREATE TABLE`` on the dev DB,
    so it carries stale ``AUTO_INCREMENT=N`` values (e.g. ``tenants``
    starts at 3731 — the current max in the dev DB).  Without this
    reset, the first INSERT into a fresh schema gets an id in the
    thousands, breaking hard-coded ``tenant_id=1`` references in
    the seed scripts (e.g. ``seed_wx_templates``).
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT TABLE_NAME FROM information_schema.tables "
            "WHERE TABLE_SCHEMA = %s",
            (conn.db.decode() if isinstance(conn.db, bytes) else conn.db,),
        )
        tables = [r[0] for r in cur.fetchall()]
    logger.info("Resetting AUTO_INCREMENT on %d tables ...", len(tables))
    with conn.cursor() as cur:
        for t in tables:
            cur.execute(f"ALTER TABLE `{t}` AUTO_INCREMENT = 1")
    conn.commit()


# Global builtin ModelConfig rows that ``init_dev_db.py`` and
# ``lumen_scripts/seed_m35_default_models`` do NOT cover.  These are
# produced by ``migrate_embedding_model_config`` (needs a KB) and
# image-model migrations, neither of which run cleanly on an empty
# schema.  We insert them directly so the import is "out of the box".
_REQUIRED_GLOBAL_MODELS: tuple[dict[str, Any], ...] = (
    {
        "name": "Auto: nomic-embed-text",
        "model_type": "ollama",
        "model_name": "nomic-embed-text",
        "base_url": "http://localhost:11434",
        "api_key": "ollama",
        "is_default": False,
        "is_active": True,
        "is_chat": False,
        "is_embedding": True,
        "is_image_generation": False,
        "is_tts": False,
        "is_subtitle_generation": False,
        "is_video": False,
        "tenant_id": None,
        "description": "Ollama 本地 embedding 模型(768 维,英文为主)。默认 KB RAG 检索。",
    },
    {
        "name": "minimax-image",
        "model_type": "minimax",
        "model_name": "image-01",
        "base_url": "https://api.minimax.chat/v1",
        "api_key": "YOUR_MINIMAX_API_KEY_HERE",
        "is_default": False,
        "is_active": True,
        "is_chat": False,
        "is_embedding": False,
        "is_image_generation": True,
        "is_tts": False,
        "is_subtitle_generation": False,
        "is_video": False,
        "tenant_id": None,
        "description": "MiniMax 图像生成(image-01)。封面图 / 视频首帧。",
    },
)


def _ensure_essential_models(conn: pymysql.connections.Connection) -> None:
    """Insert the global ``nomic-embed-text`` and ``minimax-image``
    rows if they don't already exist.  Idempotent.
    """
    with conn.cursor() as cur:
        for m in _REQUIRED_GLOBAL_MODELS:
            cur.execute(
                "SELECT id FROM model_configs WHERE name = %s LIMIT 1",
                (m["name"],),
            )
            if cur.fetchone():
                continue
            cols = ", ".join(f"`{c}`" for c in m)
            placeholders = ", ".join(["%s"] * len(m))
            cur.execute(
                f"INSERT INTO model_configs ({cols}) VALUES ({placeholders})",
                tuple(m.values()),
            )
            logger.info("  + inserted global model: %s", m["name"])
    conn.commit()


def _dump_data(conn: pymysql.connections.Connection) -> str:
    """Walk every table, build the data.sql body.  Return the body
    (without the header / footer comments)."""
    buf = io.StringIO()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT TABLE_NAME FROM information_schema.tables "
            "WHERE TABLE_SCHEMA = %s ORDER BY TABLE_NAME",
            (_TEMP_SCHEMA,),
        )
        tables = [r[0] for r in cur.fetchall()]
    logger.info("Dumping %d tables ...", len(tables))
    for t in tables:
        if t in _DUMP_SKIP_TABLES:
            logger.debug("  skip %s", t)
            continue
        with conn.cursor() as cur:
            for chunk in _dump_table(cur, t):
                buf.write(chunk)
    return buf.getvalue()


def _write_output(body: str, output: Path) -> None:
    header = _HEADER_TEMPLATE.format(
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        schema_version=_SCHEMA_SQL.stat().st_size,
        temp_schema=_TEMP_SCHEMA,
    )
    # Footer restores FOREIGN_KEY_CHECKS so subsequent SQL on the
    # target schema runs with FK enforcement on (the header turns
    # them off to allow out-of-order table inserts).
    footer = (
        "\n"
        "-- ============================================================\n"
        "-- Restore FK enforcement.  Tables above were inserted with\n"
        "-- FOREIGN_KEY_CHECKS=0 to allow out-of-order dumps; the\n"
        "-- target schema is now consistent and FKs can be re-enabled.\n"
        "-- ============================================================\n"
        "SET FOREIGN_KEY_CHECKS = 1;\n"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(header + "\n" + body + footer, encoding="utf-8")
    size_kb = output.stat().st_size / 1024
    logger.info("Wrote %s (%.1f KB)", output.relative_to(_REPO), size_kb)


def _cleanup() -> None:
    """Drop throwaway schema + remove temp storage."""
    logger.info("Cleaning up throwaway schema + storage ...")
    try:
        conn = _connect(db=None)
        try:
            with conn.cursor() as cur:
                cur.execute(f"DROP DATABASE IF EXISTS `{_TEMP_SCHEMA}`")
            conn.commit()
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not drop temp schema: %s", exc)
    tmp_storage = _BACKEND / "data" / _TEMP_STORAGE_DIR_NAME
    if tmp_storage.exists():
        shutil.rmtree(tmp_storage, ignore_errors=True)


# Header / footer template.  ``data.sql`` should be self-explanatory.
_HEADER_TEMPLATE = """\
-- ============================================================
-- Lumen AI Platform -- Default system data (ai_platform schema)
-- Generated:  {generated_at}
-- Source:     throwaway schema ``{temp_schema}`` populated by
--             backend/scripts/init_dev_db.py + lumen_scripts/seed_*
--             (NOT a dump of the dev DB; dev DB has test residue)
-- ============================================================
-- Usage:
--   1. Source this AFTER scripts/sql/schema.sql:
--        mysql ai_platform < scripts/sql/schema.sql
--        mysql ai_platform < scripts/sql/data.sql
--   2. Override the LLM api_key placeholders in ``model_configs``
--      (currently YOUR_MINIMAX_API_KEY_HERE / YOUR_OPENAI_API_KEY_HERE
--      / etc.) by editing the .sql directly OR by UPDATE:
--        UPDATE model_configs SET api_key = '<your real key>'
--          WHERE model_type = 'minimax';
--   3. (Optional) Re-generate the wx-publisher template thumbnails
--      and the stock image / audio BLOBs that live on disk:
--        cd backend && python -m scripts.seed_wx_template_thumbnails
--        cd backend && python -m lumen_scripts.seed_stock_assets
--        cd backend && python -m lumen_scripts.seed_stock_musics
--   4. Default login:
--        username: admin
--        password: admin123
--      (Override at first login via the user management UI.)
--
-- WARNING: This file is a data dump.  Re-running it on a DB that
-- already has live user data will INSERT duplicate tenants /
-- admin rows (the unique constraints on ``tenants.code`` and
-- ``users.username`` will block them; the rest will pile up).
-- Always start from a freshly-sourced schema.sql.
-- ============================================================

SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;
"""


# ─── Entry point ────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--output",
        type=Path,
        default=_DEFAULT_OUTPUT,
        help=f"Output path (default: {_DEFAULT_OUTPUT.relative_to(_REPO)})",
    )
    parser.add_argument(
        "--keep-temp",
        action="store_true",
        help="Do not drop the throwaway schema (for debugging).",
    )
    args = parser.parse_args()

    # DATABASE_URL must already be set (init_dev_db.py reads it).
    if "DATABASE_URL" not in os.environ:
        # Fall back to backend/.env so this script is one-shot.
        env_file = _BACKEND / ".env"
        if env_file.exists():
            for line in env_file.read_text(encoding="utf-8").splitlines():
                if "=" in line and not line.strip().startswith("#"):
                    k, _, v = line.partition("=")
                    os.environ.setdefault(k.strip(), v.strip())
    if "DATABASE_URL" not in os.environ:
        logger.error("DATABASE_URL not set; please export it or run from backend dir.")
        return 1

    # Persist base DSN so seed scripts reuse the same host/port.
    global _DSN_BASE
    cfg = _parse_dsn(os.environ["DATABASE_URL"])
    _DSN_BASE = f"mysql+pymysql://{cfg['user']}:{cfg['pwd']}@{cfg['host']}:{cfg['port']}"

    try:
        # 1. Create throwaway schema.
        root = _connect(db=None)
        try:
            with root.cursor() as cur:
                cur.execute(f"DROP DATABASE IF EXISTS `{_TEMP_SCHEMA}`")
                cur.execute(
                    f"CREATE DATABASE `{_TEMP_SCHEMA}` "
                    "CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci"
                )
            root.commit()
        finally:
            root.close()

        # 2. Source schema.sql.
        target = _connect(db=_TEMP_SCHEMA)
        try:
            _load_schema_sql(target)
            _reset_auto_increments(target)
            # 3. Run all seed scripts.
            # We must close the schema connection first because seed
            # scripts open their own connections, and we want them to
            # see the schema we just created.
            target.close()
            _run_seed_scripts()
            # Re-open and patch the few rows that the seed scripts
            # don't (or can't) cover on an empty schema.
            target = _connect(db=_TEMP_SCHEMA)
            try:
                _ensure_essential_models(target)
            finally:
                target.close()
            # 4. Walk and dump.
            target = _connect(db=_TEMP_SCHEMA)
            try:
                body = _dump_data(target)
            finally:
                target.close()
        except Exception:
            try:
                target.close()  # noqa: F821
            except Exception:  # noqa: BLE001
                pass
            raise

        # 5. Write output.
        _write_output(body, args.output)
    finally:
        if not args.keep_temp:
            _cleanup()
    return 0


if __name__ == "__main__":
    sys.exit(main())
