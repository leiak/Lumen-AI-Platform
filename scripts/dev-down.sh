#!/usr/bin/env bash
# scripts/dev-down.sh — graceful shutdown for the Lumen AI Platform dev stack
#
# Stops the docker containers spun up by dev-up.sh. By default it stops
# everything (mysql / redis / ollama / elasticsearch / celery) so the
# machine can idle quietly. Pass --keep-base to leave the four base
# containers running and only stop the celery worker — useful when you
# just want to free CPU/memory from the idle worker without paying the
# 30s startup cost for ES / Ollama next time.
#
# Like dev-up.sh, this does NOT touch host processes (uvicorn on 11335,
# next dev on 11334). Stop those manually if you need to.
#
# Usage:
#   bash scripts/dev-down.sh             # stop everything
#   bash scripts/dev-down.sh --keep-base # stop only celery
#
# Exit codes:
#   0 — all targeted containers stopped (or were already stopped)
#   1 — preflight failed (docker missing / daemon down)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# ---------------------------------------------------------------------------
# Flags
# ---------------------------------------------------------------------------
KEEP_BASE=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --keep-base)
      KEEP_BASE=1
      shift
      ;;
    -h|--help)
      sed -n '2,18p' "$0"
      exit 0
      ;;
    *)
      echo "Unknown flag: $1 (try --help)" >&2
      exit 1
      ;;
  esac
done

# ---------------------------------------------------------------------------
# Preflight (mirrors dev-up.sh)
# ---------------------------------------------------------------------------
if ! command -v docker >/dev/null 2>&1; then
  case "$(uname -s)" in
    MINGW*|MSYS*|CYGWIN*)
      DOCKER_BIN="/c/Program Files/Docker/Docker/resources/bin"
      if [ -d "$DOCKER_BIN" ]; then
        export PATH="$DOCKER_BIN:$PATH"
      fi
      ;;
  esac
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "ERROR: docker CLI not found." >&2
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  echo "ERROR: docker daemon not running." >&2
  exit 1
fi

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
CELERY_CONTAINER="lumen-platform-celery"
BASE_CONTAINERS=(lumen-platform-mysql lumen-platform-redis lumen-platform-ollama lumen-platform-es)

ok()   { printf '  \033[32m✓\033[0m %s\n' "$1"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$1"; }
skip() { printf '  \033[36m-\033[0m %s\n' "$1"; }
step() { printf '\n\033[1m▶ %s\033[0m\n' "$1"; }

# stop_if_running <container>
# Uses `docker stop` (SIGTERM + 10s grace) so any in-flight Celery task has
# a chance to mark its document row as completed/failed instead of leaving
# it stuck in `processing`. Idempotent: already-stopped containers are
# silently skipped via state inspection.
stop_if_running() {
  local container="$1"
  local status
  status="$(docker inspect -f '{{.State.Status}}' "$container" 2>/dev/null || echo 'missing')"

  case "$status" in
    running)
      warn "stopping $container (was running)..."
      docker stop "$container" >/dev/null
      ok "$container stopped"
      ;;
    restarting|paused)
      warn "stopping $container (was $status)..."
      docker stop "$container" >/dev/null
      ok "$container stopped"
      ;;
    exited|created|dead)
      skip "$container already stopped"
      ;;
    missing)
      skip "$container not present"
      ;;
    *)
      warn "$container: unknown state '$status' — leaving alone"
      ;;
  esac
}

# ---------------------------------------------------------------------------
# Step 1: stop celery worker first
# Reason: celery holds in-flight tasks. If we stopped mysql/redis first,
# any task currently running would crash mid-processing and leave its
# document row stuck in `processing` forever (the same bug that bit us on
# 2026-06-16 when celery died on Redis connection loss). Stopping celery
# first means any active task gets SIGTERM during its graceful shutdown
# and the worker can mark the document failed/completed in MySQL before
# the dependency services go away.
# ---------------------------------------------------------------------------
step "Step 1/2 — celery worker (always)"
stop_if_running "$CELERY_CONTAINER"

# ---------------------------------------------------------------------------
# Step 2: base containers (unless --keep-base)
# ---------------------------------------------------------------------------
if [ "$KEEP_BASE" -eq 1 ]; then
  step "Step 2/2 — base containers (--keep-base, skipping)"
  echo "  mysql / redis / ollama / elasticsearch left running."
  echo "  next bash scripts/dev-up.sh will only restart celery (instant)."
else
  step "Step 2/2 — base containers (mysql / redis / ollama / elasticsearch)"
  for container in "${BASE_CONTAINERS[@]}"; do
    stop_if_running "$container"
  done
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo
echo "=== remaining lumen-platform-* containers ==="
docker ps --filter "name=lumen-platform-" \
  --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}' || true

cat <<'EOF'

✓ dev stack down.

To bring it back:
  bash scripts/dev-up.sh

NOTE: this script does NOT touch host uvicorn (11335) or frontend next dev
(11334). Stop those manually if needed:
  - uvicorn: find PID via `netstat -ano | grep :11335` then `Stop-Process`
  - next dev: Ctrl+C in its terminal, or find PID via :11334
EOF