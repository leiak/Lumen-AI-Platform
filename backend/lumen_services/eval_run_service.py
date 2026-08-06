"""M37.2 — Eval Run service layer.

CRUD for ``EvalRun`` plus the run lifecycle helpers (start / cancel /
compare) that the API layer delegates to. Tenant isolation is enforced
via the parent ``EvalDataset`` (mirror of M37.1 EvalDatasetService).
``EvalRun.config_json`` is the source of truth at run-time — service
serializes the Pydantic ``EvalRunConfig`` straight into the JSON column.

设计要点(plan CP4 T13 + CP5 T16):

- ``start_run`` writes a ``pending`` row **and** enqueues the Celery
  task in the same call. Order matters:commit first, then enqueue;
  this way a Celery worker picking up the task can find the row even
  if the enqueue is slow. Transaction boundary is the row itself—the
  task is fire-and-forget.
- ``cancel_run`` sets ``status = "cancelled"``; the runner polls
  ``_is_cancelled`` at every item boundary and exits early. Already
  finished runs (completed / failed) cannot be cancelled.
- ``compare_runs`` wholly delegates to ``lumen_services.eval.compare``
  (already implemented in T14). The service layer is a thin wrapper
  that converts the loose ``Dict[str, Any]`` from compare into the
  Pydantic ``EvalRunCompareResponse`` contract.
- Visibility filter: NULL tenant_id (builtin) is visible to every
  tenant. Run visibility is inherited from its parent dataset.

Spec: docs-internal/superpowers/specs/m37-rag-evaluation.md §4.2
Plan: docs-internal/superpowers/plans/m37-plan.md CP5 T16
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from lumen_models.eval_dataset import EvalDataset
from lumen_models.eval_run import EvalRun, EvalRunResult
from lumen_models.knowledge import KnowledgeBase
from lumen_schemas.eval_run import (
    EvalRunConfig,
    EvalRunCompareItemDelta,
    EvalRunCompareRequest,
    EvalRunCompareResponse,
    EvalRunCompareWinner,
    EvalRunCreate,
)

logger = logging.getLogger(__name__)


class EvalRunService:
    """Stateless service: one instance shared across requests."""

    # ----- visibility helper ------------------------------------------------

    @staticmethod
    def _visibility_filter(tenant_id: Optional[int]):
        """NULL tenant_id on the parent dataset is visible to every tenant."""
        return or_(
            EvalDataset.tenant_id.is_(None),
            EvalDataset.tenant_id == tenant_id,
        )

    # ----- list / detail ----------------------------------------------------

    def list_runs(
        self,
        db: Session,
        *,
        tenant_id: Optional[int],
        dataset_id: Optional[int] = None,
        status: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Tuple[List[EvalRun], List[int], int]:
        """List runs visible to the caller.

        Returns:
            (rows, completed_counts, total). ``completed_counts`` is parallel
            to ``rows`` and carries the per-run success count (i.e. result
            rows whose ``error_message IS NULL``). Done in one query to
            avoid N+1 on the dashboard.
        """
        query = (
            db.query(EvalRun)
            .join(EvalDataset, EvalRun.dataset_id == EvalDataset.id)
            .filter(self._visibility_filter(tenant_id))
        )
        if dataset_id is not None:
            query = query.filter(EvalRun.dataset_id == dataset_id)
        if status is not None:
            query = query.filter(EvalRun.status == status)

        total = query.with_entities(func.count(EvalRun.id)).scalar() or 0
        rows = (
            query.order_by(EvalRun.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        if not rows:
            return rows, [], int(total)

        run_ids = [int(r.id) for r in rows]  # type: ignore[arg-type]
        # 一次 SELECT 拿所有 run 的完成计数
        success_subq = (
            db.query(
                EvalRunResult.run_id,
                func.count(EvalRunResult.id).label("ok_count"),
            )
            .filter(EvalRunResult.run_id.in_(run_ids))
            .filter(EvalRunResult.error_message.is_(None))
            .group_by(EvalRunResult.run_id)
            .all()
        )
        ok_by_run: Dict[int, int] = {int(rid): int(ok) for rid, ok in success_subq}
        completed_counts = [ok_by_run.get(int(r.id), 0) for r in rows]  # type: ignore[arg-type]
        # rows, completed_counts, total
        return rows, completed_counts, int(total)

    def get_run(
        self,
        db: Session,
        *,
        run_id: int,
        tenant_id: Optional[int],
    ) -> Optional[EvalRun]:
        """Single run by id, visible to the caller."""
        return (
            db.query(EvalRun)
            .join(EvalDataset, EvalRun.dataset_id == EvalDataset.id)
            .filter(EvalRun.id == run_id, self._visibility_filter(tenant_id))
            .first()
        )

    def list_results(
        self,
        db: Session,
        *,
        run_id: int,
        tenant_id: Optional[int],
        page: int = 1,
        page_size: int = 50,
    ) -> Tuple[List[EvalRunResult], int]:
        """List results of a run (paginated). 404-shaped error if run invisible."""
        if self.get_run(db, run_id=run_id, tenant_id=tenant_id) is None:
            raise LookupError(f"Run {run_id} not visible")
        query = db.query(EvalRunResult).filter(EvalRunResult.run_id == run_id)
        total = query.count()
        rows = (
            query.order_by(EvalRunResult.id.asc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        return rows, int(total)

    # ----- start / cancel ---------------------------------------------------

    def start_run(
        self,
        db: Session,
        *,
        payload: EvalRunCreate,
        tenant_id: Optional[int],
        created_by: Optional[int],
    ) -> Tuple[EvalRun, Optional[str]]:
        """Create a ``pending`` EvalRun row and enqueue the Celery task.

        Returns:
            ``(run, task_id)`` — ``task_id`` is the Celery AsyncResult id,
            or ``None`` if enqueue was not attempted (e.g. synchronous
            path or the worker is unreachable). The API returns both, the
            dashboard polls run.status — task_id is informational.

        Raises:
            LookupError: dataset not visible to the caller (or KB deleted).
            ValueError: KB embedding model deleted; run can't start.
        """
        # 1. dataset 必须对当前租户可见
        dataset = (
            db.query(EvalDataset)
            .filter(
                EvalDataset.id == payload.dataset_id,
                self._visibility_filter(tenant_id),
            )
            .first()
        )
        if dataset is None:
            raise LookupError(f"Dataset {payload.dataset_id} not visible")
        kb = (
            db.query(KnowledgeBase)
            .filter(KnowledgeBase.id == dataset.kb_id)
            .first()
        )
        if kb is None:
            raise LookupError(f"Dataset {payload.dataset_id} references a deleted KB")
        # 2. embedding_model_config_id 必须跟 KB 一致(plan T13 dim 校验)
        cfg = payload.config
        if cfg.embedding_model_config_id != kb.embedding_model_config_id:
            raise ValueError(
                f"embedding_model_config_id mismatch:config={cfg.embedding_model_config_id},"
                f" KB requires {kb.embedding_model_config_id}"
            )

        # 3. 落 pending row
        config_json: Dict[str, Any] = cfg.model_dump()
        # 把 user 起的 name 也带进去(report 里展示)
        if cfg.name:
            config_json["name"] = cfg.name
        trace_id = payload.trace_id or str(uuid.uuid4())
        run = EvalRun(
            dataset_id=payload.dataset_id,
            config_json=config_json,
            status="pending",
            total_items=0,
            completed_items=0,
            created_by=created_by,
            trace_id=trace_id,
        )
        db.add(run)
        db.commit()
        db.refresh(run)

        # 4. 派 Celery task(优雅失败:worker 没起,run 仍 pending,前端可手动重试)
        task_id = self._dispatch(run.id)
        # 4.5. eager Celery 模式下 task 立即同步跑完,但它用独立 session commit。
        #    我们的 `run` ORM 实例还是 pending 状态 —— commit 释放本 session
        #    的 InnoDB REPEATABLE READ snapshot + refresh 一次让 API 响应
        #    带回 completed / failed 等真实终态,避免前端 POST 完立刻轮询看到
        #    pending → completed 闪一下又变 completed 的"假"进度条。
        try:
            db.commit()
            db.refresh(run)
        except Exception:  # noqa: BLE001
            # run 被并发删除 → 跳过,反正下面会返 None
            pass
        return run, task_id

    @staticmethod
    def _dispatch(run_id: int) -> Optional[str]:
        """Enqueue ``run_rag_eval`` on Celery.

        失败 → log + 返 None,run 仍 pending,前端可复跑同 run_id(幂等:
        runner 检测到 completed / failed / cancelled 会 skip)。
        """
        try:
            from lumen_tasks.eval_tasks import run_eval_task
            res = run_eval_task.delay(run_id)
            return str(res.id) if res else None
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "EvalRun #%s celery enqueue failed(worker 没起?):%s",
                run_id, exc,
            )
            return None

    def cancel_run(
        self,
        db: Session,
        *,
        run_id: int,
        tenant_id: Optional[int],
        reason: Optional[str] = None,
    ) -> Optional[EvalRun]:
        """Mark a run as ``cancelled``.

        Returns:
            ``EvalRun`` on success; ``None`` if run not visible. Pending /
            running runs are cancellable; completed / failed / cancelled
            runs are no-ops (return the row unchanged).
        """
        run = self.get_run(db, run_id=run_id, tenant_id=tenant_id)
        if run is None:
            return None
        if run.status in ("completed", "failed", "cancelled"):
            return run
        run.status = "cancelled"  # type: ignore[assignment]
        if reason:
            run.error_message = f"cancelled by user:{reason}"  # type: ignore[assignment]
        else:
            run.error_message = "cancelled by user"  # type: ignore[assignment]
        db.commit()
        db.refresh(run)
        return run

    # ----- compare ----------------------------------------------------------

    def compare(
        self,
        db: Session,
        *,
        payload: EvalRunCompareRequest,
        tenant_id: Optional[int],
    ) -> EvalRunCompareResponse:
        """Compare two runs (A baseline, B new). Restricted to same dataset.

        Cross-dataset comparison is rejected because retrieval metrics
        differ wildly across KB corpora. Cross-tenant runs are filtered
        by the visibility filter on each fetch.
        """
        # 1. 两条 run 都必须对当前租户可见
        run_a = self.get_run(db, run_id=payload.run_id_a, tenant_id=tenant_id)
        run_b = self.get_run(db, run_id=payload.run_id_b, tenant_id=tenant_id)
        if run_a is None:
            raise LookupError(f"Run A ({payload.run_id_a}) not visible")
        if run_b is None:
            raise LookupError(f"Run B ({payload.run_id_b}) not visible")
        if run_a.dataset_id != run_b.dataset_id:
            raise ValueError(
                f"Cannot compare runs across different datasets:"
                f" A.dataset={run_a.dataset_id}, B.dataset={run_b.dataset_id}"
            )

        # 2. 调底层 compare —— 已有 loose dict 接口(T14)
        from lumen_services.eval.compare import compare_runs
        raw: Dict[str, Any] = compare_runs(db, payload.run_id_a, payload.run_id_b)
        #   compare_runs 在 run 找不到时返 {"error": "..."},这里两个 run
        #   都已经过层校验,所以不会进 error 分支,但 defensive 兜底
        if "error" in raw:
            raise ValueError(raw["error"])

        # 3. 强类型化成 Pydantic schema
        return _raw_to_compare_response(raw)

    # ----- helpers (analytics) ----------------------------------------------

    def latest_kpi(
        self,
        db: Session,
        *,
        tenant_id: Optional[int],
        dataset_id: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        """最近 1 条 completed run 的 hit_at_5 / mrr / status。

        Dashboard 主页 KPI 卡片用 —— 留 T19 看板做,所以 service 这里
        先实现,接口稳定。
        """
        query = (
            db.query(EvalRun)
            .join(EvalDataset, EvalRun.dataset_id == EvalDataset.id)
            .filter(
                EvalRun.status == "completed",
                self._visibility_filter(tenant_id),
            )
        )
        if dataset_id is not None:
            query = query.filter(EvalRun.dataset_id == dataset_id)
        latest = query.order_by(EvalRun.finished_at.desc()).first()
        if latest is None:
            return None
        m: Dict[str, Any] = dict(latest.metrics_json or {})
        retrieval: Dict[str, Any] = dict(m.get("retrieval") or {})
        return {
            "run_id": int(latest.id),  # type: ignore[arg-type]
            "finished_at": latest.finished_at,
            "hit_at_5": float(retrieval.get("hit_at_5", 0.0)),
            "mrr": float(retrieval.get("mrr", 0.0)),
            "latency_ms_p50": int(retrieval.get("latency_ms_p50", 0)),
        }


# ---------------------------------------------------------------------------
# helper: raw compare dict → Pydantic EvalRunCompareResponse
# ---------------------------------------------------------------------------


def _raw_to_compare_response(raw: Dict[str, Any]) -> EvalRunCompareResponse:
    """Convert ``lumen_services.eval.compare``'s loose dict into the API
    contract ``EvalRunCompareResponse``.

    ``per_item_delta`` 输入 list[{item_id, query, a, b, delta}] →
    EvalRunCompareItemDelta 列表;``aggregate_delta`` 拆 section → flat
    list of winners(API 给前端一次性喂)。
    """
    per_item: List[EvalRunCompareItemDelta] = []
    for row in raw.get("per_item_delta", []) or []:
        per_item.append(EvalRunCompareItemDelta(
            item_id=int(row.get("item_id", 0)),
            query=str(row.get("query", "")),
            retrieval_delta=_flatten_section(row.get("a"), row.get("b"), row.get("delta")) or None,
            answer_delta=None,
        ))

    # aggregate_delta 还原:section.metric 展开成 "section.metric" 全路径
    aggregate_delta: Dict[str, float] = {}
    winners: List[EvalRunCompareWinner] = []
    for section, items in (raw.get("aggregate_delta") or {}).items():
        for metric, payload in (items or {}).items():
            full_key = f"{section}.{metric}"
            try:
                delta_val = float(payload.get("delta", 0.0))
            except (TypeError, ValueError):
                delta_val = 0.0
            aggregate_delta[full_key] = delta_val
            winners.append(EvalRunCompareWinner(
                metric=full_key,
                winner=str(payload.get("winner", "tie")),
                delta=delta_val,
            ))

    # summary 字段不写到 EvalRunCompareResponse(plan §T16 schema 未要求),
    # 直接丢弃,前端需要时调 GET /runs/{id} 拿单个 metrics_json。

    run_a = raw.get("run_a") or {}
    run_b = raw.get("run_b") or {}
    return EvalRunCompareResponse(
        run_id_a=int(run_a.get("id", 0)),
        run_id_b=int(run_b.get("id", 0)),
        per_item_delta=per_item,
        aggregate_delta=aggregate_delta,
        winners=winners,
    )


def _flatten_section(
    a_block: Optional[Dict[str, Any]],
    b_block: Optional[Dict[str, Any]],
    delta_block: Optional[Dict[str, Any]],
) -> Optional[Dict[str, float]]:
    """Compare 模块已经返回 ``{hit_at_5: {a, b, delta, winner}}``;这里
    把 hit_at_5 / mrr 展平成 ``{hit_at_5: float, mrr: float}``(只留 b-a 差值)
    给 dashboard 单条 item diff 用 —— 跟 spec §4.2 per_item_delta 字段一致。
    """
    if not delta_block:
        return None
    out: Dict[str, float] = {}
    for metric in ("hit_at_5", "mrr"):
        d = delta_block.get(metric)
        if isinstance(d, dict):
            try:
                out[metric] = float(d.get("delta", 0.0))
            except (TypeError, ValueError):
                continue
    return out or None
