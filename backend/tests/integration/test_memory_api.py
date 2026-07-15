"""Integration tests for /memory endpoints — M15 conversation_id exposure.

Pins down the API contract that the /dashboard/memory page relies on
to dim current-conversation rows in the global context panel.
"""
import sys
import os
import uuid
import pytest
from fastapi.testclient import TestClient

# Add parent directory to path (mirrors test_agent_router.py pattern)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))


# CRITICAL: dispose the engine between tests so leaked Session objects
# don't hold InnoDB metadata locks on `global_memories` and deadlock the
# next migration test. Pattern is identical to test_external_chat_stream_e2e.
@pytest.fixture(autouse=True)
def _dispose_engine_after_test():
    yield
    from lumen_core.database import engine
    import gc
    gc.collect()
    engine.dispose()


@pytest.fixture
def client():
    """Bare FastAPI test client."""
    from lumen_main import app
    return TestClient(app)


@pytest.fixture
def auth_client(client):
    """Authed client — admin/admin123 (default seed account)."""
    response = client.post(
        "/api/v1/auth/login",
        data={"username": "admin", "password": "admin123"},
    )
    assert response.status_code == 200, f"login failed: {response.text}"
    token = response.json().get("data", {}).get("access_token")
    assert token, f"no access_token in login response: {response.text}"
    client.headers["Authorization"] = f"Bearer {token}"
    return client


def _seed_global_rows(tenant_id: int, pattern: str, conv_ids: list):
    """Write a list of GlobalMemory rows in a fresh session.

    Each entry in ``conv_ids`` becomes one row with that
    ``conversation_id``. Use None for legacy / pre-M15 rows. We open
    our own SessionLocal() so we don't share state with the FastAPI
    request session.
    """
    from lumen_core.database import SessionLocal
    from lumen_services.memory_service import MemoryService
    db = SessionLocal()
    try:
        svc = MemoryService()
        for cid in conv_ids:
            svc.add_global_memory(
                db, tenant_id=tenant_id, role="user",
                content=f"{pattern}-{cid}",
                conversation_id=cid,
            )
    finally:
        db.close()


