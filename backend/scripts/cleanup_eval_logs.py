"""M37.2 — dev DB 评测 trace 清理脚本。

跑评测会同时往 ``llm_call_logs`` (call_type='eval_judge') 和
``embedding_call_logs`` (call_type='eval_retrieval') 写大量 trace 行;
跑 10 次 30-item builtin → 600+ 行,跑 1 个月就是几万行 trace 占用 dev DB。
本脚本按 ``call_type IN ('eval_retrieval', 'eval_judge')`` + ``created_at``
窗口条件删除 —— **不影响非评测 trace**。

Usage:

    # 1. 试运行,看要删多少行(默认 7 天前)
    cd backend && python -m scripts.cleanup_eval_logs --dry-run

    # 2. 实际删 7 天前的评测 trace
    python -m scripts.cleanup_eval_logs

    # 3. 立即删(0 天前) + 不询问
    python -m scripts.cleanup_eval_logs --days 0 --yes

    # 4. 自定义保留窗口
    python -m scripts.cleanup_eval_logs --days 30

设计要点(plan §D7 + Risks "dev DB 评测 trace 污染" mitigation):

- **必须有 --dry-run 保护**:默认走 mode 是交互,直接给"预计删除 N 行"
  让用户确认。这个脚本会读 ``backend/.env`` 的 ``DATABASE_URL`` 解析
  连 MySQL,跟其他 service 一致(env 拿不到 → 退化到 ``localhost:3307``)。
- **限 call_type**:SQL WHERE 强制 ``call_type IN (...)``,即便输错天数
  也不会误删 chat / agent_team / workflow / image_generation 的 trace。
- **支持只清理某类**:``--only llm`` / ``--only embedding`` 给只想清一半的人。
- **幂等**:重复跑同窗口是一样的 SELECT + DELETE,DELETE 0 行不算错。

Spec: docs-internal/superpowers/specs/m37-rag-evaluation.md §4.2
Plan: docs-internal/superpowers/plans/m37-plan.md CP5 T17
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import Iterable, List, Tuple

# Windows GBK 环境(stdout 默认 cp936)打 emoji 会炸。
# 切到 utf-8;失败时(e.g. Windows 7 旧 cmd)就回退到默认值。
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
except Exception:  # noqa: BLE001
    pass

# 把 backend 根加进 sys.path,跟 run_rag_eval.py / run_mcp_server.py 同款
_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

logger = logging.getLogger("cleanup_eval_logs")
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


# 配置:跟 LLMCallLog.call_type / EmbeddingCallLog.call_type 字面值一致
EVAL_LLM_CALL_TYPES = ("eval_judge",)
EVAL_EMBED_CALL_TYPES = ("eval_retrieval",)


# ---------------------------------------------------------------------------
# args
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="M37.2 — dev DB 评测 trace 清理(eval_judge / eval_retrieval)"
    )
    p.add_argument(
        "--days", type=int, default=7,
        help="保留窗口(天);<= created_at.AGE 之前的会被删。默认 7,允许 0 表示立即删",
    )
    p.add_argument(
        "--dry-run", action="store_true", default=False,
        help="只统计 + 打印预删行数,不实际 DELETE",
    )
    p.add_argument(
        "--yes", action="store_true", default=False,
        help="跳过交互式确认(自动化 / CI 场景)",
    )
    p.add_argument(
        "--only", choices=("llm", "embedding", "both"), default="both",
        help="只清 llm 或 embedding 或两者;默认 both",
    )
    return p.parse_args()


# ---------------------------------------------------------------------------
# DB connect
# ---------------------------------------------------------------------------


def _connect():
    """试 pymysql 直连 dev DB;凭据从 backend/.env 解析。

    修法参照 MEMORY.md "MCP 禁 DDL" 段:docker MySQL 在 localhost:3307,root/rootpassword。
    """
    try:
        import pymysql  # type: ignore[import-untyped]
    except ImportError as exc:
        raise SystemExit(
            "pymysql 不可用,装上跑:pip install pymysql"
        ) from exc

    # 1. 先看 backend/.env 的 DATABASE_URL
    host = port = user = password = database = None
    env_path = Path(_HERE) / ".env"
    if env_path.exists():
        try:
            for line in env_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key == "DATABASE_URL":
                    # 解析 mysql+pymysql://user:pass@host:port/db
                    try:
                        from urllib.parse import urlparse
                        u = urlparse(value)
                        host = u.hostname or host
                        port = u.port or port
                        user = u.username or user
                        password = u.password or password
                        database = (u.path or "").lstrip("/") or database
                    except Exception:  # noqa: BLE001
                        logger.warning("failed to parse DATABASE_URL in .env")
        except Exception as exc:  # noqa: BLE001
            logger.warning("read .env failed: %s", exc)
    # 2. fallback dev DB 默认
    host = host or "localhost"
    port = port or 3307
    user = user or "root"
    password = password or "rootpassword"
    database = database or "ai_platform"

    return pymysql.connect(
        host=host, port=port, user=user, password=password,
        database=database, connect_timeout=5,
    )


# ---------------------------------------------------------------------------
# core
# ---------------------------------------------------------------------------


def _count_and_delete(
    conn,
    table: str,
    call_types: Tuple[str, ...],
    days: int,
    *,
    dry_run: bool,
) -> int:
    """SELECT COUNT + (可选)DELETE。返回影响行数。"""
    placeholders = ",".join(["%s"] * len(call_types))
    sql_count = (
        f"SELECT COUNT(*) FROM {table} "
        f"WHERE call_type IN ({placeholders}) "
        f"AND created_at < NOW() - INTERVAL %s DAY"
    )
    with conn.cursor() as cur:
        cur.execute(sql_count, (*call_types, days))
        n = int(cur.fetchone()[0])
        if dry_run or n == 0:
            return n
        sql_delete = (
            f"DELETE FROM {table} "
            f"WHERE call_type IN ({placeholders}) "
            f"AND created_at < NOW() - INTERVAL %s DAY"
        )
        cur.execute(sql_delete, (*call_types, days))
        conn.commit()
        return n


def _format_summary(rows: List[Tuple[str, int, int]]) -> str:
    """漂亮打印 (table, dry_run_count, deleted_count) 列表。"""
    lines = ["Cleanup summary:"]
    lines.append(f"  {'table':<24} {'will_delete':>12} {'status':<10}")
    for table, n, deleted in rows:
        status = "DRY-RUN" if deleted == 0 and n > 0 else ("deleted" if deleted == n else "noop")
        lines.append(f"  {table:<24} {n:>12} {status:<10}")
    total = sum(n for _, n, _ in rows)
    lines.append(f"  {'TOTAL':<24} {total:>12}")
    return "\n".join(lines)


def _confirm(prompt: str) -> bool:
    """交互式 y/N 询问(sys.stdin 不可用时返 True,让 CI 不卡)。"""
    try:
        sys.stdout.write(prompt)
        sys.stdout.flush()
    except Exception:  # noqa: BLE001
        return True
    try:
        answer = input().strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    return answer in ("y", "yes")


def main() -> int:
    args = parse_args()
    if args.days < 0:
        print("❌ --days 必须 >= 0", file=sys.stderr)
        return 1

    print(
        f"🧹 cleanup_eval_logs: days={args.days}, dry_run={args.dry_run}, "
        f"only={args.only}"
    )

    # 1. 选要清哪些表
    targets: List[Tuple[str, Tuple[str, ...]]] = []
    if args.only in ("llm", "both"):
        targets.append(("llm_call_logs", EVAL_LLM_CALL_TYPES))
    if args.only in ("embedding", "both"):
        targets.append(("embedding_call_logs", EVAL_EMBED_CALL_TYPES))

    # 2. 连 + 统计
    try:
        conn = _connect()
    except Exception as exc:  # noqa: BLE001
        print(f"❌ DB connect failed: {exc}", file=sys.stderr)
        return 1
    try:
        rows: List[Tuple[str, int, int]] = []
        for table, call_types in targets:
            n = _count_and_delete(
                conn, table, call_types, args.days,
                dry_run=True,  # 第一轮只 count
            )
            rows.append((table, n, 0))
        # 3. 打印 + 询问
        print(_format_summary(rows))
        total = sum(n for _, n, _ in rows)
        if total == 0:
            print("✅ nothing to delete, dev DB 干净 / nothing to do")
            return 0
        if args.dry_run:
            print(
                f"ℹ️  dry-run mode,实际未删。去掉 --dry-run 真正 DELETE。"
            )
            return 0
        if not args.yes and not _confirm(
            f"⚠️  确认删除 {total} 行 dev DB 评测 trace? [y/N] "
        ):
            print("❌ cancelled by user")
            return 1
        # 4. 真 DELETE
        rows2: List[Tuple[str, int, int]] = []
        for table, call_types in targets:
            n = _count_and_delete(
                conn, table, call_types, args.days,
                dry_run=False,
            )
            rows2.append((table, n, n))
        print(_format_summary(rows2))
        print(f"✅ 删除 {total} 行 dev DB 评测 trace")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
