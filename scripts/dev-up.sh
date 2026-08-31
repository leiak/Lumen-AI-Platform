#!/usr/bin/env bash
# scripts/dev-up.sh — idempotent one-shot recovery for the Lumen AI Platform dev stack
#
# Background: the dev stack is split between docker (mysql / redis / ollama /
# elasticsearch / celery) and host processes (uvicorn :11335, next dev :11334).
# On Windows + Git Bash these containers are typically created by manual
# `docker run` commands (or by an older `docker compose up -d` before the celery
# service was wired in), so a fresh reboot that takes down Docker Desktop
# leaves everything in `Exited` state without an obvious way back.
#
# This script is idempotent. Run it after a Docker Desktop restart / machine
# reboot and it brings the full docker side back. It does NOT start the host
# uvicorn (11335) or frontend next dev (11334) — those are usually running
# already and have their own restart story (Task Scheduler / pm2).
#
# Usage:
#   bash scripts/dev-up.sh
#
# Exit codes:
#   0 — all services running and reachable
#   1 — preflight failed (docker missing / daemon down / base container missing)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BACKEND_DIR="$REPO_ROOT/backend"

# ---------------------------------------------------------------------------
# Preflight: PATH fix for Windows + Git Bash where docker CLI is installed
# under "C:\Program Files\Docker\Docker\resources\bin" but not on PATH by
# default. Without this `docker` returns command-not-found in fresh shells.
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
  echo "ERROR: docker CLI not found. Install Docker Desktop:" >&2
  echo "  https://www.docker.com/products/docker-desktop/" >&2
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  echo "ERROR: docker daemon not running. Start Docker Desktop and retry." >&2
  exit 1
fi

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
NETWORK_NAME="backend_default"  # docker compose's default network for this project
CELERY_CONTAINER="lumen-platform-celery"
CELERY_IMAGE="backend-celery_worker"

# Container spec: <container-name>|<image>|<alias-on-network>
# The image+alias triple matches backend/docker-compose.yml so the celery
# container can resolve "redis", "ollama", "elasticsearch", "mysql" via DNS.
# NOTE: separator is `|` (not `:`) because image refs contain `:` (port tag).
BASE_SERVICES=(
  "lumen-platform-mysql|docker.m.daocloud.io/mysql:8.0|mysql"
  "lumen-platform-redis|docker.m.daocloud.io/redis:7-alpine|redis"
  "lumen-platform-ollama|docker.m.daocloud.io/ollama/ollama:latest|ollama"
  "lumen-platform-es|docker.elastic.co/elasticsearch/elasticsearch:8.12.0|elasticsearch"
  "lumen-platform-minio|docker.m.daocloud.io/minio/minio:latest|minio"
)

