"""Dev-only cleanup script — 方案 B:
   保留 admin (user_id=1) 真实数据,清掉 fixture 残留。

清理目标:
  - agent_teams + members + 关联 team conv/messages(共 128 team + 71 conv + 155 members + 相关 msg)
  - user_id != 1 的 conversations + messages(390 conv + 112 msg)
  - fixture users(id > 1,共 634 行) + 全部引用它们的二级行

Single transaction + FOREIGN_KEY_CHECKS=0,任一失败 ROLLBACK。
按 cleanup_users_id_gt_25.py 同模式。
"""
import re
import sys
from urllib.parse import urlparse

import pymysql


def parse_db_url(url: str) -> dict:
    url = url.replace("mysql+pymysql://", "mysql://")
    p = urlparse(url)
    return {
        "host": p.hostname, "port": p.port, "user": p.username,
        "password": p.password, "database": p.path.lstrip("/"),
    }


def load_db_creds(env_path: str) -> dict:
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            m = re.match(r"DATABASE_URL\s*=\s*(\S+)", line.strip())
            if m:
                return parse_db_url(m.group(1))
    raise RuntimeError("DATABASE_URL not found in .env")


DELETE_SQL = [
    # ============ 阶段 1:AgentTeam fixture ============
    # 先杀 messages(关联 team conv),再杀 conversations,再杀 members,再杀 teams。
    # FK 在 db 层有 ON DELETE RESTRICT,所以 messages → conv → members → teams 必须严格顺序。
    # 但有 FOREIGN_KEY_CHECKS=0 兜底,顺序错了也不会真挂 —— 只是保持可读性。
    # 注:agent_team_routes 表(若存在)也得清,它是 manager_agent_id → route 配表,
    # 不直接 FK 到 team.id 但 team 删了它的 routes 就孤立了。
    "DELETE FROM messages WHERE conversation_id IN (SELECT id FROM conversations WHERE team_id IS NOT NULL)",
    "DELETE FROM conversations WHERE team_id IS NOT NULL",
    "DELETE FROM agent_team_members",
    "DELETE FROM agent_team_routes",
    "DELETE FROM agent_teams",

    # ============ 阶段 2:Fixture conv/messages (user_id != 1) ============
    # 阶段 1 已清掉带 team_id 的 conv,所以这里剩下的都是 agent_id 直绑的 conv。
    "DELETE FROM messages WHERE conversation_id IN (SELECT id FROM conversations WHERE user_id != 1)",
    "DELETE FROM conversations WHERE user_id != 1",

    # ============ 阶段 3:Fixture users (id > 1) ============
    # 跟 cleanup_users_id_gt_25.py 同模式 —— 二级引用先清,users 主表最后。
    # 二级引用链(用户拥有的子表):
    "DELETE FROM messages WHERE conversation_id IN (SELECT id FROM conversations WHERE user_id > 1)",  # noqa: 应该已清空
    "DELETE FROM ppt_tasks WHERE user_id > 1",
    "DELETE FROM llm_call_logs WHERE user_id > 1",
    "DELETE FROM embedding_call_logs WHERE user_id > 1",
    "DELETE FROM generated_audios WHERE user_id > 1",
    "DELETE FROM generated_videos WHERE user_id > 1",
    "DELETE FROM subtitles WHERE user_id > 1",
    "DELETE FROM document_chunks WHERE document_id IN (SELECT id FROM documents WHERE created_by > 1)",
    "DELETE FROM faq_entries WHERE document_id IN (SELECT id FROM documents WHERE created_by > 1)",
    "DELETE FROM faq_entries WHERE created_by > 1",
    "DELETE FROM external_visitors WHERE app_id IN (SELECT id FROM external_apps WHERE created_by > 1)",
    "DELETE FROM conversations WHERE external_app_id IN (SELECT id FROM external_apps WHERE created_by > 1)",
    # 一级引用(直接 FK 到 users):
    "DELETE FROM audit_logs WHERE user_id > 1",
    "DELETE FROM customer_field_definitions WHERE created_by > 1",
    "DELETE FROM customer_follow_ups WHERE user_id > 1",
    "DELETE FROM customers WHERE owner_user_id > 1 OR created_by > 1",
    "DELETE FROM documents WHERE created_by > 1",
    "DELETE FROM eval_dataset_items WHERE dataset_id IN (SELECT id FROM eval_datasets WHERE created_by > 1)",
    "DELETE FROM eval_datasets WHERE created_by > 1",
    "DELETE FROM eval_run_results WHERE run_id IN (SELECT id FROM eval_runs WHERE created_by > 1)",
    "DELETE FROM eval_runs WHERE created_by > 1",
    "DELETE FROM external_apps WHERE created_by > 1",
    "DELETE FROM generated_images WHERE user_id > 1",
    "DELETE FROM notifications WHERE user_id > 1",
    "DELETE FROM playbooks WHERE created_by > 1",
    "DELETE FROM text2sql_queries WHERE user_id > 1",
    "DELETE FROM workflow_templates WHERE author_id > 1",
    "DELETE FROM wx_drafts WHERE user_id > 1",
    "DELETE FROM wx_draft_sections WHERE draft_id IN (SELECT id FROM wx_drafts WHERE user_id > 1)",
    "DELETE FROM wx_publish_records WHERE user_id > 1",
    "DELETE FROM wx_materials WHERE user_id > 1",
    "DELETE FROM wx_accounts WHERE user_id > 1",
    "DELETE FROM wx_templates WHERE created_by > 1",
    # 工作流本身也是 user-owned,得清
    "DELETE FROM workflow_node_runs",
    "DELETE FROM workflow_runs",
    "DELETE FROM workflows",
    # workspace RBAC(M38.2 ship) — workspace/folder 是 user-created,owner_id > 1 全清
    "DELETE FROM workspace_member_permissions WHERE workspace_id IN (SELECT id FROM workspaces WHERE owner_id > 1)",
    # document_folders 不直接 FK 到 workspace,而是 FK 到 knowledge_base。
    # 知识库挂 workspace,文档挂在知识库下,所以级联走 knowledge_base_id → kb.workspace_id。
    "DELETE FROM document_folders WHERE knowledge_base_id IN (SELECT id FROM knowledge_bases WHERE workspace_id IN (SELECT id FROM workspaces WHERE owner_id > 1))",
    # knowledge_bases 没有 user_id 列,只能按 workspace_id IN (...) 走
    "DELETE FROM knowledge_bases WHERE workspace_id IN (SELECT id FROM workspaces WHERE owner_id > 1)",
    "DELETE FROM workspaces WHERE owner_id > 1",
    # 最后删主表 users(notifications.user_id 已在阶段 3 第 31 步按 user_id > 1 清掉,notifications
    # 没有 created_by 列,这里不重复)
    "DELETE FROM users WHERE id > 1",
]


