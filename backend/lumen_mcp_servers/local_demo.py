"""
Local MCP demo server. Exposes 6 platform self-reflective tools.

Started by ``backend/run_mcp_server.py`` on 127.0.0.1:8765.

All tool functions follow the same return contract:

    {"ok": bool, "data": <payload> | None, "count": int,
     "message": "ok" | "<error_code>", "error": str | <absent>}

Tool functions take their DB session from ``SessionLocal()`` and close it
in a ``finally`` block, so they are safe to call from any thread.
"""
import asyncio
import os
import time
import uuid
from typing import Any, Dict, List, Optional

from mcp.server.fastmcp import FastMCP

# Pre-warm: langchain_ollama (M24) pulls in `langchain_core.language_models
# .chat_models`, which empirically takes ~10s on a cold first import due
# to a slow data-walk in langchain_core 1.0.x's fake_chat_models module.
# Importing here ensures the slow path is paid once at module load, not
# deferred to the first tool invocation (which would push the test
# fixture's cold-start deadline).
#
# See docs/superpowers/specs/2026-06-13-langchain-1.0-upgrade-design.md
# §3.2 for the full cold-start timeline analysis.
import langchain_ollama  # noqa: F401  (pre-warm)

from lumen_core.database import SessionLocal
from lumen_core.embedding_call_context import (
    EmbeddingCallContext,
    set_embedding_context,
    reset_embedding_context,
)
# The four models we query are listed explicitly; the rest are imported as
# side-effects only so SQLAlchemy's class registry can resolve the
# ``relationship("Tenant")`` etc. strings inside the queried models'
# relationship configs. Without these, the first tool invocation against a
# fresh ``uvicorn run_mcp_server.py`` process crashes with
# ``InvalidRequestError: expression 'Tenant' failed to locate a name``.
from lumen_models.tenant import Tenant  # noqa: F401
from lumen_models.user import User  # noqa: F401
from lumen_models.agent import Agent, AgentTool, AgentKnowledgeBase  # noqa: F401
from lumen_models.chat import Conversation, Message  # noqa: F401  # Conversation is queried, Message is its relationship target
from lumen_models.knowledge import KnowledgeBase, Document, DocumentChunk  # noqa: F401
from lumen_models.workflow import Workflow, WorkflowRun, WorkflowNodeRun, WorkflowSchedule  # noqa: F401
from lumen_models.llm_call_log import LLMCallLog  # noqa: F401  # WorkflowRun.llm_call_logs relationship target
from lumen_models.embedding_call_log import EmbeddingCallLog  # noqa: F401  # WorkflowRun.embedding_call_logs relationship target
from lumen_services.workflow_executor import WorkflowExecutor

MCP_DEFAULT_TENANT_ID = int(os.getenv("MCP_DEFAULT_TENANT_ID", "1"))


def _resolve_tenant(tenant_id: Optional[int] = None) -> int:
    """Resolve the tenant ID. Explicit argument wins; otherwise the env default."""
    return tenant_id if tenant_id is not None else MCP_DEFAULT_TENANT_ID


def list_agents(limit: int = 20, tenant_id: Optional[int] = None) -> dict:
    """List active agents for the tenant, ordered by most recently updated.

    Args:
        limit: Maximum number of agents to return. Default 20.
        tenant_id: Optional explicit tenant override (defaults to
            ``MCP_DEFAULT_TENANT_ID`` env var, which is ``1``).

    Returns:
        ``{"ok": True, "count": N, "data": [{"id", "name", "description"}, ...],
           "message": "ok"}`` on success.
    """
    tid = _resolve_tenant(tenant_id)
    db = SessionLocal()
    try:
        agents = (
            db.query(Agent)
            .filter(Agent.tenant_id == tid, Agent.is_active == True)  # noqa: E712
            .order_by(Agent.updated_at.desc())
            .limit(limit)
            .all()
        )
        return {
            "ok": True,
            "count": len(agents),
            "data": [
                {"id": a.id, "name": a.name, "description": a.description}
                for a in agents
            ],
            "message": "ok",
        }
    finally:
        db.close()


