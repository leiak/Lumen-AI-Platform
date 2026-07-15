from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional

from lumen_core.database import get_db
from lumen_api.v1.auth import get_current_user
from lumen_models.user import User
from lumen_schemas.common import SingleResponse, PaginatedResponse
from lumen_schemas.workflow_template import (
    WorkflowTemplateCreate,
    WorkflowTemplateResponse,
    WorkflowTemplateDetailResponse,
)
from lumen_services.workflow_template_service import WorkflowTemplateService

router = APIRouter(prefix="/workflow-templates", tags=["workflow-templates"])


@router.get("/", response_model=PaginatedResponse[WorkflowTemplateResponse])
async def list_templates(
    page: int = 1,
    page_size: int = 12,
    category: Optional[str] = None,
    tag: Optional[str] = None,
    search: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    service = WorkflowTemplateService()
    templates = service.list_templates(db, category=category, tag=tag, search=search)
    total = len(templates)
    start = (page - 1) * page_size
    end = start + page_size
    return PaginatedResponse(
        data=[WorkflowTemplateResponse.model_validate(t) for t in templates[start:end]],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/categories", response_model=SingleResponse)
async def list_categories(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from lumen_models.workflow_template import WorkflowTemplate
    from sqlalchemy import func
    rows = db.query(
        WorkflowTemplate.category,
        func.count(WorkflowTemplate.id).label("count"),
    ).group_by(WorkflowTemplate.category).all()
    return SingleResponse(data=[{"value": r.category, "count": r.count} for r in rows])


@router.get("/{template_id}", response_model=SingleResponse[WorkflowTemplateDetailResponse])
async def get_template(
    template_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    service = WorkflowTemplateService()
    template = service.get_template(db, template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    return SingleResponse(data=WorkflowTemplateDetailResponse.model_validate(template))


@router.post("/", response_model=SingleResponse[WorkflowTemplateResponse])
async def create_template(
    data: WorkflowTemplateCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    service = WorkflowTemplateService()
    try:
        template = service.create_template(db, current_user, data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return SingleResponse(data=WorkflowTemplateResponse.model_validate(template))


@router.post("/{template_id}/import", response_model=SingleResponse)
async def import_template(
    template_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a new workflow owned by the current user, cloned from the template."""
    service = WorkflowTemplateService()
    try:
        workflow = service.import_template(db, template_id, current_user)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return SingleResponse(
        data={"workflow_id": workflow.id, "name": workflow.name},
        message="Template imported successfully",
    )
