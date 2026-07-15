from typing import List, Optional, Literal
from pydantic import BaseModel


class ScreenKpiOverview(BaseModel):
    range: str
    total_tenants: int
    active_tenants: int
    total_users: int
    active_users: int
    total_agents: int
    total_kbs: int
    total_workflows: int
    total_documents: int
    total_chunks: int
    total_chat_messages: int
    ai_calls: int
    ai_errors: int
    ai_error_rate: float
    top_tenants: List[dict]
    data_source_note: str


class AiCallsPoint(BaseModel):
    ts: str
    calls: int
    errors: int
    avg_latency_ms: int
    p95_latency_ms: Optional[int] = None


class AiCallsByModel(BaseModel):
    model: str
    calls: int
    errors: int
    avg_latency_ms: int


class ScreenAiCalls(BaseModel):
    series: List[AiCallsPoint]
    by_model: List[AiCallsByModel]


class ScreenKnowledge(BaseModel):
    total_kbs: int
    total_documents: int
    total_chunks: int
    parse_success: int
    parse_failed: int
    embedding_failed: int
    by_status: List[dict]


class ScreenWorkflows(BaseModel):
    total_workflows: int
    total_runs: int
    success: int
    failed: int
    cancelled: int
    avg_duration_ms: int
    by_node_type: List[dict]


class ScreenTenantsUsers(BaseModel):
    tenant_growth: List[dict]
    user_growth: List[dict]
    top_active_tenants: List[dict]
