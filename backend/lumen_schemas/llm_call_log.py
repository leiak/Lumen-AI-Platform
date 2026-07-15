"""M26 Pydantic schemas for llm_call_logs.

Three response shapes:

- ``LLMCallLogItem``: list rows (summary only, no full messages).
- ``LLMCallLogDetail``: single-row detail (full messages / system /
  tools / tool_calls / extra).
- ``LLMCallLogStats``: 24h aggregate stats (total calls, errors,
  tokens, avg duration, by-module breakdown, top 5 models).

Spec: docs/superpowers/specs/2026-06-14-llm-call-logging-design.md §"API 设计"
"""
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Summary item (list view)
# ---------------------------------------------------------------------------

class LLMCallLogItem(BaseModel):
    call_id: str
    trace_id: str
    call_type: str
    call_index: int
    tenant_id: Optional[int] = None
    username: Optional[str] = None
    conversation_id: Optional[int] = None
    agent_id: Optional[int] = None
    team_id: Optional[int] = None
    team_member_id: Optional[int] = None
    workflow_id: Optional[int] = None
    workflow_run_id: Optional[int] = None
    image_id: Optional[int] = None
    model_type: Optional[str] = None
    model_name: str
    temperature: Optional[float] = None
    user_message_preview: Optional[str] = None
    response_preview: Optional[str] = None
    input_chars: Optional[int] = None
    output_chars: Optional[int] = None
    token_usage: Optional[Dict[str, int]] = None
    duration_ms: Optional[int] = None
    first_token_latency_ms: Optional[int] = None
    status: str
    error_type: Optional[str] = None
    started_at: datetime
    finished_at: Optional[datetime] = None
    extra: Optional[Dict[str, Any]] = None


# ---------------------------------------------------------------------------
# Detail (single row)
# ---------------------------------------------------------------------------

class LLMCallLogDetail(LLMCallLogItem):
    """Detail view: full payload (messages / tools / tool_calls / etc.)."""

    system_messages: Optional[List[Dict[str, Any]]] = None
    user_message: Optional[str] = None
    messages: Optional[List[Dict[str, Any]]] = None
    tools: Optional[List[Dict[str, Any]]] = None
    extra_params: Optional[Dict[str, Any]] = None
    response_content: Optional[str] = None
    finish_reason: Optional[str] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None
    error_message: Optional[str] = None
    request_ip: Optional[str] = None
    user_agent: Optional[str] = None


# ---------------------------------------------------------------------------
# Stats (24h summary)
# ---------------------------------------------------------------------------

class LLMCallLogStats(BaseModel):
    calls_24h: int = 0
    errors_24h: int = 0
    total_tokens_24h: int = 0
    avg_duration_ms_24h: float = 0.0
    # Module breakdown (5 modules, derived from call_type prefix)
    by_module_24h: Dict[str, int] = Field(default_factory=dict)
    # Top 5 models by call count
    by_model_24h: Dict[str, int] = Field(default_factory=dict)