ok()   { printf '  \033[32m✓\033[0m %s\n' "$1"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$1"; }
fail() { printf '  \033[31m✗\033[0m %s\n' "$1"; }
step() { printf '\n\033[1m▶ %s\033[0m\n' "$1"; }

# extract_cluster_status
# Reads JSON from stdin and prints the value of the first top-level
# `"status":"<value>"` field. Used by step 6 and the quick health check
# to parse ES's /_cluster/health response. The sed is portable across
# Git Bash on Windows (grep -oE | grep -oE breaks on multi-word matches).
extract_cluster_status() {
  sed -n 's/.*"status":"\([a-z]*\)".*/\1/p'
}

# ---------------------------------------------------------------------------
# Helper: is <container> currently attached to <network>?
# Uses `docker network inspect` JSON output to avoid shell pipe portability
# issues (Git Bash on Windows sometimes loses /usr/bin utilities like head/tail).
# ---------------------------------------------------------------------------
is_in_network() {
  local container="$1"
  local network="$2"
  # `docker network inspect` .Containers is keyed by container ID, so we read
  # $cfg.Name (the container name) to compare against $container.
  docker network inspect "$network" \
    --format '{{range $id, $cfg := .Containers}}{{$cfg.Name}} {{end}}' 2>/dev/null \
    | tr ' ' '\n' \
    | grep -Fqx "$container"
}

# ---------------------------------------------------------------------------
# Step 1: ensure each base container exists and is running.
# If a container is missing entirely (first-time setup), print the exact
# `docker run` command from docker-compose.yml and bail out — we don't auto
# create it because the original `docker run` flags (volumes, network mode,
# extra env) may differ from what the compose spec implies.
# ---------------------------------------------------------------------------
step "Step 1/5 — base containers (mysql / redis / ollama / elasticsearch / minio)"

missing_base=0
for spec in "${BASE_SERVICES[@]}"; do
  IFS='|' read -r name image alias <<<"$spec"
  status="$(docker inspect -f '{{.State.Status}}' "$name" 2>/dev/null || echo 'missing')"

  case "$status" in
    running)
      ok "$name (running)"
      ;;
    exited|created|dead|paused|restarting)
      warn "$name was $status, restarting..."
      docker start "$name" >/dev/null
      ok "$name (restarted)"
      ;;
    missing)
      fail "$name missing — first-time setup required:"
      case "$name" in
        lumen-platform-mysql)
          echo "      docker run -d --name lumen-platform-mysql -p 3307:3306 \\"
          echo "        -e MYSQL_ROOT_PASSWORD=rootpassword \\"
          echo "        -e MYSQL_DATABASE=ai_platform \\"
          echo "        -e MYSQL_USER=ai_user -e MYSQL_PASSWORD=ai_password \\"
          echo "        -v mysql_data:/var/lib/mysql \\"
          echo "        $image"
          ;;
        lumen-platform-redis)
          echo "      docker run -d --name lumen-platform-redis -p 6379:6379 \\"
          echo "        -v redis_data:/data $image"
          ;;
        lumen-platform-ollama)
          echo "      docker run -d --name lumen-platform-ollama -p 11434:11434 \\"
          echo "        -v ollama_data:/root/.ollama $image"
          ;;
        lumen-platform-es)
          echo "      docker run -d --name lumen-platform-es -p 9200:9200 -p 9300:9300 \\"
          echo "        -e discovery.type=single-node -e xpack.security.enabled=false \\"
          echo "        -e 'ES_JAVA_OPTS=-Xms1g -Xmx1g' \\"
          echo "        -v es_data:/usr/share/elasticsearch/data \\"
          echo "        $image"
          ;;
        lumen-platform-minio)
          # 端口 19000/19001 已被同机 IntelliEngine-minio 占用,避开 → 29000/29001
          echo "      docker run -d --name lumen-platform-minio -p 29000:9000 -p 29001:9001 \\"
          echo "        -e MINIO_ROOT_USER=minioadmin \\"
          echo "        -e MINIO_ROOT_PASSWORD=minioadmin \\"
          echo "        -v minio_data:/data \\"
          echo "        $image server /data --console-address ':29001'"
          ;;
      esac
      missing_base=1
      ;;
    *)
      fail "$name: unknown state '$status'"
      missing_base=1
      ;;
  esac
done

if [ "$missing_base" -ne 0 ]; then
  echo
  echo "ERROR: missing base containers. Run the docker run commands above," >&2
  echo "       then re-run this script." >&2
  exit 1
fi

# ---------------------------------------------------------------------------
# Step 2: ensure the docker-compose network exists.
# `docker compose up --no-deps` creates the network on demand, but only after
# the compose file has been touched. Creating it explicitly here means the
# attach step (next) can run even on a fresh checkout that hasn't run compose.
# ---------------------------------------------------------------------------
step "Step 2/5 — network $NETWORK_NAME"
if docker network inspect "$NETWORK_NAME" >/dev/null 2>&1; then
  ok "$NETWORK_NAME exists"
else
  warn "$NETWORK_NAME missing, creating..."
  docker network create "$NETWORK_NAME" >/dev/null
  ok "$NETWORK_NAME created"
fi

# ---------------------------------------------------------------------------
# Step 3: attach each base container to the network with its service alias.
# Without the alias, the celery container (inside $NETWORK_NAME) can't resolve
# "redis:6379" / "ollama:11434" / "elasticsearch:9200" / "mysql:3306" via DNS,
# which is what backend/.env.docker expects.
# ---------------------------------------------------------------------------
step "Step 3/5 — attach base containers to $NETWORK_NAME"
for spec in "${BASE_SERVICES[@]}"; do
  IFS='|' read -r name image alias <<<"$spec"
  if is_in_network "$name" "$NETWORK_NAME"; then
    ok "$name already attached"
  else
    warn "attaching $name (alias=$alias)..."
    docker network connect --alias "$alias" "$NETWORK_NAME" "$name"
    ok "$name attached"
  fi
done

# ---------------------------------------------------------------------------
# Step 4: build & start the celery worker container.
# Uses `docker compose up -d --no-deps` so we don't fight with the existing
# base containers for the same container names. If the image hasn't been
# built yet (fresh checkout) we trigger a build first — that takes ~20 min
# the first time because the Dockerfile installs 127 transitive deps.
# ---------------------------------------------------------------------------
step "Step 4/5 — celery worker ($CELERY_CONTAINER)"
cd "$BACKEND_DIR"

if ! docker image inspect "$CELERY_IMAGE" >/dev/null 2>&1; then
  warn "$CELERY_IMAGE image not built — first build takes ~20 minutes..."
  docker compose build celery_worker
  ok "$CELERY_IMAGE built"
