"""M30 P2-5: __repr__ for LLMCallContext / EmbeddingCallContext.

The default NamedTuple repr dumps all 17+ fields — clutters dev logs when
the same trace_id appears in many call sites. The explicit __repr__
truncates to the 4-5 fields that matter for log scanning:

- LLMCallContext:    call_id[:8]…, trace_id[:8]…, call_type, call_index
- EmbeddingCallContext: call_id[:8]…, trace_id[:8]…, call_type, [kb_id]
"""
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))


def test_llm_call_context_repr_truncates_ids_and_keeps_key_fields():
    from lumen_core.llm_call_context import LLMCallContext
    ctx = LLMCallContext(
        call_id="01234567-89ab-cdef-0123-456789abcdef",
        trace_id="fedcba98-7654-3210-fedc-ba9876543210",
        parent_call_id=None,
        call_type="chat",
        call_index=2,
        tenant_id=1, user_id=1, username="tester",
        conversation_id=42, agent_id=7, team_id=None,
        workflow_id=None, workflow_run_id=None, image_id=None,
        client_app="dashboard",
        request_ip="127.0.0.1", user_agent="curl/7.81",
        extra={"x": 1},
    )
    r = repr(ctx)
    # Truncated ids
    assert "01234567" in r and "…" in r
    assert "fedcba98" in r
    # Full uuid MUST NOT be in the output (privacy + log noise)
    assert "89ab-cdef" not in r
    assert "fedc-ba9876543210" not in r
    # Key fields visible
    assert "call_type='chat'" in r
    assert "call_index=2" in r
    # Length: well below the auto-repr ~280 chars
    assert len(r) < 130, f"repr too long: {len(r)} chars — {r!r}"


def test_embedding_call_context_repr_includes_kb_only_when_set():
    from lumen_core.embedding_call_context import EmbeddingCallContext
    # With KB id
    e = EmbeddingCallContext(
        call_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        trace_id="11111111-2222-3333-4444-555555555555",
        parent_call_id=None,
        call_type="kb_retrieval", call_index=0,
        tenant_id=1, knowledge_base_id=3,
        extra={"kb_name": "demo"},
    )
    r = repr(e)
    assert "aaaaaaaa" in r
    assert "kb_id=3" in r
    assert "call_type='kb_retrieval'" in r
    # Background path (no KB): no `kb_id=` segment
    e_bg = EmbeddingCallContext(
        call_id="ffffffff-eeee-dddd-cccc-bbbbbbbbbbbb",
        trace_id="66666666-7777-8888-9999-aaaaaaaaaaaa",
        parent_call_id=None,
        call_type="system.kb_ingest", call_index=0,
        tenant_id=1, knowledge_base_id=None,
        extra=None,
    )
    r_bg = repr(e_bg)
    assert "kb_id=" not in r_bg
    assert "call_type='system.kb_ingest'" in r_bg
