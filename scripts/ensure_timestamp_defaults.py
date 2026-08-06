"""一次性 dev DB migration — 给所有 timestamp 列加 DEFAULT CURRENT_TIMESTAMP。

背景:54 张表的 108 个 created_at/updated_at 列 IS_NULLABLE=YES 且无 DEFAULT,
导致 ORM INSERT 时 server_default 不触发,行存 NULL → Pydantic schema 校验失败。
M37 新表(eval_datasets / eval_runs / eval_dataset_items / eval_run_results)的
DEFAULT 已经在 create_all 时通过 `server_default=func.now()` 生成正确。
旧表在 BaseModel 引入 server_default 之前已经存在,没赶上。

本脚本把所有 timestamp 列 ALTER 到 NOT NULL DEFAULT CURRENT_TIMESTAMP (ON UPDATE CURRENT_TIMESTAMP)。
仅在 dev DB 执行(localhost:3307),不进生产路径。

注意:
- 涉及 NOT NULL 的列先 UPDATE ... SET col = COALESCE(col, NOW()) 把 NULL 行回填,
  再 ALTER,避免 NOT NULL 触发表级失败。
- 修改 108 列,每个 ALTER 会锁表几秒,总时长 ~1-2 分钟。
- 可重复执行(幂等):已带 DEFAULT 的列跳过,NULL 已被回填的列 UPDATE 影响 0 行。

用法:
    python scripts/ensure_timestamp_defaults.py            # 真跑
    python scripts/ensure_timestamp_defaults.py --dry-run  # 只列计划
"""
from __future__ import annotations

import argparse
import sys
from typing import Iterable

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


def discover_columns(cur) -> list[tuple[str, str, str]]:
    """发现所有 timestamp 列当前缺 DEFAULT 的 (table, column, type) 三元组。

    type 用于 ALTER MODIFY 时写回原类型(不能丢精度)。
    """
    cur.execute(
        """
        SELECT TABLE_NAME, COLUMN_NAME, COLUMN_TYPE, EXTRA
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND COLUMN_NAME IN ('created_at', 'updated_at')
          AND COLUMN_DEFAULT IS NULL
          AND DATA_TYPE IN ('datetime', 'timestamp')
        ORDER BY TABLE_NAME, COLUMN_NAME
        """,
    )
    return [(r[0], r[1], r[2]) for r in cur.fetchall()]


def backfill_null(cur, tables: Iterable[str]) -> dict[str, tuple[int, int]]:
    """回填 NULL 行 created_at/updated_at 为 NOW()。返 {table: (created_n, updated_n)}。"""
    result: dict[str, tuple[int, int]] = {}
    distinct_tables = sorted(set(tables))
    for t in distinct_tables:
        n_created = 0
        n_updated = 0
        cur.execute(f"SHOW COLUMNS FROM `{t}` LIKE 'created_at'")
        if cur.fetchone() is not None:
            cur.execute(
                f"UPDATE `{t}` SET created_at = NOW() WHERE created_at IS NULL"
            )
            n_created = cur.rowcount
        cur.execute(f"SHOW COLUMNS FROM `{t}` LIKE 'updated_at'")
        if cur.fetchone() is not None:
            cur.execute(
                f"UPDATE `{t}` SET updated_at = NOW() WHERE updated_at IS NULL"
            )
            n_updated = cur.rowcount
        if n_created or n_updated:
            result[t] = (n_created, n_updated)
    return result


def add_defaults(
    cur, columns: list[tuple[str, str, str]], dry_run: bool = False
) -> list[tuple[str, str, str]]:
    """逐列 ALTER 加 DEFAULT。返真正被 ALTER 的列。"""
    altered: list[tuple[str, str, str]] = []
    for table, column, col_type in columns:
        if column == "created_at":
            ddl = (
                f"ALTER TABLE `{table}` MODIFY `{column}` {col_type} "
                f"NOT NULL DEFAULT CURRENT_TIMESTAMP"
            )
        else:  # updated_at
            ddl = (
                f"ALTER TABLE `{table}` MODIFY `{column}` {col_type} "
                f"NOT NULL DEFAULT CURRENT_TIMESTAMP "
                f"ON UPDATE CURRENT_TIMESTAMP"
            )
        if dry_run:
            print(f"  [DRY] {ddl}")
            altered.append((table, column, col_type))
            continue
        cur.execute(ddl)
        altered.append((table, column, col_type))
    return altered


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只打印 SQL,不实际执行",
    )
    args = parser.parse_args()

    conn = pymysql.connect(**CONN_KW)
    cur = conn.cursor()

    columns = discover_columns(cur)
    print(f"== ensure_timestamp_defaults == ")
    print(f"缺 DEFAULT 的 timestamp 列: {len(columns)} 个")
    if not columns:
        print("[OK] 已经是最新状态,无需 ALTER")
        cur.close()
        conn.close()
        return 0

    tables = {t for t, _, _ in columns}
    print(f"涉及 {len(tables)} 张表")

    # Step 1: 回填 NULL 行 (避免后续 NOT NULL 失败)
    print("\n[1/2] 回填 NULL 行 ...")
    backfill = backfill_null(cur, tables)
    conn.commit()
    if backfill:
        for t in sorted(backfill):
            n_c, n_u = backfill[t]
            print(f"  {t}: created_at={n_c} updated_at={n_u}")
    else:
        print("  没有 NULL 行,跳过")

    # Step 2: ALTER 加 DEFAULT (NOT NULL 是隐含收紧,前面已回填所以安全)
    print(f"\n[2/2] ALTER {len(columns)} 列加 DEFAULT ...")
    altered = add_defaults(cur, columns, dry_run=args.dry_run)
    conn.commit()

    if not args.dry_run:
        print(f"  完成 {len(altered)} 列")

    cur.close()
    conn.close()
    print("\n[OK] done")
    return 0


if __name__ == "__main__":
    sys.exit(main())