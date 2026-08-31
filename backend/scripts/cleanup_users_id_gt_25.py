"""Cascade-delete all users with id > 25 and their referencing rows.

Dev-only cleanup. Wraps everything in a single MySQL transaction with
FOREIGN_KEY_CHECKS=0 so the order of DELETEs doesn't matter. On any
error we ROLLBACK and nothing is committed.

Usage: cd backend && python scripts/cleanup_users_id_gt_25.py
"""
import os
import re
import sys
from urllib.parse import urlparse

import pymysql


def parse_db_url(url: str) -> dict:
    """Parse mysql+pymysql://user:pass@host:port/db."""
    url = url.replace("mysql+pymysql://", "mysql://")
    p = urlparse(url)
    return {
        "host": p.hostname,
        "port": p.port,
        "user": p.username,
        "password": p.password,
        "database": p.path.lstrip("/"),
    }


def load_db_creds(env_path: str) -> dict:
    """Pull DATABASE_URL from .env without external deps."""
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            m = re.match(r"DATABASE_URL\s*=\s*(\S+)", line.strip())
            if m:
                return parse_db_url(m.group(1))
    raise RuntimeError("DATABASE_URL not found in .env")


# Cascade plan. Order matters only for nested FK chains (we list parents
# before children). All DELETEs run inside one transaction with
# FOREIGN_KEY_CHECKS=0, so a missed order would not block — but listing
# sensibly keeps the intent obvious.
DELETE_SQL = [
    # 二级引用链:先清 conversations / documents / external_apps 的子表
    "DELETE FROM messages WHERE conversation_id IN (SELECT id FROM conversations WHERE user_id > 25)",
    "DELETE FROM ppt_tasks WHERE user_id > 25",
    "DELETE FROM llm_call_logs WHERE user_id > 25",
    "DELETE FROM embedding_call_logs WHERE user_id > 25",
    "DELETE FROM generated_audios WHERE user_id > 25",
    "DELETE FROM generated_videos WHERE user_id > 25",
    "DELETE FROM subtitles WHERE user_id > 25",
    "DELETE FROM document_chunks WHERE document_id IN (SELECT id FROM documents WHERE created_by > 25)",
    "DELETE FROM faq_entries WHERE document_id IN (SELECT id FROM documents WHERE created_by > 25)",
    "DELETE FROM faq_entries WHERE created_by > 25",
    "DELETE FROM external_visitors WHERE app_id IN (SELECT id FROM external_apps WHERE created_by > 25)",
    "DELETE FROM conversations WHERE external_app_id IN (SELECT id FROM external_apps WHERE created_by > 25)",
    # 一级引用清理
    "DELETE FROM audit_logs WHERE user_id > 25",
    "DELETE FROM customer_field_definitions WHERE created_by > 25",
    "DELETE FROM customer_follow_ups WHERE user_id > 25",
    "DELETE FROM customers WHERE owner_user_id > 25 OR created_by > 25",
    "DELETE FROM documents WHERE created_by > 25",
    "DELETE FROM eval_dataset_items WHERE dataset_id IN (SELECT id FROM eval_datasets WHERE created_by > 25)",
    "DELETE FROM eval_datasets WHERE created_by > 25",
    "DELETE FROM eval_run_results WHERE run_id IN (SELECT id FROM eval_runs WHERE created_by > 25)",
    "DELETE FROM eval_runs WHERE created_by > 25",
    "DELETE FROM external_apps WHERE created_by > 25",
    "DELETE FROM generated_images WHERE user_id > 25",
    "DELETE FROM notifications WHERE user_id > 25",
    "DELETE FROM playbooks WHERE created_by > 25",
    "DELETE FROM text2sql_queries WHERE user_id > 25",
    "DELETE FROM workflow_templates WHERE author_id > 25",
    "DELETE FROM wx_drafts WHERE user_id > 25",
    "DELETE FROM wx_draft_sections WHERE draft_id IN (SELECT id FROM wx_drafts WHERE user_id > 25)",
    "DELETE FROM wx_publish_records WHERE user_id > 25",
    "DELETE FROM wx_materials WHERE user_id > 25",
    "DELETE FROM wx_accounts WHERE user_id > 25",
    "DELETE FROM wx_templates WHERE created_by > 25",
    # 最后删主表 users
    "DELETE FROM users WHERE id > 25",
]


def main() -> int:
    here = os.path.dirname(os.path.abspath(__file__))
    creds = load_db_creds(os.path.join(here, "..", ".env"))
    print(f"[connect] host={creds['host']} port={creds['port']} db={creds['database']}")

    conn = pymysql.connect(
        host=creds["host"],
        port=creds["port"],
        user=creds["user"],
        password=creds["password"],
        database=creds["database"],
        autocommit=False,
        connect_timeout=10,
    )
    total_users_deleted = 0
    try:
        with conn.cursor() as cur:
            cur.execute("START TRANSACTION")
            cur.execute("SET FOREIGN_KEY_CHECKS = 0")
            for i, sql in enumerate(DELETE_SQL, 1):
                cur.execute(sql)
                rows = cur.rowcount
                tbl = sql.split()[2]
                print(f"[{i:02d}/{len(DELETE_SQL)}] {tbl:30s} -> {rows:6d} rows")
                if "users" in sql.lower() and "id > 25" in sql:
                    total_users_deleted = rows
            cur.execute("SET FOREIGN_KEY_CHECKS = 1")
            cur.execute("COMMIT")
            print(f"\n[ok] committed. {total_users_deleted} users deleted.")
    except Exception as e:
        conn.rollback()
        print(f"\n[fail] rolled back: {e}", file=sys.stderr)
        return 1
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())