def list_knowledge_bases(limit: int = 20, tenant_id: Optional[int] = None) -> dict:
    """List knowledge bases for the tenant with each KB's document count.

    Args:
        limit: Maximum number of KBs to return. Default 20.
        tenant_id: Optional explicit tenant override.

    Returns:
        ``{"ok": True, "count": N,
           "data": [{"id", "name", "description", "doc_count"}, ...],
           "message": "ok"}``
    """
    tid = _resolve_tenant(tenant_id)
    db = SessionLocal()
    try:
        kbs = (
            db.query(KnowledgeBase)
            .filter(KnowledgeBase.tenant_id == tid)
            .order_by(KnowledgeBase.updated_at.desc())
            .limit(limit)
            .all()
        )
        result = []
        for kb in kbs:
            # kb.documents is a SQLAlchemy relationship; len() triggers
            # a lazy-load count query.
            result.append({
                "id": kb.id,
                "name": kb.name,
                "description": kb.description,
                "doc_count": len(kb.documents),
            })
        return {"ok": True, "count": len(result), "data": result, "message": "ok"}
    finally:
        db.close()


def search_knowledge_base(
    query: str,
    kb_name: str,
    top_k: int = 5,
    tenant_id: Optional[int] = None,
) -> dict:
    """Run hybrid (vector + BM25) RAG search over a knowledge base.

    Args:
        query: The user's natural-language query.
        kb_name: Name of the target knowledge base.
        top_k: Number of chunks to return. Default 5.
        tenant_id: Optional explicit tenant override.

    Returns:
        On success: ``{"ok": True, "count": N,
                        "data": [{"chunk_id", "content", "score", "metadata"}],
                        "message": "ok"}``
        On unknown KB: ``{"ok": False, "error": "Knowledge base 'X' not found",
                          "data": None, "message": "kb_not_found"}``
        On retrieval failure: ``{"ok": False, "error": str(e),
                                 "data": None, "message": "search_failed"}``
    """
    tid = _resolve_tenant(tenant_id)
    db = SessionLocal()
    # M27: install an EmbeddingCallContext for this MCP tool call. The
    # MCP server runs in its own process and has no current_user (it's
    # called by external MCP clients with tenant-scoped credentials).
    # The row is tagged ``client_app="mcp_local_demo"`` so the UI can
    # filter it out / show the MCP origin distinctly from foreground
    # dashboard queries.
    emb_ctx_token = set_embedding_context(EmbeddingCallContext(
        call_id=str(uuid.uuid4()),
        trace_id=str(uuid.uuid4()),
        parent_call_id=None,
        call_type="kb_retrieval",
        call_index=0,
        tenant_id=tid,
        client_app="mcp_local_demo",
        extra={"top_k": top_k, "kb_name": kb_name},
    ))
    try:
        kb = db.query(KnowledgeBase).filter_by(tenant_id=tid, name=kb_name).first()
        if not kb:
            return {
                "ok": False,
                "error": f"Knowledge base '{kb_name}' not found",
                "data": None,
                "message": "kb_not_found",
            }

        # Lazy import to avoid loading the heavy retrieval pipeline at module
        # import time (it pulls in ollama/httpx clients eagerly).
        from lumen_services.retrieval.pipeline import get_retrieval_pipeline

        # Drive-by fix: pass the KB id (not the name). The 1-arg form
        # ``get_retrieval_pipeline(kb.name)`` creates a phantom cache entry
        # keyed by the string name; KB id is the canonical cache key used
        # elsewhere in the project (see ``get_retrieval_pipeline`` in
        # ``app/services/retrieval/pipeline.py``).
        pipeline = get_retrieval_pipeline(
            kb_id=kb.id,
            model_config_id=kb.embedding_model_config_id,
            db=db,
        )
        filter_expr = f"tenant_id == {tid} and kb_id == {kb.id}"
        # M28: pass the KB's 4 multi_match field boosts so the
        # Elasticsearch backend can honour them. FAISS silently ignores.
        results = pipeline.search(
            query=query, k=top_k, filter_expr=filter_expr,
            search_weights=kb.search_weights,
        )

        return {
            "ok": True,
            "count": len(results),
            "data": [
                {
                    "chunk_id": r.get("chunk_id"),
                    "content": r.get("content"),
                    "score": r.get("score"),
                    "metadata": r.get("metadata"),
                }
                for r in results
            ],
            "message": "ok",
        }
    except Exception as e:
        return {
            "ok": False,
            "error": str(e),
            "data": None,
            "message": "search_failed",
        }
    finally:
        db.close()
        reset_embedding_context(emb_ctx_token)


