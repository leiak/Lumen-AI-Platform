"""Verification script for Task 8: Agent Memory Policy + Tool Choice.

Exercises the new ``memory_policy`` / ``tool_choice`` / ``allowed_tools``
fields end-to-end against the running backend.

Steps:
    1. Log in to the API.
    2. Create an agent with non-default memory policy (token_limit,
       memory_max_tokens=500) and tool_choice="specific" with an
       (empty-by-default) allowed_tools list.
    3. Read the agent back and assert all new fields are present and
       round-trip correctly.
    4. Run a chat against that agent. The response must be a non-empty
       string. We also send a multi-turn history to exercise the
       memory policy in the run path.
    5. Update the agent (change policy + tool_choice) and re-read.

Usage:
    python verify_memory_tool_choice.py [base_url]

If ``base_url`` is omitted we default to http://localhost:11335.
"""
from __future__ import annotations

import json
import os
import sys
import time

import requests


DEFAULT_BASES = [
    "http://localhost:11335/api/v1",
]

USERNAME = "admin"
PASSWORD = "admin123"


def fail(msg: str) -> None:
    print(f"FAIL: {msg}")
    sys.exit(1)


def ok(msg: str) -> None:
    print(f"OK:   {msg}")


def pick_base() -> str:
    """Pick the first base that responds to a login attempt."""
    explicit = os.environ.get("VERIFY_BASE")
    if explicit:
        return explicit
    for base in [sys.argv[1]] if len(sys.argv) > 1 else []:
        return base
    for base in DEFAULT_BASES:
        try:
            r = requests.post(
                f"{base}/auth/login",
                data={"username": USERNAME, "password": PASSWORD},
                timeout=5,
            )
            if r.status_code == 200:
                return base
        except Exception:
            continue
    fail(f"no backend responding on {DEFAULT_BASES}")
    return ""  # unreachable


def login(base: str) -> str:
    r = requests.post(
        f"{base}/auth/login",
        data={"username": USERNAME, "password": PASSWORD},
        timeout=10,
    )
    if r.status_code != 200:
        fail(f"login HTTP {r.status_code}: {r.text[:200]}")
    data = r.json().get("data") or {}
    token = data.get("access_token")
    if not token:
        fail(f"no access_token in login response: {r.text[:200]}")
    return token


def _pick_model(base: str, headers: dict) -> str:
    try:
        r = requests.get(f"{base}/models/?page=1&page_size=20", headers=headers, timeout=10)
        if r.status_code == 200:
            for m in (r.json().get("data") or []):
                if m.get("model_name"):
                    return m["model_name"]
    except Exception:
        pass
    return "gpt-4o"


