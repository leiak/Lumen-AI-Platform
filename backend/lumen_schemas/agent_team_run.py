"""Pydantic schemas for AgentRun + InterruptPayload + StreamEvent。"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from lumen_schemas.agent_team import WorkerOutput


class InterruptPayload(BaseModel):
    """HiTL 中断 payload。phase 决定字段集。"""
    phase: Literal["plan", "result"]
    manager_reasoning: Optional[str] = None
    # phase=plan
    proposed_workers: Optional[List[int]] = None  # agent_id 列表
    proposed_aggregator_prompt: Optional[str] = None
    # phase=result
    worker_outputs: Optional[List[WorkerOutput]] = None
    proposed_final_answer: Optional[str] = None


class AgentRunResponse(BaseModel):
    id: int
    team_id: int
    conversation_id: int
    user_id: int
    tenant_id: int
    status: str
    thread_id: str
    checkpoint_ns: str
    latest_checkpoint_id: Optional[str] = None
    interrupt_payload: Optional[InterruptPayload] = None
    final_answer: Optional[str] = None
    msg_metadata: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    token_count: int = 0
    latency_ms: int = 0
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class AgentRunResumeRequest(BaseModel):
    """HiTL 续跑请求 body。"""
    action: Literal[
        "approve", "modify", "reject",
        "approve_aggregate", "retry_worker",
    ]
    payload: Optional[Dict[str, Any]] = None