"""M37.2 — 两 run 对比。

入口 ``compare_runs(db, run_id_a, run_id_b)`` 返回 spec §4.2 示例格式:

```
{
    "run_a": {...summary...},
    "run_b": {...summary...},
    "aggregate_delta": {
        "retrieval": {"hit_at_5": {"a": 0.82, "b": 0.88, "delta": +0.06, "winner": "b"},
                      ...},
        "answer":    {"keyword_hit_rate": {...}, ...},
    },
    "per_item_delta": [
        # 按 item_id 配对的 (a_result, b_result) delta,只在两个 run 都
        # 命中同一 item 时出。missing 的一方用 None 占位。
    ],
    "winners": {
        # 整体赢家汇总:对每个 metric,谁高谁是 winner
        "retrieval.hit_at_5": "b",
        "answer.faithfulness_avg": "tie",
        ...
    },
    "summary": {
        "a_wins": 3, "b_wins": 5, "ties": 1,
    },
}
```

设计要点:

- **winner 规则**:数值类指标(retrieval hit / mrr / ndcg / recall + answer
  faithfulness / answer_relevancy / keyword_hit_rate)**越高越好**;latency
  越低越好(越快 = 体验越好)。两边相等或差距 < 1e-9 视为 ``"tie"``。
- **per_item_delta**:只比「两个 run 都跑了」的 item;item 只在一个 run 出
  现时,该 metric 标 ``None``(便于 dashboard 显式标注「未对比」)。
- **不做排序**:winners 是无序 dict,前端自己渲染表格时决定列顺序。
- **不抛 run 不存在错**:run_a / run_b 找不到时返回带 ``"error"`` 字段的
  dict(spec §4.2 API contract 未定义错误码,前端按 status 字段判断即可;
  这里 fail-soft 跟其它 eval 模块对齐)。

Spec: docs-internal/superpowers/specs/m37-rag-evaluation.md §4.2 compare
Plan: docs-internal/superpowers/plans/m37-plan.md CP4 T14
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from lumen_models.eval_run import EvalRun, EvalRunResult
from lumen_models.eval_dataset import EvalDatasetItem

logger = logging.getLogger(__name__)


# 数值越高越好的 metric 集合(winner 取 max);其余 metric(latency)winner 取 min
_HIGHER_IS_BETTER: Dict[str, str] = {
    # retrieval 段
    "retrieval.hit_at_5": "max",
    "retrieval.hit_at_10": "max",
    "retrieval.mrr": "max",
    "retrieval.ndcg_at_10": "max",
    "retrieval.recall_at_10": "max",
    # answer 段
    "answer.keyword_hit_rate": "max",
    "answer.faithfulness_avg": "max",
    "answer.answer_relevancy_avg": "max",
    # latency 段 — 越低越好
    "retrieval.latency_ms_p50": "min",
    "retrieval.latency_ms_p95": "min",
}


def compare_runs(
    db: Session, run_id_a: int, run_id_b: int
) -> Dict[str, Any]:
    """对比两个 run 的 metrics_json + per-item 结果。

    Args:
        db: SQLAlchemy session。
        run_id_a: 基线 run(API 语义: A 通常是「旧的 / 已有的」,B 是「新跑的」)。
        run_id_b: 新 run。

    Returns:
        spec §4.2 格式的 dict;任一 run 找不到时返 ``{"error": "..."}``。

    异常策略:
    - run_a / run_b 不存在 → ``{"error": "run_a not found" / "run_b not found"}``
    - metrics_json 缺失(还在跑 / 还没生成)→ 视为 0.0 不抛错,
      ``aggregate_delta`` 那段写 ``{"a": 0.0, "b": 0.0, "delta": 0.0, "winner": "tie"}``
      —— 让前端能拿到完整结构(只是数据是 0)。
    """
    run_a = db.get(EvalRun, run_id_a)
    if run_a is None:
        return {"error": f"run_a ({run_id_a}) not found"}
    run_b = db.get(EvalRun, run_id_b)
    if run_b is None:
        return {"error": f"run_b ({run_id_b}) not found"}

    metrics_a: Dict[str, Any] = dict(run_a.metrics_json or {})
    metrics_b: Dict[str, Any] = dict(run_b.metrics_json or {})

    aggregate_delta, winners = _build_aggregate_delta(metrics_a, metrics_b)  # type: ignore[arg-type]
    per_item_delta = _build_per_item_delta(db, run_id_a, run_id_b)
    summary = _summarize_winners(winners)

    return {
        "run_a": _run_summary(run_a),
        "run_b": _run_summary(run_b),
        "aggregate_delta": aggregate_delta,
        "per_item_delta": per_item_delta,
        "winners": winners,
        "summary": summary,
    }


# ---------------------------------------------------------------------------
# aggregate delta
# ---------------------------------------------------------------------------


def _build_aggregate_delta(
    metrics_a: Dict[str, Any],
    metrics_b: Dict[str, Any],
) -> Tuple[Dict[str, Any], Dict[str, str]]:
    """逐 metric 算 a/b 值 + delta + winner。

    遍历 ``_HIGHER_IS_BETTER`` 的 key 集合,从 ``metrics_a`` / ``metrics_b``
    同样路径(如 ``retrieval.hit_at_5``)取数;缺值视为 0.0,winner = tie。
    """
    delta: Dict[str, Any] = {}
    winners: Dict[str, str] = {}

    for path, direction in _HIGHER_IS_BETTER.items():
        section, key = path.split(".", 1)
        a_val = float((metrics_a.get(section) or {}).get(key, 0.0))
        b_val = float((metrics_b.get(section) or {}).get(key, 0.0))
        diff = b_val - a_val
        winner = _pick_winner(a_val, b_val, direction)
        delta.setdefault(section, {})[key] = {
            "a": round(a_val, 4),
            "b": round(b_val, 4),
            "delta": round(diff, 4),
            "winner": winner,
        }
        winners[path] = winner

    return delta, winners


def _pick_winner(a: float, b: float, direction: str) -> str:
    """按 direction(max / min)决定 winner。差距 < 1e-9 视为 tie。"""
    if abs(a - b) < 1e-9:
        return "tie"
    if direction == "max":
        return "b" if b > a else "a"
    # direction == "min"(latency)
    return "b" if b < a else "a"


# ---------------------------------------------------------------------------
# per-item delta
# ---------------------------------------------------------------------------


def _build_per_item_delta(
    db: Session, run_id_a: int, run_id_b: int
) -> List[Dict[str, Any]]:
    """按 item_id 配对两 run 的 result rows,逐条算 mrr / hit_at_5 delta。

    Args:
        db: SQLAlchemy session。
        run_id_a / run_id_b: 两 run 的 id。

    Returns:
        列表元素:``{"item_id": int, "query": str, "a": {...} | None, "b": {...} | None,
        "delta": {...}}``。两边都有的 item 同时有 a / b;只一边的另一方为 None。

    边界:
    - result.error_message 非空 → 该侧的 retrieval_metrics 全 0.0,
      delta 也算但标 winner = "tie"(失败行无可比性)。
    - 两 run 的 item_id 集合可能不同(数据集被改过)→ 用 item_id 做 key 配对,
      缺的那方 ``None``。
    """
    rows_a = (
        db.query(EvalRunResult)
        .filter(EvalRunResult.run_id == run_id_a)
        .all()
    )
    rows_b = (
        db.query(EvalRunResult)
        .filter(EvalRunResult.run_id == run_id_b)
        .all()
    )
    a_by_item: Dict[int, EvalRunResult] = {int(r.item_id): r for r in rows_a}  # type: ignore[misc]
    b_by_item: Dict[int, EvalRunResult] = {int(r.item_id): r for r in rows_b}  # type: ignore[misc]
    all_item_ids = sorted(set(a_by_item) | set(b_by_item))

    out: List[Dict[str, Any]] = []
    for item_id in all_item_ids:
        ra = a_by_item.get(item_id)
        rb = b_by_item.get(item_id)
        a_metrics = _extract_retrieval_metrics(ra)
        b_metrics = _extract_retrieval_metrics(rb)
        # 至少一边非 None 时取 query
        any_one = ra if ra is not None else rb
        out.append({
            "item_id": item_id,
            "query": str(any_one.query) if any_one is not None else "",
            "a": a_metrics,
            "b": b_metrics,
            "delta": {
                "hit_at_5": _safe_delta(
                    a_metrics["hit_at_5"] if a_metrics else None,
                    b_metrics["hit_at_5"] if b_metrics else None,
                ),
                "mrr": _safe_delta(
                    a_metrics["mrr"] if a_metrics else None,
                    b_metrics["mrr"] if b_metrics else None,
                ),
            },
        })
    return out


def _extract_retrieval_metrics(
    result: Optional[EvalRunResult],
) -> Optional[Dict[str, Any]]:
    """从 result 提 hit_at_5 / mrr;result 缺失 / error → None。"""
    if result is None:
        return None
    if result.error_message:
        return None
    rm: Dict[str, Any] = dict(result.retrieval_metrics or {})
    return {
        "hit_at_5": float(rm.get("hit_at_5") or 0.0),
        "mrr": float(rm.get("mrr") or 0.0),
    }


def _safe_delta(
    a: Optional[float], b: Optional[float]
) -> Optional[Dict[str, Any]]:
    """任一侧为 None → delta 也是 None(不让前端做无意义的 0 比较)。"""
    if a is None or b is None:
        return None
    diff = b - a
    return {
        "a": round(a, 4),
        "b": round(b, 4),
        "delta": round(diff, 4),
        "winner": "b" if diff > 1e-9 else ("a" if diff < -1e-9 else "tie"),
    }


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _run_summary(run: EvalRun) -> Dict[str, Any]:
    """run 的摘要信息(给 compare 响应里的 run_a / run_b 字段)。"""
    cfg: Dict[str, Any] = dict(run.config_json or {})
    return {
        "id": int(run.id),  # type: ignore[arg-type]
        "dataset_id": int(run.dataset_id),  # type: ignore[arg-type]
        "status": str(run.status),  # type: ignore[arg-type]
        "total_items": int(run.total_items),  # type: ignore[arg-type]
        "completed_items": int(run.completed_items),  # type: ignore[arg-type]
        "config_name": cfg.get("name"),
        "embedding_model_config_id": cfg.get("embedding_model_config_id"),
        "judge_model_config_id": cfg.get("judge_model_config_id"),
        "started_at": run.started_at.isoformat() if run.started_at else None,  # type: ignore[union-attr]
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,  # type: ignore[union-attr]
    }


def _summarize_winners(winners: Dict[str, str]) -> Dict[str, int]:
    """汇总 a 赢 / b 赢 / 平局 的总数。"""
    a_wins = sum(1 for v in winners.values() if v == "a")
    b_wins = sum(1 for v in winners.values() if v == "b")
    ties = sum(1 for v in winners.values() if v == "tie")
    return {"a_wins": a_wins, "b_wins": b_wins, "ties": ties}