def test_get_global_context_includes_conversation_id(auth_client):
    """GET /memory/global must return ``conversation_id`` so the UI can
    tell which rows are from the currently selected conversation.

    Test 1 of M15 Task 2. The admin user is in tenant 1, so we seed
    rows into tenant 1 and read them back via the API. The
    ``unique`` pattern is filtered server-side by ``query_text``
    so the assertion is robust against pre-existing rows in the
    dev DB.
    """
    unique = f"m15api{uuid.uuid4().hex[:10]}"
    # Seed 3 rows: 2 conv-tagged + 1 NULL-conv (legacy).
    _seed_global_rows(
        tenant_id=1,
        pattern=f"{unique}-tag",
        conv_ids=[42001, 42002],
    )
    _seed_global_rows(
        tenant_id=1,
        pattern=f"{unique}-legacy",
        conv_ids=[None],
    )

    res = auth_client.get(
        "/api/v1/memory/global",
        params={"query_text": unique},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["code"] == 200

    # Every returned row must carry a ``conversation_id`` key.
    # This is the core M15 contract — the schema must expose the
    # field so the UI can read it.
    rows = body["data"]
    assert len(rows) >= 3, f"expected >=3 rows, got {rows}"
    for row in rows:
        assert "conversation_id" in row, (
            f"row missing conversation_id: {row}"
        )

    # The 3 conv_ids we wrote must be present in the returned set.
    conv_ids = {row["conversation_id"] for row in rows}
    assert conv_ids == {42001, 42002, None}, conv_ids


def test_post_agent_chat_persists_conversation_id_to_global(auth_client):
    """The actual production write path — POST /agents/{id}/chat — must
    thread the conversation_id through to GlobalMemory. Without this,
    the UI dim/filter never has data to work with.

    Test 2 of M15 Task 2. Calls the real /agents/{id}/chat endpoint
    (which goes through Ollama at :11434), then reads /memory/global
    and asserts the new rows have the conv_id from the chat response.
    """
    from sqlalchemy import text
    from lumen_core.database import SessionLocal
    from lumen_models.model_config import ModelConfig

    # The agent chat endpoint needs a ModelConfig with base_url +
    # api_key set (agent_service.py:301). The pre-seeded
    # qwen2.5:0.5b config has base_url=None, so we patch the existing
    # row in-place to point at the local Ollama, then restore it on
    # teardown. We use an existing model_name (qwen2.5:0.5b) because
    # the unique index (tenant_id, model_type, model_name) prevents
    # inserting a duplicate. qwen2.5:0.5b is the smallest chat model
    # in the dev Ollama — fast for tests.
    db = SessionLocal()
    mc = db.query(ModelConfig).filter(
        ModelConfig.tenant_id == 1,
        ModelConfig.model_name == "qwen2.5:0.5b",
    ).first()
    assert mc is not None, "qwen2.5:0.5b ModelConfig not found in dev DB"
    # Snapshot for restore.
    orig_base_url = mc.base_url
    orig_api_key = mc.api_key
    orig_is_chat = mc.is_chat
    mc.base_url = "http://localhost:11434"
    mc.api_key = "ollama"
    mc.is_chat = True
    db.commit()
    db.close()
    model_name = "qwen2.5:0.5b"

    # We need an agent to chat with. Create one in tenant 1 via the
    # admin agent CRUD endpoint.
    agent_data = {
        "name": f"m15_mem_api_{uuid.uuid4().hex[:8]}",
        "description": "for M15 memory API test",
        "prompt_template": "You are a test assistant. {input}",
        "model_name": model_name,
        "temperature": 0,
    }
    agent_resp = auth_client.post("/api/v1/agents/", json=agent_data)
    assert agent_resp.status_code == 200, agent_resp.text
    agent_id = agent_resp.json()["data"]["id"]

    # Use a unique message so we can filter global memory down to
    # only the rows this test wrote.
    marker = f"m15chatuuid{uuid.uuid4().hex[:10]}"

    try:
        chat_resp = auth_client.post(
            f"/api/v1/agents/{agent_id}/chat",
            json={
                "agent_id": agent_id,
                "message": marker,
                "history": [],
            },
        )
        assert chat_resp.status_code == 200, chat_resp.text
        body = chat_resp.json()
        assert body["code"] == 200
        conv_id = body["data"]["conversation_id"]
        assert conv_id is not None, body

        # Don't use query_text here — the LLM's response won't
        # contain our marker, so ilike-on-marker would miss the
        # assistant row. Fetch all global memory for tenant 1 and
        # filter client-side by conv_id (which is the M15 contract
        # we're actually testing). Tenant 1's global memory has
        # ~20 rows in the dev DB, so this is cheap.
        # Pass explicit limit=1000 (router max) so the freshly-written
        # rows aren't silently filtered out as the dev DB's
        # global_memories table grows past the default 100.
        global_res = auth_client.get(
            "/api/v1/memory/global",
            params={"limit": 1000},
        )
        assert global_res.status_code == 200, global_res.text
        rows = global_res.json()["data"]

        # Filter to only the rows from this chat: rows tagged with
        # our conv_id. The chat wrote a user + an assistant row.
        our_rows = [r for r in rows if r.get("conversation_id") == conv_id]
        assert len(our_rows) >= 2, (
            f"expected >=2 rows with conv_id={conv_id}, got {rows}"
        )
        # Sanity check: the user row's content should still match
        # the marker (this is the row we wrote with the chat input).
        user_rows = [r for r in our_rows if r.get("role") == "user"]
        assert any(marker in (r.get("content") or "") for r in user_rows), (
            f"user row should contain '{marker}': {user_rows}"
        )
    finally:
        # Cleanup. The chat auto-creates a Conversation row that FKs
        # to the agent, so a soft-delete of the conversation (the
        # only kind the API exposes) leaves the FK in place and the
        # agent delete fails with FK 1451. Hard-delete the chain in
        # order via raw SQL. Also restore the ModelConfig snapshot
        # we took before patching.
        db = SessionLocal()
        try:
            if "conv_id" in dir():
                db.execute(text(
                    "DELETE FROM messages WHERE conversation_id = :cid"
                ), {"cid": conv_id})
                db.execute(text(
                    "DELETE FROM conversation_memories "
                    "WHERE conversation_id = :cid"
                ), {"cid": conv_id})
                db.execute(text(
                    "DELETE FROM global_memories "
                    "WHERE content LIKE :pat"
                ), {"pat": f"%{marker}%"})
                db.execute(text(
                    "DELETE FROM conversations WHERE id = :cid"
                ), {"cid": conv_id})
            db.execute(text(
                "DELETE FROM agents WHERE id = :aid"
            ), {"aid": agent_id})
            # Restore ModelConfig snapshot. Guard against `mc is None` so
            # a failed earlier assert doesn't get masked by an
            # AttributeError on mc.id in this finally block.
            if mc is not None:
                db.execute(text(
                    "UPDATE model_configs SET base_url = :u, api_key = :k, "
                    "is_chat = :c WHERE id = :mid"
                ), {
                    "u": orig_base_url, "k": orig_api_key, "c": orig_is_chat,
                    "mid": mc.id,
                })
            db.commit()
        except Exception:
            db.rollback()
            # Don't mask the test result with a cleanup error.
        finally:
            db.close()
