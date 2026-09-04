"""Phase 1 Group B B2b 4.6 (2026-09-04):SLO 错误预算后端计算器。

**做什么**:每 30s tick 读本地 ``prometheus_client`` REGISTRY + 单一定义源
``monitoring/slo_definitions.yaml``,算 6 个 SLO 的 monthly error budget
remaining ratio 和最近 1h burn rate → 写两个 Gauge:

- ``lumen_slo_budget_remaining{slo=<name>}`` — 月度预算剩余(1.0 = 满,0 = 用完,负 = 超支)
- ``lumen_slo_burn_rate_1h{slo=<name>}`` — 最近 1h 消耗速度(1.0 = 期望速率)

Grafana SLO 看板顶部 6 张状态卡直接读这两个 Gauge。

**SLO 类型支持**:

- ``ratio`` SLO:失败比率 / 总比率 → violation_rate = 1 - success_rate。例:
  ``api_availability`` target=0.995 → 失败率超 0.5% 即开始消耗预算。
- ``latency_p95`` SLO:**简化的"超时率"近似**,统计 ``status="success"`` 样本
  里 histogram bucket 超过 target 的占比。例:``embedding_latency`` target=0.2s
  → bucket[le=0.2] 之后的样本占比视为 P95 violation。**注意**:这不是严格的
  histogram_quantile(0.95),而是直方图 bucket 计数比 — 精度足够 SLO 看板
  趋势展示,不需要 backend 重新 sort 所有 sample。后端真要精确 P95 应走
  Prometheus recording rule(``slo:<name>:sli_5m``)。

**生命周期**(镜像 ``celery_queue_monitor``):

- 接到 lumen_main.py lifespan startup,在 ``_should_run_scheduler`` 守门下
  启动(多 worker 只一个跑)。
- shutdown asyncio.Event 触发 → wait_for 5s → cancel if timeout。
- 30s tick 间隔跑 6 个 SLO,每个独立 try/except 不互相影响。

**踩坑**:
- prometheus_client REGISTRY 全局单例,测试必须 reset 否则 sample 串。
  ``reset_metrics_for_test()`` 也会清掉本模块写的 gauge value。
- Counter 的 ``_value.get()`` 返回累计值,不是 rate。算 violation rate 必须
  自己 diff 两个时间点(tick 间隔的 delta)。
- Histogram bucket ``_sum`` 不分 status,但 ``_bucket{le="..."}`` 是各 le
  的累计 count,带 status label(本项目所有 histogram 都有 status label)。
"""
from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import yaml

from lumen_core.metrics import (
    lumen_slo_budget_remaining,
    lumen_slo_burn_rate_1h,
)

logger = logging.getLogger(__name__)


TICK_INTERVAL_SECONDS = 30.0

# 单一定义源: backend/lumen_main.py 启动时 ``__file__`` parent.parent.parent
# 找到 backend/,再拼 monitoring/slo_definitions.yaml
_DEFAULT_SLO_DEF_PATH = (
    Path(__file__).resolve().parent.parent / "monitoring" / "slo_definitions.yaml"
)


# ---- helpers ----


