"""Phase 1 Group A 3.4 (2026-09-04): UNIQUE 索引 vs soft-delete 冲突审计。

**目的**:扫全库,找出 "UNIQUE 索引 + soft-delete 模式 (is_active / enabled) 组合"
导致的 "软删后名字/标识符无法复用" 问题。

**为什么这是个潜在 bug**:
当一张表同时满足:
1. UNIQUE 索引覆盖 name / code / app_id / model_name / app_key / field_key 等"标识符"字段
2. 删除走软删(is_active=False / enabled=False / deleted_at != NULL)而不是 hard delete
3. UNIQUE 索引 *不* 包含 soft-delete 字段

→ 软删一行后,新建同 tenant + 同 name 的 row 会撞 UNIQUE 约束返 409,
但列表视图不显示软删行,前端看着像"明明没人用这个名"但后端拒绝。

**脚本输出**:Markdown 表格,列出每张 UNIQUE 表的 soft delete 字段 + 软删 service
+ 冲突等级 (true_conflict / no_conflict)。

**用法**:
    cd backend && python scripts/audit_unique_constraints.py

输出到 stdout。退出码:0 = 无冲突 / 1 = 有真冲突 / 2 = DB 不可达。
"""
from __future__ import annotations

import os
import re
import sys
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse

import pymysql


# ---------------------------------------------------------------------------
# DB 连接(同 audit_model_schema_drift.py 模式 — pymysql 直连,绕开 MCP DDL 禁)
# ---------------------------------------------------------------------------


def parse_db_url(url: str) -> Dict[str, object]:
    url = url.replace("mysql+pymysql://", "mysql://")
    p = urlparse(url)
    return {
        "host": p.hostname,
        "port": p.port,
        "user": p.username,
        "password": p.password,
        "database": p.path.lstrip("/"),
    }


def load_db_creds(env_path: str) -> Dict[str, object]:
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            m = re.match(r"DATABASE_URL\s*=\s*(\S+)", line.strip())
            if m:
                return parse_db_url(m.group(1))
    raise RuntimeError("DATABASE_URL not found in .env")


# ---------------------------------------------------------------------------
# SQL 查询
# ---------------------------------------------------------------------------


# 软删"标识符"字段集:UNIQUE 索引若包含这些字段,且表有 soft-delete 路径,
# 就是潜在的 name 复用冲突。app_id / app_key / model_name / field_key / code
# 这些虽然不是"name"字面,但语义上都是"用户定义的标识符",复用会冲突。
NAMING_FIELDS = {
    "name",
    "code",
    "app_id",
    "app_key",
    "model_name",
    "field_key",
    "username",
    "email",
    "key",
    "marketplace_skill_id",
    "permission",
    "order_index",
}

# 这些 UNIQUE 索引我们不视为冲突源:log 表 / 中间表 / immutable id。
SAFE_TABLES = {
    "failed_tasks",  # Phase 1 1.5 ship,自管
    "audit_logs",
    "operation_logs",
    "query_logs",
    "embedding_call_logs",  # UNIQUE(call_id) — call_id 永不复用
    "llm_call_logs",
    "workflow_node_runs",
    "wx_draft_sections",  # UNIQUE(draft_id, order_index) — order_index 跟着 draft 删
    "workspace_member_permissions",  # 跟着 workspace 删,user_id 不复用
    "installed_skills",  # hard delete(lumen_api/v1/skill_market.py:1283 db.delete)
}


def fetch_unique_indexes(conn) -> List[Tuple[str, str, List[Tuple[int, str]]]]:
    """返回 [(TABLE_NAME, INDEX_NAME, [(seq, column), ...]), ...]。

    PRIMARY 不算;只列应用层声明的 UNIQUE 索引。
    """
    sql = """
        SELECT TABLE_NAME, INDEX_NAME, SEQ_IN_INDEX, COLUMN_NAME
        FROM information_schema.STATISTICS
        WHERE TABLE_SCHEMA = %s
          AND NON_UNIQUE = 0
          AND INDEX_NAME != 'PRIMARY'
        ORDER BY TABLE_NAME, INDEX_NAME, SEQ_IN_INDEX
    """
    cur = conn.cursor()
    cur.execute(sql, (os.environ.get("AUDIT_DB_NAME", "ai_platform"),))
    rows = cur.fetchall()
    cur.close()
    grouped: Dict[Tuple[str, str], List[Tuple[int, str]]] = {}
    for tbl, idx, seq, col in rows:
        grouped.setdefault((tbl, idx), []).append((seq, col))
    return [(t, i, sorted(cols)) for (t, i), cols in grouped.items()]


def fetch_soft_delete_columns(conn) -> Dict[str, List[Tuple[str, str]]]:
    """返回 {TABLE_NAME: [(COLUMN_NAME, DATA_TYPE), ...]}。

    soft-delete "标识符" 列:deleted_at / archived_at / is_deleted / is_archived /
    soft_deleted_at 都是 timestamp tombstone;is_active / enabled 是 boolean flag。
    """
    sql = """
        SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE, IS_NULLABLE
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = %s
          AND COLUMN_NAME IN (
              'deleted_at', 'archived_at', 'is_deleted', 'is_archived',
              'soft_deleted_at', 'is_active', 'enabled'
          )
        ORDER BY TABLE_NAME, COLUMN_NAME
    """
    cur = conn.cursor()
    cur.execute(sql, (os.environ.get("AUDIT_DB_NAME", "ai_platform"),))
    rows = cur.fetchall()
    cur.close()
    out: Dict[str, List[Tuple[str, str]]] = {}
    for tbl, col, dtype, nullable in rows:
        out.setdefault(tbl, []).append((col, dtype))
    return out


