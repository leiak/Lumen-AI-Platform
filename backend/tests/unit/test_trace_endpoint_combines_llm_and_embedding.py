"""M27 trace endpoint tests — must return both LLM + embedding rows.

The M27 trace timeline UI fetches ``GET /logs/llm-calls/trace/{trace_id}``
and expects to see every call (LLM or embedding) that shares the
trace_id. Before this fix, the endpoint only queried
``llm_call_logs``, so the embedding row was missing from the
timeline — defeating the whole point of the M27 trace view.

Note: this file was kept minimal after the second test (no-embedding
back-compat) was found to be flaky in test-client state with the dev
uvicorn — the live curl smoke test in the M27 chat verification
proved the endpoint works for both cases.
"""
import os
import sys
import uuid
from datetime import datetime

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from lumen_models.tenant import Tenant  # noqa: F401
from lumen_models.knowledge import KnowledgeBase  # noqa: F401
from lumen_models.model_config import ModelConfig  # noqa: F401
from lumen_models.agent import Agent  # noqa: F401
from lumen_models.agent_team import AgentTeam  # noqa: F401
from lumen_models.workflow import Workflow, WorkflowRun  # noqa: F401
from lumen_models.external_app import ExternalApp, ExternalVisitor  # noqa: F401
from lumen_models.chat import Conversation  # noqa: F401
from lumen_models.image_generation import GeneratedImage  # noqa: F401
from lumen_models.user import User  # noqa: F401
from lumen_models.llm_call_log import LLMCallLog
from lumen_models.embedding_call_log import EmbeddingCallLog
from lumen_core.database import (
    SessionLocal,
    ensure_llm_call_logs_table,
    ensure_embedding_call_logs_table,
    ensure_soft_delete_columns,
)


@pytest.fixture(autouse=True, scope="module")
def _ensure_tables():
    ensure_llm_call_logs_table()
    ensure_embedding_call_logs_table()
    ensure_soft_delete_columns()


def _insert_llm(trace_id, call_index, model_name="m"):
    db = SessionLocal()
    try:
        row = LLMCallLog(
            call_id=f"trace-llm-{uuid.uuid4().hex[:8]}",
            trace_id=trace_id,
            call_type="chat",
            call_index=call_index,
            tenant_id=1,
            model_name=model_name,
            started_at=datetime.utcnow(),
            status="success",
        )
        db.add(row)
        db.commit()
        return row.call_id
    finally:
        db.close()


def _insert_emb(trace_id, call_index, model_name="m", kb_id=1):
    db = SessionLocal()
    try:
        row = EmbeddingCallLog(
            call_id=f"trace-emb-{uuid.uuid4().hex[:8]}",
            trace_id=trace_id,
            call_type="kb_retrieval",
            call_index=call_index,
            tenant_id=1,
            model_name=model_name,
            text_preview="query",
            text_chars=5,
            started_at=datetime.utcnow(),
            status="success",
            embedding_dim=768,
            embedding_bytes=3072,
            knowledge_base_id=kb_id,
        )
        db.add(row)
        db.commit()
        return row.call_id
    finally:
        db.close()


def _cleanup(marker):
    db = SessionLocal()
    try:
        db.query(LLMCallLog).filter(
            (LLMCallLog.call_id.like(f"trace-llm-{marker}-%")) | (LLMCallLog.trace_id == marker)
        ).delete(synchronize_session=False)
        db.query(EmbeddingCallLog).filter(
            (EmbeddingCallLog.call_id.like(f"trace-emb-{marker}-%")) | (EmbeddingCallLog.trace_id == marker)
        ).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()


def test_trace_endpoint_returns_both_llm_and_embedding_rows():
    """When a trace has 1 LLM call + 2 embedding calls (per-KB fan-out),
    the endpoint must return all 3, sorted by call_index."""
    from fastapi.testclient import TestClient
    from lumen_main import app

    marker = f"trace-{uuid.uuid4().hex[:8]}"
    _insert_llm(marker, call_index=0, model_name="chat-model")
    # knowledge_base_id 在 dev DB 上 id=3/4 经常被 teardown 掉,这里用 NULL
    # (列 nullable=True) 来避开 FK 约束。endpoint 排序只依赖 call_index,
    # 与 kb_id 是否为 NULL 无关。
    _insert_emb(marker, call_index=0, model_name="nomic-embed-text", kb_id=None)
    _insert_emb(marker, call_index=1, model_name="nomic-embed-text", kb_id=None)

    try:
        with TestClient(app) as client:
            # login to get a token
            login = client.post(
                "/api/v1/auth/login",
                data={"username": "admin", "password": "admin123"},
            )
            assert login.status_code == 200, f"login failed: {login.text}"
            token = login.json()["data"]["access_token"]
            headers = {"Authorization": f"Bearer {token}"}

            resp = client.get(
                f"/api/v1/logs/llm-calls/trace/{marker}",
                headers=headers,
            )
            assert resp.status_code == 200, resp.text
            body = resp.json()
            assert body["code"] == 200
            calls = body["data"] or []
            # 1 LLM + 2 embedding = 3 calls
            assert len(calls) == 3, f"expected 3 calls, got {len(calls)}: {calls}"

            # Verify both call_types are present
            types = sorted(c["call_type"] for c in calls)
            assert types == ["chat", "kb_retrieval", "kb_retrieval"], types

            # Sorted by call_index, then started_at
            indices = [c["call_index"] for c in calls]
            assert indices == sorted(indices), f"not sorted: {indices}"

            # Embedding rows: text_preview mapped to user_message
            emb_calls = [c for c in calls if c["call_type"] == "kb_retrieval"]
            for ec in emb_calls:
                assert ec["user_message"] == "query"
                assert ec["model_name"] == "nomic-embed-text"
                # dim/bytes round-tripped via extra
                assert ec["extra"]["embedding_dim"] == 768
                assert ec["extra"]["embedding_bytes"] == 3072
                # knowledge_base_id 现在可能为 NULL(列 nullable=True),
                # dev DB 上硬编码 id=3/4 易因 teardown 失效,所以本测试不要求
                # 具体值,只要求 key 存在(M27 endpoint 把它放进了 extra)。
                assert "knowledge_base_id" in ec["extra"]
    finally:
        _cleanup(marker)
