"""M37.2: Eval run HTTP endpoints — /api/v1/eval/runs/*.

5 endpoints per plan §CP5 T16:

  GET    /                          list runs (tenant-scoped, with completed_count)
  POST   /                          start a new run (← Celery task)
  GET    /{run_id}                  detail (含 metrics_json + report_markdown)
  POST   /{run_id}/cancel           mark run as cancelled
  POST   /compare                   compare two runs(A baseline, B new)

进度轮询复用 GET /{run_id}——前端 5s 轮询,看 status + completed_items。
Compare 不是按 run 子端点,而是顶级 /compare,因为对比可能涉及跨 dataset
的两个 run(虽然 service 仍校验同 dataset)。

Plan: docs-internal/superpowers/plans/m37-plan.md CP5 T16
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from lumen_api.v1.auth import get_current_user
from lumen_core.database import get_db
from lumen_models.eval_run import EvalRun, EvalRunResult
from lumen_models.user import User
from lumen_schemas.common import PaginatedResponse, ResponseBase, SingleResponse
from lumen_schemas.eval_run import (
    EvalRunCancel,
    EvalRunCompareRequest,
    EvalRunCompareResponse,
    EvalRunConfig,
    EvalRunCreate,
    EvalRunListItem,
    EvalRunRead,
    EvalRunReadWithResults,
    EvalRunResultRead,
    RetrievalMetrics,
    AnswerMetrics,
)
from lumen_services.eval_run_service import EvalRunService


router = APIRouter(prefix="/eval/runs", tags=["eval-runs"])
service = EvalRunService()


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _to_list_item(
    row: EvalRun,
    completed_count: int,
) -> EvalRunListItem:
    """把 ORM EvalRun + completion count 折算成 ListItem。

    不用 ``model_validate(row)`` 直转,因为 ``completed_count`` 不在
    ORM 列上。
    """
    return EvalRunListItem(
        id=int(row.id),  # type: ignore[arg-type]
        dataset_id=int(row.dataset_id),  # type: ignore[arg-type]
        status=row.status,  # type: ignore[arg-type]
        total_items=int(row.total_items),  # type: ignore[arg-type]
        completed_items=int(row.completed_items),  # type: ignore[arg-type]
        completed_count=completed_count,
        error_message=row.error_message,
        started_at=row.started_at,
        finished_at=row.finished_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
        created_by=row.created_by,
    )


def _to_read(row: EvalRun) -> EvalRunRead:
    """详情 = ListItem + config_json + metrics_json + report_markdown。"""
    cfg_dict: Dict[str, Any] = dict(row.config_json or {})
    # EvalRunConfig 的字段必须能反序列化,失败时降级为空 config
    try:
        cfg = EvalRunConfig.model_validate(cfg_dict)
    except Exception:  # noqa: BLE001
        cfg = EvalRunConfig(
            embedding_model_config_id=0,
            judge_model_config_id=0,
        )
    return EvalRunRead(
        id=int(row.id),  # type: ignore[arg-type]
        dataset_id=int(row.dataset_id),  # type: ignore[arg-type]
        status=row.status,  # type: ignore[arg-type]
        total_items=int(row.total_items),  # type: ignore[arg-type]
        completed_items=int(row.completed_items),  # type: ignore[arg-type]
        completed_count=None,
        error_message=row.error_message,
        started_at=row.started_at,
        finished_at=row.finished_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
        created_by=row.created_by,
        config=cfg,
        metrics_json=dict(row.metrics_json) if row.metrics_json else None,  # type: ignore[arg-type]
        report_markdown=row.report_markdown,
        trace_id=row.trace_id,
    )


def _to_result_read(row: EvalRunResult) -> EvalRunResultRead:
    """EvalRunResult ORM → schema(嵌套 RetrievalMetrics + AnswerMetrics)。

    任何 Pydantic 校验失败都降级返回 — 历史 run 可能因 NDCG 边界 bug
    等原因算出 schema 范围外的值(NDCG>1.0 等),不能让单条 result 校验
    失败导致整个详情 endpoint 500。降级时 log.warning + 用
    ``model_construct`` 跳过校验构造。
    """
    import logging as _logging
    _log = _logging.getLogger(__name__)
    try:
        rm: Dict[str, Any] = dict(row.retrieval_metrics or {})
        retrieval = RetrievalMetrics(
            hit_at_5=float(rm.get("hit_at_5", 0.0)),
            hit_at_10=float(rm.get("hit_at_10", 0.0)),
            mrr=float(rm.get("mrr", 0.0)),
            ndcg_at_10=float(rm.get("ndcg_at_10", 0.0)),
            recall_at_10=float(rm.get("recall_at_10", 0.0)),
        )
        answer: Optional[AnswerMetrics] = None
        if row.answer_metrics is not None:
            am: Dict[str, Any] = dict(row.answer_metrics)
            answer = AnswerMetrics(
                faithfulness=am.get("faithfulness"),
                answer_relevancy=am.get("answer_relevancy"),
                keyword_hit_rate=float(am.get("keyword_hit_rate", 0.0)),
            )
        return EvalRunResultRead(
            id=int(row.id),  # type: ignore[arg-type]
            run_id=int(row.run_id),  # type: ignore[arg-type]
            item_id=int(row.item_id),  # type: ignore[arg-type]
            query=str(row.query),
            retrieved_doc_ids=list(row.retrieved_doc_ids or []),
            retrieval_scores=list(row.retrieval_scores or []),
            retrieved_contexts=list(row.retrieved_contexts) if row.retrieved_contexts else None,
            answer=row.answer,
            retrieval_metrics=retrieval,
            answer_metrics=answer,
            llm_judge_calls=list(row.llm_judge_calls) if row.llm_judge_calls else None,
            latency_ms=row.latency_ms,
            embedding_call_log_ids=list(row.embedding_call_log_ids) if row.embedding_call_log_ids else None,
            error_message=row.error_message,
            created_at=row.created_at,
        )
    except Exception as e:  # noqa: BLE001
        _log.warning(
            "EvalRunResult id=%s 反序列化降级(Pydantic 校验失败 / 类型错): %s",
            getattr(row, "id", "?"), e,
        )
        # model_construct 跳过校验,允许 NDCG 等指标超 [0,1] 范围,详情页能展示
        # raw 数据,失去类型保护但比 500 强。
        return EvalRunResultRead.model_construct(
            id=int(getattr(row, "id", 0)),
            run_id=int(getattr(row, "run_id", 0)),
            item_id=int(getattr(row, "item_id", 0)),
            query=str(getattr(row, "query", "") or ""),
            retrieved_doc_ids=list(getattr(row, "retrieved_doc_ids", None) or []),
            retrieval_scores=list(getattr(row, "retrieval_scores", None) or []),
            retrieved_contexts=None,
            answer=getattr(row, "answer", None),
            retrieval_metrics=getattr(row, "retrieval_metrics", None) or {},
            answer_metrics=getattr(row, "answer_metrics", None),
            llm_judge_calls=None,
            latency_ms=getattr(row, "latency_ms", None),
            embedding_call_log_ids=None,
            error_message=getattr(row, "error_message", None),
            created_at=getattr(row, "created_at", None),
        )


# ---------------------------------------------------------------------------
# endpoints
# ---------------------------------------------------------------------------


@router.get("/", response_model=PaginatedResponse[EvalRunListItem])
def list_runs(
    dataset_id: Optional[int] = Query(None, description="按 dataset 过滤"),
    status: Optional[str] = Query(
        None,
        description="按状态过滤:pending / running / completed / failed / cancelled",
    ),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List runs visible to the caller, with ``completed_count`` per row."""
    rows, completed_counts, total = service.list_runs(
        db,
        tenant_id=int(current_user.tenant_id),  # type: ignore[arg-type]
        dataset_id=dataset_id,
        status=status,
        page=page,
        page_size=page_size,
    )
    return PaginatedResponse(
        data=[_to_list_item(r, c) for r, c in zip(rows, completed_counts)],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("/", response_model=SingleResponse[EvalRunRead], status_code=201)
def start_run(
    payload: EvalRunCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a run row + queue Celery task.

    Returns:
        201 with ``EvalRunRead`` (status=pending). The dashboard polls
        GET /{run_id} for progress.
    """
    try:
        run, _task_id = service.start_run(
            db,
            payload=payload,
            tenant_id=int(current_user.tenant_id),  # type: ignore[arg-type]
            created_by=int(current_user.id),  # type: ignore[arg-type]
        )
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return SingleResponse(data=_to_read(run))


@router.get("/{run_id}", response_model=SingleResponse[EvalRunReadWithResults])
def get_run(
    run_id: int,
    include_results: bool = Query(
        False, description="是否同时返回该 run 全部 item 的结果(默认前 50 条)",
    ),
    results_page: int = Query(1, ge=1),
    results_page_size: int = Query(50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Detail. ``include_results=true`` 时把 results 折进同一信封(分页)。"""
    run = service.get_run(
        db,
        run_id=run_id,
        tenant_id=int(current_user.tenant_id),  # type: ignore[arg-type]
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Eval run not found")
    read = _to_read(run)
    if not include_results:
        return SingleResponse(data=EvalRunReadWithResults(**read.model_dump()))
    results, total = service.list_results(
        db,
        run_id=run_id,
        tenant_id=int(current_user.tenant_id),  # type: ignore[arg-type]
        page=results_page,
        page_size=results_page_size,
    )
    return SingleResponse(data=EvalRunReadWithResults(
        **read.model_dump(),
        results=[_to_result_read(r) for r in results],
        results_total=total,
        results_page=results_page,
        results_page_size=results_page_size,
    ))


@router.post("/{run_id}/cancel", response_model=SingleResponse[EvalRunRead])
def cancel_run(
    run_id: int,
    payload: EvalRunCancel,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Mark a run as cancelled.

    pending / running → 200;completed / failed / cancelled → 200 no-op
    (返当前 row 让前端刷新)。"""
    run = service.cancel_run(
        db,
        run_id=run_id,
        tenant_id=int(current_user.tenant_id),  # type: ignore[arg-type]
        reason=payload.reason,
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Eval run not found")
    return SingleResponse(data=_to_read(run))


@router.post("/compare", response_model=SingleResponse[EvalRunCompareResponse])
def compare_runs(
    payload: EvalRunCompareRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Compare two runs on the same dataset.

    Returns:
        ``EvalRunCompareResponse`` —— per_item_delta + aggregate_delta +
        winners list,dashboard 一次 render 对比页。
    """
    try:
        result = service.compare(
            db,
            payload=payload,
            tenant_id=int(current_user.tenant_id),  # type: ignore[arg-type]
        )
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return SingleResponse(data=result)
