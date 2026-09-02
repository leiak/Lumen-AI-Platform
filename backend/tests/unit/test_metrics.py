"""Phase 0 Unit 5 4.3 (2026-09-02):Prometheus metrics 模块测试。

覆盖:
- 各 metric instance 注册到默认 REGISTRY
- render_metrics() 返 Prometheus text format + Content-Type
- get_metric_value() 命中已知 label 返 float,未知返 None
- reset_metrics_for_test() 清空 collector 后可重新注册
- 业务 metric labels 形态正确
"""
from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

import pytest
from prometheus_client import CONTENT_TYPE_LATEST

from lumen_core.metrics import (
    http_request_duration_seconds,
    http_requests_total,
    lumen_active_connections,
    lumen_celery_tasks_total,
    lumen_doc_processing_duration_seconds,
    lumen_embedding_calls_total,
    lumen_llm_calls_total,
    lumen_llm_tokens_total,
    lumen_rate_limit_rejections_total,
    get_metric_value,
    render_metrics,
    reset_metrics_for_test,
)


# ===== metric instance sanity =====


def test_http_requests_total_is_counter():
    """http_requests_total 是 Counter,labels=[method, path, status]。"""
    assert http_requests_total._type == "counter"
    labels = http_requests_total._labelnames
    assert set(labels) == {"method", "path", "status"}


def test_http_request_duration_seconds_is_histogram():
    """http_request_duration_seconds 是 Histogram,labels=[method, path]。"""
    assert http_request_duration_seconds._type == "histogram"
    assert set(http_request_duration_seconds._labelnames) == {"method", "path"}


def test_business_metrics_registered():
    """业务 metric 都注册成功,labels 形态正确。"""
    assert lumen_active_connections._type == "gauge"
    assert set(lumen_active_connections._labelnames) == {"type"}

    assert lumen_rate_limit_rejections_total._type == "counter"
    assert set(lumen_rate_limit_rejections_total._labelnames) == {"endpoint"}

    assert lumen_llm_calls_total._type == "counter"
    assert set(lumen_llm_calls_total._labelnames) == {"model", "status"}

    assert lumen_llm_tokens_total._type == "counter"
    assert set(lumen_llm_tokens_total._labelnames) == {"model", "type"}

    assert lumen_embedding_calls_total._type == "counter"
    assert set(lumen_embedding_calls_total._labelnames) == {"model", "status"}

    assert lumen_doc_processing_duration_seconds._type == "histogram"
    assert set(lumen_doc_processing_duration_seconds._labelnames) == {"status"}

    assert lumen_celery_tasks_total._type == "counter"
    assert set(lumen_celery_tasks_total._labelnames) == {"queue", "status"}


# ===== render_metrics() =====


def test_render_metrics_returns_prometheus_text_format():
    """render_metrics() 返 (bytes, content_type) tuple。"""
    body, content_type = render_metrics()
    assert isinstance(body, bytes)
    assert isinstance(content_type, str)
    # Prometheus 官方 content-type
    assert content_type.startswith("text/plain")
    assert "version=" in content_type


def test_render_metrics_body_contains_help_lines():
    """metric 输出含 # HELP / # TYPE 行(Prometheus text format 标准)。"""
    # 先 .inc() 一下让 sample 出现
    http_requests_total.labels(
        method="GET", path="/test/render", status="200",
    ).inc()
    body, _ = render_metrics()
    text = body.decode("utf-8")
    assert "# HELP http_requests_total" in text
    assert "# TYPE http_requests_total counter" in text


# ===== get_metric_value() =====


def test_get_metric_value_returns_float_for_known_label():
    """已知 label → 返 float 值。"""
    # 先 increment
    test_metric = http_requests_total.labels(
        method="GET", path="/test/getvalue", status="200",
    )
    test_metric.inc(3)

    value = get_metric_value(
        "http_requests_total",
        {"method": "GET", "path": "/test/getvalue", "status": "200"},
    )
    assert value is not None
    assert value == 3.0


def test_get_metric_value_returns_none_for_unknown_metric():
    """未知 metric 名 → 返 None(不抛)。"""
    assert get_metric_value("nonexistent_metric_xyz") is None


def test_get_metric_value_returns_none_for_mismatched_label():
    """label 不匹配 → 返 None(不是 0 — 区分"metric 不存在"与"值为 0")。"""
    value = get_metric_value(
        "http_requests_total",
        {"method": "GET", "path": "/no-such-path", "status": "999"},
    )
    assert value is None


def test_get_metric_value_no_labels_returns_total_for_unlabeled():
    """无 label 的 metric(本项目没这种,但 API 不该崩)→ 兼容。"""
    # lumen_active_connections 必须先 set 才会有 sample
    lumen_active_connections.labels(type="mysql").set(5)
    value = get_metric_value(
        "lumen_active_connections", {"type": "mysql"},
    )
    assert value == 5.0


# ===== reset_metrics_for_test() =====


def test_reset_metrics_for_test_clears_collectors():
    """reset 后再 inc 不影响之前的 sample(registry 干净)。"""
    # inc 一个唯一 path
    test_path = "/test/reset-marker-12345"
    http_requests_total.labels(
        method="GET", path=test_path, status="200",
    ).inc(99)

    before = get_metric_value(
        "http_requests_total",
        {"method": "GET", "path": test_path, "status": "200"},
    )
    assert before == 99.0

    reset_metrics_for_test()

    after = get_metric_value(
        "http_requests_total",
        {"method": "GET", "path": test_path, "status": "200"},
    )
    assert after is None  # reset 后没了


# ===== histogram bucket sanity =====


def test_histogram_buckets_cover_typical_request_durations():
    """http_request_duration_seconds buckets 涵盖 5ms ~ 10s。"""
    buckets = http_request_duration_seconds._upper_bounds
    # 关键 bucket 都在
    assert 0.005 in buckets
    assert 0.1 in buckets
    assert 1.0 in buckets
    assert 10.0 in buckets


# ===== fixture:每个 test 完后 reset 防止 cross-test 污染 =====


@pytest.fixture(autouse=True)
def _reset_after_test():
    """每个 test 完 reset registry,避免 sample 串。"""
    yield
    try:
        reset_metrics_for_test()
    except Exception:
        pass