def list_chat_sessions(user_id: int, limit: int = 20) -> dict:
    """List a user's recent chat conversations, scoped to the default tenant.

    Args:
        user_id: The user whose conversations to list.
        limit: Maximum number of sessions to return. Default 20.

    Returns:
        ``{"ok": True, "count": N, "data": [{"id", "title", "updated_at"}],
           "message": "ok"}``
    """
    db = SessionLocal()
    try:
        sessions = (
            db.query(Conversation)
            .filter(
                Conversation.user_id == user_id,
                Conversation.tenant_id == _resolve_tenant(),
            )
            .order_by(Conversation.updated_at.desc())
            .limit(limit)
            .all()
        )
        return {
            "ok": True,
            "count": len(sessions),
            "data": [
                {
                    "id": s.id,
                    "title": s.title,
                    "updated_at": s.updated_at.isoformat() if s.updated_at else None,
                }
                for s in sessions
            ],
            "message": "ok",
        }
    finally:
        db.close()


def list_workflows(limit: int = 20, tenant_id: Optional[int] = None) -> dict:
    """List active workflows for the tenant, ordered by most recently updated.

    Args:
        limit: Maximum number of workflows to return. Default 20.
        tenant_id: Optional explicit tenant override.

    Returns:
        ``{"ok": True, "count": N,
           "data": [{"id", "name", "description"}, ...], "message": "ok"}``
    """
    tid = _resolve_tenant(tenant_id)
    db = SessionLocal()
    try:
        wfs = (
            db.query(Workflow)
            .filter(Workflow.tenant_id == tid, Workflow.is_active == True)  # noqa: E712
            .order_by(Workflow.updated_at.desc())
            .limit(limit)
            .all()
        )
        return {
            "ok": True,
            "count": len(wfs),
            "data": [
                {"id": w.id, "name": w.name, "description": w.description}
                for w in wfs
            ],
            "message": "ok",
        }
    finally:
        db.close()


def run_workflow(
    name: str,
    input_data: dict,
    tenant_id: Optional[int] = None,
) -> dict:
    """Synchronously execute a workflow by name and return the result.

    The platform's ``WorkflowExecutor.execute`` is async; we wrap it with
    ``asyncio.run`` since MCP tool functions are sync from FastMCP's perspective.

    Args:
        name: Name of the workflow to execute.
        input_data: JSON-serializable input payload.
        tenant_id: Optional explicit tenant override.

    Returns:
        On success: ``{"ok": True, "data": {"workflow_id", "result",
                        "execution_time_ms"}, "message": "ok"}``
        On unknown workflow: ``{"ok": False, "error": "Workflow 'X' not found",
                                 "data": None, "message": "workflow_not_found"}``
        On execution failure: ``{"ok": False, "error": str(e), "data": None,
                                 "message": "execution_failed",
                                 "execution_time_ms": <ms>}``
    """
    tid = _resolve_tenant(tenant_id)
    db = SessionLocal()
    start = time.time()
    try:
        wf = db.query(Workflow).filter_by(tenant_id=tid, name=name).first()
        if not wf:
            return {
                "ok": False,
                "error": f"Workflow '{name}' not found",
                "data": None,
                "message": "workflow_not_found",
            }

        executor = WorkflowExecutor()
        # execute() is async: workflow is the DAG dict, not the ORM object.
        result = asyncio.run(executor.execute(wf.definition, input_data, tid))
        return {
            "ok": True,
            "count": 1,
            "data": {
                "workflow_id": wf.id,
                "result": result,
                "execution_time_ms": int((time.time() - start) * 1000),
            },
            "message": "ok",
        }
    except Exception as e:
        return {
            "ok": False,
            "error": str(e),
            "data": None,
            "message": "execution_failed",
            "execution_time_ms": int((time.time() - start) * 1000),
        }
    finally:
        db.close()


