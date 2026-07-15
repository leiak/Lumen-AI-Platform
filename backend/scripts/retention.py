"""M27 retention CLI — manual soft/hard delete of old log rows.

Usage:
    cd backend

    # Dry-run: how many rows would be affected at default 90/180 day cutoffs?
    python scripts/retention.py --dry-run

    # Override cutoffs (e.g. for dev cleanup — 30/60 days)
    python scripts/retention.py --dry-run --days-soft 30 --days-hard 60

    # Actually run the sweep
    python scripts/retention.py --confirm

    # Confirm with non-default cutoffs + batch size
    python scripts/retention.py --confirm --days-soft 7 --days-hard 14 --batch-size 500

Notes:
- The script does NOT refuse non-localhost (unlike
  ``dev_cleanup_llm_call_logs.py``) — production deployments may want
  to invoke this manually for ad-hoc cleanup. Production deployments
  should rely on the APScheduler cron registered by
  ``register_retention_jobs`` for the automatic daily sweep.
- ``--dry-run`` prints counts only. Without ``--dry-run`` you must pass
  ``--confirm`` to actually mutate; bare invocation prints help and exits.

Spec: docs/superpowers/specs/2026-06-15-embedding-trace-retention.md §"CLI"
"""
from __future__ import annotations

import argparse
import json
import sys

from lumen_services.retention import (
    DEFAULT_BATCH_SIZE,
    DEFAULT_DAYS_HARD,
    DEFAULT_DAYS_SOFT,
    archive_old_logs,
    dry_run_count,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="M27 retention CLI: soft + hard delete of old log rows.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print counts only (no DB mutation).",
    )
    parser.add_argument(
        "--confirm", action="store_true",
        help="Actually run the sweep. Required for any DB mutation.",
    )
    parser.add_argument(
        "--days-soft", type=int, default=DEFAULT_DAYS_SOFT,
        help=f"Rows older than this # days are soft-deleted (default {DEFAULT_DAYS_SOFT}).",
    )
    parser.add_argument(
        "--days-hard", type=int, default=DEFAULT_DAYS_HARD,
        help=f"Rows older than this # days are hard-deleted (default {DEFAULT_DAYS_HARD}).",
    )
    parser.add_argument(
        "--batch-size", type=int, default=DEFAULT_BATCH_SIZE,
        help=f"Rows per batch (default {DEFAULT_BATCH_SIZE}).",
    )
    args = parser.parse_args()

    if not args.dry_run and not args.confirm:
        parser.print_help()
        print("\nERROR: pass --dry-run or --confirm to do anything.")
        return 1

    if args.days_hard <= args.days_soft:
        print(
            f"ERROR: --days-hard ({args.days_hard}) must be > "
            f"--days-soft ({args.days_soft})"
        )
        return 1

    if args.dry_run:
        counts = dry_run_count(
            days_soft=args.days_soft,
            days_hard=args.days_hard,
        )
        print(json.dumps(counts, indent=2))
        return 0

    print(
        f"Running retention sweep: soft={args.days_soft}d, "
        f"hard={args.days_hard}d, batch_size={args.batch_size}"
    )
    result = archive_old_logs(
        days_soft=args.days_soft,
        days_hard=args.days_hard,
        batch_size=args.batch_size,
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
