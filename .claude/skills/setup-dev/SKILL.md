---
name: setup-dev
description: Use when the user wants to verify the dev environment is healthy — checks port 11334 (frontend), 11335 (backend), 11434 (Ollama), pings MySQL via the project MCP, and tests an embedding call. Invoked as `/setup-dev`.
---

# /setup-dev — Dev Environment Health Check

Use this when the user says "check dev env", "is everything running?", "setup-dev", or after a long pause / fresh clone / OOM kill.

The skill runs `scripts/dev-health-check.sh` (bundled with this skill). Do not re-implement the checks — just run the script.

## What it checks

1. **Ports listening** — 11334 (Next.js), 11335 (uvicorn), 11434 (Ollama)
2. **Process count** — flag potential zombie-worker situations (many `python.exe` running)
3. **Ollama embedding ping** — `POST /api/embeddings` with `nomic-embed-text` on a short Chinese test phrase. If the model isn't pulled, the script prints the exact `ollama pull` command.
4. **MySQL MCP** — reminds the user to verify with the `mcp__ai_platform_docker_mysql__mysql_query` tool (we don't auto-query from the script to keep it fast).

## Usage

When the user invokes `/setup-dev`:

1. **Locate the script.** It is bundled with this skill at `scripts/dev-health-check.sh` relative to this `SKILL.md`'s directory. Resolve the absolute path with:

   ```bash
   # Search common plugin cache locations
   SCRIPT=$(find ~/.claude/plugins/cache -name 'dev-health-check.sh' -path '*/setup-dev/*' 2>/dev/null | head -1)
   [ -z "$SCRIPT" ] && SCRIPT=$(find .claude -name 'dev-health-check.sh' -path '*/setup-dev/*' 2>/dev/null | head -1)
   echo "$SCRIPT"
   ```

2. Run it: `bash "$SCRIPT"`
3. Read the output.
4. Summarize the result in Chinese, with the table the script prints.
5. If a service is **DOWN**, suggest the exact start command from the script's output.
6. If a service shows a **zombie warning**, point to `CLAUDE.md §5` and `docs/troubleshooting/uvicorn-zombie.md`.
7. If the user wants to fix a problem (not just check), proceed to diagnose — but only after the health check is done.

## What this skill does NOT do

- It does **not** start services automatically (the user can do that, or you can suggest the commands).
- It does **not** modify code, kill processes, or restart uvicorn. Diagnosis → fix is a separate flow.
- It does **not** re-run the test suites. Use `pytest` / `npm run test:unit` for that.

## Related

- `CLAUDE.md` §5 — uvicorn zombie protocol
- `.claude/hooks/check-dev-services.sh` (project) — the lighter SessionStart version (no Ollama ping)
- `project-conventions` skill — port allocation + conventions reference