def main() -> int:
    creds = load_db_creds(".env")
    print(f"[connect] host={creds['host']} port={creds['port']} db={creds['database']}")

    conn = pymysql.connect(
        host=creds["host"], port=creds["port"], user=creds["user"],
        password=creds["password"], database=creds["database"],
        autocommit=False, connect_timeout=10,
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
                if "users" in sql.lower() and "id > 1" in sql:
                    total_users_deleted = rows
            cur.execute("SET FOREIGN_KEY_CHECKS = 1")
            cur.execute("COMMIT")
            print(f"\n[ok] committed. {total_users_deleted} fixture users deleted.")

            # 验证残留
            print("\n=== 验证 ===")
            cur.execute("SELECT COUNT(*) FROM users")
            print(f"  users remain: {cur.fetchone()[0]}")
            cur.execute("SELECT COUNT(*) FROM agent_teams")
            print(f"  agent_teams remain: {cur.fetchone()[0]}")
            cur.execute("SELECT COUNT(*) FROM conversations")
            print(f"  conversations remain: {cur.fetchone()[0]}")
            cur.execute("SELECT COUNT(*) FROM messages")
            print(f"  messages remain: {cur.fetchone()[0]}")
            cur.execute("SELECT COUNT(*) FROM agent_team_members")
            print(f"  agent_team_members remain: {cur.fetchone()[0]}")
    except Exception as e:
        conn.rollback()
        print(f"\n[fail] rolled back: {e}", file=sys.stderr)
        return 1
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())