def query_database(
    question: str,
    db_alias: str = "ai_platform",
    tenant_id: Optional[int] = None,
) -> dict:
    """M33 智能问数 (7th tool) — natural-language → SQL → rows.

    Wraps ``Text2SqlEngine.ask`` so the MCP demo client can ask
    business questions without going through the dashboard UI.
    Uses the project's ai_platform database (the only supported
    db_alias today).

    Returns the same shape as the standalone /text2sql/ask endpoint:
    ``{ sql, rows, columns, explanation, row_count, ... }`` on
    success, ``{ ok: False, error: ... }`` on failure.
    """
    start = time.time()
    from lumen_core.database import SessionLocal
    from lumen_models.text2sql import Text2SqlDataSource
    from lumen_services.text2sql.engine import Text2SqlEngine
    from lumen_services.text2sql.data_source_service import (
        Text2SqlDataSourceService,
    )

    db = SessionLocal()
    try:
        tid = _resolve_tenant(tenant_id)
        ds = Text2SqlDataSourceService.get_default(db, tenant_id=tid)
        if ds is None:
            return {
                "ok": False,
                "error": "no data source found",
                "data": None,
                "message": "datasource_not_found",
            }
        result = Text2SqlEngine(db, ds).ask(
            question,
            user_id=None,
            tenant_id=tid,
            client_app="mcp_local_demo",
        )
        if result.status != "success":
            return {
                "ok": False,
                "error": result.error_message or "engine failed",
                "error_type": result.error_type,
                "data": None,
                "message": f"text2sql.{result.status}",
                "execution_time_ms": int((time.time() - start) * 1000),
            }
        return {
            "ok": True,
            "count": result.row_count,
            "data": {
                "sql": result.generated_sql,
                "columns": result.columns,
                "rows": result.rows,
                "row_count": result.row_count,
                "truncated": result.truncated,
                "explanation": result.explanation,
                "confidence": result.confidence,
                "attempts": result.attempts,
                "duration_ms": result.duration_ms,
            },
            "message": "ok",
            "execution_time_ms": int((time.time() - start) * 1000),
        }
    except Exception as e:
        return {
            "ok": False,
            "error": str(e),
            "data": None,
            "message": "query_failed",
            "execution_time_ms": int((time.time() - start) * 1000),
        }
    finally:
        db.close()
        db.close()


# FastMCP instance.
mcp = FastMCP("lumen-platform-local-demo")

# Register all 7 tools with the FastMCP instance.
mcp.tool()(list_agents)
mcp.tool()(list_knowledge_bases)
mcp.tool()(search_knowledge_base)
mcp.tool()(list_chat_sessions)
mcp.tool()(list_workflows)
mcp.tool()(run_workflow)
# M33: 7th tool — 智能问数(Text2SQL)
mcp.tool()(query_database)


# Expose the ASGI app for uvicorn.
# NOTE: mcp==1.2.0 does not yet expose ``FastMCP.streamable_http_app()`` (that
# helper was added in mcp 1.3+). We build the equivalent Starlette ASGI app
# by hand:
#   - ``/sse``  + ``/messages/`` — the standard MCP SSE transport, used by
#     proper MCP clients (e.g. ``mcp.client.sse.sse_client``).
#   - ``/mcp``  (POST)            — a Streamable-HTTP-style synchronous
#     JSON-RPC endpoint that lets plain HTTP clients (``curl``, the
#     platform's own ``discover_tools``) talk to the server without going
#     through the SSE handshake dance. Auto-initializes the session on the
#     first non-init request, so a single ``curl -d '{"method":"tools/list"}'``
#     just works.
import json
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from mcp.server.sse import SseServerTransport

_sse_transport = SseServerTransport("/messages/")


async def _run_sse_session(request):
    """Open an SSE session and run the MCP server on top of it.

    Shared by the legacy ``/sse`` endpoint and the streamable-HTTP-style
    ``/mcp`` GET handler (newer MCP clients like Trae CN use a single URL
    for both GET-SSE and POST-JSON-RPC).
    """
    async with _sse_transport.connect_sse(
        request.scope, request.receive, request._send
    ) as streams:
        await mcp._mcp_server.run(
            streams[0],
            streams[1],
            mcp._mcp_server.create_initialization_options(),
        )


async def _handle_sse(request):
    return await _run_sse_session(request)


async def _dispatch_mcp(request):
    """``/mcp`` accepts both GET (open SSE stream) and POST (synchronous
    JSON-RPC). Older MCP clients (Claude Desktop, Cline, Cursor) use the
    dedicated ``/sse`` + ``/messages/`` pair; newer streamable-HTTP clients
    (Trae CN, etc.) reuse a single URL for both directions.
    """
    if request.method == "GET":
        return await _run_sse_session(request)
    if request.method == "POST":
        return await _handle_mcp_http(request)
    return JSONResponse(
        {"error": f"Method not allowed: {request.method}"},
        status_code=405,
    )


# Tracks whether any client has completed the MCP handshake. Resetting on
# every process start is fine — this is a single-tenant local demo.
_mcp_http_initialized: bool = False