def main() -> None:
    base = pick_base()
    print(f"Using base URL: {base}")
    token = login(base)
    headers = {"Authorization": f"Bearer {token}"}
    ok("logged in")

    model_name = _pick_model(base, headers)
    print(f"Using model: {model_name}")

    # 1. Create agent with new policy fields
    ts = int(time.time())
    payload = {
        "name": f"verify-memtool-{ts}",
        "description": "auto-created by verify_memory_tool_choice.py",
        "prompt_template": "你是一个测试智能体，请用中文简短回答问题。",
        "model_name": model_name,
        "temperature": 0,
        # Task 8 fields
        "memory_policy": "token_limit",
        "memory_window_size": 25,
        "memory_max_tokens": 500,
        "memory_compression": False,
        "tool_choice": "specific",
        "tool_choice_required": False,
        "allowed_tools": ["nonexistent_tool_for_test"],
    }
    r = requests.post(f"{base}/agents/", json=payload, headers=headers, timeout=20)
    if r.status_code != 200:
        fail(f"create agent HTTP {r.status_code}: {r.text[:400]}")
    agent = r.json().get("data") or {}
    agent_id = agent.get("id")
    if not agent_id:
        fail(f"no agent id in response: {r.text[:400]}")
    ok(f"created agent id={agent_id} name={agent.get('name')!r}")

    # 2. Assert all new fields are in the create response
    for field in [
        "memory_policy",
        "memory_window_size",
        "memory_max_tokens",
        "memory_compression",
        "tool_choice",
        "tool_choice_required",
        "allowed_tools",
    ]:
        if field not in agent:
            fail(f"create response missing field {field!r}: {json.dumps(agent, ensure_ascii=False)[:300]}")
    if agent["memory_policy"] != "token_limit":
        fail(f"memory_policy mismatch: {agent['memory_policy']!r}")
    if agent["memory_max_tokens"] != 500:
        fail(f"memory_max_tokens mismatch: {agent['memory_max_tokens']!r}")
    if agent["tool_choice"] != "specific":
        fail(f"tool_choice mismatch: {agent['tool_choice']!r}")
    if agent["allowed_tools"] != ["nonexistent_tool_for_test"]:
        fail(f"allowed_tools mismatch: {agent['allowed_tools']!r}")
    ok("create response contains all new fields with correct values")

    # 3. Re-read and assert again
    r = requests.get(f"{base}/agents/{agent_id}", headers=headers, timeout=10)
    if r.status_code != 200:
        fail(f"get agent HTTP {r.status_code}: {r.text[:400]}")
    fetched = (r.json().get("data") or {})
    if fetched.get("memory_policy") != "token_limit":
        fail(f"GET memory_policy mismatch: {fetched.get('memory_policy')!r}")
    if fetched.get("memory_max_tokens") != 500:
        fail(f"GET memory_max_tokens mismatch: {fetched.get('memory_max_tokens')!r}")
    if fetched.get("tool_choice") != "specific":
        fail(f"GET tool_choice mismatch: {fetched.get('tool_choice')!r}")
    if fetched.get("allowed_tools") != ["nonexistent_tool_for_test"]:
        fail(f"GET allowed_tools mismatch: {fetched.get('allowed_tools')!r}")
    ok("GET /agents/{id} returns all new fields correctly")

    # 4. Chat — exercise the memory policy in the run path
    # Build a long history (well over the 500-token budget) so the
    # token_limit policy actually has work to do.
    history = []
    for i in range(20):
        history.append({"role": "user", "content": f"这是历史消息 #{i}：" + ("填充文字" * 30)})
        history.append({"role": "assistant", "content": f"回复 #{i}：" + ("占位内容" * 30)})
    chat_payload = {
        "agent_id": agent_id,
        "message": "你好，请用一句话总结上面你看到的内容。",
        "history": history,
    }
    print("    ...running chat (this calls real LLM, may take ~30s)...")
    r = requests.post(
        f"{base}/agents/{agent_id}/chat",
        json=chat_payload,
        headers=headers,
        timeout=180,
    )
    if r.status_code != 200:
        fail(f"chat HTTP {r.status_code}: {r.text[:400]}")
    body = r.json()
    if body.get("code") != 200:
        fail(f"chat bad code: {body}")
    chat_data = body.get("data") or {}
    response_text = (chat_data.get("response") or "").strip()
    if not response_text:
        fail(f"empty chat response: {json.dumps(chat_data, ensure_ascii=False)[:500]}")
    if len(response_text) < 2:
        fail(f"chat response suspiciously short: {response_text!r}")
    ok(f"chat OK (response_len={len(response_text)})")

    # 5. Update the agent and re-read
    update_payload = {
        "memory_policy": "semantic_compression",
        "memory_compression": True,
        "memory_window_size": 10,
        "tool_choice": "required",
        "tool_choice_required": True,
        "allowed_tools": ["a", "b"],
    }
    r = requests.put(
        f"{base}/agents/{agent_id}",
        json=update_payload,
        headers=headers,
        timeout=20,
    )
    if r.status_code != 200:
        fail(f"update agent HTTP {r.status_code}: {r.text[:400]}")
    updated = (r.json().get("data") or {})
    if updated.get("memory_policy") != "semantic_compression":
        fail(f"UPDATE memory_policy mismatch: {updated.get('memory_policy')!r}")
    if updated.get("tool_choice") != "required":
        fail(f"UPDATE tool_choice mismatch: {updated.get('tool_choice')!r}")
    if updated.get("tool_choice_required") is not True:
        fail(f"UPDATE tool_choice_required mismatch: {updated.get('tool_choice_required')!r}")
    if updated.get("memory_compression") is not True:
        fail(f"UPDATE memory_compression mismatch: {updated.get('memory_compression')!r}")
    if updated.get("allowed_tools") != ["a", "b"]:
        fail(f"UPDATE allowed_tools mismatch: {updated.get('allowed_tools')!r}")
    ok("PUT /agents/{id} persists all new fields correctly")

    # 6. Re-GET to confirm persistence
    r = requests.get(f"{base}/agents/{agent_id}", headers=headers, timeout=10)
    if r.status_code != 200:
        fail(f"re-GET agent HTTP {r.status_code}: {r.text[:400]}")
    after = (r.json().get("data") or {})
    if after.get("memory_policy") != "semantic_compression":
        fail(f"re-GET memory_policy mismatch: {after.get('memory_policy')!r}")
    if after.get("tool_choice") != "required":
        fail(f"re-GET tool_choice mismatch: {after.get('tool_choice')!r}")
    ok("re-GET confirms persisted fields")

    # 7. Cleanup
    r = requests.delete(f"{base}/agents/{agent_id}", headers=headers, timeout=10)
    if r.status_code != 200:
        print(f"WARN: cleanup delete HTTP {r.status_code}: {r.text[:200]}")
    else:
        ok("cleanup: agent deleted")

    # 8. Summary
    print("\n=== SAMPLE AGENT (final state before delete) ===")
    print(json.dumps(after, ensure_ascii=False, indent=2))
    print("\n=== SAMPLE CHAT RESPONSE (preview) ===")
    print(response_text[:200])
    print("\nALL CHECKS PASSED")


if __name__ == "__main__":
    main()
