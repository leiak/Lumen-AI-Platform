from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional, List, Dict, Any


class WorkflowTemplateBase(BaseModel):
    name: str
    description: Optional[str] = None
    category: str = "general"
    tags: Optional[List[str]] = None


class WorkflowTemplateCreate(WorkflowTemplateBase):
    """Publish a workflow as a template.

    The client may either pass `workflow_id` (we will pull the latest
    definition server-side) OR pass a complete `workflow_json` blob.
    """
    workflow_id: Optional[int] = None
    workflow_json: Optional[Dict[str, Any]] = None


class WorkflowTemplateUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    tags: Optional[List[str]] = None


class WorkflowTemplateResponse(WorkflowTemplateBase):
    id: int
    author_id: int
    author_name: Optional[str] = None
    downloads: int
    created_at: datetime

    class Config:
        from_attributes = True


class WorkflowTemplateDetailResponse(WorkflowTemplateResponse):
    workflow_json: Dict[str, Any]
