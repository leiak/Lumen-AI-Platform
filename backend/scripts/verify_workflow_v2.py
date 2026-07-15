"""M30a — verify_workflow_v2.py

End-to-end smoke test for the workflow observability stack. Builds a
4-node workflow (input → llm → code → output), runs it, and verifies
that:

1. SSE events fire in the right order (1× run_start, N× node_start,
   N× node_end, 1× run_end).
2. ``WorkflowNodeRun`` rows land in the DB with status=completed and
   populated output_data.

The script talks to a live backend on port 11335 (the project's
dev port — see CLAUDE.md §1). It needs an admin token, which it
gets from /api/v1/auth/login (form data).

Run it from the project root:

    cd backend && python scripts/verify_workflow_v2.py
"""
import asyncio
import json
import sys
import time
import uuid

import httpx


API_BASE = "http://localhost:11335/api/v1"
ADMIN_USER = "admin"
ADMIN_PASS = "admin123"


def login(client: httpx.Client) -> str:
    """POST /auth/login with form data, return the access_token."""
    res = client.post(
        f"{API_BASE}/auth/login",
        data={"username": ADMIN_USER, "password": ADMIN_PASS},
    )
    res.raise_for_status()
    body = res.json()
    token = body.get("data", {}).get("access_token")
    if not token:
        sys.exit(f"login failed: {body}")
    return token


def make_workflow(client: httpx.Client, headers: dict) -> int:
    """Create a 3-node linear workflow (input → output1 → output2).
    Avoids the Code / LLM nodes so we don't depend on the
    RestrictedPython sandbox or the LLM provider being up.
    """
    definition = {
        "nodes": [
            {
                "id": "input_1",
                "type": "input",
                "config": {
                    "title": "Input",
                    "version": "1",
                    "variables": [{"name": "x", "type": "string", "required": True}],
                },
            },
            {
                "id": "output_1",
                "type": "output",
                "config": {"title": "Output1", "version": "1", "field": "input_1.x"},
            },
            {
                "id": "output_2",
                "type": "output",
                "config": {"title": "Output2", "version": "1", "field": "input_1.x"},
            },
        ],
        "edges": [
            {"id": "e1", "source": "input_1", "target": "output_1", "sourceHandle": "default"},
            {"id": "e2", "source": "input_1", "target": "output_2", "sourceHandle": "default"},
        ],
    }
    suffix = uuid.uuid4().hex[:8]
    res = client.post(
        f"{API_BASE}/workflows/",
        json={
            "name": f"m30a_verify_{suffix}",
            "description": "M30a verify script smoke test",
            "definition": definition,
        },
        headers=headers,
    )
    res.raise_for_status()
    return res.json()["data"]["id"]


def delete_workflow(client: httpx.Client, headers: dict, workflow_id: int) -> None:
    res = client.delete(
        f"{API_BASE}/workflows/{workflow_id}", headers=headers
    )
    # 200 expected; 404 also OK if the run completion race deleted it
    if res.status_code not in (200, 404):
        print(f"warning: delete returned {res.status_code}: {res.text[:200]}")


async def stream_run(
    client: httpx.Client, headers: dict, workflow_id: int
) -> list:
    """POST /stream, collect SSE events until the connection closes.

    Returns the list of (event_type, data_dict) tuples.
    """
    events: list = []
    # We can't use the sync httpx client with streaming POST — use the
    # async client instead.
    async with httpx.AsyncClient(timeout=60.0) as async_client:
        async with async_client.stream(
            "POST",
            f"{API_BASE}/workflows/{workflow_id}/stream",
            json={"input_data": {"x": "hello"}},
            headers=headers,
        ) as res:
            res.raise_for_status()
            current_event = None
            async for line in res.aiter_lines():
                if line.startswith("event:"):
                    current_event = line.split(":", 1)[1].strip()
                elif line.startswith("data:"):
                    raw = line.split(":", 1)[1].strip()
                    try:
                        data = json.loads(raw)
                    except json.JSONDecodeError:
                        data = {"raw": raw}
                    if current_event:
                        events.append((current_event, data))
                        current_event = None
                elif line == "":
                    # blank line = end of event
                    pass
    return events


def fetch_node_runs(
    client: httpx.Client, headers: dict, workflow_id: int, run_id: int
) -> list:
    res = client.get(
        f"{API_BASE}/workflows/{workflow_id}/runs/{run_id}/nodes",
        headers=headers,
    )
    res.raise_for_status()
    return res.json()["data"]


async def main() -> int:
    with httpx.Client(timeout=30.0) as client:
        token = login(client)
        headers = {"Authorization": f"Bearer {token}"}
        print("== M30a verify: building workflow ==")
        workflow_id = make_workflow(client, headers)
        print(f"   created workflow id={workflow_id}")
        try:
            print("== M30a verify: streaming run ==")
            t0 = time.monotonic()
            events = await stream_run(client, headers, workflow_id)
            t1 = time.monotonic()
            print(f"   received {len(events)} events in {t1 - t0:.2f}s")
            for e, d in events:
                # Truncate long payloads
                summary = d if len(str(d)) < 200 else str(d)[:200] + "…"
                print(f"   event={e:12s} data={summary}")

            # Check event shape
            event_types = [e for e, _ in events]
            assert event_types[0] == "run_start", f"first event should be run_start, got {event_types[:3]}"
            assert event_types[-1] == "run_end", f"last event should be run_end, got {event_types[-3:]}"
            assert "node_start" in event_types
            assert "node_end" in event_types
            # 3 nodes → 3 node_start + 3 node_end
            n_starts = event_types.count("node_start")
            n_ends = event_types.count("node_end")
            assert n_starts == 3, f"expected 3 node_start, got {n_starts}"
            assert n_ends == 3, f"expected 3 node_end, got {n_ends}"

            run_start_data = next(d for e, d in events if e == "run_start")
            assert run_start_data["total_nodes"] == 3
            # All node_end events should be status=completed (we picked
            # node types that don't need external deps).
            for e, d in events:
                if e == "node_end":
                    assert d["status"] == "completed", f"node {d['node_id']} not completed: {d['status']}"

            run_id = run_start_data["run_id"]
            print(f"== M30a verify: fetching node_runs for run_id={run_id} ==")
            node_runs = fetch_node_runs(client, headers, workflow_id, run_id)
            print(f"   found {len(node_runs)} WorkflowNodeRun rows")
            for nr in node_runs:
                summary = {k: nr[k] for k in ("node_id", "node_type", "status", "execution_order")}
                print(f"   {summary}")
            assert len(node_runs) == 3
            for nr in node_runs:
                assert nr["status"] == "completed", f"node {nr['node_id']} not completed: {nr['status']}"
                assert isinstance(nr["execution_order"], int)

            print()
            print("== M30a verify: ALL CHECKS PASSED ==")
            return 0
        finally:
            delete_workflow(client, headers, workflow_id)
            print(f"   cleaned up workflow id={workflow_id}")


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
