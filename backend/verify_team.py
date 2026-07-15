"""Verification script for the multi-agent team feature.

Run with the backend up on http://localhost:11335 (FastAPI) and at least
two existing Agent rows in the DB for the demo tenant.

Usage:
    python verify_team.py

Exits 0 on success, non-zero on any assertion failure.
"""
from __future__ import annotations

import json
import sys
import time

import requests

BASE = "http://localhost:11335/api/v1"
USERNAME = "admin"
PASSWORD = "admin123"


def fail(msg: str) -> None:
    print(f"FAIL: {msg}")
    sys.exit(1)


def ok(msg: str) -> None:
    print(f"OK:   {msg}")


def main() -> None:
    # 1. login
    r = requests.post(
        f"{BASE}/auth/login",
        data={"username": USERNAME, "password": PASSWORD},
        timeout=15,
    )
    if r.status_code != 200:
        fail(f"login HTTP {r.status_code}: {r.text[:200]}")
    token = r.json().get("data", {}).get("access_token")
    if not token:
        fail(f"no access_token in login response: {r.text[:200]}")
    ok("logged in")
    headers = {"Authorization": f"Bearer {token}"}

    # 2. list existing agents; bootstrap if we have fewer than 3
    r = requests.get(f"{BASE}/agents/?page=1&page_size=50", headers=headers, timeout=15)
    if r.status_code != 200:
        fail(f"list agents HTTP {r.status_code}: {r.text[:200]}")
    agents = r.json().get("data") or []

    def _create_agent(name: str, prompt: str) -> dict:
        # Pick the first model the user has configured
        mr = requests.get(f"{BASE}/models/?page=1&page_size=20", headers=headers, timeout=15)
        model_name = None
        if mr.status_code == 200:
            for m in (mr.json().get("data") or []):
                if m.get("model_name"):
                    model_name = m["model_name"]
                    break
        payload = {
            "name": name,
            "description": f"auto-created by verify_team.py ({name})",
            "prompt_template": prompt,
            "model_name": model_name or "gpt-4o",
            "temperature": 0,
        }
        rr = requests.post(f"{BASE}/agents/", json=payload, headers=headers, timeout=20)
        if rr.status_code != 200:
            fail(f"create agent {name} HTTP {rr.status_code}: {rr.text[:400]}")
        return rr.json().get("data") or {}

    while len(agents) < 3:
        idx = len(agents) + 1
        created = _create_agent(
            f"verify-agent-{idx}-{int(time.time())}",
            "你是一个测试智能体，请用中文简短回答问题。",
        )
        agents.append(created)

    manager = agents[0]
    worker_a = agents[1]
    worker_b = agents[2]
    ok(f"agents ready: manager={manager['name']}, "
       f"workers={worker_a['name']}, {worker_b['name']}")

    # 3. create the team
    payload = {
        "name": f"verify-team-{int(time.time())}",
        "description": "auto-created by verify_team.py",
        "manager_agent_id": manager["id"],
        "route_policy": "manager_decides",
        "members": [
            {"agent_id": worker_a["id"], "role": "researcher", "priority": 10},
            {"agent_id": worker_b["id"], "role": "writer", "priority": 20},
        ],
    }
    r = requests.post(f"{BASE}/agent-teams/", json=payload, headers=headers, timeout=20)
    if r.status_code != 200:
        fail(f"create team HTTP {r.status_code}: {r.text[:400]}")
    team = r.json().get("data") or {}
    team_id = team.get("id")
    if not team_id:
        fail(f"no team id in response: {r.text[:400]}")
    ok(f"created team id={team_id} with {len(team.get('members') or [])} members")

    # 4. list teams
    r = requests.get(f"{BASE}/agent-teams/?page=1&page_size=50", headers=headers, timeout=15)
    if r.status_code != 200 or not r.json().get("data"):
        fail(f"list teams HTTP {r.status_code}: {r.text[:200]}")
    ok(f"team listed (total={r.json().get('total')})")

    # 5. chat (real LLM call — may take a while)
    chat_payload = {"message": "你好，请简短介绍一下你自己。", "history": []}
    print("    ...running team chat (this calls real LLM)...")
    r = requests.post(
        f"{BASE}/agent-teams/{team_id}/chat",
        json=chat_payload,
        headers=headers,
        timeout=180,
    )
    if r.status_code != 200:
        fail(f"team chat HTTP {r.status_code}: {r.text[:400]}")
    body = r.json()
    if body.get("code") != 200:
        fail(f"team chat bad code: {body}")
    chat = body.get("data") or {}
    final = (chat.get("final_answer") or "").strip()
    if not final:
        fail(f"empty final_answer: {json.dumps(chat, ensure_ascii=False)[:500]}")
    if len(final) < 4:
        fail(f"final_answer suspiciously short: {final!r}")
    workers_out = chat.get("worker_outputs") or []
    if not workers_out:
        fail(f"no worker_outputs in response: {json.dumps(chat, ensure_ascii=False)[:500]}")
    worker_names = {w.get("agent_name") for w in workers_out}
    ok(
        f"chat OK: policy={chat.get('policy_used')}, "
        f"routing={chat.get('routing_decision')}, "
        f"workers={sorted(worker_names)}, "
        f"final_len={len(final)}"
    )

    # 6. cleanup: delete the team
    r = requests.delete(f"{BASE}/agent-teams/{team_id}", headers=headers, timeout=15)
    if r.status_code != 200:
        print(f"WARN: cleanup delete team HTTP {r.status_code}: {r.text[:200]}")
    else:
        ok("cleanup: team deleted")

    # 7. print sample
    print("\n=== SAMPLE INPUT ===")
    print(json.dumps(chat_payload, ensure_ascii=False))
    print("=== SAMPLE OUTPUT ===")
    print(json.dumps(
        {
            "final_answer": final,
            "manager_reasoning": chat.get("manager_reasoning"),
            "routing_decision": chat.get("routing_decision"),
            "policy_used": chat.get("policy_used"),
            "worker_outputs": [
                {
                    "agent_id": w.get("agent_id"),
                    "agent_name": w.get("agent_name"),
                    "role": w.get("role"),
                    "response_preview": (w.get("response") or "")[:120],
                }
                for w in workers_out
            ],
        },
        ensure_ascii=False,
        indent=2,
    ))
    print("\nALL CHECKS PASSED")


if __name__ == "__main__":
    main()
