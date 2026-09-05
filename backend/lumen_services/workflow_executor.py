"""
WorkflowExecutor v2 — single source of truth: VariablePool.

Public class signature unchanged so workflow_service.py keeps working.
Old handlers (_handle_start, _handle_input, ...) are removed in favor of
delegating to BaseNode subclasses in app.core.workflow.nodes.

SPEC FIXES (2026-06-04 review):
  - DB sessions created in _instantiate are tracked and closed in finally
  - The `db` parameter to execute() is intentionally unused; the executor
    opens its own session via SessionLocal() to avoid coupling to caller
    session lifecycle
  - _collect_final_output uses a precomputed output_node_ids set for
    O(n) filtering instead of nested loops

M30a (2026-06-16) — observability:
  - BFS now writes a WorkflowNodeRun row per node (running → completed/failed)
    so the frontend can show per-node progress, input_data, output_data, and
    error_message. Previously WorkflowNodeRun was defined in models.workflow
    but never written to.
  - Added `on_event` callback hook for SSE streaming — the /stream endpoint
    passes a callback that yields run_start/node_start/node_end/run_end/error
    events to the client.
  - Added `cancel_event` (asyncio.Event) so /cancel can stop a running
    workflow between nodes. The currently-running node is allowed to
    finish naturally; we check the event only at node boundaries.
"""
import asyncio
import logging
import time
import uuid
from collections import deque
from datetime import datetime
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Dict, List, Optional

from sqlalchemy.orm import Session

from lumen_core.workflow.entities import NodeRunResult
from lumen_core.workflow.executor_helpers import (
    _FAILED_RESULT,
    run_node_with_handling,
)
from lumen_core.workflow.node_mapping import resolve_node_class
from lumen_core.workflow.retry import NodeRunError
from lumen_core.workflow.variable_pool import VariablePool

if TYPE_CHECKING:
    from lumen_models.user import User

logger = logging.getLogger(__name__)


# M30a: event name constants. Use these instead of inline string literals
# so the SSE endpoint and the executor share a single vocabulary.
EVENT_RUN_START = "run_start"
EVENT_NODE_START = "node_start"
EVENT_NODE_END = "node_end"
EVENT_RUN_END = "run_end"
EVENT_ERROR = "error"


EventCallback = Callable[[str, Dict[str, Any]], Awaitable[None]]