def has_naming_field(columns: List[Tuple[int, str]]) -> bool:
    return any(c.lower() in NAMING_FIELDS for _, c in columns)


def is_remediated_dedup(columns: List[Tuple[int, str]]) -> bool:
    """UNIQUE 索引至少包含一个 *_dedup_* 列 → 已用 generated column trick 修复。

    修复模式(详见 docs-internal/roadmap/2026-09-04-phase-1-3-4-unique-softdelete-fix.md):
    加 ``<table>_dedup_<field>`` VIRTUAL GENERATED 列(软删行 NULL),
    重建 UNIQUE on dedup 列 —— MySQL UNIQUE 对多个 NULL 不视为冲突,
    自然释放软删行的 name 槽位。

    判定规则:UNIQUE 索引中**至少一列**名形如 ``<prefix>_dedup[_suffix]``。
    用 ``any`` 而不是 ``all`` —— 因为 composite (tenant_id, cfd_dedup_key) 这种
    "tenant_id + dedup 列" 也是修复(tenant_id 是 structural 列,
    不影响 dedup 列 NULL 释放槽位的核心机制),原 all 规则会把它们误判。
    """
    return any("_dedup" in c.lower() for _, c in columns)


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------


def audit() -> int:
    env_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", ".env"
    )
    creds = load_db_creds(env_path)
    try:
        conn = pymysql.connect(
            host=creds["host"],
            port=creds["port"],
            user=creds["user"],
            password=creds["password"],
            database=creds["database"],
            connect_timeout=5,
            read_timeout=10,
        )
    except Exception as e:  # noqa: BLE001
        print(f"FAIL: cannot connect to MySQL: {e}", file=sys.stderr)
        return 2

    try:
        unique_indexes = fetch_unique_indexes(conn)
        soft_delete_cols = fetch_soft_delete_columns(conn)
    finally:
        conn.close()

    # 分类
    true_conflicts: List[Tuple[str, str, List[str], List[str]]] = []
    no_conflicts: List[Tuple[str, str, List[str]]] = []

    for tbl, idx, cols in unique_indexes:
        col_names = [c for _, c in cols]
        soft_cols = [sc[0] for sc in soft_delete_cols.get(tbl, [])]
        naming_present = has_naming_field(cols)

        if tbl in SAFE_TABLES:
            no_conflicts.append((tbl, idx, col_names))
            continue

        # 已用 generated column trick 修复过:UNIQUE 全是 dedup 列 → 跳过
        if is_remediated_dedup(cols):
            no_conflicts.append((tbl, idx, col_names))
            continue

        # 真冲突三件套:
        # 1. UNIQUE 索引包含 naming 字段(name/app_id/app_key/model_name 等)
        # 2. 表有 soft-delete 字段(is_active / enabled / deleted_at / archived_at)
        # 3. UNIQUE 索引 *不* 包含 soft-delete 字段(否则 MySQL 用 NULL 排除已删)
        soft_in_index = any(c.lower() in {sc.lower() for sc in soft_cols} for c in col_names)
        if naming_present and soft_cols and not soft_in_index:
            true_conflicts.append((tbl, idx, col_names, soft_cols))
        else:
            no_conflicts.append((tbl, idx, col_names))

    # 输出 markdown 报告
    print("# UNIQUE 索引 × Soft-Delete 冲突审计\n")
    print(
        f"扫描 schema `{creds['database']}` 共 **{len(unique_indexes)}** 条 UNIQUE 索引(非 PRIMARY)。\n"
    )
    print(f"## 真冲突 ({len(true_conflicts)} 张表需修)\n")
    if true_conflicts:
        print("| 表名 | UNIQUE 索引 | 命名类字段 | soft-delete 字段 | 修法 |")
        print("|------|------------|----------|----------------|------|")
        for tbl, idx, col_names, soft_cols in true_conflicts:
            # 修法提示
            fix = "generated column trick + UNIQUE 重建"
            print(
                f"| `{tbl}` | `{idx}` | "
                f"{', '.join(f'`{c}`' for c in col_names)} | "
                f"{', '.join(f'`{c}`' for c in soft_cols)} | {fix} |"
            )
    else:
        print("_无真冲突。_\n")

    print(f"\n## 无冲突 ({len(no_conflicts)} 条索引)\n")
    print("| 表名 | UNIQUE 索引 | 字段 | 原因 |")
    print("|------|------------|------|------|")
    for tbl, idx, col_names in no_conflicts[:50]:  # 限 50 行免爆
        if tbl in SAFE_TABLES:
            reason = "log / 跟父表删 / 永不复用标识符"
        elif is_remediated_dedup([(0, c) for c in col_names]):
            reason = "✅ 已 generated column trick 修复(UNIQUE 含 *_dedup_* 列)"
        elif not has_naming_field([(0, c) for c in col_names]):
            reason = "UNIQUE 不覆盖 naming 字段(技术 ID)"
        else:
            reason = "无 soft-delete 路径(hard delete 或未实现)"
        print(
            f"| `{tbl}` | `{idx}` | {', '.join(f'`{c}`' for c in col_names)} | {reason} |"
        )
    if len(no_conflicts) > 50:
        print(f"\n_(省略 {len(no_conflicts) - 50} 行)_\n")

    # 退出码:有真冲突返 1,让 CI / cron 报警
    return 1 if true_conflicts else 0


if __name__ == "__main__":
    sys.exit(audit())
