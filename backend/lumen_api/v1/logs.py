from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from typing import Optional, List
from datetime import datetime
from lumen_core.database import get_db
from lumen_api.v1.auth import get_current_user
from lumen_models.user import User
from lumen_models.llm_call_log import LLMCallLog
from lumen_schemas.common import SingleResponse, PaginatedResponse
from lumen_schemas.llm_call_log import (
    LLMCallLogItem, LLMCallLogDetail, LLMCallLogStats,
)
from lumen_services.logging_service import get_logging_service, AuditLog, OperationLog

router = APIRouter(prefix="/logs", tags=["logs"])


# ---------------------------------------------------------------------------
# M26 — Per-LLM-call observability
# ---------------------------------------------------------------------------

PREVIEW_LEN = 200


def _row_to_item(row: LLMCallLog) -> LLMCallLogItem:
    """Convert an ORM row to the list-item summary."""
    return LLMCallLogItem(
        call_id=row.call_id,
        trace_id=row.trace_id,
        call_type=row.call_type,
        call_index=row.call_index,
        tenant_id=row.tenant_id,
        username=row.username,
        conversation_id=row.conversation_id,
        agent_id=row.agent_id,
        team_id=row.team_id,
        team_member_id=row.team_member_id,
        workflow_id=row.workflow_id,
        workflow_run_id=row.workflow_run_id,
        image_id=row.image_id,
        model_type=row.model_type,
        model_name=row.model_name,
        temperature=row.temperature,
        user_message_preview=(
            (row.user_message or "")[:PREVIEW_LEN] if row.user_message else None
        ),
        response_preview=(
            (row.response_content or "")[:PREVIEW_LEN] if row.response_content else None
        ),
        input_chars=row.input_chars,
        output_chars=row.output_chars,
        token_usage=row.token_usage,
        duration_ms=row.duration_ms,
        first_token_latency_ms=row.first_token_latency_ms,
        status=row.status or "success",
        error_type=row.error_type,
        started_at=row.started_at,
        finished_at=row.finished_at,
        extra=row.extra,
    )


def _row_to_detail(row: LLMCallLog) -> LLMCallLogDetail:
    base = _row_to_item(row).model_dump()
    base.update({
        "system_messages": row.system_messages,
        "user_message": row.user_message,
        "messages": row.messages,
        "tools": row.tools,
        "extra_params": row.extra_params,
        "response_content": row.response_content,
        "finish_reason": row.finish_reason,
        "tool_calls": row.tool_calls,
        "error_message": row.error_message,
        "request_ip": row.request_ip,
        "user_agent": row.user_agent,
    })
    return LLMCallLogDetail(**base)


# Map `module` query param → call_type prefix used in the DB.
_MODULE_TO_PREFIX = {
    "chat": "chat",
    "widget": "widget",
    "agent_team": "team.",   # team.manager_decision / team.worker / team.aggregate
    "workflow": "workflow.",
    "image_gen": "image_generation",
}