else
  ok "$CELERY_IMAGE image present"
fi

celery_status="$(docker inspect -f '{{.State.Status}}' "$CELERY_CONTAINER" 2>/dev/null || echo 'missing')"
case "$celery_status" in
  running)
    ok "$CELERY_CONTAINER (running)"
    ;;
  exited|created|dead|paused|restarting)
    warn "$CELERY_CONTAINER was $celery_status, restarting..."
    docker start "$CELERY_CONTAINER" >/dev/null
    ok "$CELERY_CONTAINER (restarted)"
    ;;
  missing)
    warn "creating $CELERY_CONTAINER via compose..."
    docker compose up -d --no-deps celery_worker
    ok "$CELERY_CONTAINER (created)"
    ;;
esac

# ---------------------------------------------------------------------------
# Step 5: wait for celery worker to reach "ready" (i.e. connected to redis).
# On first start after a long downtime the DNS resolution inside the celery
# container can take 20-30s as it retries "redis:6379" against the network
# alias attached in step 3.
# ---------------------------------------------------------------------------
step "Step 5/6 — wait for celery worker ready"
ready=0
for i in $(seq 1 30); do
  if docker logs "$CELERY_CONTAINER" 2>&1 | grep -qE 'celery@[a-f0-9]+ ready'; then
    ready=1
    break
  fi
  printf '.'
  sleep 2
done
echo
if [ "$ready" -eq 1 ]; then
  ok "celery worker ready"
else
  fail "celery worker did not reach 'ready' in 60s — check:"
  echo "      docker logs $CELERY_CONTAINER"
  exit 1
fi

# ---------------------------------------------------------------------------
# Step 6: wait for ES cluster status to reach green or yellow.
# Reason: ES takes 20-30s after `docker start` to elect a master and start
# accepting reads. If a user opens the KB page in the browser the moment
# dev-up.sh reports "ready", they'll see a 9200 connection error for
# ~30 seconds — and the KB ingest / search path will silently fall back to
# FAISS (see backend/app/services/retrieval/pipeline.py), losing BM25 and
# the M28 search_weights field-weight knobs. Waiting here is cheap and
# avoids both gotchas.
#
# Single-node ES clusters never reach green (the replica shard is always
# unassigned because there's no second node), so we accept yellow too.
# ---------------------------------------------------------------------------
step "Step 6/6 — wait for Elasticsearch cluster health"
es_status=""
for i in $(seq 1 30); do
  es_status="$(curl -sf --max-time 2 http://localhost:9200/_cluster/health 2>/dev/null \
    | extract_cluster_status || true)"
  case "$es_status" in
    green|yellow)
      ok "ES cluster status: $es_status"
      break
      ;;
    red|"")
      printf '.'
      sleep 2
      ;;
    *)
      printf '.'
      sleep 2
      ;;
  esac
done

if [ "$es_status" != "green" ] && [ "$es_status" != "yellow" ]; then
  # Don't hard-exit: the user can still use FAISS fallback. Just warn.
  fail "ES did not reach green/yellow in 60s — current status: '${es_status:-unreachable}'"
  echo "      docker logs lumen-platform-es   # to debug"
  echo "      KB ingest/search will fall back to FAISS until ES recovers."
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo
echo "=== docker services ==="
docker ps --filter "name=lumen-platform-" \
  --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'

echo
echo "=== quick health check ==="
# Format: "<label>|<url>|<expected-status-field-or-empty>"
# For ES we hit /_cluster/health and verify the `status` JSON field is
# green or yellow. For services without a status field (Ollama) leave the
# third field empty and we just check reachability.
for entry in \
  "es|http://localhost:9200/_cluster/health|green yellow" \
  "ollama|http://localhost:11434/api/tags|" \
  "minio|http://localhost:29000/minio/health/live|"; do
  IFS='|' read -r label url expected <<<"$entry"
  body="$(curl -sf --max-time 3 "$url" 2>/dev/null || true)"
  if [ -z "$body" ]; then
    fail "$label ($url not reachable)"
    continue
  fi
  if [ -z "$expected" ]; then
    ok "$label (reachable)"
    continue
  fi
  status="$(printf '%s' "$body" | extract_cluster_status)"
  if [ -z "$status" ]; then
    fail "$label (no status field in response)"
    continue
  fi
  if printf '%s' "$expected" | tr ' ' '\n' | grep -Fqx "$status"; then
    ok "$label (status=$status)"
  else
    fail "$label (status=$status, expected one of: $expected)"
  fi
done

cat <<'EOF'

✓ dev docker stack ready.

Next (NOT handled by this script — start manually if needed):
  - host uvicorn (11335):  cd backend && uvicorn app.main:app --reload
  - frontend next dev (11334):  cd frontend && npm run dev
EOF