#!/usr/bin/env bash
# SessionStart hook: dev service health check + zombie worker hint.
# Cross-platform bash (works in Git Bash on Windows, native bash on macOS/Linux).
# Plain stdout is shown to Claude at session start.

set +e

echo "=== Dev service status ==="

# --- Helper: PID listening on a port (uses Windows netstat format) ---
get_pid() {
  local port=$1
  # netstat on Windows Git Bash:  "  TCP    0.0.0.0:11335    0.0.0.0:0    LISTENING    87584"
  # On macOS/Linux:                "tcp        0      0  0.0.0.0:11335      0.0.0.0:*    LISTEN"
  netstat -ano 2>/dev/null | grep -E "[:.]$port[[:space:]].*LISTEN(I?N?G?)" | head -1 | awk '{print $NF}'
}

# --- Helper: process start time (Windows) / start time fallback ---
get_started() {
  local pid=$1
  [ -z "$pid" ] && return
  if command -v tasklist.exe >/dev/null 2>&1; then
    # tasklist columns: Image Name, PID, Session Name, Session#, Mem Usage, Status, User, CPU Time, Window Title
    tasklist.exe //FI "PID eq $pid" 2>/dev/null | awk 'NR>3 && $2 ~ /^[0-9]+$/ {print "at "$5; exit}'
  fi
}

# --- Per-port check ---
check_port() {
  local port=$1
  local name=$2
  local pid
  pid=$(get_pid "$port")
  if [ -n "$pid" ]; then
    local started
    started=$(get_started "$pid")
    printf "  %-9s port %-6s PID %-6s up%s\n" "$name" "$port" "$pid" "${started}"
  else
    printf "  %-9s port %-6s — DOWN\n" "$name" "$port"
  fi
}

check_port 11334 "frontend"
check_port 11335 "backend"
check_port 11434 "ollama"

# --- Zombie hint ---
# On Windows, uvicorn runs as python.exe. If we see too many python processes,
# there may be zombie workers holding the socket. 4+ is the threshold because
# the local Anaconda base + a few project subprocesses (e.g., docling) is normal.
if command -v tasklist.exe >/dev/null 2>&1; then
  python_count=$(tasklist.exe 2>/dev/null | awk 'tolower($1) == "python.exe"' | wc -l | tr -d ' ')
  if [ "${python_count:-0}" -gt 4 ]; then
    echo ""
    echo "  ⚠  $python_count python.exe processes running."
    echo "     If backend (port 11335) returns empty data, this is a zombie-worker symptom."
    echo "     See CLAUDE.md §5 / docs/troubleshooting/uvicorn-zombie.md"
  fi
fi

# --- MCP self-check hint ---
# If the project-specific MySQL MCP is configured, this should be a fast ping.
# (No actual query here — we don't want a slow hook. The mcp__ai_platform_docker_mysql__mysql_query
# tool itself surfaces errors if the server is unreachable.)

exit 0
