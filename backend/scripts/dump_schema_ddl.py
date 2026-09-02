"""Dump dev MySQL DB (ai_platform @ localhost:3307) schema-only (DDL) to a local SQL file.

Pure pymysql ``SHOW CREATE TABLE`` walk; no data rows emitted.
镜像 ``dump_dev_db.py`` 的连接 / 编码约定,只输出 DDL,不输出 INSERT,适合给生产部署 / 文档 / 数据字典用。

Usage:
    python backend/scripts/dump_schema_ddl.py [output_path]

Default output_path: 项目根 ``lumen_schema_<YYYY-MM-DD>.sql``。

Restore(可执行,自带 DROP + FK off):
    mysql -h <host> -P <port> -u <user> -p <database> < lumen_schema_<date>.sql

注意:
  - 只 dump 结构,不 dump 数据。
  - 输出放项目根 ``/*.sql`` 已被 root ``.gitignore`` 兜底(Misc dev-only root 临时文件段),不会进 git。
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
    # 写到项目根(lumen AI Platform 根目录),不是 backend/ 下面
    here = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.normpath(os.path.join(here, "..", ".."))
    today = datetime.date.today().isoformat()
    return os.path.join(project_root, f"lumen_schema_{today}.sql")


OUT_PATH = sys.argv[1] if len(sys.argv) > 1 else default_output_path()


def dump() -> None:
    conn = pymysql.connect(**DB_CONFIG, connect_timeout=10)
    out_dir = os.path.dirname(OUT_PATH)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    table_count = 0
    skipped: list[str] = []

    with open(OUT_PATH, "w", encoding="utf-8") as out, conn.cursor() as cur:
        # 文件头: 注释 + 兼容性 SET(可直接被 ``mysql < file.sql`` 重放)
        out.write("-- Lumen AI Platform schema dump (DDL only, no data)\n")
        out.write(f"-- Generated {datetime.datetime.now().isoformat(timespec='seconds')}\n")
        out.write(
            f"-- Source: {DB_CONFIG['host']}:{DB_CONFIG['port']}  "
            f"Database: {DB_CONFIG['database']}\n"
        )
        out.write(
            "-- Restore:  mysql -h <host> -P <port> -u <user> -p "
            f"{DB_CONFIG['database']} < {os.path.basename(OUT_PATH)}\n\n"
        )
        out.write("SET NAMES utf8mb4;\n")
        out.write("SET FOREIGN_KEY_CHECKS=0;\n\n")
        out.write(f"USE `{DB_CONFIG['database']}`;\n\n")

        # 列出所有表(排除视图,视图不算 schema 主体)
        cur.execute(
            "SELECT TABLE_NAME FROM information_schema.tables "
            "WHERE TABLE_SCHEMA = %s AND TABLE_TYPE = 'BASE TABLE' "
            "ORDER BY TABLE_NAME",
            (DB_CONFIG["database"],),
        )
        tables = [row[0] for row in cur.fetchall()]
        print(f"found {len(tables)} base tables")

        for tbl in tables:
            try:
                cur.execute(f"SHOW CREATE TABLE `{tbl}`")
                row = cur.fetchone()
            except pymysql.MySQLError as e:
                # 极少数情况 SHOW CREATE 会失败(损坏 / 权限),继续下一张不中断整个 dump
                skipped.append(f"{tbl}: {e}")
                print(f"  SKIP {tbl}: {e}")
                continue
            ddl = row[1]
            out.write(f"-- Table: {tbl}\n")
            out.write(f"DROP TABLE IF EXISTS `{tbl}`;\n")
            out.write(f"{ddl};\n\n")
            table_count += 1

        # 收尾:恢复 FK 检查
        out.write("SET FOREIGN_KEY_CHECKS=1;\n")

    conn.close()
    sz = os.path.getsize(OUT_PATH)
    print(f"\nDONE -> {OUT_PATH}  ({sz/1024:.1f} KB, {table_count} tables)")
    if skipped:
        print(f"SKIPPED {len(skipped)}: {', '.join(skipped)}")


if __name__ == "__main__":
    dump()