@router.get("/llm-calls", response_model=PaginatedResponse[LLMCallLogItem])
async def list_llm_call_logs(
    page: int = 1,
    page_size: int = 20,
    module: Optional[str] = None,
    call_type: Optional[str] = None,
    model_name: Optional[str] = None,
    status: Optional[str] = None,
    conversation_id: Optional[int] = None,
    agent_id: Optional[int] = None,
    team_id: Optional[int] = None,
    workflow_id: Optional[int] = None,
    workflow_run_id: Optional[int] = None,
    trace_id: Optional[str] = None,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List LLM call logs filtered by tenant + optional filters."""
    q = db.query(LLMCallLog).filter(LLMCallLog.tenant_id == current_user.tenant_id)
    if call_type is not None:
        q = q.filter(LLMCallLog.call_type == call_type)
    elif module is not None:
        prefix = _MODULE_TO_PREFIX.get(module)
        if prefix is None:
            return PaginatedResponse(data=[], total=0, page=page, page_size=page_size)
        if prefix.endswith("."):
            q = q.filter(LLMCallLog.call_type.like(f"{prefix}%"))
        else:
            q = q.filter(LLMCallLog.call_type == prefix)
    if model_name is not None:
        q = q.filter(LLMCallLog.model_name == model_name)
    if status is not None:
        q = q.filter(LLMCallLog.status == status)
    if conversation_id is not None:
        q = q.filter(LLMCallLog.conversation_id == conversation_id)
    if agent_id is not None:
        q = q.filter(LLMCallLog.agent_id == agent_id)
    if team_id is not None:
        q = q.filter(LLMCallLog.team_id == team_id)
    if workflow_id is not None:
        q = q.filter(LLMCallLog.workflow_id == workflow_id)
    if workflow_run_id is not None:
        q = q.filter(LLMCallLog.workflow_run_id == workflow_run_id)
    if trace_id is not None:
        q = q.filter(LLMCallLog.trace_id == trace_id)
    if start_time is not None:
        q = q.filter(LLMCallLog.started_at >= start_time)
    if end_time is not None:
        q = q.filter(LLMCallLog.started_at <= end_time)

    total = q.count()
    rows = (
        q.order_by(LLMCallLog.started_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return PaginatedResponse(
        data=[_row_to_item(r) for r in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/llm-calls/stats", response_model=SingleResponse[LLMCallLogStats])
async def get_llm_call_log_stats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """24h aggregate stats for the LLM Calls tab top cards."""
    from datetime import timedelta
    from sqlalchemy import func

    now = datetime.utcnow()
    yesterday = now - timedelta(days=1)

    base = db.query(LLMCallLog).filter(
        LLMCallLog.tenant_id == current_user.tenant_id,
        LLMCallLog.started_at >= yesterday,
    )

    calls_24h = base.count()
    errors_24h = base.filter(LLMCallLog.status == "failure").count()

    # Sum total_tokens across rows that have non-null token_usage. MySQL
    # JSON_EXTRACT / JSON_UNQUOTE works, but SQLAlchemy's JSON column +
    # func.json_extract is portable enough; we use a portable approach
    # by computing in Python (calls_24h is bounded by the dev DB size).
    total_tokens_24h = 0
    duration_sum = 0
    duration_count = 0
    by_module: dict = {m: 0 for m in _MODULE_TO_PREFIX}
    by_model: dict = {}
    for row in base.all():
        if row.token_usage:
            total_tokens_24h += int(row.token_usage.get("total_tokens") or 0)
        if row.duration_ms is not None:
            duration_sum += row.duration_ms
            duration_count += 1
        # Module bucketing
        for mod, prefix in _MODULE_TO_PREFIX.items():
            if prefix.endswith(".") and row.call_type.startswith(prefix):
                by_module[mod] += 1
                break
            if not prefix.endswith(".") and row.call_type == prefix:
                by_module[mod] += 1
                break
        # Model counter
        by_model[row.model_name] = by_model.get(row.model_name, 0) + 1

    # Top 5 models
    top_models = dict(sorted(by_model.items(), key=lambda kv: kv[1], reverse=True)[:5])

    avg_duration_ms = (duration_sum / duration_count) if duration_count else 0.0

    return SingleResponse(data=LLMCallLogStats(
        calls_24h=calls_24h,
        errors_24h=errors_24h,
        total_tokens_24h=total_tokens_24h,
        avg_duration_ms_24h=avg_duration_ms,
        by_module_24h=by_module,
        by_model_24h=top_models,
    ))


@router.get("/llm-calls/{call_id}", response_model=SingleResponse[LLMCallLogDetail])
async def get_llm_call_log(
    call_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Fetch a single LLM call row by call_id, scoped to the caller's tenant."""
    row = db.query(LLMCallLog).filter(
        LLMCallLog.call_id == call_id,
        LLMCallLog.tenant_id == current_user.tenant_id,
    ).first()
    if not row:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="LLMCallLog not found")
    return SingleResponse(data=_row_to_detail(row))