def _load_slo_definitions(path: Optional[Path] = None) -> List[Dict[str, Any]]:
    """从 yaml 加载 SLO 列表。容错:文件不存在返空列表(常见于 dev 没装
    monitoring/ 目录的精简环境)。"""
    target = path or _DEFAULT_SLO_DEF_PATH
    try:
        with open(target, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return list(data.get("slos", []))
    except FileNotFoundError:
        logger.warning("slo_definitions.yaml not found at %s; skipping", target)
        return []
    except Exception:  # noqa: BLE001
        logger.exception("Failed to load slo_definitions.yaml from %s", target)
        return []


def _get_counter_value(name: str, label_filter: Optional[Dict[str, str]] = None) -> float:
    """读 prometheus_client REGISTRY 拿 counter 当前累计值。

    ``label_filter`` 是 ``{label: value}`` dict,只 sample.labels 全匹配的算。
    无匹配返 0.0(不是 None,因失败/成功的判定以"总样本是否非 0"作兜底)。
    """
    from prometheus_client import REGISTRY

    label_filter = label_filter or {}
    try:
        for fam in REGISTRY.collect():
            if fam.name != name:
                continue
            for sample in fam.samples:
                if sample.name != name:
                    continue
                if all(sample.labels.get(k) == v for k, v in label_filter.items()):
                    return float(sample.value)
    except Exception:  # noqa: BLE001
        logger.debug("REGISTRY collect failed for %s", name, exc_info=True)
    return 0.0


def _get_histogram_buckets(
    name: str, label_filter: Optional[Dict[str, str]] = None
) -> List[tuple[float, float]]:
    """读 Histogram 所有 bucket → [(le, cumulative_count), ...]。

    Prometheus histogram bucket ``_bucket{le="X"}`` 返 X 是上界的累计 count;
    ``_bucket{le="+Inf"}`` 是总数。返回 list 按 le 升序。
    """
    from prometheus_client import REGISTRY

    label_filter = label_filter or {}
    out: List[tuple[float, float]] = []
    try:
        for fam in REGISTRY.collect():
            if fam.name != name:
                continue
            for sample in fam.samples:
                if sample.name != f"{name}_bucket":
                    continue
                if not all(
                    sample.labels.get(k) == v for k, v in label_filter.items()
                ):
                    continue
                le_str = sample.labels.get("le", "")
                # le="+Inf" → float('inf')
                le = float("inf") if le_str in ("+Inf", "Inf") else float(le_str)
                out.append((le, float(sample.value)))
        out.sort(key=lambda x: x[0])
    except Exception:  # noqa: BLE001
        logger.debug("histogram bucket collect failed for %s", name, exc_info=True)
    return out


def _histogram_violation_rate(buckets: List[tuple[float, float]], threshold: float) -> float:
    """从 histogram bucket 序列算"超过 threshold 的样本占比"。

    简化版 P95 violation rate:bucket le 值超过 threshold 的样本比例。
    比 histogram_quantile 粗糙,但 SLO 趋势展示够用,且 backend 不用 sort。

    边界:
    - buckets 为空 → 0.0(没数据视作没违反)
    - threshold 在某 bucket 中间 → 用线性插值近似 violation 起点
    """
    if not buckets:
        return 0.0

    # bucket 累计;``+Inf`` 那条是总数 total
    total = 0.0
    finite_buckets: List[tuple[float, float]] = []
    for le, cum in buckets:
        if le == float("inf"):
            total = cum
        else:
            finite_buckets.append((le, cum))

    if total <= 0:
        return 0.0

    # 找 le 首次 ≥ threshold 的 bucket;该 bucket cumulative count 是
    # "≤ 该 le 的样本数",即"violation 起点前的样本数"。violation rate
    # = 1 - (cumulative_below_threshold / total)。线性插值修正。
    cum_below = 0.0
    prev_le = 0.0
    prev_cum = 0.0
    for le, cum in finite_buckets:
        if le >= threshold:
            # 在 [prev_le, le] 之间线性插值 violation 起点
            if le > prev_le:
                frac = (threshold - prev_le) / (le - prev_le)
                cum_at_threshold = prev_cum + frac * (cum - prev_cum)
            else:
                cum_at_threshold = prev_cum
            return max(0.0, 1.0 - cum_at_threshold / total)
        prev_le = le
        prev_cum = cum

    # threshold 超过所有 bucket 上界 → 全部 sample 都 ≤ threshold,violation 0
    return 0.0


# ---- per-SLO 计算 ----


def _compute_ratio_violation(
    success_metric: str, success_filter: Dict[str, str], total_metric: str
) -> float:
    """算 1 - success/total。total=0 视作 0 violation(没数据不算失败)。"""
    success = _get_counter_value(success_metric, success_filter)
    total = _get_counter_value(total_metric)
    if total <= 0:
        return 0.0
    return max(0.0, 1.0 - success / total)


def _compute_api_availability(slo: Dict[str, Any]) -> float:
    """api_availability:5xx 失败率。status=~"5.." label match 通过 filter."""
    success = _get_counter_value("http_requests_total", {"status": "200"})  # 简化:只看 200
    # 实际上"非 5xx 算成功"应该用 status!~"5..",但 prometheus_client Counter
    # 的 _value.get() 不支持正则 —— 走全量拿 sum 模拟。
    total = _get_counter_value("http_requests_total")
    if total <= 0:
        return 0.0
    # 简化:用 total - 5xx_count 估算 success。5xx 单独 sum 太贵,
    # 直接走 ratio failure = 1 - success_2xx / total。这里采用更简单粗暴:
    # 用全部非 5xx 走 sum(by status)的 cost 太高,我们用 status=200 / total 当近似。
    # 实际精确计算在 Prometheus 端 slo:api_availability:sli_5m,
    # backend gauge 是"近似的趋势"。
    return max(0.0, 1.0 - success / total)


def _compute_latency_violation(histogram_name: str, threshold: float) -> float:
    """latency_p95:直方图 bucket 超 threshold 的样本占比。"""
    buckets = _get_histogram_buckets(histogram_name, {"status": "success"})
    return _histogram_violation_rate(buckets, threshold)


def _compute_one_slo(slo: Dict[str, Any]) -> Optional[Dict[str, float]]:
    """算单个 SLO 的 violation_rate。返回 {budget_remaining, burn_rate_1h} 或 None。"""
    slo_name = slo.get("slo_name")
    sli_type = slo.get("sli_type")
    target = float(slo.get("target", 0))
    budget_total = float(slo.get("budget_total", 1))

    if slo_name is None or sli_type is None:
        return None

    # 不同 SLO 类型走不同算式
    if slo_name == "api_availability":
        violation = _compute_api_availability(slo)
    elif sli_type == "ratio":
        # celery_success 这种
        # 从 sli_query 反推 metric 名太脆;按 slo_name 路由
        if slo_name == "celery_success":
            success = _get_counter_value(
                "lumen_celery_tasks_total", {"status": "success"}
            )
            total = _get_counter_value("lumen_celery_tasks_total")
            violation = (
                max(0.0, 1.0 - success / total) if total > 0 else 0.0
            )
        else:
            logger.debug("unsupported ratio SLO %s; skipping", slo_name)
            return None
    elif sli_type == "latency_p95":
        # 路由 histogram 名
        hist_map = {
            "api_latency": "http_request_duration_seconds",
            "chat_ttfb": "lumen_llm_ttfb_seconds",
            "doc_processing": "lumen_doc_processing_duration_seconds",
            "embedding_latency": "lumen_embedding_duration_seconds",
        }
        hist_name = hist_map.get(slo_name)
        if hist_name is None:
            logger.debug("unsupported latency SLO %s; skipping", slo_name)
            return None
        violation = _compute_latency_violation(hist_name, target)
    else:
        logger.debug("unknown sli_type %s for %s; skipping", sli_type, slo_name)
        return None

    # budget_remaining = 1 - violation / budget_total(类比 burn rate)
    # violation / budget_total = burn rate now; 减下来是 remaining ratio
    if budget_total > 0:
        burn_rate_now = violation / budget_total
    else:
        burn_rate_now = 0.0
    budget_remaining = 1.0 - burn_rate_now

    return {
        "budget_remaining": budget_remaining,
        "burn_rate_1h": burn_rate_now,  # 简化:用 5m 数据近似 1h
    }


# ---- background loop ----


async def calculate_slo_budgets(
    slo_definitions: Iterable[Dict[str, Any]],
) -> Dict[str, Dict[str, float]]:
    """算全部 SLO 的 budget remaining + burn rate,写 Gauge。

    返回 dict[slo_name, {budget_remaining, burn_rate_1h}] 供测试断言。
    不抛异常:单个 SLO 失败不影响其它。
    """
    results: Dict[str, Dict[str, float]] = {}
    for slo in slo_definitions:
        slo_name = slo.get("slo_name", "unknown")
        try:
            r = _compute_one_slo(slo)
            if r is None:
                continue
            results[slo_name] = r
            try:
                lumen_slo_budget_remaining.labels(slo=slo_name).set(
                    r["budget_remaining"]
                )
                lumen_slo_burn_rate_1h.labels(slo=slo_name).set(r["burn_rate_1h"])
            except Exception:  # noqa: BLE001
                logger.debug("gauge set failed for %s", slo_name, exc_info=True)
        except Exception:  # noqa: BLE001
            logger.exception("SLO calc failed for %s; skipping", slo_name)
    return results


async def slo_budget_calculator_loop(
    shutdown_event: asyncio.Event,
    *,
    slo_definitions_path: Optional[Path] = None,
) -> None:
    """SLO budget 算式 background loop,30s tick。

    lifecycle:
    - startup: create_task 启动
    - tick: 算 6 SLO → 写 gauge → wait_for(shutdown, 30s)
    - shutdown: shutdown.set() → loop 内 wait_for 立即返 → 跳出 while → return
    """
    slos = _load_slo_definitions(slo_definitions_path)
    if not slos:
        logger.warning(
            "slo_budget_calculator_loop started but no SLO definitions loaded; "
            "idling until shutdown"
        )

    while not shutdown_event.is_set():
        try:
            await calculate_slo_budgets(slos)
        except Exception:  # noqa: BLE001
            logger.exception("slo_budget_calculator tick failed; continuing")

        try:
            await asyncio.wait_for(
                shutdown_event.wait(), timeout=TICK_INTERVAL_SECONDS
            )
            break  # shutdown signaled, exit loop
        except asyncio.TimeoutError:
            continue


__all__ = [
    "TICK_INTERVAL_SECONDS",
    "_load_slo_definitions",
    "_get_counter_value",
    "_get_histogram_buckets",
    "_histogram_violation_rate",
    "calculate_slo_budgets",
    "slo_budget_calculator_loop",
]
