"""Phase 1 Group B B2b 4.6 (2026-09-04):SLO 错误预算计算器测试。

覆盖:
- lumen_slo_budget_remaining / lumen_slo_burn_rate_1h Gauge 类型 / labels
- _load_slo_definitions:从 yaml 正确解析 / 文件不存在 / 损坏
- _get_counter_value / _get_histogram_buckets:本地 REGISTRY 读
- _histogram_violation_rate:边界(bucket 空 / threshold 超界 / 阈值在 bucket 中间)
- calculate_slo_budgets:6 SLO 路由 / 异常隔离 / gauge 写入
- slo_budget_calculator_loop:tick 一次后等,shutdown 立即退出
- slo_budget_calculator_loop:无 SLO 定义不抛,只是空转
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from lumen_core.metrics import (
    lumen_slo_budget_remaining,
    lumen_slo_burn_rate_1h,
    reset_metrics_for_test,
)
from lumen_core.slo_budget_calculator import (
    TICK_INTERVAL_SECONDS,
    _get_counter_value,
    _get_histogram_buckets,
    _histogram_violation_rate,
    _load_slo_definitions,
    calculate_slo_budgets,
    slo_budget_calculator_loop,
)


# ===== fixture =====


@pytest.fixture(autouse=True)
def _reset_metrics():
    """每个 test 完 reset Gauge 避免 sample 串。"""
    yield
    reset_metrics_for_test()


# ===== Gauge sanity =====


def test_lumen_slo_budget_remaining_is_gauge():
    """slo_budget_remaining 是 Gauge,labels=[slo]。"""
    assert lumen_slo_budget_remaining._type == "gauge"
    assert set(lumen_slo_budget_remaining._labelnames) == {"slo"}


def test_lumen_slo_burn_rate_1h_is_gauge():
    """slo_burn_rate_1h 是 Gauge,labels=[slo]。"""
    assert lumen_slo_burn_rate_1h._type == "gauge"
    assert set(lumen_slo_burn_rate_1h._labelnames) == {"slo"}


def test_tick_interval_is_30s():
    """30s tick — 跟 celery_queue_monitor 协调(同周期不抢 REGISTRY 写)。"""
    assert TICK_INTERVAL_SECONDS == 30.0


# ===== _load_slo_definitions =====


def test_load_slo_definitions_returns_six_slos(tmp_path: Path):
    """加载默认 slo_definitions.yaml 应该拿到 6 个 SLO。"""
    slos = _load_slo_definitions()
    names = {s["slo_name"] for s in slos}
    assert names == {
        "api_availability",
        "api_latency",
        "chat_ttfb",
        "doc_processing",
        "embedding_latency",
        "celery_success",
    }


def test_load_slo_definitions_missing_file_returns_empty(tmp_path: Path):
    """不存在的路径返空 list(不抛)。"""
    slos = _load_slo_definitions(tmp_path / "nope.yaml")
    assert slos == []


def test_load_slo_definitions_corrupt_yaml_returns_empty(tmp_path: Path):
    """坏 yaml 返空 list + logger.exception,不抛。"""
    bad = tmp_path / "bad.yaml"
    bad.write_text("this is not: valid: yaml: at all: :::", encoding="utf-8")
    slos = _load_slo_definitions(bad)
    assert slos == []


def test_load_slo_definitions_each_slo_has_required_fields():
    """每个 SLO 必须有 slo_name / sli_type / target / budget_total。"""
    slos = _load_slo_definitions()
    required = {"slo_name", "sli_type", "target", "budget_total"}
    for slo in slos:
        assert required.issubset(slo.keys()), f"{slo.get('slo_name')} missing fields"


# ===== _histogram_violation_rate =====


def test_histogram_violation_rate_empty_buckets_returns_zero():
    """空 buckets 返 0(没数据视作没违反)。"""
    assert _histogram_violation_rate([], 0.2) == 0.0


def test_histogram_violation_rate_all_below_threshold():
    """所有 bucket 都在阈值下 → 0% violation。"""
    buckets = [(0.05, 10), (0.1, 30), (0.2, 50), (float("inf"), 50)]
    assert _histogram_violation_rate(buckets, 0.5) == 0.0


def test_histogram_violation_rate_threshold_in_middle_bucket():
    """阈值落在 bucket 中间 → 用线性插值算 violation rate。

    buckets: le=0.1 时 cum=10,le=0.5 时 cum=40,total=50。
    threshold=0.2 → 在 (0.1, 0.5) 中间,cum_at_threshold 用插值:
      frac = (0.2 - 0.1) / (0.5 - 0.1) = 0.25
      cum_at = 10 + 0.25 * (40 - 10) = 17.5
      violation = 1 - 17.5/50 = 0.65
    """
    buckets = [(0.1, 10), (0.5, 40), (float("inf"), 50)]
    violation = _histogram_violation_rate(buckets, 0.2)
    assert 0.6 < violation < 0.7


def test_histogram_violation_rate_all_over_threshold():
    """第一个 bucket 就超阈值 → 全部 sample violation。"""
    buckets = [(1.0, 0), (5.0, 0), (float("inf"), 100)]
    # le=1.0 时 cum=0(没 sample ≤ 1s),violation ≈ 1.0
    assert _histogram_violation_rate(buckets, 0.5) == 1.0


def test_histogram_violation_rate_threshold_above_all_buckets():
    """threshold > 所有 le 上界 → violation 0。"""
    buckets = [(0.01, 5), (0.1, 20), (0.5, 50), (float("inf"), 50)]
    assert _histogram_violation_rate(buckets, 100.0) == 0.0


def test_histogram_violation_rate_zero_total_returns_zero():
    """total=0(全空 histogram)→ 0 violation(避免 div by zero)。"""
    buckets = [(0.1, 0), (0.5, 0), (float("inf"), 0)]
    assert _histogram_violation_rate(buckets, 0.2) == 0.0


# ===== calculate_slo_budgets 路由 =====


@pytest.mark.asyncio
async def test_calculate_slo_budgets_writes_gauges_for_all_slos():
    """6 个 SLO 都进 gauge,即使没真实 counter 数据也写。"""
    slos = _load_slo_definitions()
    results = await calculate_slo_budgets(slos)
    # 6 个 SLO 都应该出 dict
    assert set(results.keys()) == {
        "api_availability",
        "api_latency",
        "chat_ttfb",
        "doc_processing",
        "embedding_latency",
        "celery_success",
    }
    # 每个 result 都包含 budget_remaining / burn_rate_1h
    for slo_name, r in results.items():
        assert "budget_remaining" in r
        assert "burn_rate_1h" in r
        # gauge 也被写了
        br = lumen_slo_budget_remaining.labels(slo=slo_name)._value.get()
        burn = lumen_slo_burn_rate_1h.labels(slo=slo_name)._value.get()
        assert br == r["budget_remaining"]
        assert burn == r["burn_rate_1h"]


@pytest.mark.asyncio
async def test_calculate_slo_budgets_empty_slos_returns_empty_dict():
    """空 SLO list 返空 dict,无 gauge 写入。"""
    results = await calculate_slo_budgets([])
    assert results == {}


@pytest.mark.asyncio
async def test_calculate_slo_budgets_skips_unsupported_sli_type():
    """sli_type 不在白名单(ratio / latency_p95)的 SLO 被 skip,不抛。"""
    slos = [
        {
            "slo_name": "bogus",
            "sli_type": "completely_unknown",
            "target": 1.0,
            "budget_total": 1.0,
        }
    ]
    # 不抛
    results = await calculate_slo_budgets(slos)
    assert "bogus" not in results


@pytest.mark.asyncio
async def test_calculate_slo_budgets_isolates_per_slo_exceptions():
    """单个 SLO 抛错不影响其它。

    celery_success 是已知支持的 ratio SLO,total=0 → violation=0 → 进 results;
    混入一个 target=None 的 SLO,float(None) 抛 TypeError 被 catch 跳过。
    """
    # reset 让 counter 为 0,celery_success total=0 → violation=0
    reset_metrics_for_test()
    slos = [
        {
            "slo_name": "celery_success",  # supported ratio SLO
            "sli_type": "ratio",
            "target": 0.99,
            "budget_total": 0.01,
        },
        {
            "slo_name": "bad",
            "sli_type": "ratio",
            "target": None,  # 让 float(None) 抛 TypeError
            "budget_total": 0.01,
        },
    ]
    # 不抛,且 'celery_success' 写进 gauge
    results = await calculate_slo_budgets(slos)
    assert "celery_success" in results
    # 'bad' 没写(被 try/except 跳过)
    assert "bad" not in results


# ===== 数值正确性 =====


@pytest.mark.asyncio
async def test_celery_success_with_zero_total_returns_zero_violation():
    """celery_success SLO,total counter 为 0 时,违反率 0(不 div by zero)。

    模拟:清空 Counter 后跑 calculate。
    """
    # 重置 metric 让 counter 全 0
    reset_metrics_for_test()
    slos = _load_slo_definitions()
    results = await calculate_slo_budgets(slos)
    # total=0 → violation=0 → budget_remaining=1.0, burn_rate=0
    assert results["celery_success"]["budget_remaining"] == 1.0
    assert results["celery_success"]["burn_rate_1h"] == 0.0


@pytest.mark.asyncio
async def test_latency_slo_zero_violation_gives_full_budget():
    """latency SLO 全 0 violation → budget_remaining=1.0。

    Histogram 全 sample ≤ target → violation 0 → budget 满。
    """
    reset_metrics_for_test()
    # 写一些 embedding call 的 sample,全部 ≤ 0.2s
    from lumen_core.metrics import lumen_embedding_duration_seconds

    lumen_embedding_duration_seconds.labels(model="m1", status="success").observe(0.05)
    lumen_embedding_duration_seconds.labels(model="m1", status="success").observe(0.1)
    slos = _load_slo_definitions()
    results = await calculate_slo_budgets(slos)
    # embedding_latency 全 sample ≤ 0.2 → violation ≈ 0 → budget 满
    assert results["embedding_latency"]["budget_remaining"] >= 0.99
    assert results["embedding_latency"]["burn_rate_1h"] <= 0.01


@pytest.mark.asyncio
async def test_latency_slo_full_violation_gives_negative_budget():
    """latency SLO 全部 sample 超 target → budget 负数(超支)。

    Histogram 全 sample > target → violation=1.0 → budget_remaining < 0。
    """
    reset_metrics_for_test()
    from lumen_core.metrics import lumen_embedding_duration_seconds

    # observe 超 0.2s 的值
    lumen_embedding_duration_seconds.labels(model="m1", status="success").observe(0.5)
    lumen_embedding_duration_seconds.labels(model="m1", status="success").observe(1.0)
    slos = _load_slo_definitions()
    results = await calculate_slo_budgets(slos)
    # 全部 sample > 0.2s,violation ≈ 1.0,budget = 1 - 1.0/0.2 = -4
    assert results["embedding_latency"]["budget_remaining"] < 0
    assert results["embedding_latency"]["burn_rate_1h"] > 1


# ===== slo_budget_calculator_loop =====


@pytest.mark.asyncio
async def test_monitor_loop_ticks_then_exits_on_shutdown():
    """loop 跑一次 calculate 后等,shutdown Event 触发立即退出。"""
    shutdown = asyncio.Event()

    calc_mock = AsyncMock(return_value={})

    with patch(
        "lumen_core.slo_budget_calculator.calculate_slo_budgets", calc_mock,
    ):
        task = asyncio.create_task(slo_budget_calculator_loop(shutdown))
        await asyncio.sleep(0.1)  # 让 loop 至少跑一次
        shutdown.set()
        await asyncio.wait_for(task, timeout=2.0)

    assert calc_mock.await_count >= 1


@pytest.mark.asyncio
async def test_monitor_loop_uses_wait_for_so_shutdown_is_prompt():
    """shutdown 触发后应在 ~0 内退出,不必等满 30s tick。"""
    calc_mock = AsyncMock(return_value={})
    shutdown = asyncio.Event()

    with patch(
        "lumen_core.slo_budget_calculator.calculate_slo_budgets", calc_mock,
    ):
        task = asyncio.create_task(slo_budget_calculator_loop(shutdown))
        await asyncio.sleep(0.05)  # 等 50ms
        shutdown.set()
        start = asyncio.get_event_loop().time()
        await asyncio.wait_for(task, timeout=2.0)
        elapsed = asyncio.get_event_loop().time() - start
        assert elapsed < 1.0, f"loop took {elapsed}s to exit after shutdown"


@pytest.mark.asyncio
async def test_monitor_loop_survives_tick_exceptions():
    """单次 tick 抛错 loop 仍能干净退出,不被一次失败打死。

    实现:TICK_INTERVAL_SECONDS 默认 30s 太长不便测,临时 patch 成 0.05s
    让 loop 能跑多次 tick。第一次失败,后续成功,loop 收到 shutdown 后退出。
    """
    call_count = 0

    async def flaky_calc(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("calc explosion")
        return {}

    shutdown = asyncio.Event()
    # patch TICK 让 loop 多次跑,而不是一次进 30s wait_for
    with patch(
        "lumen_core.slo_budget_calculator.calculate_slo_budgets", flaky_calc,
    ), patch("lumen_core.slo_budget_calculator.TICK_INTERVAL_SECONDS", 0.05):
        task = asyncio.create_task(slo_budget_calculator_loop(shutdown))
        # 等够 3-4 个 tick
        await asyncio.sleep(0.3)
        shutdown.set()
        await asyncio.wait_for(task, timeout=2.0)

    # 第一次失败,后续成功 → 至少 2 次调用,且 loop 干净退出没卡住
    assert call_count >= 2


@pytest.mark.asyncio
async def test_monitor_loop_with_no_slo_definitions_idles():
    """无 SLO 定义时不抛,只是空转等 shutdown。"""
    shutdown = asyncio.Event()
    task = asyncio.create_task(slo_budget_calculator_loop(shutdown))
    await asyncio.sleep(0.1)
    shutdown.set()
    # 应该 1s 内干净退出
    await asyncio.wait_for(task, timeout=2.0)


@pytest.mark.asyncio
async def test_monitor_loop_with_missing_yaml_file_idles(tmp_path: Path):
    """传不存在的 yaml 路径,loop 不抛,空转退出。"""
    shutdown = asyncio.Event()
    bad_path = tmp_path / "nope.yaml"
    task = asyncio.create_task(
        slo_budget_calculator_loop(shutdown, slo_definitions_path=bad_path)
    )
    await asyncio.sleep(0.1)
    shutdown.set()
    await asyncio.wait_for(task, timeout=2.0)


# ===== _get_counter_value / _get_histogram_buckets sanity =====


def test_get_counter_value_returns_zero_for_missing_metric():
    """不存在的 metric 名返 0.0。"""
    assert _get_counter_value("definitely_not_a_real_metric_xyz") == 0.0


def test_get_histogram_buckets_returns_empty_for_missing_metric():
    """不存在的 histogram 返 []。"""
    assert _get_histogram_buckets("definitely_not_a_real_histogram_xyz") == []
