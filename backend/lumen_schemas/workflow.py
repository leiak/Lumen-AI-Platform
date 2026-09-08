from pydantic import BaseModel
from datetime import datetime
from typing import Optional, List, Dict, Any


class WorkflowNode(BaseModel):
    id: str
    type: str  # agent, tool, condition, start, end
    config: Dict[str, Any]
    # Canvas coordinates the designer paints. Optional + Dict (not a
    # strict {x: float, y: float} model) so the legacy executor, which
    # ignores position entirely, doesn't fail validation if some other
    # tool ever sends extra keys. Without this field, Pydantic used to
    # silently drop ``position`` on the PUT body, so every node stacked
    # at (0, 0) on reload and the designer looked broken.
    position: Optional[Dict[str, float]] = None


class WorkflowEdge(BaseModel):
    id: str
    source: str
    target: str
    condition: Optional[str] = None  # for conditional edges


class WorkflowDefinition(BaseModel):
    nodes: List[WorkflowNode]
    edges: List[WorkflowEdge]


class WorkflowBase(BaseModel):
    name: str
    description: Optional[str] = None


class WorkflowCreate(WorkflowBase):
    definition: WorkflowDefinition


class WorkflowUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    definition: Optional[WorkflowDefinition] = None
    is_active: Optional[bool] = None
    # 2.1 B.1 (2026-09-08): optional free-text summary of this save
    # (e.g. "调高 temperature 到 0.7"). Forwarded to the
    # ``WorkflowVersion.change_summary`` column when the row is
    # written by the PUT trigger. Optional + nullable so legacy
    # callers that don't know about the field stay backward-compat.
    change_summary: Optional[str] = None


class WorkflowResponse(WorkflowBase):
    id: int
    tenant_id: int
    is_active: bool
    created_at: datetime
    # M30d 2.0 (2026-09-07): echoed on every PUT so the designer's
    # useAutoSave can send it back as the If-Match header on the next
    # save. Without this field the frontend can never seed
    # ``lastKnownUpdatedAt`` and the optimistic-lock guard stays
    # inert — the backend then happily accepts concurrent last-write-wins
    # clobbers instead of 409.
    updated_at: Optional[datetime] = None
    # Canvas data the frontend designer paints. Typed as a free-form
    # dict (not ``WorkflowDefinition``) so any extra node-config keys
    # we add later don't get silently stripped by Pydantic. The DB
    # column is a JSON blob; this is the round-trip carrier.
    definition: Optional[Dict[str, Any]] = None
    # 2.1 B.1 (2026-09-08): current version counter, bumped by 1 on
    # every successful PUT. Echoed on every response so the UI can
    # show "version 17" badge next to the workflow name without an
    # extra round-trip to /workflows/{id}/versions.
    version: Optional[int] = None

    class Config:
        from_attributes = True


class WorkflowRunResponse(BaseModel):
    id: int
    workflow_id: int
    status: str
    trigger_source: Optional[str] = None  # "manual" | "scheduled"
    input_data: Optional[Dict[str, Any]] = None
    output_data: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class WorkflowRunRequest(BaseModel):
    """Request body for POST /api/v1/workflows/{id}/run"""
    input_data: Dict[str, Any] = {}


class WorkflowNodeRunResponse(BaseModel):
    """Per-node execution record. Mirrors models/workflow.py:WorkflowNodeRun."""
    id: int
    run_id: int
    node_id: str
    node_type: str
    status: str
    input_data: Optional[Dict[str, Any]] = None
    output_data: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    execution_order: Optional[int] = None

    class Config:
        from_attributes = True


# M30b 2.0: workflow version history (read-only in 2.0; write in 2.1).
class WorkflowVersionRead(BaseModel):
    id: int
    workflow_id: int
    version: int
    definition_snapshot: Dict[str, Any]
    change_summary: Optional[str] = None
    created_by_user_id: Optional[int] = None
    created_at: datetime

    class Config:
        from_attributes = True


# Schedule schemas
class WorkflowScheduleBase(BaseModel):
    name: str
    cron_expression: str
    input_data: Optional[Dict[str, Any]] = None
    is_active: bool = True


class WorkflowScheduleCreate(WorkflowScheduleBase):
    # `workflow_id` is intentionally NOT here. It's already on the
    # path (`POST /workflows/{workflow_id}/schedules`) and the
    # endpoint sets `WorkflowSchedule.workflow_id` from the path
    # parameter — `data.workflow_id` is never read. Frontend schedule
    # modals only send {name, cron_expression} from the form.
    pass


class WorkflowScheduleUpdate(BaseModel):
    name: Optional[str] = None
    cron_expression: Optional[str] = None
    input_data: Optional[Dict[str, Any]] = None
    is_active: Optional[bool] = None


class WorkflowScheduleResponse(WorkflowScheduleBase):
    id: int
    workflow_id: int
    tenant_id: int
    last_run_at: Optional[datetime] = None
    next_run_at: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True