class WorkflowExecutor:
    def __init__(self) -> None:
        self.pool: Optional[VariablePool] = None
        self.results: Dict[str, NodeRunResult] = {}
        self.definition: Dict[str, Any] = {}
        self._sessions: List[Session] = []
        # M30a: meta session dedicated to WorkflowNodeRun writes. Kept
        # separate from per-node sessions (which the node subclasses own
        # and close themselves) so a failing node can't roll back the
        # running-status row we just persisted.
        self._meta_session: Optional[Session] = None

    async def execute(
        self,
        definition: Dict[str, Any],
        input_data: Dict[str, Any],
        tenant_id: int,
        run_id: int,
        db: Session,
        on_event: Optional[EventCallback] = None,
        cancel_event: Optional[asyncio.Event] = None,
        persist_node_runs: bool = False,
        user: Optional["User"] = None,
    ) -> Dict[str, Any]:
        # Note: `db` parameter is intentionally unused. The executor opens
        # its own session per node (see _instantiate) and closes them in
        # the finally block. This decouples the executor from the caller's
        # session lifecycle (which may be tied to a request or scheduler job).
        del db
        self.definition = definition
        self.pool = VariablePool()
        self.results = {}
        self._sessions = []
        # M26: per-execution trace_id. All LLM nodes in this run share it
        # so the UI can group their LLMCallLog rows into one timeline.
        # workflow_id / run_id are propagated to node configs in
        # _instantiate so LLMNode._run() can stamp the LLMCallContext.
        self.trace_id = str(uuid.uuid4())
        self.workflow_id = definition.get("workflow_id")
        self.run_id = run_id
        # M30a: opt-in observability hooks. Default to no-op so the
        # non-SSE call path (scheduled runs, /run endpoint) is unaffected.
        self._on_event = on_event
        self._cancel_event = cancel_event
        self._cancelled = False

        # M30a: WorkflowNodeRun row writes. When ``persist_node_runs``
        # is True, the executor opens its own ``SessionLocal()`` for
        # the row writes (lifecycle owned by the executor, closed in
        # the finally block). When False (the default, used by unit
        # tests that pass ``db=MagicMock()``), the executor still
        # emits on_event and checks cancel_event, but skips the row
        # writes entirely.
        self._meta_session = None
        if persist_node_runs:
            from lumen_core.database import SessionLocal
            self._meta_session = SessionLocal()
            self._sessions.append(self._meta_session)
        # Local import to avoid circular: models.workflow imports Base from
        # models.base which doesn't depend on workflow_executor, but
        # importing at module top means tests that mock workflow_executor
        # have to also stub models.workflow.
        from lumen_models.workflow import WorkflowNodeRun
        self._WorkflowNodeRun = WorkflowNodeRun

        total_nodes = len(definition.get("nodes", []))

        # Phase 1 Group B 4.4 Day 3 (2026-09-05): workflow.run root span + per
        # BFS iteration workflow.node child span。span attribute 用 workflow.*
        # 命名空间;status / duration_ms 在 finally 写。
        from opentelemetry import trace as _otel_trace
        from opentelemetry.trace import Status, StatusCode

        _run_span = _otel_trace.get_tracer("lumen.manual").start_span(
            "workflow.run",
            attributes={
                "workflow.run_id": int(run_id) if isinstance(run_id, int) else -1,
                "workflow.workflow_id": (
                    int(self.workflow_id) if isinstance(self.workflow_id, int) else -1
                ),
                "workflow.tenant_id": int(tenant_id) if isinstance(tenant_id, int) else -1,
                "workflow.total_nodes": total_nodes,
                "workflow.status": "running",
            },
        )
        _run_t0 = time.monotonic()
        _run_status = "completed"

        try:
            nodes: List[dict] = definition["nodes"]
            edges: List[dict] = definition["edges"]

            # 1. Inject input_data into the ["input", ...] namespace
            if isinstance(input_data, dict):
                for k, v in input_data.items():
                    self.pool.add(["input", k], v)
            else:
                self.pool.add(["input", "value"], input_data)

            # 2. Build reverse adjacency and find start nodes (no incoming edges)
            reverse_adj: Dict[str, List[str]] = {}
            for e in edges:
                reverse_adj.setdefault(e["target"], []).append(e["source"])
            start_nodes = [n["id"] for n in nodes if n["id"] not in reverse_adj]

            await self._emit(EVENT_RUN_START, {
                "run_id": run_id,
                "workflow_id": self.workflow_id,
                "total_nodes": total_nodes,
            })

            # 3. BFS
            queue = deque(start_nodes)
            ran: set[str] = set()
            execution_order = 0
            while queue:
                # M30a: cancel check at node boundary. We poll the event
                # with a tight timeout so the BFS still proceeds normally
                # if no cancel was ever issued. We never kill the
                # in-flight node — it runs to completion and we then
                # mark the run as cancelled in the finally block.
                if self._cancel_event is not None and self._cancel_event.is_set():
                    self._cancelled = True
                    logger.info(f"Workflow run {run_id} cancelled at boundary")
                    _run_status = "cancelled"
                    return {
                        "status": "cancelled",
                        "results": {
                            nid: r.model_dump() for nid, r in self.results.items()
                        },
                        "final_output": None,
                    }

                node_id = queue.popleft()
                if node_id in ran:
                    continue
                ran.add(node_id)
                node = next((n for n in nodes if n["id"] == node_id), None)
                if node is None:
                    continue

                node_started_at = datetime.utcnow()
                node_started_monotonic = time.monotonic()
                node_type = node.get("type", "unknown")

                # M30a: persist running row BEFORE executing, so the
                # frontend can see the node is in flight even if _run
                # blocks for 30s on a long LLM call.
                node_run_id = self._start_node_run(
                    node_id=node_id,
                    node_type=node_type,
                    started_at=node_started_at,
                    execution_order=execution_order,
                )

                await self._emit(EVENT_NODE_START, {
                    "run_id": run_id,
                    "node_id": node_id,
                    "node_type": node_type,
                    "execution_order": execution_order,
                })

                execution_order += 1

                # Phase 1 Group B 4.4 Day 3 (2026-09-05): workflow.node 子 span。
                # 用 set_span_in_context 把 _run_span 包成 Context 显式传给
                # start_span(context=...) — 比 use_span 嵌套 try/finally 干净。
                from opentelemetry.trace import set_span_in_context
                _parent_ctx = set_span_in_context(_run_span) if _run_span else None
                _node_span = _otel_trace.get_tracer("lumen.manual").start_span(
                    "workflow.node",
                    context=_parent_ctx,
                    attributes={
                        "workflow.node.id": str(node_id),
                        "workflow.node.type": str(node_type),
                        "workflow.node.execution_order": int(execution_order),
                        "workflow.run_id": int(run_id) if isinstance(run_id, int) else -1,
                    },
                )
                _node_status = "running"
                try:
                    node_instance = self._instantiate(node, tenant_id, user)
                    result = await run_node_with_handling(node_instance)
                    # P2: P1's BaseNode.run() also wrote outputs to pool. The
                    # helper only awaits _run() with retry/timeout — we replicate
                    # the pool-write here so downstream nodes still see upstream
                    # outputs (e.g. LLM template rendering reads from the pool).
                    if result is not _FAILED_RESULT:
                        result.node_id = result.node_id or node_id
                        result.outputs = node_instance.outputs()
                        for name, value in result.output_values.items():
                            node_instance.pool.add(
                                [node_instance.node_id, name], value
                            )
                    self.results[node_id] = result

                    duration_ms = int(
                        (time.monotonic() - node_started_monotonic) * 1000
                    )

                    if result is _FAILED_RESULT:
                        _node_status = "failed"
                        self._finish_node_run(
                            node_run_id=node_run_id,
                            status="failed",
                            error_message=result.error,
                        )

                        await self._emit(EVENT_NODE_END, {
                            "run_id": run_id,
                            "node_id": node_id,
                            "status": "failed",
                            "error_message": result.error,
                            "duration_ms": duration_ms,
                        })

                        _run_status = "failed"
                        try:
                            _node_span.set_attribute("workflow.node.status", _node_status)
                            _node_span.set_attribute(
                                "workflow.node.duration_ms",
                                int((time.monotonic() - node_started_monotonic) * 1000),
                            )
                        except Exception:  # noqa: BLE001
                            pass
                        finally:
                            try:
                                _node_span.end()
                            except Exception:  # noqa: BLE001
                                pass
                        return {
                            "status": "failed",
                            "error": result.error,
                            "results": {
                                nid: r.model_dump()
                                for nid, r in self.results.items()
                            },
                            "final_output": None,
                        }

                    # success path
                    _node_status = "completed"
                    self._finish_node_run(
                        node_run_id=node_run_id,
                        status="completed",
                        output_data=result.output_values,
                    )

                    await self._emit(EVENT_NODE_END, {
                        "run_id": run_id,
                        "node_id": node_id,
                        "status": "completed",
                        "output_data": result.output_values,
                        "duration_ms": duration_ms,
                    })

                    for nid in self._route(node, node_id, result, edges):
                        if nid not in ran:
                            queue.append(nid)
                except NodeRunError as e:
                    _node_status = "failed"
                    duration_ms = int(
                        (time.monotonic() - node_started_monotonic) * 1000
                    )
                    logger.exception(f"Node {node_id} NodeRunError: {e}")
                    self.results[node_id] = NodeRunResult(
                        node_id=node_id, error=str(e)
                    )

                    self._finish_node_run(
                        node_run_id=node_run_id,
                        status="failed",
                        error_message=str(e),
                    )

                    await self._emit(EVENT_NODE_END, {
                        "run_id": run_id,
                        "node_id": node_id,
                        "status": "failed",
                        "error_message": str(e),
                        "duration_ms": duration_ms,
                    })
                    await self._emit(EVENT_ERROR, {
                        "run_id": run_id,
                        "node_id": node_id,
                        "error_message": str(e),
                    })

                    try:
                        from opentelemetry.trace import Status as _St, StatusCode as _Sc
                        _node_span.record_exception(e)
                        _node_span.set_status(_St(_Sc.ERROR, str(e)[:200]))
                    except Exception:  # noqa: BLE001
                        pass
                    _run_status = "failed"
                    # Phase 1 Group B 4.4 Day 3: workflow.node span 收尾
                    try:
                        _node_span.set_attribute("workflow.node.status", _node_status)
                        _node_span.set_attribute(
                            "workflow.node.duration_ms",
                            int((time.monotonic() - node_started_monotonic) * 1000),
                        )
                    except Exception:  # noqa: BLE001
                        pass
                    finally:
                        try:
                            _node_span.end()
                        except Exception:  # noqa: BLE001
                            pass
                    return {
                        "status": "failed",
                        "error": str(e),
                        "results": {nid: r.model_dump() for nid, r in self.results.items()},
                        "final_output": None,
                    }
                finally:
                    # Phase 1 Group B 4.4 Day 3: workflow.node span 收尾
                    # (覆盖非 except 的成功 + NodeRunError 之外的异常路径)
                    try:
                        _node_span.set_attribute("workflow.node.status", _node_status)
                        _node_span.set_attribute(
                            "workflow.node.duration_ms",
                            int((time.monotonic() - node_started_monotonic) * 1000),
                        )
                    except Exception:  # noqa: BLE001
                        pass
                    finally:
                        try:
                            _node_span.end()
                        except Exception:  # noqa: BLE001
                            pass

            final_output = self._collect_final_output()
            await self._emit(EVENT_RUN_END, {
                "run_id": run_id,
                "status": "completed",
                "final_output": final_output,
            })
            return {
                "status": "completed",
                "results": {nid: r.model_dump() for nid, r in self.results.items()},
                "final_output": final_output,
            }
        finally:
            for session in self._sessions:
                try:
                    session.close()
                except Exception:
                    logger.warning("Failed to close executor session", exc_info=True)
            # Phase 1 Group B 4.4 Day 3: workflow.run root span 收尾。
            try:
                _run_span.set_attribute("workflow.status", _run_status)
                _run_span.set_attribute(
                    "workflow.duration_ms",
                    int((time.monotonic() - _run_t0) * 1000),
                )
                _run_span.set_attribute(
                    "workflow.completed_nodes",
                    len(self.results or {}),
                )
                if _run_status == "failed":
                    _run_span.set_status(Status(StatusCode.ERROR, "workflow failed"))
                elif _run_status == "cancelled":
                    _run_span.set_attribute("workflow.cancelled", True)
            except Exception:  # noqa: BLE001
                logger.debug("workflow.run span attr write failed; ignored", exc_info=True)
            finally:
                try:
                    _run_span.end()
                except Exception:  # noqa: BLE001
                    pass

    async def _emit(self, event: str, data: Dict[str, Any]) -> None:
        """M30a: best-effort event emission. A failure here must NEVER
        abort the run — the run is the source of truth, the event stream
        is a UX nicety.
        """
        if self._on_event is None:
            return
        try:
            await self._on_event(event, data)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"on_event callback raised: {e}", exc_info=True)

    def _start_node_run(
        self,
        *,
        node_id: str,
        node_type: str,
        started_at: datetime,
        execution_order: int,
    ) -> Optional[int]:
        """M30a: insert a 'running' WorkflowNodeRun row and return its id.
        No-op when ``meta_session`` is None (unit tests that pass
        ``db=MagicMock()``). Returns the inserted row's id, or None
        when the write is skipped.
        """
        if self._meta_session is None:
            return None
        node_run = self._WorkflowNodeRun(
            run_id=self.run_id,
            node_id=node_id,
            node_type=node_type,
            status="running",
            started_at=started_at,
            execution_order=execution_order,
        )
        self._meta_session.add(node_run)
        self._meta_session.commit()
        self._meta_session.refresh(node_run)
        return node_run.id

    def _finish_node_run(
        self,
        *,
        node_run_id: Optional[int],
        status: str,
        output_data: Optional[Dict[str, Any]] = None,
        error_message: Optional[str] = None,
    ) -> None:
        """M30a: update a WorkflowNodeRun row to completed/failed.
        No-op when meta_session is None or node_run_id is None.
        """
        if self._meta_session is None or node_run_id is None:
            return
        update: Dict[str, Any] = {
            "status": status,
            "finished_at": datetime.utcnow(),
        }
        if output_data is not None:
            update["output_data"] = output_data
        if error_message is not None:
            update["error_message"] = error_message
        self._meta_session.query(self._WorkflowNodeRun).filter(
            self._WorkflowNodeRun.id == node_run_id
        ).update(update)
        self._meta_session.commit()

    def _instantiate(self, node: dict, tenant_id: int, user: Optional["User"] = None):
        # SPEC FIX: open a session per node and track it for cleanup
        from lumen_core.database import SessionLocal
        session = SessionLocal()
        self._sessions.append(session)
        cls = resolve_node_class(
            node["type"], node.get("config", {}).get("version", "1")
        )
        # M26: propagate trace/workflow/run identifiers so node subclasses
        # (e.g. LLMNode) can stamp LLMCallContext rows correctly.
        config = {
            **(node.get("config") or {}),
            "tenant_id": tenant_id,
            "workflow_id": self.workflow_id,
            "workflow_run_id": self.run_id,
            "trace_id": self.trace_id,
        }
        return cls(
            node_id=node["id"],
            config=config,
            pool=self.pool,  # type: ignore[arg-type]
            db=session,
            tenant_id=tenant_id,
            user=user,
        )

    def _route(
        self, node: dict, node_id: str, result: NodeRunResult, edges: List[dict]
    ) -> List[str]:
        outgoing = [e for e in edges if e["source"] == node_id]
        if node["type"] == "condition":
            handle = result.edge_source_handle or "false"
            return [
                e["target"]
                for e in outgoing
                if e.get("sourceHandle", "default") == handle
            ]
        return [e["target"] for e in outgoing]

    def _collect_final_output(self) -> Optional[dict]:
        """Return the last OutputNode's value, or None if no OutputNode ran."""
        # SPEC FIX: precompute output_node_ids for O(n) filtering
        nodes = self.definition.get("nodes", [])
        output_node_ids = {n["id"] for n in nodes if n.get("type") == "output"}
        output_results = [r for nid, r in self.results.items() if nid in output_node_ids]
        if not output_results:
            return None
        last = output_results[-1]
        return {"value": last.output_values.get("value"), "outputs": last.output_values}
