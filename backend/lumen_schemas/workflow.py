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


class WorkflowResponse(WorkflowBase):
    id: int
    tenant_id: int
    is_active: bool
    created_at: datetime
    # Canvas data the frontend designer paints. Typed as a free-form
    # dict (not ``WorkflowDefinition``) so any extra node-config keys
    # we add later don't get silently stripped by Pydantic. The DB
    # column is a JSON blob; this is the round-trip carrier.
    definition: Optional[Dict[str, Any]] = None

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
