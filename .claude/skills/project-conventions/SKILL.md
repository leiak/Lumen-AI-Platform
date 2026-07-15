---
name: project-conventions
description: Use when working in the Lumen AI Platform repo (FastAPI + Next.js 15 + LangChain). This is Claude-only background knowledge — surface the response envelope contract, frontend read pattern, MySQL MCP selection, and workflow node spec location automatically. Do not invoke directly.
user-invocable: false
---

# Project Conventions — AI Agent Platform

You are working in a multi-service AI agent platform. These patterns are non-obvious and easy to get wrong. Apply them automatically when reading or writing code in this repo.

## Backend response envelope (HARD CONTRACT)

Every FastAPI endpoint **must** wrap its return value in `SingleResponse[T]` or `PaginatedResponse[T]` from `lumen_schemas.common`. Never return raw ORM objects or bare dicts.

```python
from lumen_schemas.common import SingleResponse, PaginatedResponse

# Single item
@router.get("/{id}", response_model=SingleResponse[AgentRead])
def get_agent(id: int, db: Session = Depends(get_db)) -> SingleResponse[AgentRead]:
    agent = agent_service.get(db, id)
    return SingleResponse(data=agent)

# List with pagination
@router.get("/", response_model=PaginatedResponse[AgentRead])
def list_agents(...) -> PaginatedResponse[AgentRead]:
    items, total = agent_service.list(db, page, page_size)
    return PaginatedResponse(data=items, total=total, page=page, page_size=page_size)
```

The envelope is what the frontend reads from. Skipping it breaks the UI even if the route returns 200.

## Frontend read pattern (HARD CONTRACT)

```ts
import { api } from "@/services/api"  // or services/* modules

const res = await api.get<SingleResponse<T>>("/agents/1")
const body = res.data
if (body.code === 200) {
  const agent: T = body.data
}

// Paginated
const res = await api.get<PaginatedResponse<T>>("/agents/", { params: { page: 1, page_size: 20 } })
if (res.data.code === 200) {
  const items: T[] = res.data.data
  const total: number = res.data.total
}
```

Auth token: `localStorage.getItem("access_token")` — **NOT** `"token"`. The login response also stores it under `access_token`.

API base: `process.env.NEXT_PUBLIC_API_BASE` (= `http://localhost:11335/api/v1`).

For native `fetch()` callers, set `Authorization: Bearer <access_token>` manually.

## MySQL MCP — use the right one

This project has its own Docker MySQL. Use:

- ✅ `mcp__ai_platform_docker_mysql__mysql_query` (project-specific)

**Never** use the generic `mcp__mcp_server_mysql__mysql_query` for this project — it points at a different database.

## Workflow module — spec-driven

The workflow subsystem (P1 + P2, 19 nodes total) is the most complex part of the codebase and is **spec-driven**. Before modifying workflow code, always check:

- `docs-internal/superpowers/specs/` — node specifications (single source of truth)
- `docs-internal/superpowers/plans/` — implementation plans
- `backend/lumen_services/workflow_executor.py` — executor (look at `_handle_<node_type>` for the dispatch pattern)
- `backend/lumen_services/workflow_service.py` — CRUD
- `backend/lumen_api/v1/workflow.py` — routes

P2 (shipped 2026-06-05) added 9 nodes: `code`, `http`, `tool`, `knowledge_retrieval`, `template_transform`, `parameter_extractor`, `question_classifier`, `variable_assigner`, `variable_aggregator`. Each has a `error_strategy` + `retry_config` + per-node `timeout` field. The shared infra lives in `backend/lumen_services/workflow_executor.py` (look for `ErrorStrategy` / `RetryConfig` references).

## Port allocation

| Service | Port |
|---------|------|
| Frontend dev | 11334 |
| Backend (uvicorn) | 11335 |
| Ollama | 11434 |
| Local MCP demo server | 8765 |

`localhost:8000` and `localhost:3000` do **not** exist in this setup. If you see references to them in old docs, they're stale.

## Test baselines (must not regress)

| Suite | Count | Command |
|-------|-------|---------|
| Backend pytest | 369 pass | `cd backend && pytest` |
| Frontend vitest | 126 pass | `cd frontend && npm run test:unit` |
| mypy on workflow_executor | 0 errors | `mypy backend/lumen_services/workflow_executor.py` |
| tsc | 0 new errors | `cd frontend && npx tsc --noEmit` |

After any code change, the relevant test command should still pass.

## Uvicorn zombie (Windows-only gotcha)

`uvicorn --reload` on Windows can leave zombie workers holding port 11335. Symptoms: imports work, but endpoints return `[]` or fail silently. Do **not** poke the same instance. Either:

1. Kill the worker child process (parent is the reloader; child is the `multiprocessing.spawn`-derived one).
2. If that fails, start a fresh uvicorn on port 11336 and point the frontend / API tests there.

Full protocol: `docs/troubleshooting/uvicorn-zombie.md`.

## Python environment

The local Anaconda Python is what works. Don't assume missing modules — check for zombie workers first.

## Conversation language

User-facing replies are in **Chinese**. Code, commands, file content, log dumps, and commit messages stay in English.