async def _handle_mcp_http(request):
    """Streamable-HTTP-style endpoint: POST a JSON-RPC request, get a JSON-RPC response.

    Supports the two methods that matter for smoke tests and the platform's
    ``mcp_service.discover_tools`` flow:

      - ``initialize``            → return ``InitializeResult``
      - ``notifications/initialized`` → 204 No Content
      - ``tools/list``            → list the 6 registered tools
      - ``tools/call``            → invoke one tool, return the
                                    ``{"content": [...], "isError": false}``
                                    envelope the rest of the platform expects

    Auto-initializes on the first ``tools/list``/``tools/call`` request so a
    bare ``curl -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'``
    works without prior handshake.

    Response format follows the ``Accept`` request header:
      - ``Accept: text/event-stream`` (or both) → SSE-wrapped (the platform
        and proper MCP clients use this; matches what ``/messages/`` returns)
      - ``Accept: application/json``            → plain JSON
    """
    global _mcp_http_initialized
    try:
        body = await request.body()
        msg = json.loads(body) if body else {}
    except json.JSONDecodeError as e:
        return JSONResponse(
            {"jsonrpc": "2.0", "id": None,
             "error": {"code": -32700, "message": f"Parse error: {e}"}},
            status_code=400,
        )

    method = msg.get("method")
    req_id = msg.get("id")
    params = msg.get("params") or {}
    accept = request.headers.get("accept", "")
    wants_sse = "text/event-stream" in accept

    def _respond(payload: dict, status_code: int = 200):
        """Return SSE-wrapped or plain-JSON response per Accept header."""
        if wants_sse:
            # Single-event SSE: ``event: message\\ndata: <json>\\n\\n``.
            # The platform's ``_parse_sse_response`` joins multi-line ``data:``
            # blocks with ``\\n`` and parses the combined string, so a single
            # line works.
            sse_body = f"event: message\ndata: {json.dumps(payload)}\n\n"
            from starlette.responses import Response
            return Response(
                content=sse_body,
                media_type="text/event-stream",
                status_code=status_code,
            )
        return JSONResponse(payload, status_code=status_code)

    # ---- initialize ---------------------------------------------------
    if method == "initialize":
        _mcp_http_initialized = True
        return _respond({
            "jsonrpc": "2.0", "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "lumen-platform-local-demo",
                               "version": "1.0.0"},
            },
        })

    # ---- notifications/initialized -----------------------------------
    if method == "notifications/initialized":
        _mcp_http_initialized = True
        # No response body for a notification, but respect the Accept header
        # anyway (clients that insist on SSE get an empty event stream).
        if wants_sse:
            from starlette.responses import Response
            return Response(content="event: message\ndata: {}\n\n",
                            media_type="text/event-stream", status_code=204)
        return JSONResponse({}, status_code=204)

    # ---- auto-initialize shortcut (non-standard; see docstring) ------
    # Real MCP clients always send initialize first. We accept requests
    # without prior init so curl smoke tests work.
    _mcp_http_initialized = True

    # ---- tools/list ---------------------------------------------------
    if method == "tools/list":
        tools_out = []
        for name, tool in mcp._tool_manager._tools.items():
            tools_out.append({
                "name": tool.name,
                "description": tool.description or "",
                # ``parameters`` is the pydantic-generated JSON schema for the
                # function's signature. The MCP wire field name is
                # ``inputSchema``.
                "inputSchema": tool.parameters,
            })
        return _respond({
            "jsonrpc": "2.0", "id": req_id,
            "result": {"tools": tools_out},
        })

    # ---- tools/call ---------------------------------------------------
    if method == "tools/call":
        tool_name = params.get("name")
        arguments = params.get("arguments") or {}
        tool = mcp._tool_manager._tools.get(tool_name)
        if tool is None:
            return _respond({
                "jsonrpc": "2.0", "id": req_id,
                "error": {"code": -32602,
                          "message": f"Tool not found: {tool_name}"},
            })
        try:
            # ``Tool.run`` is a coroutine even for sync-decorated functions
            # (mcp 1.2.0 wraps it), so we always await.
            raw = await tool.run(arguments=arguments)
            text = raw if isinstance(raw, str) else json.dumps(raw, default=str)
            return _respond({
                "jsonrpc": "2.0", "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": text}],
                    "isError": False,
                },
            })
        except Exception as e:
            return _respond({
                "jsonrpc": "2.0", "id": req_id,
                "result": {
                    "content": [{"type": "text",
                                 "text": f"Tool raised: {type(e).__name__}: {e}"}],
                    "isError": True,
                },
            })

    # ---- unknown method ----------------------------------------------
    return _respond({
        "jsonrpc": "2.0", "id": req_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    })


app = Starlette(
    debug=mcp.settings.debug,
    routes=[
        Route("/sse", endpoint=_handle_sse),
        Mount("/messages/", app=_sse_transport.handle_post_message),
        Route("/mcp", endpoint=_dispatch_mcp, methods=["GET", "POST"]),
    ],
)
