"""Verify M39 team run metrics are registered in metrics.py module.

M39 T1.17 Part A (2026-09-29):5 件套 team run Prometheus metric
(启动计数 / 总耗时 / HiTL 中断 / checkpoint 写入 / PG 健康)已经
添加到 lumen_core.metrics,本测试验证:

- 5 个 metric instance 都是合法 prometheus_client 类型
- metric name 跟 spec / Grafana / Alertmanager 对齐
- label 集合符合 spec,Grafana 看板按 label 拆分
- 5 个 metric 都能正常 .inc() / .observe() / .set()(没拿错类型)
- reset_metrics_for_test() 把它们也清掉(测试隔离)

T1.17 Part B 会在 TeamRunner.stream 上线后 import,届时再加
integration test 验证端到端 inc 行为。
"""
from __future__ import annotations

import pytest
from prometheus_client import Counter, Gauge, Histogram

from lumen_core.metrics import (
    postgres_health,
    team_checkpoint_write_seconds,
    team_run_duration_seconds,
    team_run_interrupt_total,
    team_run_started_total,
    reset_metrics_for_test,
)


# ===== metric instance sanity =====


def test_metrics_registered():
    """5 个 M39 metric 都是合法 prometheus_client 实例,类型正确。"""
    assert isinstance(team_run_started_total, Counter)
    assert isinstance(team_run_duration_seconds, Histogram)
    assert isinstance(team_run_interrupt_total, Counter)
    assert isinstance(team_checkpoint_write_seconds, Histogram)
    assert isinstance(postgres_health, Gauge)


def test_metric_names():
    """metric name 跟 spec 一致,跟 Grafana 看板 / Alertmanager rule 对齐。

    注意:prometheus_client.Counter._name 会自动 strip ``_total`` 后缀
    (暴露给 Prometheus scrape 时会再加回来,Prometheus 官方约定)。
    所以 Counter 的断言比较的是 strip 后的内部名。
    """
    # Counter:内部 _name 已 strip _total
    assert team_run_started_total._name == "lumen_team_run_started"
    assert team_run_interrupt_total._name == "lumen_team_run_interrupt"
    # Histogram / Gauge:无 _total 约定,内部名 = 全名
    assert team_run_duration_seconds._name == "lumen_team_run_duration_seconds"
    assert team_checkpoint_write_seconds._name == "lumen_team_checkpoint_write_seconds"
    assert postgres_health._name == "lumen_postgres_health"


def test_metric_labels():
    """label 集合符合 spec,Grafana 看板按 label 拆分。"""
    # Counter / Histogram with label
    started_labelnames = set(team_run_started_total._labelnames)
    assert started_labelnames == {"status"}

    duration_labelnames = set(team_run_duration_seconds._labelnames)
    assert duration_labelnames == {"status"}

    interrupt_labelnames = set(team_run_interrupt_total._labelnames)
    assert interrupt_labelnames == {"phase"}

    # Histogram / Gauge no labels
    assert set(team_checkpoint_write_seconds._labelnames) == set()
    assert set(postgres_health._labelnames) == set()


def test_metrics_can_be_inc_and_observe():
    """注册过的 metric 能正常调用 inc/observe(没拿错类型)。"""
    # Smoke: inc 一次,set 一次,observe 一次
    team_run_started_total.labels(status="completed").inc()
    team_run_interrupt_total.labels(phase="plan").inc()
    team_run_duration_seconds.labels(status="completed").observe(1.5)
    team_checkpoint_write_seconds.observe(0.05)
    postgres_health.set(1)
    # 至少没抛异常就是 pass


# ===== reset isolation =====


def test_reset_metrics_clears_team_metrics():
    """reset_metrics_for_test() 也清掉 M39 5 件套,避免跨测试污染。

    注意:reset_metrics_for_test() 只清 ``_metrics`` dict(labeled sample),
    对 unlabeled metric(Gauge ``_value`` / Histogram ``_sum`` / ``_count``)
    不重置 —— 这是 pre-existing 限制,见 lumen_core/metrics.py:286 注释。
    本测试只验证 labeled metric 被清掉,unlabeled 留给后续 fix。
    """
    team_run_started_total.labels(status="completed").inc(5)
    team_run_interrupt_total.labels(phase="plan").inc(3)
    team_run_duration_seconds.labels(status="completed").observe(2.0)

    reset_metrics_for_test()

    # 清完后同一 label 再 inc,应视为新 sample(从 0 起)
    # 验证方式:清完后 get_metric_value 拿不到旧 sample。
    from lumen_core.metrics import get_metric_value

    assert get_metric_value(
        "lumen_team_run_started_total", {"status": "completed"},
    ) is None
    assert get_metric_value(
        "lumen_team_run_interrupt_total", {"phase": "plan"},
    ) is None


# ===== fixture:每 test 后 reset 防 cross-test 污染 =====


@pytest.fixture(autouse=True)
def _reset_after_test():
    """每个 test 完 reset registry,避免 sample 串。"""
    yield
    try:
        reset_metrics_for_test()
    except Exception:
        pass