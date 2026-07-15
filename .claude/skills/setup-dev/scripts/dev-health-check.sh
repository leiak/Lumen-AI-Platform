#!/usr/bin/env bash
# /setup-dev skill: dev environment health check.
#
# Checks (cross-platform bash, works in Git Bash on Windows):
#   1. Ports 11334 (frontend), 11335 (backend), 11434 (ollama) listening
#   2. Ollama embedding ping (nomic-embed-text)
#   3. python.exe process count (zombie-worker hint)
#
# Does NOT:
#   - start services (suggest commands only)
#   - kill processes
#   - query MySQL (use mcp__ai_platform_docker_mysql__mysql_query for that)
#
# Exit 0 = everything healthy, 1 = at least one service down or unhealthy.

set +e

RED=$'\033[31m'; GRN=$'\033[32m'; YEL=$'\033[33m'; DIM=$'\033[2m'; RST=$'\033[0m'

print_header() {
  echo "=================================================="
  echo "  Dev environment health check  ($(date '+%Y-%m-%d %H:%M:%S'))"
  echo "=================================================="
}

# --- Per-port check ---
get_pid() {
  local port=$1
  netstat -ano 2>/dev/null | grep -E "[:.]$port[[:space:]].*LISTEN(I?N?G?)" | head -1 | awk '{print $NF}'
}

get_started() {
  local pid=$1
  [ -z "$pid" ] && return
  if command -v tasklist.exe >/dev/null 2>&1; then
    tasklist.exe //FI "PID eq $pid" 2>/dev/null | awk 'NR>3 && $2 ~ /^[0-9]+$/ {print $5; exit}'
  fi
}

declare -a DOWN_PORTS=()
declare -a DOWN_NAMES=()

check_port() {
  local port=$1
  local name=$2
  local started_col=$3   # column hint for "started at" line
  local pid
  pid=$(get_pid "$port")
  if [ -n "$pid" ]; then
    local started
    started=$(get_started "$pid")
    printf "  ${GRN}✓${RST}  %-9s  port %-6s  PID %-6s  %s\n" "$name" "$port" "$pid" "${DIM}started $started${RST}"
  else
    printf "  ${RED}✗${RST}  %-9s  port %-6s  ${RED}DOWN${RST}\n" "$name" "$port"
    DOWN_PORTS+=("$port")
    DOWN_NAMES+=("$name")
  fi
}

print_header

echo ""
echo "[1/3] Port status"
echo "-----------------"
check_port 11334 "frontend" ""
check_port 11335 "backend" ""
check_port 11434 "ollama" ""

# --- Ollama embedding ping ---
echo ""
echo "[2/3] Ollama embedding ping (nomic-embed-text)"
echo "----------------------------------------------"
if curl -sS --max-time 5 -X POST http://localhost:11434/api/embeddings \
    -H "Content-Type: application/json" \
    -d '{"model":"nomic-embed-text","prompt":"测试连通性"}' \
    > /tmp/_ollama_ping.json 2>/tmp/_ollama_ping.err; then
  if grep -q '"embedding"' /tmp/_ollama_ping.json; then
    # Try to extract dim (count of numbers in the first embedding array)
    dim=$(grep -o '"embedding":\[[^]]*\]' /tmp/_ollama_ping.json | head -1 | tr ',' '\n' | wc -l | tr -d ' ')
    printf "  ${GRN}✓${RST}  embedding OK  ${DIM}(~%s dims)${RST}\n" "$dim"
  else
    printf "  ${YEL}!${RST}  embedding response but no 'embedding' field.\n"
    head -c 200 /tmp/_ollama_ping.json
    echo ""
  fi
else
  printf "  ${RED}✗${RST}  Ollama unreachable or model missing.\n"
  err=$(cat /tmp/_ollama_ping.err 2>/dev/null | head -c 200)
  [ -n "$err" ] && printf "      ${DIM}%s${RST}\n" "$err"
  printf "      Fix: ${YEL}ollama pull nomic-embed-text${RST}\n"
fi
rm -f /tmp/_ollama_ping.json /tmp/_ollama_ping.err

# --- Python process count (zombie hint) ---
echo ""
echo "[3/3] Process hints"
echo "-------------------"
if command -v tasklist.exe >/dev/null 2>&1; then
  python_count=$(tasklist.exe 2>/dev/null | awk 'tolower($1) == "python.exe"' | wc -l | tr -d ' ')
  node_count=$(tasklist.exe 2>/dev/null | awk 'tolower($1) == "node.exe"' | wc -l | tr -d ' ')
  printf "  python.exe : %s   node.exe : %s\n" "$python_count" "$node_count"
  if [ "${python_count:-0}" -gt 4 ]; then
    printf "  ${YEL}⚠${RST}  $python_count python.exe processes.  May indicate zombie uvicorn workers.\n"
    printf "      See: ${DIM}docs/troubleshooting/uvicorn-zombie.md${RST}\n"
  fi
else
  printf "  ${DIM}(tasklist not available — skipping)${RST}\n"
fi

# --- MySQL MCP reminder ---
echo ""
echo "[info] MySQL MCP"
echo "---------------"
printf "  ${DIM}Run via tool: mcp__ai_platform_docker_mysql__mysql_query${RST}\n"
printf "  ${DIM}Quick check:   SELECT 1;${RST}\n"

# --- Summary ---
echo ""
echo "=================================================="
if [ "${#DOWN_PORTS[@]}" -gt 0 ]; then
  printf "${YEL}Result:${RST}  %d service(s) down: %s\n" "${#DOWN_PORTS[@]}" "${DOWN_NAMES[*]}"
  echo ""
  echo "Suggested start commands:"
  for name in "${DOWN_NAMES[@]}"; do
    case "$name" in
      frontend)
        printf "  ${DIM}cd frontend && npm run dev${RST}\n"
        ;;
      backend)
        printf "  ${DIM}cd backend && python -m uvicorn app.main:app --host 0.0.0.0 --port 11335 --reload${RST}\n"
        ;;
      ollama)
        printf "  ${DIM}ollama serve   # then: ollama pull nomic-embed-text${RST}\n"
        ;;
    esac
  done
  exit 1
else
  printf "${GRN}Result:${RST}  all services up.\n"
  exit 0
fi
