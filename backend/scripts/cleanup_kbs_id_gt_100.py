#!/usr/bin/env python
"""一次性清理 dev DB 中 id > 100 的 knowledge_bases + 全部 FK 引用。

FK 拓扑(按删除顺序):
    document_chunks ──(NO ACTION)──► documents ──(NO ACTION)──► knowledge_bases ──► agent_knowledge_bases (NO ACTION)
                                                                       ├──► embedding_call_logs (NO ACTION, 0 行实际)
                                                                       ├──► eval_datasets          (CASCADE → eval_runs / eval_dataset_items)
                                                                       ├──► faq_entries            (CASCADE, 部分通过 document.faq_entries 也清掉)
                                                                       └──► wx_drafts              (SET NULL, 0 行实际)

不可逆,只在本机 localhost:3307/ai_platform dev DB 用。

USAGE:
    cd backend && PYTHONIOENCODING=utf-8 python scripts/cleanup_kbs_id_gt_100.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.parse import urlparse

import pymysql
from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BACKEND_DIR / ".env")

url = os.environ["DATABASE_URL"]
parsed = urlparse(url)
host = parsed.hostname or "localhost"
port = parsed.port or 3306
user = parsed.username or "root"
password = parsed.password or ""
database = (parsed.path or "/").lstrip("/")


def connect() -> pymysql.Connection:
    """Open a fresh pymysql connection (each call returns a new one — avoids
    REPEATABLE READ cross-session visibility problems).
    """
    return pymysql.connect(
        host=host,
        port=port,
        user=user,
        password=password,
        database=database,
        autocommit=False,
        connect_timeout=5,
        charset="utf8mb4",
    )


# 事前清单 + 清理
conn = connect()
deleted: dict[str, int] = {}
try:
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM knowledge_bases WHERE id > 100")
        before_kb = cur.fetchone()[0]
        print(f"[before] knowledge_bases id>100 = {before_kb}")

        # 1. document_chunks 是 document_id → documents 的 NO ACTION,必须先于 documents 清
        cur.execute(
            "DELETE FROM document_chunks "
            "WHERE document_id IN ("
            "  SELECT id FROM documents WHERE knowledge_base_id > 100"
            ")"
        )
        deleted["document_chunks"] = cur.rowcount
        print(f"[1] document_chunks 删 {cur.rowcount} 行")

        # 2. documents 删 → cascade 清掉 faq_entries 中关联到 documents 的那部分
        cur.execute("DELETE FROM documents WHERE knowledge_base_id > 100")
        deleted["documents"] = cur.rowcount
        print(f"[2] documents 删 {cur.rowcount} 行 (cascade 清 docs 关联的 faq_entries)")

        # 3. agent_knowledge_bases
        cur.execute("DELETE FROM agent_knowledge_bases WHERE knowledge_base_id > 100")
        deleted["agent_knowledge_bases"] = cur.rowcount
        print(f"[3] agent_knowledge_bases 删 {cur.rowcount} 行")

        # 4. embedding_call_logs
        cur.execute("DELETE FROM embedding_call_logs WHERE knowledge_base_id > 100")
        deleted["embedding_call_logs"] = cur.rowcount
        print(f"[4] embedding_call_logs 删 {cur.rowcount} 行")

        # 5. 删 KB 主表 → cascade 自动清 eval_datasets(再 cascade 清 eval_runs/eval_dataset_items)+ 剩余 faq_entries
        cur.execute("DELETE FROM knowledge_bases WHERE id > 100")
        deleted["knowledge_bases"] = cur.rowcount
        print(f"[5] knowledge_bases 删 {cur.rowcount} 行 (cascade 清 eval_datasets + 剩余 faq_entries)")

    conn.commit()
    print("[commit] OK")
except Exception as exc:
    conn.rollback()
    print(f"[rollback] {exc!r}", file=sys.stderr)
    raise
finally:
    conn.close()

# 验证 — 新开连接避开 REPEATABLE READ 缓存
conn2 = connect()
try:
    with conn2.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM knowledge_bases WHERE id > 100")
        after_kb_id_gt_100 = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM knowledge_bases")
        kb_total = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM eval_datasets")
        eval_ds_total = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM eval_runs")
        runs_total = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM documents")
        docs_total = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM document_chunks")
        chunks_total = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM agent_knowledge_bases")
        akb_total = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM faq_entries")
        faq_total = cur.fetchone()[0]
    print("---")
    print(f"[verify] knowledge_bases WHERE id>100 = {after_kb_id_gt_100}    (期望 0)")
    print(f"[verify] knowledge_bases total            = {kb_total}    (期望 1005,清理前 1495)")
    print(f"[verify] documents total                  = {docs_total}")
    print(f"[verify] document_chunks total            = {chunks_total}")
    print(f"[verify] agent_knowledge_bases total      = {akb_total}")
    print(f"[verify] faq_entries total                = {faq_total}")
    print(f"[verify] eval_datasets total              = {eval_ds_total}    (期望 33,清理前 42)")
    print(f"[verify] eval_runs total                  = {runs_total}    (期望 1,清理前 17)")

    if after_kb_id_gt_100 != 0:
        print("[FAIL] knowledge_bases id>100 还有残留!", file=sys.stderr)
        sys.exit(1)
    print("[OK] 全部验证通过")
finally:
    conn2.close()
