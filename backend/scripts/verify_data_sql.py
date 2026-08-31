"""Validate ``scripts/sql/data.sql`` by sourcing it on a fresh schema.

Idempotent: drops + recreates a throwaway ``ai_platform_verify`` schema
each run, then counts rows in every table after the load and asserts
the totals match the export script's expected counts.
"""
from __future__ import annotations

import io
import re
import subprocess
import sys
import time
from pathlib import Path

import pymysql  # type: ignore[import-untyped]

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent.parent
_SCHEMA = _REPO / "scripts" / "sql" / "schema.sql"
_DATA = _REPO / "scripts" / "sql" / "data.sql"
_VERIFY_SCHEMA = "ai_platform_verify"

# Expected row counts after data.sql import.  These are the values
# reported by the export script's "INFO: Dumping 70 tables ..."
# output; if a new seed script is added, the export will print
# different numbers and this dict needs to be updated.
EXPECTED = {
    "tenants": 1,
    "users": 1,
    "model_configs": 9,
    "system_configs": 2,
    "mcp_servers": 1,
    "mcp_tools": 7,
    "skill_marketplace": 25,
    "installed_skills": 1,
    "external_apps": 1,
    "text2sql_data_sources": 1,
    "workflow_templates": 8,
    "wx_templates": 15,
    "stock_assets": 30,
    "stock_musics": 5,
}


def _split_sql_statements(sql: str) -> list[str]:
    out: list[str] = []
    buf: list[str] = []
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
    if buf:
        leftover = "\n".join(buf).strip()
        if leftover:
            out.append(leftover)
    return out


def main() -> int:
    print(f"=== verify {time.strftime('%Y-%m-%d %H:%M:%S')} ===")
    print(f"schema: {_SCHEMA.relative_to(_REPO)}")
    print(f"data:   {_DATA.relative_to(_REPO)}")
    if not _SCHEMA.exists():
        print(f"FAIL: {_SCHEMA} not found")
        return 1
    if not _DATA.exists():
        print(f"FAIL: {_DATA} not found")
        return 1

    # 1. Drop + create verify schema.
    root = pymysql.connect(
        host="localhost", port=3307, user="root", password="rootpassword", autocommit=False,
    )
    try:
        with root.cursor() as cur:
            cur.execute(f"DROP DATABASE IF EXISTS `{_VERIFY_SCHEMA}`")
            cur.execute(
                f"CREATE DATABASE `{_VERIFY_SCHEMA}` "
                "CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci"
            )
        root.commit()
    finally:
        root.close()

    # 2. Source schema.sql then data.sql.
    conn = pymysql.connect(
        host="localhost", port=3307, user="root", password="rootpassword",
        database=_VERIFY_SCHEMA, autocommit=False,
    )
    try:
        for label, path in (("schema", _SCHEMA), ("data", _DATA)):
            sql = path.read_text(encoding="utf-8")
            stmts = _split_sql_statements(sql)
            print(f"  sourcing {label} ({len(stmts)} statements) ...")
            with conn.cursor() as cur:
                for i, stmt in enumerate(stmts, 1):
                    try:
                        cur.execute(stmt)
                    except Exception as exc:
                        # Re-raise with line context so we can spot
                        # the bad row in the .sql file.
                        first_line = stmt.splitlines()[0][:80]
                        raise RuntimeError(
                            f"Statement #{i} in {label} failed: {exc}\n"
                            f"  first line: {first_line!r}"
                        ) from exc
        conn.commit()
    finally:
        conn.close()

    # 3. Count rows in every table.
    print()
    print("Row counts:")
    conn = pymysql.connect(
        host="localhost", port=3307, user="root", password="rootpassword",
        database=_VERIFY_SCHEMA, autocommit=False,
    )
    failures: list[str] = []
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT TABLE_NAME FROM information_schema.tables "
                "WHERE TABLE_SCHEMA = %s ORDER BY TABLE_NAME",
                (_VERIFY_SCHEMA,),
            )
            tables = [r[0] for r in cur.fetchall()]
            for t in tables:
                cur.execute(f"SELECT COUNT(*) FROM `{t}`")
                count = cur.fetchone()[0]
                if count == 0:
                    continue
                expected = EXPECTED.get(t)
                marker = ""
                if expected is not None and expected != count:
                    marker = f"  ← EXPECTED {expected}!"
                    failures.append(f"{t}: got {count}, expected {expected}")
                print(f"  {t:40s} {count:5d}{marker}")
    finally:
        conn.close()

    # 4. Cleanup.
    root = pymysql.connect(
        host="localhost", port=3307, user="root", password="rootpassword", autocommit=False,
    )
    try:
        with root.cursor() as cur:
            cur.execute(f"DROP DATABASE IF EXISTS `{_VERIFY_SCHEMA}`")
        root.commit()
    finally:
        root.close()

    print()
    if failures:
        print(f"FAIL: {len(failures)} table(s) had unexpected counts:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("OK — all expected row counts match.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
