"""Dump dev MySQL DB (ai_platform @ localhost:3307) to a local SQL file.

Structure + data via pymysql. Mirrors what ``mysqldump`` would emit but works
without the mysqldump binary on this Windows box.

Usage:
    python backend/scripts/dump_dev_db.py [output_path]

Default output_path: ``backend/sql/ai_platform_dump_<today>.sql``.

The dump is intended as a **dev-only** snapshot, NOT for production:
  - It contains plaintext user data, API keys, etc.
  - ``backend/sql/*.sql`` is git-ignored (see root ``.gitignore``).

To restore: read ``backend/sql/README.md``.
"""
import datetime
import os
import sys

import pymysql


DB_CONFIG = {
    "host": "localhost",
    "port": 3307,
    "user": "root",
    "password": "rootpassword",
    "database": "ai_platform",
    "charset": "utf8mb4",
}


def default_output_path() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    sql_dir = os.path.normpath(os.path.join(here, "..", "sql"))
    today = datetime.date.today().isoformat()
    return os.path.join(sql_dir, f"ai_platform_dump_{today}.sql")


OUT_PATH = sys.argv[1] if len(sys.argv) > 1 else default_output_path()


def quote_value(v):
    if v is None:
        return "NULL"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, (datetime.date, datetime.datetime)):
        return f"'{v.isoformat(sep=' ', timespec='seconds')}'"
    if isinstance(v, (bytes, bytearray)):
        return "0x" + v.hex()
    s = str(v).replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n").replace("\r", "\\r")
    return f"'{s}'"


def dump():
    conn = pymysql.connect(**DB_CONFIG, connect_timeout=10)
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    out = open(OUT_PATH, "w", encoding="utf-8")
    out.write("-- ai_platform DB dump\n")
    out.write(f"-- Generated {datetime.datetime.now().isoformat()}\n")
    out.write(f"-- Host: {DB_CONFIG['host']}:{DB_CONFIG['port']}  Database: {DB_CONFIG['database']}\n\n")
    out.write("SET FOREIGN_KEY_CHECKS=0;\n")
    out.write("SET NAMES utf8mb4;\n\n")

    with conn.cursor() as cur:
        cur.execute("SHOW TABLES")
        tables = [row[0] for row in cur.fetchall()]
        print(f"found {len(tables)} tables")

        for tbl in tables:
            cur.execute(f"SHOW CREATE TABLE `{tbl}`")
            row = cur.fetchone()
            ddl = row[1]
            out.write(f"-- Table: {tbl}\n")
            out.write(f"DROP TABLE IF EXISTS `{tbl}`;\n")
            out.write(f"{ddl};\n\n")

            cur.execute(f"SELECT COUNT(*) FROM `{tbl}`")
            cnt = cur.fetchone()[0]
            if cnt == 0:
                continue
            print(f"  {tbl}: {cnt} rows")
            cur.execute(f"SELECT * FROM `{tbl}`")
            cols = [d[0] for d in cur.description]
            cols_sql = ", ".join(f"`{c}`" for c in cols)
            batch = []
            for row in cur.fetchall():
                vals = ", ".join(quote_value(v) for v in row)
                batch.append(f"({vals})")
                if len(batch) >= 500:
                    out.write(
                        f"INSERT INTO `{tbl}` ({cols_sql}) VALUES\n  "
                        + ",\n  ".join(batch) + ";\n"
                    )
                    batch = []
            if batch:
                out.write(
                    f"INSERT INTO `{tbl}` ({cols_sql}) VALUES\n  "
                    + ",\n  ".join(batch) + ";\n"
                )
            out.write("\n")

    out.write("SET FOREIGN_KEY_CHECKS=1;\n")
    out.close()
    conn.close()
    sz = os.path.getsize(OUT_PATH)
    print(f"\nDONE -> {OUT_PATH}  ({sz/1024/1024:.2f} MB)")


if __name__ == "__main__":
    dump()