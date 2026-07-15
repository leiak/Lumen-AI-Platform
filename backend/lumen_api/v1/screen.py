from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from lumen_core.database import get_db
from lumen_schemas.common import SingleResponse
from lumen_schemas.screen import (
    ScreenKpiOverview, ScreenAiCalls, ScreenKnowledge,
    ScreenWorkflows, ScreenTenantsUsers,
)
from lumen_services.aggregate_service import AggregateService
from lumen_services.logging_service import get_logging_service

router = APIRouter(prefix="/screen", tags=["screen"])
_log = get_logging_service()


# Note: 2026-06-06, screen endpoints are intentionally public (no auth) so the
# operations dashboard at frontend-overview:11337 can render anonymously. The
# require_admin dependency is still available in app.api.v1.auth for other
# admin-gated endpoints; it is just no longer wired into this router.


@router.get("/overview", response_model=SingleResponse[ScreenKpiOverview])
def get_overview(
    range: Literal["1h", "24h", "7d", "30d"] = "24h",
    db: Session = Depends(get_db),
):
    try:
        window = AggregateService.range_to_window(range)
        data = AggregateService(db).overview(window)
        data["range"] = range
        return SingleResponse(data=data)
    except Exception as e:
        _log.error(f"screen/overview failed: {e}")
        raise HTTPException(status_code=500, detail="查询失败")


@router.get("/ai-calls", response_model=SingleResponse[ScreenAiCalls])
def get_ai_calls(
    range: Literal["1h", "24h", "7d", "30d"] = "24h",
    granularity: Literal["minute", "hour", "day"] = "hour",
    db: Session = Depends(get_db),
):
    try:
        window = AggregateService.range_to_window(range)
        data = AggregateService(db).ai_calls_series(window, granularity)
        return SingleResponse(data=data)
    except Exception as e:
        _log.error(f"screen/ai-calls failed: {e}")
        raise HTTPException(status_code=500, detail="查询失败")


@router.get("/knowledge", response_model=SingleResponse[ScreenKnowledge])
def get_knowledge(
    range: Literal["1h", "24h", "7d", "30d"] = "24h",
    db: Session = Depends(get_db),
):
    try:
        window = AggregateService.range_to_window(range)
        data = AggregateService(db).knowledge_summary(window)
        return SingleResponse(data=data)
    except Exception as e:
        _log.error(f"screen/knowledge failed: {e}")
        raise HTTPException(status_code=500, detail="查询失败")


@router.get("/workflows", response_model=SingleResponse[ScreenWorkflows])
def get_workflows(
    range: Literal["1h", "24h", "7d", "30d"] = "24h",
    db: Session = Depends(get_db),
):
    try:
        window = AggregateService.range_to_window(range)
        data = AggregateService(db).workflow_summary(window)
        return SingleResponse(data=data)
    except Exception as e:
        _log.error(f"screen/workflows failed: {e}")
        raise HTTPException(status_code=500, detail="查询失败")


@router.get("/tenants-users", response_model=SingleResponse[ScreenTenantsUsers])
def get_tenants_users(
    range: Literal["1h", "24h", "7d", "30d"] = "24h",
    db: Session = Depends(get_db),
):
    try:
        window = AggregateService.range_to_window(range)
        data = AggregateService(db).tenant_user_growth(window)
        return SingleResponse(data=data)
    except Exception as e:
        _log.error(f"screen/tenants-users failed: {e}")
        raise HTTPException(status_code=500, detail="查询失败")
