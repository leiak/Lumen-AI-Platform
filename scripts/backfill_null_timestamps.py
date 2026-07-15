"""一次性回填 dev DB 里所有表 NULL created_at / updated_at。

背景:DB 列定义都是 IS_NULLABLE=YES,项目历史上 fixture 直插 NULL 留下污染。
Pydantic schema 大多写死 `datetime`(不带 Optional),NULL → ValidationError → 500。
本脚本把所有 NULL 时间戳回填为 NOW(),不动业务数据,可逆。

用法:python scripts/backfill_null_timestamps.py
"""
from __future__ import annotations

import sys

import pymysql

CONN_KW = dict(
    host="localhost",
    port=3307,
    user="root",
    password="rootpassword",
    database="ai_platform",
    connect_timeout=5,
    charset="utf8mb4",
)

# 24 张用户面 + 7 张日志/记录表,共 31 张实际有 NULL 的表。
# 实际跑前脚本会 SHOW COLUMNS 动态校验,这里只作参考排序。
TABLES = [
    "agents", "agent_teams", "agent_team_members", "agent_tools",
    "agent_knowledge_bases",
    "conversations", "messages",
    "customers", "customer_field_definitions", "customer_follow_ups",
    "documents", "document_chunks",
    "embedding_call_logs", "llm_call_logs",
    "external_apps", "external_visitors",
    "faq_entries", "generated_images",
    "global_memories", "installed_skills",
    "knowledge_bases",
    "mcp_servers", "mcp_tools",
    "nlp_annotation", "nlp_classification", "nlp_qa",
    "notifications", "operation_logs", "permissions",
    "ppt_tasks", "query_logs",
    "roles", "skill_marketplace", "skills",
    "system_configs", "tenants",
    "text2sql_data_sources", "text2sql_queries",
    "users", "vision_classification", "vision_image",
    "workflow_node_runs", "workflow_runs", "workflow_schedules",
    "workflow_templates", "workflows",
    "wx_accounts", "wx_drafts", "wx_draft_sections",
    "wx_materials", "wx_publish_records", "wx_templates",
]


def main() -> int:
    conn = pymysql.connect(**CONN_KW)
    cur = conn.cursor()
    grand_total = 0
    skipped: list[str] = []
    affected_per_table: list[tuple[str, int]] = []

    for t in TABLES:
        # 动态校验列存在(防止我列错了表名)
        cur.execute(f"SHOW COLUMNS FROM `{t}` LIKE 'created_at'")
        has_created = cur.fetchone() is not None
        cur.execute(f"SHOW COLUMNS FROM `{t}` LIKE 'updated_at'")
        has_updated = cur.fetchone() is not None

        if not has_created and not has_updated:
            skipped.append(t)
            continue

        set_clauses = []
        where_clauses = []
        if has_created:
            set_clauses.append("created_at = COALESCE(created_at, NOW())")
            where_clauses.append("created_at IS NULL")
        if has_updated:
            set_clauses.append("updated_at = COALESCE(updated_at, NOW())")
            where_clauses.append("updated_at IS NULL")
        sql = (
            f"UPDATE `{t}` SET " + ", ".join(set_clauses) +
            " WHERE " + " OR ".join(where_clauses)
        )
        cur.execute(sql)
        n = cur.rowcount
        grand_total += n
        if n > 0:
            affected_per_table.append((t, n))

    conn.commit()
    cur.close()
    conn.close()

    # 报告
    print(f"\n=== 回填结果 ===")
    print(f"扫描表: {len(TABLES)} 张")
    print(f"跳过(无时间戳列): {len(skipped)} 张 -> {skipped}")
    print(f"修改行数: {grand_total}\n")
    if affected_per_table:
        print("各表行数:")
        for t, n in sorted(affected_per_table, key=lambda x: -x[1]):
            print(f"  {t:<30} {n:>5}")
    return 0


if __name__ == "__main__":
    sys.exit(main())