@router.get("/llm-calls/trace/{trace_id}", response_model=SingleResponse[List[LLMCallLogDetail]])
async def get_llm_call_log_trace(
    trace_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Fetch every call in a trace (LLM + embedding), ordered by
    ``call_index`` then by ``started_at``.

    M27: the trace timeline UI needs to see both ``llm_call_logs`` and
    ``embedding_call_logs`` rows in one chronological view. We fetch
    both and convert embedding rows to ``LLMCallLogDetail`` shape
    (text_preview → ``user_message``, ``embedding_dim`` → ``extra``).
    """
    from lumen_models.embedding_call_log import EmbeddingCallLog

    llm_rows = (
        db.query(LLMCallLog)
        .filter(
            LLMCallLog.trace_id == trace_id,
            LLMCallLog.tenant_id == current_user.tenant_id,
        )
        .all()
    )
    emb_rows = (
        db.query(EmbeddingCallLog)
        .filter(
            EmbeddingCallLog.trace_id == trace_id,
            EmbeddingCallLog.tenant_id == current_user.tenant_id,
        )
        .all()
    )

    # Convert embedding rows to LLMCallLogDetail shape.
    emb_as_detail: List[LLMCallLogDetail] = []
    for er in emb_rows:
        # text_preview is the LLM-side `user_message` equivalent for embed.
        # Embedding dim/bytes are useful for UI display, so we attach
        # them via the `extra` JSON column.
        emb_extra = dict(er.extra or {})
        emb_extra["embedding_dim"] = er.embedding_dim
        emb_extra["embedding_bytes"] = er.embedding_bytes
        emb_extra["is_batch"] = er.is_batch
        emb_extra["batch_size"] = er.batch_size
        emb_extra["knowledge_base_id"] = er.knowledge_base_id
        emb_as_detail.append(LLMCallLogDetail(
            call_id=er.call_id,
            trace_id=er.trace_id,
            call_type=er.call_type,
            call_index=er.call_index,
            tenant_id=er.tenant_id,
            username=er.username,
            conversation_id=er.conversation_id,
            agent_id=er.agent_id,
            team_id=er.team_id,
            workflow_id=er.workflow_id,
            workflow_run_id=er.workflow_run_id,
            model_type=er.model_type,
            model_name=er.model_name,
            model_config_id=er.model_config_id,
            # Embedding row's text_preview plays the user_message role
            user_message_preview=(er.text_preview or "")[:PREVIEW_LEN] if er.text_preview else None,
            user_message=er.text_preview,
            # Embedding has no response; leave response fields as None.
            duration_ms=er.duration_ms,
            status=er.status,
            error_type=er.error_type,
            error_message=er.error_message,
            started_at=er.started_at,
            finished_at=er.finished_at,
            request_ip=er.request_ip,
            user_agent=er.user_agent,
            extra=emb_extra,
        ))

    # Combine + sort by call_index then by started_at so the timeline
    # is monotonically ordered. Embedding rows tend to have a slightly
    # earlier started_at than their LLM root (KB retrieval happens
    # before the chat LLM call), so the call_index sort + started_at
    # tiebreaker keeps the order stable.
    all_rows = [_row_to_detail(r) for r in llm_rows] + emb_as_detail
    all_rows.sort(
        key=lambda c: (c.call_index, c.started_at),
    )
    return SingleResponse(data=all_rows)


@router.get("/audit", response_model=PaginatedResponse[dict])
async def list_audit_logs(
    page: int = 1,
    page_size: int = 50,
    user_id: Optional[int] = None,
    action: Optional[str] = None,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """查询审计日志"""
    service = get_logging_service()
    logs = service.get_audit_logs(
        db=db,
        tenant_id=current_user.tenant_id,
        user_id=user_id,
        action=action,
        start_time=start_time,
        end_time=end_time,
        limit=page_size
    )
    total = len(logs)
    start = (page - 1) * page_size
    end = start + page_size

    # 转换为字典
    log_dicts = []
    for log in logs[start:end]:
        log_dicts.append({
            "id": log.id,
            "user_id": log.user_id,
            "username": log.username,
            "action": log.action,
            "resource_type": log.resource_type,
            "resource_id": log.resource_id,
            "details": log.details,
            "ip_address": log.ip_address,
            "status": log.status,
            "error_message": log.error_message,
            "duration_ms": log.duration_ms,
            "created_at": log.created_at.isoformat() if log.created_at else None
        })

    return PaginatedResponse(
        data=log_dicts,
        total=total,
        page=page,
        page_size=page_size
    )


@router.get("/operations", response_model=PaginatedResponse[dict])
async def list_operation_logs(
    page: int = 1,
    page_size: int = 50,
    module: Optional[str] = None,
    level: Optional[str] = None,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """查询操作日志"""
    service = get_logging_service()
    logs = service.get_operation_logs(
        db=db,
        tenant_id=current_user.tenant_id,
        module=module,
        start_time=start_time,
        end_time=end_time,
        level=level,
        limit=page_size
    )
    total = len(logs)
    start = (page - 1) * page_size
    end = start + page_size

    # 转换为字典
    log_dicts = []
    for log in logs[start:end]:
        log_dicts.append({
            "id": log.id,
            "module": log.module,
            "action": log.action,
            "operator": log.operator,
            "target": log.target,
            "method": log.method,
            "path": log.path,
            "status_code": log.status_code,
            "duration_ms": log.duration_ms,
            "level": log.level,
            "created_at": log.created_at.isoformat() if log.created_at else None
        })

    return PaginatedResponse(
        data=log_dicts,
        total=total,
        page=page,
        page_size=page_size
    )


@router.get("/stats")
async def get_log_stats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """获取日志统计"""
    # 统计最近24小时的日志数量
    from datetime import timedelta

    now = datetime.utcnow()
    yesterday = now - timedelta(days=1)

    audit_count = db.query(AuditLog).filter(
        AuditLog.tenant_id == current_user.tenant_id,
        AuditLog.created_at >= yesterday
    ).count()

    operation_count = db.query(OperationLog).filter(
        OperationLog.tenant_id == current_user.tenant_id,
        OperationLog.created_at >= yesterday
    ).count()

    # 最近的错误数
    error_count = db.query(AuditLog).filter(
        AuditLog.tenant_id == current_user.tenant_id,
        AuditLog.created_at >= yesterday,
        AuditLog.status == "failure"
    ).count()

    return SingleResponse(data={
        "audit_logs_24h": audit_count,
        "operation_logs_24h": operation_count,
        "errors_24h": error_count
    })


@router.post("/audit")
async def create_audit_log(
    action: str,
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
    details: Optional[dict] = None,
    status: str = "success",
    error_message: Optional[str] = None,
    duration_ms: Optional[int] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """手动创建审计日志（通常用于记录重要业务操作）"""
    service = get_logging_service()
    log = service.log_audit(
        db=db,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
        username=current_user.username,
        details=details,
        status=status,
        error_message=error_message,
        duration_ms=duration_ms
    )
    if log:
        return SingleResponse(data={"id": log.id, "message": "Audit log created"})
    return SingleResponse(data={"message": "Failed to create audit log"})
