"""End-to-end tests for the local MCP demo server.

Spawns a real uvicorn process running the FastMCP app, then sends JSON-RPC
requests over HTTP and asserts the responses.

The MCP server in mcp==1.2.0 uses SSE transport (not Streamable HTTP). The
protocol is:

  1. Client opens GET /sse to establish a long-lived event stream.
  2. Server sends an ``endpoint`` event with a session-scoped POST URL like
     ``/messages/?session_id=<uuid>``.
  3. Client POSTs JSON-RPC requests to that URL.
  4. Server delivers the JSON-RPC response back over the GET stream.

Requires:
  - MySQL reachable at the configured URL (for DB-backed tools)
  - Port to be free (the test asks the OS for one)
"""
import json
import os
import queue
import socket
import subprocess
import sys
import threading
import time
import uuid
from typing import Tuple

import httpx
import pytest

BACKEND_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
# mcp==1.2.0 SSE transport paths.
MCP_SSE_PATH = "/sse"
MCP_POST_PATH = "/messages/"


def _free_port() -> int:
    """Ask the OS for a free TCP port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def mcp_server() -> Tuple[str, int, subprocess.Popen]:
    """Start the FastMCP app on a free port; return (host, port, process)."""
    port = _free_port()
    # ``local_demo.py`` explicitly imports the transitive SQLAlchemy
    # relationship targets (Tenant, User, Document, …) so the subprocess
    # can boot in isolation — same as a real ``python run_mcp_server.py``
    # deployment would. No pre-import bootstrap hack needed.
    proc = subprocess.Popen(
        [
            sys.executable, "-m", "uvicorn", "lumen_mcp_servers.local_demo:app",
            "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning",
        ],
        cwd=BACKEND_ROOT,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    # Poll until the server accepts connections.
    #
    # Empirically the cold-start import chain is ~15-20s on Windows:
    #   - pydantic model validation warnings (4)             ~0.5s
    #   - jieba pkg_resources deprecation warning + load     ~12-14s
    #     (jieba 0.42 still imports pkg_resources at module
    #      load; that walk over setuptools' egg-info directory
    #      is the dominant cost on a cold start)
    #   - FastMCP + SQLAlchemy + langchain module imports     ~2-3s
    # The original 10s deadline was set pre-jieba-pkg_resources
    # and is no longer sufficient; bump to 30s which still
    # fails fast on a real hang (socket not accepting) but
    # accommodates the slow-path cold start.
    deadline = time.time() + 30
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                break
        except OSError:
            time.sleep(0.2)
    else:
        proc.terminate(); proc.wait()
        stderr = proc.stderr.read().decode("utf-8", "replace") if proc.stderr else ""
        raise RuntimeError(
            f"MCP server did not become ready on port {port} in 30s.\nSTDERR: {stderr}"
        )
    yield ("127.0.0.1", port, proc)
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


def _jsonrpc(method: str, params: dict, id_: int = 1) -> dict:
    return {"jsonrpc": "2.0", "id": id_, "method": method, "params": params}


class _McpSseClient:
    """Minimal MCP-over-SSE client for the e2e test.

    A background thread reads the GET /sse stream line-by-line and assembles
    SSE events, pushing them onto a queue. The main thread POSTs JSON-RPC
    requests and pops the next matching event off the queue.
    """

    def __init__(self, base_url: str):
        self._base_url = base_url
        # One HTTP client for the long-lived streaming GET and the
        # session-scoped POSTs.
        self._client = httpx.Client(timeout=None)
        self._cm = self._client.stream("GET", base_url + MCP_SSE_PATH)
        # __enter__ returns the Response itself (httpx.Response).
        self._response = self._cm.__enter__()
        # Verify the content type is SSE.
        ct = self._response.headers.get("content-type", "")
        assert "text/event-stream" in ct, (
            f"GET /sse did not return text/event-stream; got content-type={ct!r}"
        )

        self._queue: "queue.Queue[dict]" = queue.Queue()
        self._closed = False
        # Reader thread pulls lines from the stream and assembles events.
        self._reader = threading.Thread(
            target=self._read_loop, name="mcp-sse-reader", daemon=True,
        )
        self._reader.start()

        # First event must be the 'endpoint' event with our session-scoped URL.
        first = self._pop_event(timeout=10.0)
        assert first and first["event"] == "endpoint", (
            f"Expected first SSE event to be 'endpoint', got: {first!r}"
        )
        endpoint_path = first["data"]
        self._post_url = base_url + endpoint_path
        self._session_id = endpoint_path.split("session_id=", 1)[-1]

        # MCP requires an initialize handshake before any other request.
        # The server won't process tools/list until it has seen initialize +
        # the notifications/initialized notification.
        self._do_handshake()

    def _do_handshake(self):
        """Send ``initialize`` and the ``initialized`` notification.

        After the handshake, the MCP server is ready to process normal
        requests like ``tools/list`` and ``tools/call``.
        """
        import time as _time
        _time.sleep(0.05)  # let the SSE writer task settle
        # 1) initialize request
        init = {
            "jsonrpc": "2.0", "id": 0, "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "e2e-test", "version": "0.0.1"},
            },
        }
        self._post_raw(init)
        init_resp = self._pop_event(timeout=10.0)
        assert init_resp is not None, "No SSE response for initialize"
        body = json.loads(init_resp["data"])
        assert "result" in body, f"initialize failed: {body!r}"
        # 2) notifications/initialized (no response expected)
        notif = {
            "jsonrpc": "2.0", "method": "notifications/initialized", "params": {},
        }
        self._post_raw(notif)

    @property
    def session_id(self) -> str:
        return self._session_id

    def _read_loop(self):
        """Background loop: read lines, assemble SSE events, push to queue."""
        try:
            pending: list = []
            for line in self._response.iter_lines():
                if self._closed:
                    return
                if line == "":
                    if not pending:
                        continue
                    event: dict = {"event": None, "data": ""}
                    for raw in pending:
                        if raw.startswith("event: "):
                            event["event"] = raw[len("event: "):]
                        elif raw.startswith("data: "):
                            payload = raw[len("data: "):]
                            event["data"] = (
                                event["data"] + "\n" + payload
                                if event["data"] else payload
                            )
                    pending = []
                    self._queue.put(event)
                else:
                    pending.append(line)
        except Exception as e:
            # Surface the error to any blocked caller.
            self._queue.put({"_error": repr(e)})

    def _pop_event(self, timeout: float) -> dict | None:
        """Pop the next SSE event off the queue, respecting a deadline."""
        try:
            evt = self._queue.get(timeout=timeout)
        except queue.Empty:
            return None
        if "_error" in evt:
            raise RuntimeError(f"SSE reader thread failed: {evt['_error']}")
        return evt

    def _post_raw(self, payload: dict) -> httpx.Response:
        """POST a JSON-RPC payload to the session-scoped messages URL."""
        resp = self._client.post(
            self._post_url, json=payload,
            headers={"Accept": "text/event-stream"},
        )
        assert resp.status_code in (200, 202), (
            f"POST to {self._post_url} returned {resp.status_code}: {resp.text!r}"
        )
        return resp

    def call(self, method: str, params: dict, id_: int = 1, timeout: float = 10.0) -> dict:
        payload = _jsonrpc(method, params, id_)
        self._post_raw(payload)
        # The response comes back over the GET stream as an SSE event.
        event = self._pop_event(timeout=timeout)
        assert event is not None, f"No SSE response event received for {method}"
        return json.loads(event["data"])

    def close(self):
        self._closed = True
        try:
            self._cm.__exit__(None, None, None)
        finally:
            self._client.close()


@pytest.fixture(scope="module")
def mcp_client(mcp_server):
    host, port, _proc = mcp_server
    base_url = f"http://{host}:{port}"
    client = _McpSseClient(base_url)
    try:
        yield client
    finally:
        client.close()


class TestToolsList:
    def test_returns_six_tools(self, mcp_client):
        body = mcp_client.call("tools/list", {})
        assert "result" in body, f"Unexpected body: {body!r}"
        tools = body["result"]["tools"]
        assert len(tools) == 6
        names = {t["name"] for t in tools}
        assert names == {
            "list_agents", "list_knowledge_bases", "search_knowledge_base",
            "list_chat_sessions", "list_workflows", "run_workflow",
        }
        # Each tool must declare an inputSchema.
        for t in tools:
            assert "inputSchema" in t
            assert t["inputSchema"]["type"] == "object"


class TestResponseIsSse:
    def test_tools_list_response_uses_sse_format(self, mcp_client):
        """A successful round-trip proves the GET /sse delivers SSE events.

        If the server's POST response were synchronous (not delivered on the
        GET stream), this call would hang and time out — the act of parsing
        the JSON from an SSE ``data:`` frame is the proof.
        """
        body = mcp_client.call("tools/list", {})
        assert "result" in body

    def test_get_sse_endpoint_returns_event_stream(self, mcp_server):
        """GET /sse must return Content-Type: text/event-stream."""
        host, port, _proc = mcp_server
        with httpx.Client(timeout=5) as client:
            with client.stream("GET", f"http://{host}:{port}{MCP_SSE_PATH}") as resp:
                ct = resp.headers.get("content-type", "")
                assert "text/event-stream" in ct, (
                    f"Expected text/event-stream, got content-type={ct!r}"
                )


class TestToolsCall:
    def test_list_agents_returns_data(self, mcp_client, tmp_user):
        """End-to-end: insert an agent, call list_agents, verify the agent appears."""
        from lumen_core.database import SessionLocal
        from lumen_models.agent import Agent

        suffix = uuid.uuid4().hex[:8]
        db = SessionLocal()
        try:
            agent = Agent(
                name=f"e2e-{suffix}", description="end-to-end test",
                prompt_template="hi", tenant_id=tmp_user.tenant_id, is_active=True,
            )
            db.add(agent); db.commit(); db.refresh(agent)
            agent_id = agent.id
        finally:
            db.close()

        body = mcp_client.call("tools/call", {
            "name": "list_agents",
            "arguments": {"limit": 50},
        })
        assert body.get("error") is None, f"MCP error: {body.get('error')}"
        result = body["result"]
        assert result["isError"] is False
        # content[0].text contains the JSON-stringified return value.
        text_payload = result["content"][0]["text"]
        payload = json.loads(text_payload)
        assert payload["ok"] is True
        assert any(a["id"] == agent_id for a in payload["data"]), (
            f"Inserted agent {agent_id} not found in: {payload['data']}"
        )
